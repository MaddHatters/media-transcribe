#!/usr/bin/env python3
"""Video quality analysis script for MasterClass recordings on the obs-machine.

Runs ON the Windows obs-machine.  Analyzes MKV recordings captured via OBS
screen capture, detecting quality issues: black frames, frozen frames, audio
silence gaps, and bitrate drops.

Deployed to:  C:\\Users\\Matt\\agent-control\\scripts\\video_analyzer.py
Invoked by:   acquire/analyze_recordings.py on devbox-01 via SSH.

Usage (on the obs-machine directly):
  python video_analyzer.py "D:\\MasterClass Video Backup"
  python video_analyzer.py "D:\\MasterClass Video Backup" --single "Masterclass 1.mkv"
  python video_analyzer.py "D:\\MasterClass Video Backup" --output results.json
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Force UTF-8 output so the SSH stream doesn't emit cp1252 bytes
# (Windows console defaults to cp1252/cp437 which breaks the Linux receiver)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
FFMPEG = r"C:\Users\Matt\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe"
FFPROBE = r"C:\Users\Matt\AppData\Local\Microsoft\WinGet\Links\ffprobe.exe"

# Detection thresholds
BLACK_DETECT_DURATION = 0.5       # minimum black frame duration (seconds)
BLACK_DETECT_PIX_TH = 0.10       # pixel darkness threshold
BLACK_HEAD_WINDOW = 60            # scan first N seconds for black at start
BLACK_TAIL_WINDOW = 120           # scan last N seconds for black at end

FREEZE_NOISE_TH = 0.003          # freezedetect noise threshold
FREEZE_MIN_DURATION = 3           # minimum freeze duration (seconds)
FREEZE_FLAG_DURATION = 10         # flag video if any freeze > this
FREEZE_FLAG_COUNT = 3             # flag video if more than this many freezes

SILENCE_DB = -50                  # silence threshold in dB
SILENCE_MIN_DURATION = 5          # minimum silence gap (seconds)

BITRATE_DROP_THRESHOLD = 0.50    # flag if bitrate drops below 50% of average
BITRATE_DROP_MIN_DURATION = 5    # for at least this many seconds

# Output path on the obs-machine
DEFAULT_OUTPUT = r"C:\Users\Matt\agent-control\state\video_quality_report.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _run_cmd(
    cmd: list[str],
    *,
    timeout: int = 600,
) -> subprocess.CompletedProcess:
    """Run a subprocess, capturing stdout and stderr.

    On timeout, kills the process and returns a CompletedProcess with
    returncode=-1 and a descriptive stderr — caller checks returncode.
    """
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        # Return a synthetic result so callers don't crash
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=-1,
            stdout=exc.stdout or "" if isinstance(exc.stdout, str) else "",
            stderr=f"TIMEOUT after {timeout}s",
        )


def _timeout_for_duration(duration_sec: float, multiplier: float = 1.5) -> int:
    """Estimate a generous timeout based on video duration.

    For full-file ffmpeg filters (freeze/silence), processing speed is
    roughly 2-10× real-time on this machine.  We use 1.5× duration as a
    safe baseline, with a floor of 120s and cap of 7200s.
    """
    return max(120, min(7200, int(duration_sec * multiplier)))


def _format_duration(seconds: float) -> str:
    """Format seconds as H:MM:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h}:{m:02d}:{s:02d}"


def _parse_float(value: str | None, default: float = 0.0) -> float:
    """Safely parse a float from a string."""
    if not value:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Probe: basic metadata via ffprobe
# ---------------------------------------------------------------------------
def probe_metadata(filepath: Path) -> dict:
    """Extract basic video metadata using ffprobe.

    Returns dict with duration, resolution, codec, bitrate, file_size_mb.
    """
    result = _run_cmd([
        FFPROBE,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(filepath),
    ])

    if result.returncode != 0:
        raise RuntimeError(
            f"ffprobe failed for {filepath.name}: {result.stderr[:500]}"
        )

    data = json.loads(result.stdout)
    fmt = data.get("format", {})
    streams = data.get("streams", [])

    # Find video stream
    video_stream = next(
        (s for s in streams if s.get("codec_type") == "video"),
        {},
    )

    duration = _parse_float(fmt.get("duration"))
    width = int(video_stream.get("width", 0))
    height = int(video_stream.get("height", 0))
    codec = video_stream.get("codec_name", "unknown")
    bitrate = _parse_float(fmt.get("bit_rate")) / 1000  # bps -> kbps
    file_size_mb = filepath.stat().st_size / (1024 * 1024)

    return {
        "duration_seconds": round(duration, 2),
        "duration_display": _format_duration(duration),
        "resolution": f"{width}x{height}" if width and height else "unknown",
        "codec": codec,
        "avg_bitrate_kbps": round(bitrate, 1),
        "file_size_mb": round(file_size_mb, 1),
    }


