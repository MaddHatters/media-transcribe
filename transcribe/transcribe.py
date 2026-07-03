#!/usr/bin/env python3
"""Local, offline transcription of a folder of videos using Whisper large-v3.

Reads every video in a folder, writes a clean .txt and a timestamped .srt per
video into a `transcripts/` subfolder (next to the source by default).

Everything runs locally on the CPU via faster-whisper (CTranslate2). No network,
no API key, no per-minute cost. Resumable: files already transcribed are skipped.

A single Whisper stream scales poorly past ~4-8 threads, so on a many-core CPU
it is much faster to run several videos at once with few threads each. Use
--workers for that (default 4 workers x 4 threads = 16 cores).

Usage:
    uv run transcribe.py "/mnt/secondary/media/patreon/FIRE Investing Masterclass"
    uv run transcribe.py "<folder>" --only "Masterclass 13"     # one file
    uv run transcribe.py "<folder>" --workers 4 --cpu-threads 4 # parallel
    uv run transcribe.py "<folder>" --model large-v3-turbo      # ~4x faster
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from corrections import apply_rules, load_rules

VIDEO_EXTS = {".mkv", ".mp4", ".mov", ".m4v", ".webm", ".avi", ".mp3", ".m4a", ".wav"}

# Per-worker globals, initialised once per process (model load is expensive).
_MODEL = None
_PROMPT = None
_BEAM = 5
_RULES: list = []


def fmt_ts(seconds: float) -> str:
    """Seconds -> SRT timestamp HH:MM:SS,mmm."""
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def load_prompt(path: Path | None) -> str | None:
    if path and path.exists():
        return " ".join(path.read_text(encoding="utf-8").split())
    return None


def _init_worker(model_name: str, compute_type: str, cpu_threads: int,
                 prompt: str | None, beam: int, corrections_path: str | None) -> None:
    global _MODEL, _PROMPT, _BEAM, _RULES
    from faster_whisper import WhisperModel
    _MODEL = WhisperModel(model_name, device="cpu",
                          compute_type=compute_type, cpu_threads=cpu_threads)
    _PROMPT = prompt
    _BEAM = beam
    _RULES = load_rules(corrections_path) if corrections_path else []


def _transcribe_one(src_str: str, out_str: str) -> tuple[str, str, float, float]:
    """Worker: transcribe one file -> .txt + .srt. Returns (name, status, audio_s, wall_s)."""
    src = Path(src_str)
    out_dir = Path(out_str)
    stem = src.stem
    txt_path = out_dir / f"{stem}.txt"
    srt_path = out_dir / f"{stem}.srt"
    if txt_path.exists() and srt_path.exists():
        return (stem, "skip", 0.0, 0.0)

    t0 = time.monotonic()
    segments, info = _MODEL.transcribe(
        str(src),
        language="en",
        beam_size=_BEAM,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        initial_prompt=_PROMPT,
        condition_on_previous_text=True,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_srt = srt_path.with_suffix(".srt.part")
    txt_lines: list[str] = []
    with tmp_srt.open("w", encoding="utf-8") as srt:
        for i, seg in enumerate(segments, start=1):
            text = seg.text.strip()
            if _RULES:
                text, _ = apply_rules(text, _RULES)
            srt.write(f"{i}\n{fmt_ts(seg.start)} --> {fmt_ts(seg.end)}\n{text}\n\n")
            txt_lines.append(text)
    tmp_srt.replace(srt_path)
    txt_path.write_text(" ".join(txt_lines) + "\n", encoding="utf-8")
    return (stem, "done", info.duration or 0.0, time.monotonic() - t0)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("folder", help="Folder containing video files")
    ap.add_argument("--model", default="large-v3", help="Whisper model (default: large-v3)")
    ap.add_argument("--out", default=None, help="Output dir (default: <folder>/transcripts)")
    ap.add_argument("--only", default=None, help="Substring filter on filename")
    ap.add_argument("--compute-type", default="int8", help="int8 | int8_float16 | float32")
    ap.add_argument("--workers", type=int, default=4, help="Videos transcribed in parallel")
    ap.add_argument("--cpu-threads", type=int, default=4, help="Threads per worker")
    ap.add_argument("--beam-size", type=int, default=5, help="Beam size (1 = greedy, faster)")
    ap.add_argument("--vocab", default=str(Path(__file__).parent / "finance_vocab.txt"),
                    help="initial_prompt vocab file (or '' to disable)")
    ap.add_argument("--corrections", default=str(Path(__file__).parent / "corrections.txt"),
                    help="post-processing correction dictionary (or '' to disable)")
    args = ap.parse_args()

    folder = Path(args.folder).expanduser()
    if not folder.is_dir():
        print(f"ERROR: not a folder: {folder}", file=sys.stderr)
        return 2

    out_dir = Path(args.out).expanduser() if args.out else folder / "transcripts"
    prompt = load_prompt(Path(args.vocab)) if args.vocab else None

    vids = sorted(
        p for p in folder.iterdir()
        if p.suffix.lower() in VIDEO_EXTS and (not args.only or args.only.lower() in p.name.lower())
    )
    if not vids:
        print(f"No videos found in {folder}" + (f" matching '{args.only}'" if args.only else ""))
        return 1

    workers = max(1, min(args.workers, len(vids)))
    print(f"Model '{args.model}' (compute={args.compute_type}) | "
          f"{workers} worker(s) x {args.cpu_threads} threads | beam={args.beam_size}")
    print(f"{len(vids)} file(s) -> {out_dir}\n(first run downloads weights ~1.5 GB)\n")

    batch_t0 = time.monotonic()
    done = skipped = 0
    audio_total = 0.0
    with ProcessPoolExecutor(
        max_workers=workers,
        initializer=_init_worker,
        initargs=(args.model, args.compute_type, args.cpu_threads, prompt,
                  args.beam_size, args.corrections or None),
    ) as ex:
        futs = {ex.submit(_transcribe_one, str(p), str(out_dir)): p for p in vids}
        for n, fut in enumerate(as_completed(futs), start=1):
            stem, status, audio_s, wall_s = fut.result()
            if status == "skip":
                skipped += 1
                print(f"[{n}/{len(vids)}] SKIP  {stem}")
            else:
                done += 1
                audio_total += audio_s
                rtf = (audio_s / wall_s) if wall_s else 0
                print(f"[{n}/{len(vids)}] DONE  {stem[:48]:<48} "
                      f"{audio_s/60:5.1f}m audio / {wall_s/60:4.1f}m  ({rtf:.1f}x)")

    wall = time.monotonic() - batch_t0
    agg = (audio_total / wall) if wall else 0
    print(f"\nFinished: {done} transcribed, {skipped} skipped in {wall/60:.1f} min "
          f"(aggregate {agg:.1f}x realtime).")
    print(f"Output in: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
