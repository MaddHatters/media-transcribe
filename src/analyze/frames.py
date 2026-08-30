"""Frame extraction from videos at specific timestamps using ffmpeg."""
from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


def _run_cmd(cmd: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            args=cmd, returncode=-1, stdout="", stderr="TIMEOUT",
        )


def parse_srt_timestamp(ts: str) -> float:
    """Parse 'HH:MM:SS,mmm' or 'HH:MM:SS,mmm --> ...' to seconds."""
    ts = ts.split("-->")[0].strip()
    match = re.match(r"(\d+):(\d+):(\d+)[,.](\d+)", ts)
    if not match:
        return 0.0
    h, m, s, ms = match.groups()
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def extract_frame(
    video_path: Path,
    timestamp: float,
    output_path: Path,
    ffmpeg: str = "ffmpeg",
) -> Path | None:
    """Extract a single frame at the given timestamp."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = _run_cmd([
        ffmpeg,
        "-ss", f"{timestamp:.3f}",
        "-i", str(video_path),
        "-frames:v", "1",
        "-q:v", "2",
        str(output_path),
    ])
    if result.returncode != 0:
        log.error("Frame extraction failed at %.1fs: %s", timestamp, result.stderr[:200])
        return None
    return output_path


def extract_frames_from_gaps(
    video_path: Path,
    gaps: list,
    output_dir: Path,
    ffmpeg: str = "ffmpeg",
) -> list[Path]:
    """Extract frames at each gap's timestamp."""
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for i, gap in enumerate(gaps):
        ts = parse_srt_timestamp(gap.timestamp)
        out = output_dir / f"gap_{i:04d}_{ts:.0f}s.jpg"
        result = extract_frame(video_path, ts, out, ffmpeg=ffmpeg)
        if result:
            paths.append(result)
    return paths