# ---------------------------------------------------------------------------
# Black frame detection (start/end)
# ---------------------------------------------------------------------------
def detect_black_frames(filepath: Path, duration: float) -> list[dict]:
    """Detect black frames at the start and end of the video.

    Only scans the first BLACK_HEAD_WINDOW seconds and last BLACK_TAIL_WINDOW
    seconds to keep analysis fast on large files.
    """
    black_frames: list[dict] = []

    # --- Scan start of video (decode first 60s — fast, no seeking) ---
    result = _run_cmd([
        FFMPEG, "-i", str(filepath),
        "-t", str(BLACK_HEAD_WINDOW),
        "-vf", f"blackdetect=d={BLACK_DETECT_DURATION}:pix_th={BLACK_DETECT_PIX_TH}",
        "-an", "-f", "null", "-",
    ], timeout=300)

    if result.returncode == -1:
        print("    WARNING: black-start detection timed out", flush=True)
    else:
        stderr = result.stderr or ""
        for match in re.finditer(
            r"black_start:(\S+)\s+black_end:(\S+)\s+black_duration:(\S+)",
            stderr,
        ):
            start = _parse_float(match.group(1))
            end = _parse_float(match.group(2))
            dur = _parse_float(match.group(3))
            # Only include if it touches the very beginning
            if start < 1.0:
                black_frames.append({
                    "start": round(start, 2),
                    "end": round(end, 2),
                    "duration": round(dur, 2),
                    "location": "start",
                })

    # --- Scan end of video (use -ss BEFORE -i for fast keyframe seeking) ---
    tail_start = max(0, duration - BLACK_TAIL_WINDOW)
    result = _run_cmd([
        FFMPEG,
        "-ss", str(tail_start),   # fast seek (before -i = input seeking)
        "-i", str(filepath),
        "-vf", f"blackdetect=d={BLACK_DETECT_DURATION}:pix_th={BLACK_DETECT_PIX_TH}",
        "-an", "-f", "null", "-",
    ], timeout=300)

    if result.returncode == -1:
        print("    WARNING: black-end detection timed out", flush=True)
    else:
        stderr = result.stderr or ""
        for match in re.finditer(
            r"black_start:(\S+)\s+black_end:(\S+)\s+black_duration:(\S+)",
            stderr,
        ):
            # Adjust timestamps: with input seeking, ffmpeg reports times
            # relative to the seek point
            start = _parse_float(match.group(1)) + tail_start
            end = _parse_float(match.group(2)) + tail_start
            dur = _parse_float(match.group(3))
            # Only include if it touches the very end
            if end >= duration - 1.0:
                black_frames.append({
                    "start": round(start, 2),
                    "end": round(end, 2),
                    "duration": round(dur, 2),
                    "location": "end",
                })

    return black_frames


# ---------------------------------------------------------------------------
# Frozen frame detection
# ---------------------------------------------------------------------------
def detect_freezes(filepath: Path, duration: float = 0) -> list[dict]:
    """Detect frozen frames (no change for FREEZE_MIN_DURATION+ seconds).

    Indicates buffering or stalls during screen-capture recording.
    """
    timeout = _timeout_for_duration(duration) if duration > 0 else 1800
    result = _run_cmd([
        FFMPEG, "-i", str(filepath),
        "-vf", f"freezedetect=n={FREEZE_NOISE_TH}:d={FREEZE_MIN_DURATION}",
        "-an", "-f", "null", "-",
    ], timeout=timeout)

    if result.returncode == -1:
        print(f"    WARNING: freeze detection timed out after {timeout}s", flush=True)
        return []

    freezes: list[dict] = []
    stderr = result.stderr or ""

    # freezedetect outputs pairs: freeze_start / freeze_end+freeze_duration
    starts: list[float] = []
    for match in re.finditer(r"freeze_start:\s*(\S+)", stderr):
        starts.append(_parse_float(match.group(1)))

    ends_and_durations: list[tuple[float, float]] = []
    for match in re.finditer(
        r"freeze_end:\s*(\S+).*?freeze_duration:\s*(\S+)",
        stderr,
    ):
        ends_and_durations.append((
            _parse_float(match.group(1)),
            _parse_float(match.group(2)),
        ))

    for i, (end, dur) in enumerate(ends_and_durations):
        start = starts[i] if i < len(starts) else end - dur
        freezes.append({
            "start": round(start, 2),
            "end": round(end, 2),
            "duration": round(dur, 2),
            "start_display": _format_duration(start),
        })

    return freezes


