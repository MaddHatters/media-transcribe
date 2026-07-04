#!/usr/bin/env python3
"""Fetch a YouTube video's caption track and save it as a timestamped transcript.

A fast shortcut around the Whisper pipeline: when a YouTube video already has
captions (manual or auto-generated), pull them directly with yt-dlp instead of
downloading audio and running transcribe.py. Output is one .txt per video, one
line per caption cue: ``[M:SS] text``.

This trades quality for speed. YouTube auto-captions are unpunctuated and skip
this repo's finance vocab + ticker corrections. For the high-quality path,
download the audio (see patreon_download.sh / yt-dlp) and run transcribe.py.

No API key. yt-dlp is invoked via ``uvx yt-dlp``, matching patreon_download.sh.

Usage:
    uv run acquire/youtube_transcript.py https://www.youtube.com/watch?v=EBw7gsDPAYQ
    uv run acquire/youtube_transcript.py EBw7gsDPAYQ --dest transcripts
    uv run acquire/youtube_transcript.py <url> --lang en --keep-vtt
"""
from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

INDEX_FILENAME = "index.jsonl"
METADATA_FILENAME = "metadata.json"


@dataclass
class VideoMetadata:
    """The facts we persist about a video — notably its real publish date."""
    video_id: str
    title: str
    channel: str
    upload_date: str        # "YYYY-MM-DD" (publish date), or "" if unknown
    timestamp: int | None   # unix seconds at publish, or None
    url: str

# A YouTube video id is exactly 11 URL-safe base64 chars.
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_URL_ID_RE = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})")

# A VTT cue timing line, e.g. "00:01:02.500 --> 00:01:05.000 align:start".
_CUE_TIME_RE = re.compile(
    r"(\d{1,2}:\d{2}:\d{2}[.,]\d{3}|\d{1,2}:\d{2}[.,]\d{3})\s*-->\s*"
    r"(\d{1,2}:\d{2}:\d{2}[.,]\d{3}|\d{1,2}:\d{2}[.,]\d{3})"
)
_TAG_RE = re.compile(r"<[^>]+>")
_UNSAFE_FILENAME_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


def extract_video_id(value: str) -> str:
    """Accept a raw 11-char video id or any YouTube URL and return the id."""
    value = value.strip()
    if _VIDEO_ID_RE.match(value):
        return value
    match = _URL_ID_RE.search(value)
    if match:
        return match.group(1)
    raise ValueError(f"Could not extract a YouTube video id from: {value!r}")


def vtt_timestamp_to_seconds(timestamp: str) -> float:
    """Parse a VTT/SRT timestamp (HH:MM:SS.mmm or MM:SS.mmm) into seconds."""
    seconds = 0.0
    for part in timestamp.replace(",", ".").split(":"):
        seconds = seconds * 60 + float(part)
    return seconds


def format_timestamp(seconds: float) -> str:
    """Seconds -> ``M:SS`` (or ``H:MM:SS`` past an hour), matching the pi-skill."""
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def strip_vtt_tags(text: str) -> str:
    """Remove inline timing/markup tags and collapse whitespace to one line."""
    return " ".join(html.unescape(_TAG_RE.sub("", text)).split())


def parse_vtt(vtt_text: str) -> list[tuple[float, str]]:
    """Parse VTT captions into ``(start_seconds, text)`` cues, de-duplicated.

    YouTube auto-captions repeat text across a rolling two-line window and grow a
    line word-by-word; manual captions do not. We collapse both: a line that
    repeats or merely extends the previous one replaces it rather than adding a
    duplicate, so the output reads once through cleanly.
    """
    cues: list[tuple[float, str]] = []
    lines = vtt_text.splitlines()
    index = 0
    while index < len(lines):
        match = _CUE_TIME_RE.search(lines[index])
        if not match:
            index += 1
            continue
        start = vtt_timestamp_to_seconds(match.group(1))
        index += 1
        while index < len(lines) and lines[index].strip():
            clean = strip_vtt_tags(lines[index])
            index += 1
            if not clean:
                continue
            if cues:
                prev_start, prev_text = cues[-1]
                if clean == prev_text or prev_text.startswith(clean):
                    continue  # exact repeat or a shorter partial of what we have
                if clean.startswith(prev_text):
                    cues[-1] = (prev_start, clean)  # the growing line, extended
                    continue
            cues.append((start, clean))
    return cues


def render_transcript(cues: list[tuple[float, str]]) -> str:
    """Render cues as ``[M:SS] text`` lines."""
    return "\n".join(f"[{format_timestamp(start)}] {text}" for start, text in cues)


def sanitize_filename(name: str) -> str:
    """Strip characters that are unsafe in filenames across platforms."""
    cleaned = _UNSAFE_FILENAME_RE.sub("_", name).strip(" ._")
    return cleaned or "transcript"


def video_output_dir(dest: Path, channel: str, title: str, video_id: str) -> Path:
    """Per-video folder ``<dest>/<channel>/<title> [<id>]``.

    The video id keeps the folder unique — a channel often reuses a title across
    uploads, which would otherwise collide.
    """
    return dest / sanitize_filename(channel) / f"{sanitize_filename(title)} [{video_id}]"


