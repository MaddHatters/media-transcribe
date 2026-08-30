"""Video quality analysis using ffmpeg subprocess calls."""
from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

BLACK_DETECT_DURATION = 0.5
BLACK_DETECT_PIX_TH = 0.10
BLACK_HEAD_WINDOW = 60
BLACK_TAIL_WINDOW = 120
FREEZE_NOISE_TH = 0.003
FREEZE_MIN_DURATION = 3
FREEZE_FLAG_DURATION = 10
FREEZE_FLAG_COUNT = 3
SILENCE_DB = -50
SILENCE_MIN_DURATION = 5
BITRATE_DROP_THRESHOLD = 0.50
BITRATE_DROP_MIN_DURATION = 5


@dataclass
class QualityReport:
    filename: str
    duration: float
    resolution: tuple[int, int]
    verdict: str
    black_frames: list[dict] = field(default_factory=list)
    silence_gaps: list[dict] = field(default_factory=list)
    bitrate_drops: list[dict] = field(default_factory=list)
    freezes: list[dict] = field(default_factory=list)
    notes: str = ""
    trim_start: float | None = None
    trim_end: float | None = None
    codec: str = ""
    avg_bitrate_kbps: float = 0.0
    file_size_mb: float = 0.0


def _run_cmd(cmd: list[str], *, timeout: int = 600) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            args=cmd, returncode=-1, stdout="", stderr=f"TIMEOUT after {timeout}s",
        )


def _parse_float(value: str | None, default: float = 0.0) -> float:
    if not value:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _format_duration(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h}:{m:02d}:{s:02d}"


def _timeout_for_duration(duration_sec: float, multiplier: float = 1.5) -> int:
    return max(120, min(7200, int(duration_sec * multiplier)))


def compute_trim_points(
    duration: float, black_frames: list[dict],
) -> tuple[float | None, float | None]:
    trim_start: float | None = None
    trim_end: float | None = None
    for bf in black_frames:
        if bf["location"] == "start":
            candidate = bf["end"]
            if trim_start is None or candidate > trim_start:
                trim_start = candidate
        elif bf["location"] == "end":
            candidate = bf["start"]
            if trim_end is None or candidate < trim_end:
                trim_end = candidate
    if trim_start is not None and trim_end is not None and trim_start >= trim_end:
        trim_start = trim_end = None
    if trim_start is not None and trim_start < 0.5:
        trim_start = None
    if trim_end is not None and (duration - trim_end) < 0.5:
        trim_end = None
    return trim_start, trim_end


def compute_verdict(
    *, black_frames, freezes, silence_gaps, bitrate_drops,
    trim_start, trim_end,
) -> tuple[str, str]:
    """Determine quality verdict: clean, trim_needed, has_issues, or re_record."""
    issues: list[str] = []
    severity = 0

    if black_frames:
        start_blacks = [bf for bf in black_frames if bf["location"] == "start"]
        end_blacks = [bf for bf in black_frames if bf["location"] == "end"]
        if start_blacks:
            total_dur = sum(bf["duration"] for bf in start_blacks)
            issues.append(f"{total_dur:.1f}s black at start")
        if end_blacks:
            total_dur = sum(bf["duration"] for bf in end_blacks)
            issues.append(f"{total_dur:.1f}s black at end")
        if severity < 1:
            severity = 1

    if freezes:
        max_freeze = max(f["duration"] for f in freezes)
        total_freeze_time = sum(f["duration"] for f in freezes)
        if max_freeze > FREEZE_FLAG_DURATION or len(freezes) > FREEZE_FLAG_COUNT:
            severity = max(severity, 3)
            issues.append(
                f"{len(freezes)} freeze(s), "
                f"longest {max_freeze:.1f}s, "
                f"total {total_freeze_time:.1f}s — MAJOR"
            )
        else:
            severity = max(severity, 2)
            issues.append(
                f"{len(freezes)} freeze(s), "
                f"longest {max_freeze:.1f}s"
            )

    if silence_gaps:
        max_silence = max(s["duration"] for s in silence_gaps)
        if max_silence > 30:
            severity = max(severity, 3)
            issues.append(
                f"{len(silence_gaps)} silence gap(s), "
                f"longest {max_silence:.1f}s — MAJOR"
            )
        elif len(silence_gaps) > 5:
            severity = max(severity, 2)
            issues.append(
                f"{len(silence_gaps)} silence gap(s), "
                f"longest {max_silence:.1f}s"
            )

    if bitrate_drops:
        max_drop_dur = max(d["duration"] for d in bitrate_drops)
        if max_drop_dur > 30:
            severity = max(severity, 3)
            issues.append(
                f"{len(bitrate_drops)} bitrate drop(s), "
                f"longest {max_drop_dur}s — MAJOR"
            )
        elif len(bitrate_drops) > 3:
            severity = max(severity, 2)
            issues.append(f"{len(bitrate_drops)} bitrate drop(s)")

    verdicts = {0: "clean", 1: "trim_needed", 2: "has_issues", 3: "re_record"}
    verdict = verdicts.get(severity, "re_record")

    if issues:
        notes = "; ".join(issues)
    elif trim_start is not None or trim_end is not None:
        notes = "Minor trim only, otherwise clean"
    else:
        notes = "No issues detected"

    return verdict, notes