# ---------------------------------------------------------------------------
# Audio silence detection
# ---------------------------------------------------------------------------
def detect_silence(filepath: Path, duration: float = 0) -> list[dict]:
    """Detect audio silence gaps longer than SILENCE_MIN_DURATION seconds."""
    timeout = _timeout_for_duration(duration, multiplier=0.5) if duration > 0 else 600
    result = _run_cmd([
        FFMPEG, "-i", str(filepath),
        "-vn",  # skip video — audio analysis only
        "-af", f"silencedetect=n={SILENCE_DB}dB:d={SILENCE_MIN_DURATION}",
        "-f", "null", "-",
    ], timeout=timeout)

    if result.returncode == -1:
        print(f"    WARNING: silence detection timed out after {timeout}s", flush=True)
        return []

    silences: list[dict] = []
    stderr = result.stderr or ""

    starts: list[float] = []
    for match in re.finditer(r"silence_start:\s*(\S+)", stderr):
        starts.append(_parse_float(match.group(1)))

    for match in re.finditer(
        r"silence_end:\s*(\S+)\s*\|\s*silence_duration:\s*(\S+)",
        stderr,
    ):
        end = _parse_float(match.group(1))
        dur = _parse_float(match.group(2))
        start = starts.pop(0) if starts else end - dur

        # Skip silence at the very start (before content begins) and very end
        # — those are covered by black frame detection
        if start < 2.0 or end < 2.0:
            continue

        silences.append({
            "start": round(start, 2),
            "end": round(end, 2),
            "duration": round(dur, 2),
            "start_display": _format_duration(start),
        })

    return silences


# ---------------------------------------------------------------------------
# Bitrate analysis (per-second)
# ---------------------------------------------------------------------------
def analyze_bitrate(filepath: Path, avg_bitrate_kbps: float) -> list[dict]:
    """Analyze per-second bitrate for significant drops.

    Uses ffprobe to get per-frame sizes, aggregates to per-second, and
    flags sustained drops below BITRATE_DROP_THRESHOLD of average.
    """
    # Skip if average bitrate is unknown/zero
    if avg_bitrate_kbps <= 0:
        return []

    result = _run_cmd([
        FFPROBE,
        "-v", "quiet",
        "-select_streams", "v:0",
        "-show_entries", "packet=pts_time,size",
        "-print_format", "csv=p=0",
        str(filepath),
    ], timeout=1200)

    if result.returncode != 0:
        if result.returncode == -1:
            print("    WARNING: bitrate analysis timed out", flush=True)
        return []

    # Aggregate packet sizes by second
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

    # Find contiguous runs of low bitrate
    sorted_secs = sorted(second_bytes.keys())
    drop_start: int | None = None
    drop_min_kbps: float = float("inf")

    for sec in sorted_secs:
        kbps = (second_bytes[sec] * 8) / 1000  # bytes -> kbps (1-second window)

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
                        "start": drop_start,
                        "end": sec,
                        "duration": drop_duration,
                        "min_bitrate_kbps": round(drop_min_kbps, 1),
                        "avg_bitrate_kbps": round(avg_bitrate_kbps, 1),
                        "start_display": _format_duration(drop_start),
                    })
                drop_start = None
                drop_min_kbps = float("inf")

    # Close any trailing drop
    if drop_start is not None:
        last_sec = sorted_secs[-1]
        drop_duration = last_sec - drop_start
        if drop_duration >= BITRATE_DROP_MIN_DURATION:
            drops.append({
                "start": drop_start,
                "end": last_sec,
                "duration": drop_duration,
                "min_bitrate_kbps": round(drop_min_kbps, 1),
                "avg_bitrate_kbps": round(avg_bitrate_kbps, 1),
                "start_display": _format_duration(drop_start),
            })

    return drops