def _pick_vtt(workdir: Path, video_id: str, lang: str) -> Path:
    """Return the best subtitle file yt-dlp wrote, preferring the requested lang."""
    candidates = sorted(workdir.glob(f"{video_id}*.vtt"))
    if not candidates:
        raise FileNotFoundError(
            f"No captions available for {video_id} (language {lang!r}). "
            "The video may have captions disabled; try the Whisper path instead."
        )
    for path in candidates:
        if f".{lang}" in path.name:
            return path
    return candidates[0]


def format_upload_date(raw: str | None) -> str:
    """yt-dlp's 'YYYYMMDD' upload_date -> 'YYYY-MM-DD' (or '' if missing/odd)."""
    if raw and raw.isdigit() and len(raw) == 8:
        return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
    return ""


def metadata_from_info(video_id: str, info: dict) -> VideoMetadata:
    """Build VideoMetadata from a yt-dlp info.json dict (accurate publish date)."""
    timestamp = info.get("timestamp")
    return VideoMetadata(
        video_id=video_id,
        title=info.get("title") or video_id,
        channel=info.get("channel") or info.get("uploader") or "unknown channel",
        upload_date=format_upload_date(info.get("upload_date")),
        timestamp=int(timestamp) if isinstance(timestamp, (int, float)) else None,
        url=f"https://www.youtube.com/watch?v={video_id}",
    )


def write_channel_index(channel_dir: Path) -> Path:
    """(Re)build ``<channel_dir>/index.jsonl`` from every video's metadata.json.

    One JSON object per line, sorted by publish date — a queryable record of
    what was published when. Rebuilt from the per-video files, so it never
    accumulates duplicates.
    """
    rows = []
    for meta_path in channel_dir.glob(f"*/{METADATA_FILENAME}"):
        rows.append(json.loads(meta_path.read_text(encoding="utf-8")))
    rows.sort(key=lambda row: (row.get("upload_date") or "", row.get("video_id") or ""))
    index_path = channel_dir / INDEX_FILENAME
    with index_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return index_path


def fetch_captions(video_id: str, lang: str, workdir: Path) -> tuple[Path, VideoMetadata]:
    """Download captions + metadata for one video into workdir via yt-dlp.

    Returns (vtt_path, VideoMetadata). Lets yt-dlp failures propagate.
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    subprocess.run(
        [
            "uvx", "yt-dlp",
            "--skip-download",
            "--write-subs", "--write-auto-subs",
            "--sub-langs", lang,
            "--sub-format", "vtt",
            "--convert-subs", "vtt",
            "--write-info-json",
            "--no-warnings",
            "-o", str(workdir / "%(id)s.%(ext)s"),
            url,
        ],
        check=True,
    )
    info_path = workdir / f"{video_id}.info.json"
    info = json.loads(info_path.read_text(encoding="utf-8")) if info_path.exists() else {}
    return _pick_vtt(workdir, video_id, lang), metadata_from_info(video_id, info)


def save_transcript(video_id: str, dest: Path, lang: str = "en",
                    keep_vtt: bool = False) -> tuple[Path, int]:
    """Fetch one video's captions and write ``transcript.txt`` into its folder.

    Output lands in ``<dest>/<channel>/<title> [<id>]/`` as ``transcript.txt``
    plus ``metadata.json`` (video id, title, channel, publish date, url). With
    ``--keep-vtt``, the raw .vtt and .info.json are kept there too. Returns
    (output_path, line_count). Raises FileNotFoundError when the video has no
    captions in the requested language, and propagates yt-dlp failures.
    """
    workdir = Path(tempfile.mkdtemp())
    try:
        vtt_path, meta = fetch_captions(video_id, lang, workdir)
        cues = parse_vtt(vtt_path.read_text(encoding="utf-8"))
        out_dir = video_output_dir(dest, meta.channel, meta.title, video_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "transcript.txt"
        out_path.write_text(render_transcript(cues) + "\n", encoding="utf-8")
        write_metadata(out_dir, meta, transcript_lines=len(cues))
        if keep_vtt:
            for extra in (vtt_path, workdir / f"{video_id}.info.json"):
                if extra.exists():
                    extra.replace(out_dir / extra.name)
        return out_path, len(cues)
    finally:
        for leftover in workdir.glob("*"):
            leftover.unlink()
        workdir.rmdir()


def write_metadata(out_dir: Path, meta: VideoMetadata, transcript_lines: int,
                   fetched_at: str | None = None) -> Path:
    """Write ``metadata.json`` for one video into its folder; return the path."""
    record = asdict(meta)
    record["transcript_lines"] = transcript_lines
    record["fetched_at"] = fetched_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    path = out_dir / METADATA_FILENAME
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("video", help="YouTube video id or URL")
    parser.add_argument("--dest", type=Path, default=Path("."),
                        help="output folder for the .txt transcript (default: .)")
    parser.add_argument("--lang", default="en",
                        help="caption language code to fetch (default: en)")
    parser.add_argument("--keep-vtt", action="store_true",
                        help="also keep the raw .vtt file next to the transcript")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    video_id = extract_video_id(args.video)
    try:
        out_path, line_count = save_transcript(video_id, args.dest, args.lang, args.keep_vtt)
    except subprocess.CalledProcessError as error:
        print(f"yt-dlp failed for {video_id}: exit {error.returncode}", file=sys.stderr)
        raise
    write_channel_index(out_path.parent.parent)
    print(f"Wrote {line_count} lines -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
