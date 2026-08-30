#!/usr/bin/env python3
"""Unified CLI for the media-transcribe pipeline.

Usage:
    uv run cli.py transcribe <folder> [--only "name"] [--model large-v3-turbo]
    uv run cli.py analyze <folder> [--single "file.mp4"]
    uv run cli.py correct <transcripts-folder> [--dry-run]
    uv run cli.py find-gaps <transcripts-folder> [--output gaps.yaml]
    uv run cli.py extract-frames --gaps gaps.yaml --videos <folder> --out <folder>
    uv run cli.py preflight
    uv run cli.py record --queue data/queues/conference.json
    uv run cli.py pipeline --queue <file> [--steps record,transcribe,correct]
    uv run cli.py transfer-transcripts [--apply-corrections] [--force]
    uv run cli.py screenshot
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="media-transcribe — unified pipeline CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest="command", required=True)

    # --- transcribe ---
    t = sub.add_parser("transcribe", help="Transcribe videos in a folder")
    t.add_argument("folder", help="Folder containing video files")
    t.add_argument("--model", default="large-v3-turbo")
    t.add_argument("--out", default=None, help="Output dir (default: <folder>/transcripts)")
    t.add_argument("--only", default=None, help="Substring filter on filename")
    t.add_argument("--workers", type=int, default=1)
    t.add_argument("--cpu-threads", type=int, default=4)
    t.add_argument("--corrections", default="transcribe/corrections.txt")

    # --- analyze ---
    a = sub.add_parser("analyze", help="Analyze video quality")
    a.add_argument("folder", help="Folder containing video files")
    a.add_argument("--single", default=None, help="Analyze only this file")
    a.add_argument("--output", default=None, help="Output JSON path")

    # --- correct ---
    c = sub.add_parser("correct", help="Apply corrections to transcripts")
    c.add_argument("path", help="Transcripts folder or single file")
    c.add_argument("--corrections", default="transcribe/corrections.txt")
    c.add_argument("--dry-run", action="store_true")

    # --- find-gaps ---
    fg = sub.add_parser("find-gaps", help="Find visual-context gaps in SRT transcripts")
    fg.add_argument("transcripts_dir", help="Directory containing .srt files")
    fg.add_argument("--output", "-o", default=None, help="Output YAML file")

    # --- extract-frames ---
    ef = sub.add_parser("extract-frames", help="Extract video frames at gap timestamps")
    ef.add_argument("--gaps", required=True, help="Gaps YAML file")
    ef.add_argument("--videos", required=True, help="Video folder")
    ef.add_argument("--out", required=True, help="Output frames folder")

    # --- preflight ---
    sub.add_parser("preflight", help="Run preflight validation checks")

    # --- record ---
    r = sub.add_parser("record", help="Record videos from a queue")
    r.add_argument("--queue", required=True, help="Queue JSON file")

    # --- pipeline ---
    p = sub.add_parser("pipeline", help="Run the full pipeline")
    p.add_argument("--queue", required=True, help="Queue JSON file")
    p.add_argument("--steps", default=None, help="Comma-separated step names")

    # --- transfer-transcripts ---
    tt = sub.add_parser("transfer-transcripts", help="Sync transcripts from obs-machine")
    tt.add_argument("--apply-corrections", action="store_true")
    tt.add_argument("--force", action="store_true")
    tt.add_argument("--dry-run", action="store_true")

    # --- screenshot ---
    sub.add_parser("screenshot", help="Take a screenshot via OBS")

    return ap


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "transcribe":
        from src.transcribe.whisper_runner import WhisperRunner
        corrections = Path(args.corrections) if args.corrections else None
        runner = WhisperRunner(
            model=args.model, workers=args.workers,
            cpu_threads=args.cpu_threads,
        )
        out = Path(args.out) if args.out else None
        runner.transcribe_folder(
            Path(args.folder), output_dir=out,
            only=args.only, corrections=corrections,
        )

    elif args.command == "analyze":
        from src.analyze.quality import QualityAnalyzer
        analyzer = QualityAnalyzer()
        reports = analyzer.analyze_folder(Path(args.folder), single=args.single)
        for r in reports:
            print(f"{r.filename}: {r.verdict} — {r.notes}")

    elif args.command == "correct":
        from src.transcribe.corrections import apply_rules, load_rules
        rules = load_rules(args.corrections)
        if not rules:
            print(f"No rules loaded from {args.corrections}", file=sys.stderr)
            return 1
        root = Path(args.path)
        files = [root] if root.is_file() else sorted(root.rglob("*.txt")) + sorted(root.rglob("*.srt"))
        changed = 0
        for f in files:
            text = f.read_text(encoding="utf-8")
            new, counts = apply_rules(text, rules)
            if counts:
                changed += 1
                summary = ", ".join(f"{k}x{v}" for k, v in sorted(counts.items()))
                print(f"{'(dry) ' if args.dry_run else ''}{f.name}: {summary}")
                if not args.dry_run:
                    f.write_text(new, encoding="utf-8")
        print(f"{'Would change' if args.dry_run else 'Changed'} {changed}/{len(files)} files.")

    elif args.command == "find-gaps":
        from src.transcribe.visual_gaps import find_gaps_in_folder
        import yaml
        result = find_gaps_in_folder(Path(args.transcripts_dir))
        all_gaps = [g.__dict__ for gaps in result.values() for g in gaps]
        output_data = {"total_gaps": len(all_gaps), "gaps": all_gaps}
        yaml_str = yaml.dump(output_data, default_flow_style=False, sort_keys=False)
        if args.output:
            Path(args.output).write_text(yaml_str, encoding="utf-8")
            print(f"Saved {len(all_gaps)} gaps to {args.output}")
        else:
            print(yaml_str)

    elif args.command == "extract-frames":
        import yaml
        from src.analyze.frames import extract_frame, parse_srt_timestamp
        gaps_data = yaml.safe_load(Path(args.gaps).read_text(encoding="utf-8"))
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        videos_dir = Path(args.videos)
        for i, gap in enumerate(gaps_data.get("gaps", [])):
            ts = parse_srt_timestamp(gap.get("timestamp", "00:00:00,000"))
            video_file = gap.get("file", "").replace(".srt", ".mp4")
            video_path = videos_dir / video_file
            if video_path.exists():
                out = out_dir / f"gap_{i:04d}_{ts:.0f}s.jpg"
                extract_frame(video_path, ts, out)

    elif args.command == "preflight":
        from src.capture.preflight import Preflight
        pf = Preflight()
        ok, gates = pf.run_all()
        return 0 if ok else 1

    elif args.command == "record":
        from src.capture.batch import load_queue
        queue = load_queue(Path(args.queue))
        print(f"Loaded {len(queue)} entries from {args.queue}")

    elif args.command == "pipeline":
        import asyncio
        from src.pipeline.runner import Pipeline
        from src.capture.batch import load_queue
        from src.sources.base import Post
        queue_data = load_queue(Path(args.queue))
        posts = [Post(url=e["url"], title=e.get("title", e["filename"]),
                      filename=e["filename"]) for e in queue_data]
        steps = args.steps.split(",") if args.steps else None
        pipeline = Pipeline(source=None, engine=None)
        asyncio.run(pipeline.run(posts, steps=steps))

    elif args.command == "transfer-transcripts":
        from src.transfer.sync import TransferClient
        from src.config import LOCAL_TRANSCRIPTS
        client = TransferClient()
        remote_dir = "D:/MasterClass Video Backup/transcripts/"
        synced = client.sync_transcripts(remote_dir, LOCAL_TRANSCRIPTS, force=args.force)
        print(f"Synced {len(synced)} file(s)")
        if args.apply_corrections and synced:
            from src.transcribe.corrections import apply_rules, load_rules
            rules = load_rules("transcribe/corrections.txt")
            for fname in synced:
                fpath = LOCAL_TRANSCRIPTS / fname
                if fpath.exists():
                    text = fpath.read_text(encoding="utf-8")
                    new, counts = apply_rules(text, rules)
                    if counts and not args.dry_run:
                        fpath.write_text(new, encoding="utf-8")

    elif args.command == "screenshot":
        from src.engines.obs_engine import OBSEngine
        engine = OBSEngine()
        engine.connect()
        data = engine.get_screenshot()
        if data:
            print(f"Screenshot captured ({len(data)} bytes base64)")
        else:
            print("Screenshot failed", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
