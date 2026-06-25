#!/usr/bin/env python3
"""Local, free slide OCR — frame extraction (PyAV) + RapidOCR (ONNX).

No cloud, no API key, nothing leaves the machine. Recovers TEXT (numbers, labels,
table cells) from on-screen slides. Does NOT interpret chart shapes/diagrams — for
those, an optional vision pass is needed (see ocr/README.md).

Usage:
  # OCR specific timestamps (validate analysis/ocr-candidates.md):
  uv run ocr/extract_and_ocr.py "<video.mkv>" --timestamps 26:10,31:54 --save-frames
  # Sweep a whole video (sample every N seconds, dedupe static slides):
  uv run ocr/extract_and_ocr.py "<video.mkv>" --interval 4
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def parse_ts(s: str) -> float:
    p = [float(x) for x in s.split(":")]
    return p[0] if len(p) == 1 else p[0] * 60 + p[1] if len(p) == 2 else p[0] * 3600 + p[1] * 60 + p[2]


def fmt_ts(t: float) -> str:
    h, m, s = int(t // 3600), int(t % 3600 // 60), int(t % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def ahash(img) -> int:
    px = list(img.convert("L").resize((16, 16)).getdata())
    avg = sum(px) / len(px)
    return sum(1 << i for i, v in enumerate(px) if v > avg)


def grab_frame(container, stream, ts: float):
    container.seek(int(ts / stream.time_base), stream=stream, backward=True)
    last = None
    for frame in container.decode(stream):
        last = frame
        if frame.time is not None and frame.time >= ts:
            return frame
    return last


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("video")
    ap.add_argument("--timestamps", help="comma list, MM:SS / HH:MM:SS / seconds")
    ap.add_argument("--interval", type=float, help="sweep: sample every N seconds")
    ap.add_argument("--out", default=None, help="output dir (default: <video dir>/ocr/<stem>)")
    ap.add_argument("--save-frames", action="store_true", help="also write the PNG frames")
    args = ap.parse_args()

    import av
    import numpy as np
    from rapidocr_onnxruntime import RapidOCR

    video = Path(args.video)
    if not video.exists():
        print(f"ERROR: no such video: {video}", file=sys.stderr)
        return 2
    out_dir = Path(args.out) if args.out else video.parent / "ocr" / video.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    container = av.open(str(video))
    stream = container.streams.video[0]
    dur = float(stream.duration * stream.time_base) if stream.duration else (container.duration or 0) / 1e6

    if args.timestamps:
        tss = [parse_ts(s.strip()) for s in args.timestamps.split(",")]
    elif args.interval:
        n = int(dur / args.interval) if dur else 0
        tss = [i * args.interval for i in range(n)]
    else:
        print("give --timestamps or --interval", file=sys.stderr)
        return 2

    engine = RapidOCR()
    results, last_hash = [], None
    for ts in tss:
        frame = grab_frame(container, stream, ts)
        if frame is None:
            continue
        img = frame.to_image()
        h = ahash(img)
        if args.interval and last_hash is not None and bin(h ^ last_hash).count("1") < 8:
            continue  # near-identical static slide — skip
        last_hash = h
        res, _ = engine(np.array(img))
        text = "\n".join(line[1] for line in res) if res else ""
        results.append({"ts": round(ts, 1), "tc": fmt_ts(ts), "text": text})
        if args.save_frames:
            img.save(out_dir / f"{int(ts):06d}.png")
        print(f"--- {fmt_ts(ts)} ---\n{text}\n")

    (out_dir / "ocr.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    container.close()
    print(f"{len(results)} frame(s) OCR'd -> {out_dir}/ocr.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