# ---------------------------------------------------------------------------
# Trim point calculation
# ---------------------------------------------------------------------------
def compute_trim_points(
    duration: float,
    black_frames: list[dict],
) -> tuple[float | None, float | None]:
    """Compute suggested trim start and end from black frame data.

    Returns (trim_start, trim_end) — either or both may be None if
    no trimming is suggested.
    """
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

    # Sanity: trim_start must be before trim_end
    if trim_start is not None and trim_end is not None:
        if trim_start >= trim_end:
            trim_start = None
            trim_end = None

    # Only suggest trim if it actually removes something meaningful (> 0.5s)
    if trim_start is not None and trim_start < 0.5:
        trim_start = None
    if trim_end is not None and (duration - trim_end) < 0.5:
        trim_end = None

    return trim_start, trim_end


# ---------------------------------------------------------------------------
# Quality verdict
# ---------------------------------------------------------------------------
def compute_verdict(
    *,
    black_frames: list[dict],
    freezes: list[dict],
    silence_gaps: list[dict],
    bitrate_drops: list[dict],
    trim_start: float | None,
    trim_end: float | None,
) -> tuple[str, str]:
    """Determine quality verdict and generate a human-readable note.

    Returns (verdict, notes) where verdict is one of:
      - "clean"        — no issues, maybe minor trim needed
      - "trim_needed"  — black frames at start/end, otherwise fine
      - "has_issues"   — some freezes or silence gaps, might be acceptable
      - "re_record"    — major issues
    """
    issues: list[str] = []
    severity = 0  # 0=clean, 1=trim, 2=has_issues, 3=re_record

    # Black frames
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

    # Freezes
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

    # Silence gaps (skip if they coincide with freezes — already counted)
    non_freeze_silences = silence_gaps  # simplified; could cross-reference
    if non_freeze_silences:
        max_silence = max(s["duration"] for s in non_freeze_silences)
        if max_silence > 30:
            severity = max(severity, 3)
            issues.append(
                f"{len(non_freeze_silences)} silence gap(s), "
                f"longest {max_silence:.1f}s — MAJOR"
            )
        elif len(non_freeze_silences) > 5:
            severity = max(severity, 2)
            issues.append(
                f"{len(non_freeze_silences)} silence gap(s), "
                f"longest {max_silence:.1f}s"
            )

    # Bitrate drops
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
            issues.append(
                f"{len(bitrate_drops)} bitrate drop(s)"
            )

    verdicts = {0: "clean", 1: "trim_needed", 2: "has_issues", 3: "re_record"}
    verdict = verdicts.get(severity, "re_record")

    if issues:
        notes = "; ".join(issues)
    elif trim_start is not None or trim_end is not None:
        notes = "Minor trim only, otherwise clean"
    else:
        notes = "No issues detected"

    return verdict, notes