class QualityAnalyzer:
    def __init__(self, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe"):
        self._ffmpeg = ffmpeg
        self._ffprobe = ffprobe

    def _probe_metadata(self, filepath: Path) -> dict:
        result = _run_cmd([
            self._ffprobe,
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(filepath),
        ])
        if result.returncode != 0:
            raise RuntimeError(f"ffprobe failed for {filepath.name}: {result.stderr[:500]}")

        data = json.loads(result.stdout)
        fmt = data.get("format", {})
        streams = data.get("streams", [])
        video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})

        duration = _parse_float(fmt.get("duration"))
        width = int(video_stream.get("width", 0))
        height = int(video_stream.get("height", 0))
        codec = video_stream.get("codec_name", "unknown")
        bitrate = _parse_float(fmt.get("bit_rate")) / 1000
        file_size_mb = filepath.stat().st_size / (1024 * 1024)

        return {
            "duration": round(duration, 2),
            "resolution": (width, height),
            "codec": codec,
            "avg_bitrate_kbps": round(bitrate, 1),
            "file_size_mb": round(file_size_mb, 1),
        }

    def _detect_black_frames(self, filepath: Path, duration: float) -> list[dict]:
        black_frames: list[dict] = []

        result = _run_cmd([
            self._ffmpeg, "-i", str(filepath),
            "-t", str(BLACK_HEAD_WINDOW),
            "-vf", f"blackdetect=d={BLACK_DETECT_DURATION}:pix_th={BLACK_DETECT_PIX_TH}",
            "-an", "-f", "null", "-",
        ], timeout=300)

        if result.returncode != -1:
            for match in re.finditer(
                r"black_start:(\S+)\s+black_end:(\S+)\s+black_duration:(\S+)",
                result.stderr or "",
            ):
                start = _parse_float(match.group(1))
                end = _parse_float(match.group(2))
                dur = _parse_float(match.group(3))
                if start < 1.0:
                    black_frames.append({
                        "start": round(start, 2), "end": round(end, 2),
                        "duration": round(dur, 2), "location": "start",
                    })

        tail_start = max(0, duration - BLACK_TAIL_WINDOW)
        result = _run_cmd([
            self._ffmpeg, "-ss", str(tail_start), "-i", str(filepath),
            "-vf", f"blackdetect=d={BLACK_DETECT_DURATION}:pix_th={BLACK_DETECT_PIX_TH}",
            "-an", "-f", "null", "-",
        ], timeout=300)

        if result.returncode != -1:
            for match in re.finditer(
                r"black_start:(\S+)\s+black_end:(\S+)\s+black_duration:(\S+)",
                result.stderr or "",
            ):
                start = _parse_float(match.group(1)) + tail_start
                end = _parse_float(match.group(2)) + tail_start
                dur = _parse_float(match.group(3))
                if end >= duration - 1.0:
                    black_frames.append({
                        "start": round(start, 2), "end": round(end, 2),
                        "duration": round(dur, 2), "location": "end",
                    })

        return black_frames

    def _detect_freezes(self, filepath: Path, duration: float) -> list[dict]:
        timeout = _timeout_for_duration(duration) if duration > 0 else 1800
        result = _run_cmd([
            self._ffmpeg, "-i", str(filepath),
            "-vf", f"freezedetect=n={FREEZE_NOISE_TH}:d={FREEZE_MIN_DURATION}",
            "-an", "-f", "null", "-",
        ], timeout=timeout)

        if result.returncode == -1:
            return []

        freezes: list[dict] = []
        stderr = result.stderr or ""

        starts: list[float] = []
        for match in re.finditer(r"freeze_start:\s*(\S+)", stderr):
            starts.append(_parse_float(match.group(1)))

        for i, match in enumerate(re.finditer(
            r"freeze_end:\s*(\S+).*?freeze_duration:\s*(\S+)", stderr,
        )):
            end = _parse_float(match.group(1))
            dur = _parse_float(match.group(2))
            start = starts[i] if i < len(starts) else end - dur
            freezes.append({
                "start": round(start, 2), "end": round(end, 2),
                "duration": round(dur, 2),
                "start_display": _format_duration(start),
            })

        return freezes

    def _detect_silence(self, filepath: Path, duration: float) -> list[dict]:
        timeout = _timeout_for_duration(duration, multiplier=0.5) if duration > 0 else 600
        result = _run_cmd([
            self._ffmpeg, "-i", str(filepath),
            "-vn",
            "-af", f"silencedetect=n={SILENCE_DB}dB:d={SILENCE_MIN_DURATION}",
            "-f", "null", "-",
        ], timeout=timeout)

        if result.returncode == -1:
            return []

        silences: list[dict] = []
        stderr = result.stderr or ""

        starts: list[float] = []
        for match in re.finditer(r"silence_start:\s*(\S+)", stderr):
            starts.append(_parse_float(match.group(1)))

        for match in re.finditer(
            r"silence_end:\s*(\S+)\s*\|\s*silence_duration:\s*(\S+)", stderr,
        ):
            end = _parse_float(match.group(1))
            dur = _parse_float(match.group(2))
            start = starts.pop(0) if starts else end - dur
            if start < 2.0 or end < 2.0:
                continue
            silences.append({
                "start": round(start, 2), "end": round(end, 2),
                "duration": round(dur, 2),
                "start_display": _format_duration(start),
            })

        return silences

    def _analyze_bitrate(self, filepath: Path, avg_bitrate_kbps: float) -> list[dict]:
        if avg_bitrate_kbps <= 0:
            return []

        result = _run_cmd([
            self._ffprobe,
            "-v", "quiet",
            "-select_streams", "v:0",
            "-show_entries", "packet=pts_time,size",
            "-print_format", "csv=p=0",
            str(filepath),
        ], timeout=1200)

        if result.returncode != 0:
            return []

        second_bytes: dict[int, int] = {}
        for line in result.stdout.splitlines():
            parts = line.strip().split(",")
            if len(parts) < 2:
                continue
            pts = _parse_float(parts[0])
            size = int(_parse_float(parts[1]))
            sec = int(pts)
            second_bytes[sec] = second_bytes.get(sec, 0) + size

        if not second_bytes:
            return []

        threshold_kbps = avg_bitrate_kbps * BITRATE_DROP_THRESHOLD
        drops: list[dict] = []
        sorted_secs = sorted(second_bytes.keys())
        drop_start: int | None = None
        drop_min_kbps: float = float("inf")

        for sec in sorted_secs:
            kbps = (second_bytes[sec] * 8) / 1000
            if kbps < threshold_kbps:
                if drop_start is None:
                    drop_start = sec
                    drop_min_kbps = kbps
                else:
                    drop_min_kbps = min(drop_min_kbps, kbps)
            else:
                if drop_start is not None:
                    drop_duration = sec - drop_start
                    if drop_duration >= BITRATE_DROP_MIN_DURATION:
                        drops.append({
                            "start": drop_start, "end": sec,
                            "duration": drop_duration,
                            "min_bitrate_kbps": round(drop_min_kbps, 1),
                            "avg_bitrate_kbps": round(avg_bitrate_kbps, 1),
                            "start_display": _format_duration(drop_start),
                        })
                    drop_start = None
                    drop_min_kbps = float("inf")

        if drop_start is not None:
            last_sec = sorted_secs[-1]
            drop_duration = last_sec - drop_start
            if drop_duration >= BITRATE_DROP_MIN_DURATION:
                drops.append({
                    "start": drop_start, "end": last_sec,
                    "duration": drop_duration,
                    "min_bitrate_kbps": round(drop_min_kbps, 1),
                    "avg_bitrate_kbps": round(avg_bitrate_kbps, 1),
                    "start_display": _format_duration(drop_start),
                })

        return drops

    def analyze(self, video_path: Path) -> QualityReport:
        """Run all analysis passes on a single video file."""
        try:
            meta = self._probe_metadata(video_path)
        except RuntimeError as e:
            return QualityReport(
                filename=video_path.name, duration=0.0,
                resolution=(0, 0), verdict="re_record",
                notes=f"Could not probe file: {e}",
            )

        duration = meta["duration"]
        avg_bitrate = meta["avg_bitrate_kbps"]

        black_frames = self._detect_black_frames(video_path, duration)
        freezes = self._detect_freezes(video_path, duration)
        silence_gaps = self._detect_silence(video_path, duration)
        bitrate_drops = self._analyze_bitrate(video_path, avg_bitrate)

        trim_start, trim_end = compute_trim_points(duration, black_frames)
        verdict, notes = compute_verdict(
            black_frames=black_frames, freezes=freezes,
            silence_gaps=silence_gaps, bitrate_drops=bitrate_drops,
            trim_start=trim_start, trim_end=trim_end,
        )

        return QualityReport(
            filename=video_path.name,
            duration=duration,
            resolution=meta["resolution"],
            verdict=verdict,
            black_frames=black_frames,
            silence_gaps=silence_gaps,
            bitrate_drops=bitrate_drops,
            freezes=freezes,
            notes=notes,
            trim_start=trim_start,
            trim_end=trim_end,
            codec=meta["codec"],
            avg_bitrate_kbps=avg_bitrate,
            file_size_mb=meta["file_size_mb"],
        )

    def analyze_folder(
        self, folder: Path, single: str | None = None,
    ) -> list[QualityReport]:
        """Analyze all videos in a folder."""
        extensions = {".mkv", ".mp4", ".avi", ".webm", ".mov"}
        if single:
            target = folder / single
            if not target.exists():
                log.error("File not found: %s", target)
                return []
            video_files = [target]
        else:
            video_files = sorted(
                f for f in folder.iterdir()
                if f.suffix.lower() in extensions and f.is_file()
            )

        return [self.analyze(vf) for vf in video_files]
