#!/usr/bin/env python3
"""Full-video slide OCR sweep over a folder — local, free, no cloud.

For each video: decode KEYFRAMES only (slides are static, so keyframes catch them),
dedupe near-identical frames by perceptual hash, OCR the unique ones with RapidOCR.
Writes <video dir>/ocr/<stem>/slides.json (+ slides.md) per episode. Resumable.

Usage:
  uv run ocr/run_all.py "/mnt/secondary/media/patreon/FIRE Investing Masterclass"
  uv run ocr/run_all.py "<folder>" --only "Masterclass 7"
"""
from __future__ import annotations

import os

# OCR's small ONNX models don't scale past a few threads; onnxruntime otherwise
# grabs every core and oversubscribes. Cap before importing onnxruntime-backed libs.
# Override with OMP_NUM_THREADS in the environment if needed.
os.environ.setdefault("OMP_NUM_THREADS", "6")
os.environ.setdefault("OMP_WAIT_POLICY", "PASSIVE")

import argparse
import json
import sys
import time
from pathlib import Path

VIDEO_EXTS = {".mkv", ".mp4", ".mov", ".m4v", ".webm", ".avi"}


def fmt_ts(t: float) -> str:
    h, m, s = int(t // 3600), int(t % 3600 // 60), int(t % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def ahash(img) -> int:
    px = list(img.convert("L").resize((16, 16)).getdata())
    avg = sum(px) / len(px)
    return sum(1 << i for i, v in enumerate(px) if v > avg)


def sweep_video(video: Path, engine, min_gap: float = 2.0, hash_thresh: int = 8) -> list[dict]:
    """Keyframe-decode, dedupe, OCR. Returns [{ts, tc, text}]."""
    import av
    import numpy as np

    container = av.open(str(video))
    stream = container.streams.video[0]
    stream.codec_context.skip_frame = "NONKEY"  # keyframes only — fast

    out, last_hash, last_t = [], None, -1e9
    for frame in container.decode(stream):
        t = float(frame.time) if frame.time is not None else last_t
        if t - last_t < min_gap:
            continue
        img = frame.to_image()
        h = ahash(img)
        if last_hash is not None and bin(h ^ last_hash).count("1") < hash_thresh:
            continue  # near-identical slide
        last_hash, last_t = h, t
        res, _ = engine(np.array(img))
        text = "\n".join(line[1] for line in res).strip() if res else ""
        if text:
            out.append({"ts": round(t, 1), "tc": fmt_ts(t), "text": text})
    container.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("folder", help="folder of videos")
    ap.add_argument("--only", default=None, help="filename substring filter")
    ap.add_argument("--min-gap", type=float, default=2.0, help="min seconds between kept frames")
    args = ap.parse_args()

    from rapidocr_onnxruntime import RapidOCR

    folder = Path(args.folder).expanduser()
    vids = sorted(p for p in folder.iterdir()
                  if p.suffix.lower() in VIDEO_EXTS and (not args.only or args.only.lower() in p.name.lower()))
    if not vids:
        print(f"no videos in {folder}", file=sys.stderr)
        return 1

    engine = RapidOCR()
    print(f"OCR sweep over {len(vids)} video(s) -> <dir>/ocr/<stem>/slides.json\n")
    batch_t0 = time.monotonic()
    for i, video in enumerate(vids, 1):
        out_dir = video.parent / "ocr" / video.stem
        slides_json = out_dir / "slides.json"
        if slides_json.exists():
            print(f"[{i}/{len(vids)}] SKIP {video.stem} (done)")
            continue
        t0 = time.monotonic()
        print(f"[{i}/{len(vids)}] {video.stem} ...", flush=True)
        slides = sweep_video(video, engine, min_gap=args.min_gap)
        out_dir.mkdir(parents=True, exist_ok=True)
        slides_json.write_text(json.dumps(slides, indent=2), encoding="utf-8")
        md = "\n".join(f"## {s['tc']}\n\n{s['text']}\n" for s in slides)
        (out_dir / "slides.md").write_text(f"# {video.stem} — slide OCR\n\n{md}", encoding="utf-8")
        print(f"    {len(slides)} unique slides in {(time.monotonic()-t0)/60:.1f} min")

    print(f"\nDone in {(time.monotonic()-batch_t0)/60:.1f} min.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