# ---------------------------------------------------------------------------
# Analyze a single video
# ---------------------------------------------------------------------------
def analyze_video(filepath: Path, index: int, total: int) -> dict:
    """Run all analysis passes on a single video file.

    Returns a dict with all metadata, detections, and verdict.
    """
    filename = filepath.name
    print(f"Analyzing {index}/{total}: {filename}", flush=True)

    # Step 1: Basic metadata
    print(f"  [1/5] Probing metadata...", flush=True)
    try:
        meta = probe_metadata(filepath)
    except RuntimeError as e:
        print(f"  ERROR: {e}", file=sys.stderr, flush=True)
        return {
            "filename": filename,
            "error": str(e),
            "verdict": "re_record",
            "notes": f"Could not probe file: {e}",
        }

    duration = meta["duration_seconds"]
    avg_bitrate = meta["avg_bitrate_kbps"]
    print(
        f"  Duration: {meta['duration_display']}, "
        f"Resolution: {meta['resolution']}, "
        f"Size: {meta['file_size_mb']:.0f} MB",
        flush=True,
    )

    # Step 2: Black frame detection
    print(f"  [2/5] Detecting black frames...", flush=True)
    black_frames = detect_black_frames(filepath, duration)
    if black_frames:
        print(f"    Found {len(black_frames)} black region(s)", flush=True)

    # Step 3: Frozen frame detection
    print(f"  [3/5] Detecting frozen frames...", flush=True)
    freezes = detect_freezes(filepath, duration)
    if freezes:
        print(f"    Found {len(freezes)} freeze(s)", flush=True)
        for f in freezes:
            print(
                f"      {f['start_display']} — {f['duration']:.1f}s",
                flush=True,
            )

    # Step 4: Audio silence detection
    print(f"  [4/5] Detecting audio silence gaps...", flush=True)
    silence_gaps = detect_silence(filepath, duration)
    if silence_gaps:
        print(f"    Found {len(silence_gaps)} silence gap(s)", flush=True)

    # Step 5: Bitrate analysis
    print(f"  [5/5] Analyzing bitrate...", flush=True)
    bitrate_drops = analyze_bitrate(filepath, avg_bitrate)
    if bitrate_drops:
        print(f"    Found {len(bitrate_drops)} bitrate drop(s)", flush=True)

    # Compute trim points and verdict
    trim_start, trim_end = compute_trim_points(duration, black_frames)
    verdict, notes = compute_verdict(
        black_frames=black_frames,
        freezes=freezes,
        silence_gaps=silence_gaps,
        bitrate_drops=bitrate_drops,
        trim_start=trim_start,
        trim_end=trim_end,
    )

    print(f"  Verdict: {verdict.upper()} — {notes}", flush=True)

    result = {
        "filename": filename,
        **meta,
        "verdict": verdict,
        "notes": notes,
        "black_frames": black_frames,
        "freezes": freezes,
        "silence_gaps": silence_gaps,
        "bitrate_drops": bitrate_drops,
    }

    if trim_start is not None:
        result["trim_start"] = round(trim_start, 2)
    if trim_end is not None:
        result["trim_end"] = round(trim_end, 2)

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="Analyze MasterClass video recordings for quality issues.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "video_dir",
        help="Directory containing MKV video files to analyze",
    )
    ap.add_argument(
        "--single",
        metavar="FILENAME",
        help="Analyze only this file (basename, e.g. 'Masterclass 1.mkv')",
    )
    ap.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"Output JSON report path (default: {DEFAULT_OUTPUT})",
    )
    ap.add_argument(
        "--skip-bitrate",
        action="store_true",
        help="Skip per-frame bitrate analysis (much faster)",
    )
    args = ap.parse_args()

    video_dir = Path(args.video_dir)
    if not video_dir.is_dir():
        print(f"ERROR: not a directory: {video_dir}", file=sys.stderr)
        return 1

    # Verify ffmpeg and ffprobe are available
    for tool_path, tool_name in [(FFMPEG, "ffmpeg"), (FFPROBE, "ffprobe")]:
        if not Path(tool_path).exists():
            print(
                f"ERROR: {tool_name} not found at {tool_path}",
                file=sys.stderr,
            )
            return 1

    # Discover video files
    extensions = {".mkv", ".mp4", ".avi", ".webm", ".mov"}
    if args.single:
        target = video_dir / args.single
        if not target.exists():
            print(f"ERROR: file not found: {target}", file=sys.stderr)
            return 1
        video_files = [target]
    else:
        video_files = sorted(
            f for f in video_dir.iterdir()
            if f.suffix.lower() in extensions and f.is_file()
        )

    if not video_files:
        print(f"ERROR: no video files found in {video_dir}", file=sys.stderr)
        return 1

    total = len(video_files)
    print(f"\nFound {total} video file(s) in {video_dir}", flush=True)
    print(f"{'=' * 60}", flush=True)

    # Analyze each video sequentially
    results: list[dict] = []
    for i, vf in enumerate(video_files, 1):
        print(f"\n{'—' * 60}", flush=True)
        entry = analyze_video(vf, i, total)
        results.append(entry)

    # Build summary counts
    summary: dict[str, int] = {
        "clean": 0,
        "trim_needed": 0,
        "has_issues": 0,
        "re_record": 0,
    }
    for r in results:
        v = r.get("verdict", "re_record")
        summary[v] = summary.get(v, 0) + 1

    report = {
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "video_dir": str(video_dir),
        "total_videos": total,
        "summary": summary,
        "videos": results,
    }

    # Write report
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Print summary
    print(f"\n\n{'=' * 60}", flush=True)
    print("ANALYSIS COMPLETE", flush=True)
    print(f"{'=' * 60}", flush=True)
    print(f"  Total:        {total}", flush=True)
    print(f"  Clean:        {summary['clean']}", flush=True)
    print(f"  Trim needed:  {summary['trim_needed']}", flush=True)
    print(f"  Has issues:   {summary['has_issues']}", flush=True)
    print(f"  Re-record:    {summary['re_record']}", flush=True)
    print(f"\nReport saved to: {output_path}", flush=True)

    # Machine-readable output line (for the orchestrator to parse)
    print(f"REPORT:{output_path}", flush=True)
    print(f"RESULT:{json.dumps({'ok': True, 'report_path': str(output_path), 'total': total, 'summary': summary})}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
