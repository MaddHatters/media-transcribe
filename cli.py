#!/usr/bin/env python3
"""Unified CLI for the media-transcribe pipeline.

Long-running commands (record, transcribe, analyze, pipeline) run in the
background by default — the process detaches and output goes to a log file.
Use --foreground to run in the terminal instead.

Usage:
    uv run cli.py transcribe <folder> [--only "name"] [--model large-v3-turbo]
    uv run cli.py analyze <folder> [--single "file.mp4"]
    uv run cli.py correct <transcripts-folder> [--dry-run]
    uv run cli.py find-gaps <transcripts-folder> [--output gaps.yaml]
    uv run cli.py extract-frames --gaps gaps.yaml --videos <folder> --out <folder>
    uv run cli.py preflight
    uv run cli.py record --queue data/queues/conference.json [--start-at "22:00"]
    uv run cli.py pipeline --queue <file> [--steps record,transcribe,correct] [--start-at "HH:MM"]
    uv run cli.py transfer-transcripts [--apply-corrections] [--force]
    uv run cli.py screenshot
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

LONG_RUNNING_COMMANDS = {"record", "transcribe", "analyze", "pipeline", "watch"}


def background_relaunch(args: argparse.Namespace, log_dir: Path) -> int:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"{args.command}_{timestamp}.log"
    log_dir.mkdir(parents=True, exist_ok=True)

    uv_path = shutil.which("uv")
    if uv_path:
        child_cmd = [uv_path, "run"] + sys.argv + ["--foreground"]
    else:
        child_cmd = [sys.executable] + sys.argv + ["--foreground"]

    fh = open(log_file, "w", buffering=1)  # noqa: SIM115

    kwargs: dict = {
        "stdout": fh,
        "stderr": fh,
        "env": os.environ.copy(),
        "cwd": os.getcwd(),
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True

    proc = subprocess.Popen(child_cmd, **kwargs)

    time.sleep(1)
    if proc.poll() is not None:
        print(f"ERROR: child exited immediately with code {proc.returncode}")
        print(f"Check log: {log_file}")
        return proc.returncode or 1

    print(f"PID:     {proc.pid}")
    print(f"Log:     {log_file}")
    print(f"Command: {' '.join(child_cmd)}")
    print(f"Tail:    tail -f {log_file}")
    return 0


def wait_until(start_at: str) -> int:
    """Sleep until the specified time. Returns 0 on success, 1 on parse error."""
    now = datetime.now()
    target = None
    for fmt in ("%Y-%m-%d %H:%M", "%H:%M"):
        try:
            target = datetime.strptime(start_at, fmt)
            if fmt == "%H:%M":
                target = target.replace(year=now.year, month=now.month, day=now.day)
                if target <= now:
                    target += timedelta(days=1)
            break
        except ValueError:
            continue

    if target is None:
        print(f"Invalid --start-at format: {start_at} (use 'HH:MM' or 'YYYY-MM-DD HH:MM')")
        return 1

    delta = (target - now).total_seconds()
    if delta > 0:
        print(f"Scheduled: waiting until {target.strftime('%Y-%m-%d %H:%M')}")
        print(f"   ({delta/3600:.1f} hours / {delta/60:.0f} minutes from now)")
        print(f"   PID: {os.getpid()}")
        time.sleep(delta)
        print(f"Wake up! Starting at {datetime.now().strftime('%H:%M:%S')}")
    return 0


def parse_interval(value: str) -> float:
    """Parse an interval string like '24h' or '12h' into hours."""
    value = value.strip().lower()
    if value.endswith("h"):
        try:
            return float(value[:-1])
        except ValueError:
            pass
    raise ValueError(f"Invalid interval: {value} (use e.g. '24h', '12h')")


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
    t.add_argument("--foreground", action="store_true",
                   help="Run in foreground instead of backgrounding (default: background)")

    # --- analyze ---
    a = sub.add_parser("analyze", help="Analyze video quality")
    a.add_argument("folder", help="Folder containing video files")
    a.add_argument("--single", default=None, help="Analyze only this file")
    a.add_argument("--output", default=None, help="Output JSON path")
    a.add_argument("--foreground", action="store_true",
                   help="Run in foreground instead of backgrounding (default: background)")

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
    r.add_argument("--start-at", default=None,
        help="Delay start until this time (format: 'YYYY-MM-DD HH:MM' or 'HH:MM' for today)")
    r.add_argument("--foreground", action="store_true",
                   help="Run in foreground instead of backgrounding (default: background)")

    # --- pipeline ---
    p = sub.add_parser("pipeline", help="Run the full pipeline")
    p.add_argument("--queue", required=True, help="Queue JSON file")
    p.add_argument("--steps", default=None, help="Comma-separated step names")
    p.add_argument("--output-dir", default=None,
        help="Output directory for recordings (default: D:\\MasterClass Video Backup)")
    p.add_argument("--no-shuffle", action="store_true",
        help="Process queue in original order")
    p.add_argument("--no-breaks", action="store_true",
        help="Skip human-like breaks between videos")
    p.add_argument("--skip-preflight", action="store_true",
        help="Skip preflight validation checks")
    p.add_argument("--test-mode", action="store_true",
        help="Use local test video instead of Patreon (no network access needed)")
    p.add_argument("--start-at", default=None,
        help="Delay start until this time (format: 'YYYY-MM-DD HH:MM' or 'HH:MM' for today)")
    p.add_argument("--foreground", action="store_true",
                   help="Run in foreground instead of backgrounding (default: background)")

    # --- generate-test-video ---
    gtv = sub.add_parser("generate-test-video", help="Generate test video for --test-mode")
    gtv.add_argument("--duration", type=int, default=60, help="Duration in seconds")

    # --- transfer-transcripts ---
    tt = sub.add_parser("transfer-transcripts", help="Sync transcripts from obs-machine")
    tt.add_argument("--apply-corrections", action="store_true")
    tt.add_argument("--force", action="store_true")
    tt.add_argument("--dry-run", action="store_true")

    # --- setup ---
    sub.add_parser("setup", help="Launch Chrome + OBS and configure recording environment")

    # --- teardown ---
    sub.add_parser("teardown", help="Stop recording and close Chrome + OBS")

    # --- screenshot ---
    sub.add_parser("screenshot", help="Take a screenshot via OBS")

    # --- release-info ---
    sub.add_parser("release-info", help="Show version, commit, and deploy status")

    # --- discover ---
    d = sub.add_parser("discover", help="Discover content from Patreon")
    d.add_argument("--full-catalog", action="store_true",
        help="Fetch all posts (paginate through entire history)")
    d.add_argument("--video-only", action="store_true", default=True,
        help="Only discover video posts (default: True)")
    d.add_argument("--all-types", action="store_true",
        help="Discover all post types, not just video")
    d.add_argument("--output", default="data/patreon_catalog.json",
        help="Catalog output path")
    d.add_argument("--queue-new", default=None,
        help="Write new (unrecorded) video posts to a queue file")
    d.add_argument("--force", action="store_true",
        help="Ignore cooldown timer")
    d.add_argument("--campaign-id", default="5008493",
        help="Patreon campaign ID (default: Mr. FIRED Up Wealth)")

    # --- watch ---
    w = sub.add_parser("watch", help="Autonomous content discovery + recording loop")
    w.add_argument("--source", default="patreon",
        help="Content source (default: patreon)")
    w.add_argument("--every", required=False, default=None,
        help="Interval between runs (e.g. '24h', '12h'). Minimum: 12h")
    w.add_argument("--start-at", default=None,
        help="Time of first run (format: 'HH:MM' or 'YYYY-MM-DD HH:MM')")
    w.add_argument("--steps", default=None,
        help="Pipeline steps to run (default: record,analyze,transcribe,correct)")
    w.add_argument("--max-per-run", type=int, default=3,
        help="Maximum videos to process per cycle (default: 3)")
    w.add_argument("--dry-run", action="store_true",
        help="Discover but don't record")
    w.add_argument("--foreground", action="store_true",
        help="Don't auto-background")
    w.add_argument("--status", action="store_true",
        help="Show watcher status and exit")

    return ap


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    is_foreground = getattr(args, "foreground", False) or args.command not in LONG_RUNNING_COMMANDS
    from src.logging_config import setup_logging
    log_path = setup_logging(args.command, foreground=is_foreground)

    if args.command in LONG_RUNNING_COMMANDS and not getattr(args, "foreground", False):
        if args.command == "watch" and getattr(args, "status", False):
            pass  # --status is a quick inline command
        else:
            from src.config import IS_WINDOWS, LOGS_DIR
            import logging
            log = logging.getLogger("cli")
            log.info("Backgrounding %s — log at %s", args.command, log_path)
            log_dir = LOGS_DIR if IS_WINDOWS else Path("/tmp")
            return background_relaunch(args, log_dir)

    if args.command in LONG_RUNNING_COMMANDS and getattr(args, "foreground", False):
        import logging
        log = logging.getLogger("cli")
        log.info("Child process started: %s", " ".join(sys.argv))

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
        if args.start_at:
            rc = wait_until(args.start_at)
            if rc:
                return rc

    elif args.command == "pipeline":
        import asyncio
        from src.pipeline.runner import Pipeline
        from src.capture.batch import load_queue, filter_unseen, mild_shuffle
        from src.sources.base import Post
        from src.config import BACKUP_DIR

        queue_data = load_queue(Path(args.queue))
        steps = [s.replace("-", "_") for s in args.steps.split(",")] if args.steps else None
        has_record = not steps or "record" in steps

        skipped_seen = 0
        if has_record:
            queue_data, skipped_seen = filter_unseen(queue_data)
            if skipped_seen:
                print(f"Skipping {skipped_seen} already-recorded URL(s)")
            if not args.no_shuffle and len(queue_data) > 1:
                queue_data = mild_shuffle(queue_data)

        if not queue_data:
            print("No entries to process.")
            return 0

        if args.start_at:
            print(f"   Queue: {args.queue} ({len(queue_data)} videos)")
            rc = wait_until(args.start_at)
            if rc:
                return rc

        if args.test_mode:
            print("*** TEST MODE — using local test video ***")

        posts = [Post(url=e["url"], title=e.get("title", e["filename"]),
                      filename=e["filename"]) for e in queue_data]

        engine = None
        source = None
        if has_record:
            from src.engines.obs_engine import OBSEngine
            engine = OBSEngine()
            if args.test_mode:
                from src.sources.test_source import TestSource
                source = TestSource()
            else:
                from src.sources.patreon import PatreonSource
                source = PatreonSource()

        output_dir = Path(args.output_dir) if args.output_dir else BACKUP_DIR

        if has_record:
            from src.capture.environment import EnvironmentManager
            env = EnvironmentManager()
            env_ok, env_messages = env.setup()
            for msg in env_messages:
                print(msg)
            if not env_ok:
                print("Environment setup failed — aborting")
                return 1

        pf = None
        if has_record and not args.skip_preflight:
            from src.capture.preflight import Preflight
            pf = Preflight(skip_patreon=args.test_mode)
            ok, gates = pf.run_all()
            if not ok:
                print("Preflight failed — aborting")
                return 1

        pipeline = Pipeline(
            source=source, engine=engine, output_dir=output_dir,
            enable_breaks=has_record and not args.no_breaks,
            preflight=pf,
        )
        results = asyncio.run(pipeline.run(posts, steps=steps))

        ok_count = sum(1 for r in results if not r.steps_failed)
        fail_count = len(results) - ok_count
        print(f"\nResults: {ok_count}/{len(results)} succeeded")
        if skipped_seen:
            print(f"Skipped: {skipped_seen} (already recorded)")
        if fail_count:
            for r in results:
                if r.steps_failed:
                    print(f"  FAILED: {r.post_title} — {r.steps_failed}")
        return 1 if fail_count else 0

    elif args.command == "generate-test-video":
        from test_assets.generate_test_video import generate
        out = Path("test_assets/test_video.mp4")
        out.parent.mkdir(exist_ok=True)
        generate(out, duration=args.duration)
        return 0

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

    elif args.command == "setup":
        from src.capture.environment import EnvironmentManager
        env = EnvironmentManager()
        ok, messages = env.setup()
        for msg in messages:
            print(msg)
        return 0 if ok else 1

    elif args.command == "teardown":
        from src.capture.environment import EnvironmentManager
        env = EnvironmentManager()
        ok, messages = env.teardown()
        for msg in messages:
            print(msg)
        return 0 if ok else 1

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

    elif args.command == "discover":
        import json as json_mod
        from src.sources.discovery import PatreonDiscovery, DiscoveredPost, MAX_PAGES

        discovery = PatreonDiscovery(campaign_id=args.campaign_id)

        if args.full_catalog and not args.force:
            state_dir = Path("data")
            if not discovery.check_cooldown(state_dir):
                print("Cooldown active. Use --force to override.")
                return 0

        media_type = None if args.all_types else "video"
        max_pages = MAX_PAGES if args.full_catalog else 1

        label = "all" if args.full_catalog else "latest"
        type_label = media_type or "all"
        print(f"Discovering {label} {type_label} posts...")
        posts = discovery.fetch_posts(media_type=media_type, max_pages=max_pages)

        catalog_path = Path(args.output)
        new_posts = discovery.diff_catalog(posts, catalog_path)

        if catalog_path.exists():
            existing = json_mod.loads(catalog_path.read_text(encoding="utf-8"))
            existing_by_id = {p["post_id"]: p for p in existing.get("posts", [])}
            from dataclasses import asdict
            discovered_by_id = {p.post_id: p for p in posts}
            all_posts = list(discovered_by_id.values())
            valid_fields = {f.name for f in DiscoveredPost.__dataclass_fields__.values()}
            for pid, pdata in existing_by_id.items():
                if pid not in discovered_by_id and pdata is not None:
                    filtered = {k: v for k, v in pdata.items() if k in valid_fields}
                    filtered.setdefault("post_id", pid)
                    filtered.setdefault("url", f"https://www.patreon.com/posts/{pid}")
                    filtered.setdefault("title", "")
                    filtered.setdefault("created_at", "")
                    filtered.setdefault("post_type", "")
                    filtered.setdefault("has_video", False)
                    all_posts.append(DiscoveredPost(**filtered))
        else:
            all_posts = posts

        discovery.save_catalog(all_posts, catalog_path)

        if args.full_catalog:
            discovery.update_cooldown(Path("data"))

        video_count = sum(1 for p in posts if p.has_video)
        print(f"\nDiscovery complete:")
        print(f"  Total found: {len(posts)}")
        print(f"  Video posts: {video_count}")
        print(f"  New: {len(new_posts)}")
        if new_posts:
            print(f"\n  New posts:")
            for p in new_posts[:10]:
                print(f"    {p.created_at[:10]}  {p.title[:70]}")

        if args.queue_new and new_posts:
            video_posts = [p for p in new_posts if p.has_video]
            bad = '<>:"/\\|?*'
            queue = []
            for p in video_posts:
                cleaned = "".join("_" if c in bad else c for c in p.title).strip()
                filename = cleaned if cleaned.strip("_ ") else "episode"
                queue.append({"url": p.url, "filename": filename})
            Path(args.queue_new).parent.mkdir(parents=True, exist_ok=True)
            Path(args.queue_new).write_text(
                json_mod.dumps(queue, indent=2), encoding="utf-8")
            print(f"\n  Queue written: {len(queue)} videos to {args.queue_new}")

        return 0

    elif args.command == "watch":
        if args.status:
            from src.pipeline.watcher import ContentWatcher
            status = ContentWatcher.read_status()
            if status is None:
                print("No watcher running (no status file found)")
                return 0
            print(f"Running:  {status['running']}")
            print(f"PID:      {status['pid']}")
            print(f"Cycle:    {status['cycle']}")
            print(f"Last run: {status['last_run']}")
            print(f"Next run: {status['next_run']}")
            last = status.get("last_result", {})
            print(f"Last result: found={last.get('new_found', 0)}, "
                  f"recorded={last.get('recorded', 0)}, "
                  f"failed={last.get('failed', 0)}")
            print(f"Total recorded: {status['total_recorded']}")
            print(f"Started at:     {status['started_at']}")
            return 0

        if not args.every:
            print("--every is required (e.g. --every 24h)")
            return 1

        interval_hours = parse_interval(args.every)
        steps = [s.replace("-", "_") for s in args.steps.split(",")] if args.steps else None

        if args.start_at:
            rc = wait_until(args.start_at)
            if rc:
                return rc

        import asyncio
        from src.pipeline.watcher import ContentWatcher

        watcher = ContentWatcher(
            source=args.source,
            interval_hours=interval_hours,
            steps=steps or ["record", "analyze", "transcribe", "correct"],
            max_per_run=args.max_per_run,
            dry_run=args.dry_run,
        )
        asyncio.run(watcher.run_forever())

    elif args.command == "release-info":
        from src import __version__
        from src.config import SSH_HOST, REMOTE_PROJECT_DIR

        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True,
        ).stdout.strip() or "unknown"

        print(f"Version:  {__version__}")
        print(f"Commit:   {commit}")
        print(f"Target:   {SSH_HOST}:{REMOTE_PROJECT_DIR}/")

        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=5", SSH_HOST,
             f"cd {REMOTE_PROJECT_DIR}; uv run python -c "
             "\"from src import __version__; print(__version__)\""],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            remote_ver = result.stdout.strip()
            print(f"Deployed: {remote_ver}")
        else:
            print("Deployed: (unreachable)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
