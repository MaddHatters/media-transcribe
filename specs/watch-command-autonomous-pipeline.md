# Plan: Add `watch` Command — Autonomous Content Pipeline

## Task Description

Build a `cli.py watch` subcommand that combines content discovery (Phase 2) with pipeline execution into an autonomous, recurring loop. The watcher discovers new Patreon content on a configurable interval, caps the batch size, runs the pipeline on new videos, and writes structured status to disk. It supports graceful shutdown (finish current video, don't leave OBS recording), deferred start via `--start-at`, and a `--status` flag to inspect the running watcher from another terminal.

## Objective

When complete:
```bash
# Start autonomous pipeline — discover + record every 24h starting at 10pm:
uv run cli.py watch --source patreon --every 24h --start-at "22:00"

# Check watcher status from another terminal:
uv run cli.py watch --status

# Dry-run — discover but don't record:
uv run cli.py watch --source patreon --every 24h --dry-run
```

The watcher runs indefinitely, surviving individual cycle failures. It writes `state/watch_status.json` after each cycle for observability.

## Problem Statement

Discovery and pipeline are currently separate manual operations:
1. Run `cli.py discover` to find new content
2. Run `cli.py pipeline --queue <file>` to process it

This requires human intervention to connect the two. The watch command closes that gap — a single SSH command starts an autonomous content pipeline that runs overnight or indefinitely.

## Solution Approach

A `ContentWatcher` class in `src/pipeline/watcher.py` owns the main loop:
1. Wait until `--start-at` time (if specified) using existing `wait_until()` logic
2. Run discovery → diff catalog → filter to video posts → cap at `--max-per-run`
3. Run pipeline on the batch (unless `--dry-run`)
4. Write status JSON
5. Sleep for `--every` interval
6. Repeat from step 2

Signal handling: install custom SIGTERM/SIGINT handlers that set a shutdown flag. If the watcher is sleeping between cycles, the sleep gets interrupted and the loop exits cleanly. If it's mid-pipeline, the flag is checked after each video finishes — the current video completes but no more are started.

The status file lets `watch --status` work from a separate terminal without any IPC.

## Relevant Files

Use these files to complete the task:

- **`cli.py`** — Add `watch` subcommand to `build_parser()`, add `watch` to `LONG_RUNNING_COMMANDS`, add handler in `main()`. Reference: existing `discover` handler (line 454–499) for async discovery pattern, `pipeline` handler (line 316–400) for pipeline setup pattern.
- **`src/pipeline/runner.py`** — `Pipeline` class and `PipelineResult` dataclass. The watcher instantiates `Pipeline` and calls `pipeline.run()` on each batch. Reference: how the pipeline handler sets up `source`, `engine`, `output_dir`, `enable_breaks`, `preflight` (cli.py lines 350–389).
- **`src/sources/discovery.py`** — `PatreonDiscovery` class. The watcher calls `discover()` and `diff_catalog()` each cycle. Reference: how the `discover` CLI handler uses it (cli.py lines 464–498). Note: `diff_catalog()` returns `(new_posts, all_posts)` as `list[DiscoveredPost]` — NOT dicts. The `DiscoveredPost` dataclass has `has_video`, `url`, `title`, `post_id` fields.
- **`src/sources/base.py`** — `Post` dataclass with `url`, `title`, `filename` fields. The watcher converts `DiscoveredPost` → `Post` for the pipeline.
- **`src/config.py`** — `STATE_DIR` (Windows: `C:\Users\Matt\agent-control\state`), `BACKUP_DIR`, `IS_WINDOWS`. Status file goes to `STATE_DIR / "watch_status.json"`.
- **`src/logging_config.py`** — `setup_logging()` registers signal handlers and atexit guards. The watcher overrides these signal handlers after setup_logging runs.
- **`src/cdp.py`** — `CDPClient` async context manager. The watcher creates a fresh CDP client per discovery cycle (don't hold a browser connection across 24h sleeps).
- **`AGENTS.md`** — Add "Automated Watch" section with SSH usage examples.
- **`tests/test_start_at.py`** — Reference for mocking `datetime`, `time.sleep`, and `os.getpid`.
- **`tests/test_discovery.py`** — Reference for `_make_cdp_with_network()`, mock CDP patterns, `PatreonDiscovery` fixture.
- **`tests/test_pipeline.py`** — Reference for mocking `Pipeline`, `PipelineResult`.

### New Files

- **`src/pipeline/watcher.py`** — `ContentWatcher` class with the main loop, signal handling, status writing
- **`tests/test_watcher.py`** — Tests for interval enforcement, batch capping, status file, shutdown, error resilience, dry-run

## Implementation Phases

### Phase 1: Foundation

Create `ContentWatcher` with constructor, interval validation, and status file writing. Add `watch` subparser to CLI.

### Phase 2: Core Implementation

Implement the main loop (`run_forever`), discovery integration (`_discover`), pipeline integration (`_run_pipeline`), graceful shutdown, and dry-run mode.

### Phase 3: Integration & Polish

Write tests, update AGENTS.md, validate full test suite.

## Step by Step Tasks

IMPORTANT: Execute every step in order, top to bottom.

### 1. Write tests first (TDD)

Create `tests/test_watcher.py` with the following test cases. Import `ContentWatcher` from `src.pipeline.watcher`.

**Fixtures:**
```python
@pytest.fixture
def watcher():
    return ContentWatcher(
        source="patreon",
        interval_hours=24.0,
        steps=["record", "analyze", "transcribe", "correct"],
        max_per_run=3,
    )

@pytest.fixture
def status_dir(tmp_path):
    return tmp_path
```

**Interval enforcement tests:**
- `test_interval_minimum_enforced` — `ContentWatcher(interval_hours=6.0)` stores `12.0` (clamped)
- `test_interval_at_minimum_accepted` — `ContentWatcher(interval_hours=12.0)` stores `12.0` (no clamping)
- `test_interval_above_minimum_accepted` — `ContentWatcher(interval_hours=24.0)` stores `24.0`
- `test_interval_zero_clamped` — `ContentWatcher(interval_hours=0)` stores `12.0`

**Batch capping tests:**
- `test_max_per_run_caps_batch` — Given 5 posts and `max_per_run=3`, only 3 are processed
- `test_max_per_run_no_cap_needed` — Given 2 posts and `max_per_run=3`, all 2 are processed
- `test_max_per_run_default` — Default `max_per_run` is 3

**Status file tests:**
- `test_write_status_creates_file` — After `_write_status()`, the status JSON file exists and is valid JSON
- `test_write_status_structure` — Status JSON has keys: `running`, `pid`, `cycle`, `last_run`, `next_run`, `last_result`, `total_recorded`, `started_at`
- `test_read_status_from_file` — `read_status()` (static/classmethod) loads and returns the status dict
- `test_read_status_no_file` — `read_status()` returns `None` when no status file exists

**CLI `--status` flag tests:**
- `test_watch_status_flag_parsed` — `build_parser()` accepts `watch --status`
- `test_watch_every_flag_parsed` — `build_parser()` accepts `watch --every 24h`
- `test_watch_source_default` — `--source` defaults to `"patreon"`
- `test_watch_max_per_run_default` — `--max-per-run` defaults to 3
- `test_watch_dry_run_flag` — `--dry-run` flag is accepted and defaults to False
- `test_watch_foreground_flag` — `--foreground` flag is accepted
- `test_watch_start_at_flag` — `--start-at` flag is accepted

**Shutdown tests:**
- `test_shutdown_flag_stops_loop` — Set `watcher._shutdown = True` before starting; loop exits after one cycle without sleeping
- `test_shutdown_writes_final_status` — After shutdown, status file has `"running": false`

**Error resilience tests:**
- `test_discovery_failure_doesnt_crash_loop` — Mock `_discover` to raise `Exception`; the loop logs the error and continues to the next cycle (verify it sleeps and attempts another cycle)
- `test_pipeline_failure_doesnt_crash_loop` — Mock `_run_pipeline` to raise `Exception`; same behavior

**Dry-run tests:**
- `test_dry_run_discovers_but_skips_pipeline` — With `dry_run=True`, `_discover` is called but `_run_pipeline` is NOT called
- `test_dry_run_still_writes_status` — Dry-run still writes status file with discovery results

**Interval parsing tests (helper function in cli.py):**
- `test_parse_interval_24h` — `"24h"` → `24.0`
- `test_parse_interval_12h` — `"12h"` → `12.0`
- `test_parse_interval_6h` — `"6h"` → `6.0` (will be clamped by ContentWatcher)
- `test_parse_interval_invalid` — `"foo"` raises `ValueError`

### 2. Create `src/pipeline/watcher.py` — ContentWatcher class

```python
"""Autonomous content discovery + recording loop."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.sources.discovery import DiscoveredPost

log = logging.getLogger(__name__)

MIN_INTERVAL_HOURS = 12.0


class ContentWatcher:
    def __init__(
        self,
        source: str,
        interval_hours: float,
        steps: list[str],
        max_per_run: int = 3,
        dry_run: bool = False,
        status_dir: Path | None = None,
    ):
        self.source = source
        self.interval_hours = max(interval_hours, MIN_INTERVAL_HOURS)
        self.steps = steps
        self.max_per_run = max_per_run
        self.dry_run = dry_run

        from src.config import STATE_DIR
        self._status_dir = status_dir or STATE_DIR
        self._status_path = self._status_dir / "watch_status.json"

        self._shutdown = False
        self._sleeping = False
        self._cycle = 0
        self._total_recorded = 0
        self._started_at = datetime.now().isoformat()

    def _install_signal_handlers(self) -> None:
        def _handler(signum, frame):
            log.info("[watch] Received %s — shutting down gracefully", signal.Signals(signum).name)
            self._shutdown = True
            if self._sleeping:
                raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, _handler)
        signal.signal(signal.SIGINT, _handler)
        from src.config import IS_WINDOWS
        if IS_WINDOWS:
            signal.signal(signal.SIGBREAK, _handler)

    async def run_forever(self) -> None:
        self._install_signal_handlers()
        log.info("[watch] Starting autonomous watcher (interval=%.1fh, max_per_run=%d, dry_run=%s)",
                 self.interval_hours, self.max_per_run, self.dry_run)

        while not self._shutdown:
            self._cycle += 1
            log.info("[watch] Cycle %d starting at %s", self._cycle, datetime.now().isoformat())
            cycle_result = {"new_found": 0, "recorded": 0, "failed": 0}

            try:
                new_posts = await self._discover()
                cycle_result["new_found"] = len(new_posts) if new_posts else 0

                if new_posts and not self.dry_run:
                    batch = new_posts[:self.max_per_run]
                    if len(new_posts) > self.max_per_run:
                        log.info("[watch] Capping at %d (remaining saved for next cycle)", self.max_per_run)
                    ok, failed = await self._run_pipeline(batch)
                    cycle_result["recorded"] = ok
                    cycle_result["failed"] = failed
                    self._total_recorded += ok
                elif new_posts and self.dry_run:
                    log.info("[watch] Dry-run: found %d new video(s), skipping pipeline", len(new_posts))
                else:
                    log.info("[watch] No new content found")

            except Exception as exc:
                log.error("[watch] Cycle %d failed: %s", self._cycle, exc)

            next_run = datetime.now() + timedelta(hours=self.interval_hours)
            self._write_status(
                running=not self._shutdown,
                last_result=cycle_result,
                next_run=next_run.isoformat(),
            )

            if self._shutdown:
                break

            log.info("[watch] Next cycle at %s", next_run.isoformat())
            try:
                self._sleeping = True
                await asyncio.sleep(self.interval_hours * 3600)
            except (KeyboardInterrupt, asyncio.CancelledError):
                log.info("[watch] Sleep interrupted — shutting down")
                break
            finally:
                self._sleeping = False

        self._write_status(running=False, last_result=cycle_result, next_run=None)
        log.info("[watch] Watcher stopped after %d cycles (%d total recorded)",
                 self._cycle, self._total_recorded)

    async def _discover(self) -> list[DiscoveredPost]:
        from src.sources.discovery import PatreonDiscovery
        from src.cdp import CDPClient
        from src.sources.patreon import PatreonSource
        from src.config import LOCAL_DATA

        discovery = PatreonDiscovery(cooldown_hours=0)
        catalog_path = LOCAL_DATA / "patreon_catalog.json"

        async with CDPClient() as cdp:
            source = PatreonSource()
            if not await source.authenticate(cdp):
                log.error("[watch] Patreon authentication failed")
                return []

            all_posts = await discovery.discover(cdp, full_catalog=False)
            new_posts, merged = discovery.diff_catalog(all_posts, catalog_path)
            discovery.save_catalog(merged, catalog_path)

        video_posts = [p for p in new_posts if p.has_video]
        if video_posts:
            log.info("[watch] Found %d new video(s)", len(video_posts))
        return video_posts

    async def _run_pipeline(self, posts: list[DiscoveredPost]) -> tuple[int, int]:
        from src.pipeline.runner import Pipeline
        from src.engines.obs_engine import OBSEngine
        from src.sources.patreon import PatreonSource
        from src.sources.base import Post
        from src.config import BACKUP_DIR
        from src.capture.environment import EnvironmentManager
        from src.capture.preflight import Preflight

        env = EnvironmentManager()
        env_ok, env_messages = env.setup()
        for msg in env_messages:
            log.info("[watch] %s", msg)
        if not env_ok:
            log.error("[watch] Environment setup failed")
            return 0, len(posts)

        pf = Preflight()
        pf_ok, _ = pf.run_all()
        if not pf_ok:
            log.error("[watch] Preflight failed")
            return 0, len(posts)

        engine = OBSEngine()
        source = PatreonSource()
        pipeline = Pipeline(
            source=source, engine=engine, output_dir=BACKUP_DIR,
            enable_breaks=True, preflight=pf,
        )

        post_objects = [
            Post(url=p.url, title=p.title)
            for p in posts
        ]

        results = await pipeline.run(post_objects, steps=self.steps)
        ok = sum(1 for r in results if not r.steps_failed)
        failed = len(results) - ok
        log.info("[watch] Pipeline complete: %d/%d succeeded", ok, len(results))
        return ok, failed

    def _write_status(self, running: bool, last_result: dict, next_run: str | None) -> None:
        status = {
            "running": running,
            "pid": os.getpid(),
            "cycle": self._cycle,
            "last_run": datetime.now().isoformat(),
            "next_run": next_run,
            "last_result": last_result,
            "total_recorded": self._total_recorded,
            "started_at": self._started_at,
        }
        self._status_dir.mkdir(parents=True, exist_ok=True)
        self._status_path.write_text(
            json.dumps(status, indent=2), encoding="utf-8",
        )

    @staticmethod
    def read_status(status_dir: Path | None = None) -> dict | None:
        from src.config import STATE_DIR
        path = (status_dir or STATE_DIR) / "watch_status.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
```

Key design decisions:
- **`cooldown_hours=0` in discovery**: The watcher manages its own schedule — discovery's built-in cooldown would interfere with the `--every` interval.
- **Fresh CDP client per cycle**: Don't hold a browser connection across 24h sleeps. Each `_discover()` call opens and closes its own CDP session.
- **`Post.__post_init__` handles filename sanitization**: No need to duplicate the bad-chars logic from `base.py`. Just pass `url` and `title` to `Post()`.
- **Signal handlers raise `KeyboardInterrupt` during sleep**: This cleanly interrupts `asyncio.sleep()` without needing a separate event loop mechanism.
- **Environment + preflight per pipeline run**: The watcher re-runs preflight before each pipeline batch because Chrome/OBS state may change over 24h.

### 3. Add interval parsing helper to `cli.py`

Add a `parse_interval()` function after `wait_until()`:

```python
def parse_interval(value: str) -> float:
    """Parse an interval string like '24h' or '12h' into hours."""
    value = value.strip().lower()
    if value.endswith("h"):
        try:
            return float(value[:-1])
        except ValueError:
            pass
    raise ValueError(f"Invalid interval: {value} (use e.g. '24h', '12h')")
```

### 4. Add `watch` subcommand to `build_parser()` in `cli.py`

Add after the `discover` subparser (before `return ap`):

```python
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
```

### 5. Add `watch` to `LONG_RUNNING_COMMANDS`

Change line 31 of `cli.py`:

```python
LONG_RUNNING_COMMANDS = {"record", "transcribe", "analyze", "pipeline", "watch"}
```

### 6. Add `watch` handler in `main()` in `cli.py`

Add `elif args.command == "watch":` block after the `discover` handler. Two code paths: `--status` (quick inline) and the full watcher (long-running).

```python
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
```

**Important subtlety**: When `--status` is used, the command is NOT long-running — it reads a file and exits. The `LONG_RUNNING_COMMANDS` check in `main()` (line 220) runs before the command handler, so `watch --status` would try to background. Fix this by checking `--status` before the backgrounding logic:

In the existing backgrounding check (line 220-226), modify to:
```python
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
```

### 7. Update AGENTS.md

Add an "Automated Watch" section after the existing "Execution" examples (after line 78, before the infrastructure section). Insert:

```markdown
### Automated Watch

```bash
# Start autonomous content pipeline — discover + record every 24h at 10pm:
ssh Matt@100.66.194.100 "cd C:\Users\Matt\transcribe; uv run cli.py watch --source patreon --every 24h --start-at '22:00'"

# Check watcher status:
ssh Matt@100.66.194.100 "cd C:\Users\Matt\transcribe; uv run cli.py watch --status"

# Dry-run — discover but don't record:
ssh Matt@100.66.194.100 "cd C:\Users\Matt\transcribe; uv run cli.py watch --source patreon --every 24h --dry-run"

# Custom pipeline steps and batch size:
ssh Matt@100.66.194.100 "cd C:\Users\Matt\transcribe; uv run cli.py watch --every 24h --steps record,transcribe,correct --max-per-run 5"
```

**Safety:** 12h minimum interval enforced, default 3 videos per cycle, graceful shutdown on SIGTERM/SIGINT (finishes current video).
```

### 8. Validate

- Run `uv run python -m py_compile src/pipeline/watcher.py` — compiles
- Run `uv run python -m py_compile cli.py` — compiles
- Run `uv run pytest tests/test_watcher.py -v` — all watcher tests pass
- Run `uv run pytest tests/test_cli.py -v` — existing CLI tests still pass
- Run `uv run pytest` — full suite passes (no regressions)
- Run `uv run cli.py watch --help` — shows all flags

## Testing Strategy

**Unit tests** cover all pure logic without requiring a browser, OBS, or network:

1. **Constructor validation** — interval clamping, default values, attribute storage. No mocks needed.
2. **Batch capping** — feed a list of mock posts, verify only `max_per_run` are passed to `_run_pipeline`. Mock `_discover` and `_run_pipeline` as `AsyncMock`.
3. **Status file** — use `tmp_path` for the status directory. Call `_write_status()` directly, verify JSON structure and content. Test `read_status()` classmethod with existing and missing files.
4. **Signal/shutdown** — set `watcher._shutdown = True`, call `run_forever()`, verify it exits after one cycle. Mock `_discover` to return empty list and `asyncio.sleep` to avoid real delays.
5. **Error resilience** — mock `_discover` to raise `Exception`, verify `run_forever()` doesn't crash (it logs and continues to sleep). Set `_shutdown = True` after one cycle to stop the loop. Same for `_run_pipeline`.
6. **Dry-run** — mock `_discover` to return posts, verify `_run_pipeline` is NOT called. Verify status file is still written.
7. **CLI argument parsing** — use `build_parser()` directly, assert arg values match.
8. **Interval parsing** — test `parse_interval()` with valid and invalid inputs.

**Mock patterns:**
- For loop tests, mock `asyncio.sleep` to avoid real delays and set `watcher._shutdown = True` in a side effect to break after N cycles
- For discovery/pipeline, mock `_discover` and `_run_pipeline` as `AsyncMock` returning controlled data
- For status tests, set `watcher._status_dir` to `tmp_path`

## Acceptance Criteria

- `uv run cli.py watch --help` shows all flags: `--source`, `--every`, `--start-at`, `--steps`, `--max-per-run`, `--dry-run`, `--foreground`, `--status`
- `watch` is in `LONG_RUNNING_COMMANDS` (auto-backgrounds over SSH)
- `watch --status` is a quick inline command (does NOT auto-background)
- Interval below 12h is clamped to 12h
- `--max-per-run` caps the batch size per cycle
- `--dry-run` discovers but does not run the pipeline
- `--start-at` defers the first cycle using existing `wait_until()`
- Status file written to `state/watch_status.json` after each cycle
- Status file has: `running`, `pid`, `cycle`, `last_run`, `next_run`, `last_result`, `total_recorded`, `started_at`
- Discovery failure in one cycle does not crash the loop
- Pipeline failure in one cycle does not crash the loop
- SIGTERM/SIGINT: finish current video → stop loop → write final status
- `uv run pytest` — full test suite passes (no regressions)
- AGENTS.md updated with "Automated Watch" section

## Validation Commands

Execute these commands to validate the task is complete:

- `uv run python -m py_compile src/pipeline/watcher.py` — Watcher module compiles
- `uv run python -m py_compile cli.py` — CLI changes compile
- `uv run pytest tests/test_watcher.py -v` — All watcher tests pass
- `uv run pytest tests/test_cli.py -v` — Existing CLI tests still pass
- `uv run pytest` — Full test suite passes (no regressions)
- `uv run cli.py watch --help` — Shows usage with all flags

## Notes

- No new dependencies needed — `asyncio`, `json`, `signal`, `os`, `datetime` are all stdlib.
- The watcher sets `cooldown_hours=0` on `PatreonDiscovery` because it manages its own schedule. Discovery's built-in 12h cooldown would conflict with the watcher's `--every` interval.
- Each discovery cycle opens a fresh `CDPClient` context — don't hold a browser WebSocket across 24h sleeps.
- `Post.__post_init__()` in `src/sources/base.py` handles filename sanitization automatically — no need to duplicate that logic when converting `DiscoveredPost` → `Post`.
- Environment setup and preflight run before every pipeline batch (not once at watcher start) because Chrome/OBS state may change between cycles.
- The `--status` flag reads a file — no IPC, no socket, no shared state. This is intentionally simple.
- The watcher saves the catalog after each discovery cycle via `discovery.save_catalog()`, so posts that weren't processed this cycle (due to `max_per_run` cap) won't appear as "new" next cycle. They're in the catalog. **This means over-capped posts are effectively skipped.** If this is undesirable, the watcher should maintain its own pending queue in the status file. For v1, the simpler approach is fine — discovery only shows truly new posts, and the `max_per_run` cap is a safety valve, not a queueing mechanism. Document this behavior.
