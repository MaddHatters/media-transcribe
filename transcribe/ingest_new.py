#!/usr/bin/env python3
"""Scan for new Patreon Masterclass videos and transcribe only the missing ones.

Compares .mkv files in the source directory against existing .txt + .srt
transcripts and feeds any gaps through the transcribe.py pipeline. Idempotent:
re-running when everything is already transcribed is a no-op.

Usage:
    uv run transcribe/ingest_new.py
    uv run transcribe/ingest_new.py /path/to/source --out /path/to/transcripts
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

DEFAULT_SOURCE = Path("/mnt/secondary/media/patreon/FIRE Investing Masterclass")


def find_new(source_dir: Path, transcripts_dir: Path) -> list[Path]:
    all_mkv = sorted(
        p for p in source_dir.iterdir()
        if p.suffix.lower() == ".mkv"
    )
    if not transcripts_dir.is_dir():
        return all_mkv
    done = {
        p.stem
        for p in transcripts_dir.glob("*.txt")
        if (transcripts_dir / f"{p.stem}.srt").exists()
    }
    return [v for v in all_mkv if v.stem not in done]


def ingest(source_dir: Path, transcripts_dir: Path, *, transcribe_fn=None) -> list[str]:
    new = find_new(source_dir, transcripts_dir)
    if not new:
        print("Nothing new to transcribe.")
        return []
    transcribe_fn = transcribe_fn or _default_transcribe
    print(f"{len(new)} new video(s) to transcribe:")
    for v in new:
        print(f"  {v.name}")
    for v in new:
        transcribe_fn(v, transcripts_dir)
    return [v.stem for v in new]


def _default_transcribe(video: Path, transcripts_dir: Path) -> None:
    subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent / "transcribe.py"),
         str(video.parent), "--only", video.stem, "--out", str(transcripts_dir)],
        check=True,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", nargs="?", default=str(DEFAULT_SOURCE),
                    help="Directory containing .mkv files (default: Patreon Masterclass path)")
    ap.add_argument("--out", default=None,
                    help="Output directory for transcripts (default: <source>/transcripts)")
    args = ap.parse_args()

    source = Path(args.source).expanduser()
    if not source.is_dir():
        print(f"ERROR: not a directory: {source}", file=sys.stderr)
        return 2

    out_dir = Path(args.out).expanduser() if args.out else source / "transcripts"
    out_dir.mkdir(parents=True, exist_ok=True)

    ingest(source, out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
