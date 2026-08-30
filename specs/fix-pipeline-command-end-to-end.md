# Plan: Fix `cli.py pipeline` command end-to-end

## Task Description

The `cli.py pipeline` command currently passes `Pipeline(source=None, engine=None)`, which means the record step crashes immediately because `Recorder(self._engine)` receives `None`. Beyond that, the pipeline runner is missing all the batch-orchestration behaviors from the old working `acquire/record_batch.py`: preflight checks, human-like breaks between videos, seen-file tracking, mild URL shuffling, inter-video health checks, file move-to-backup with retry, and Chrome window focusing before recording.

## Objective

Make `cli.py pipeline --queue <file> [--steps ...]` run end-to-end, producing results equivalent to the old `record_batch.py` workflow when the `record` step is included, while also supporting post-processing-only runs (`--steps transcribe,correct,find-gaps`) that skip recording entirely.

## Problem Statement

1. **Immediate crash**: `Pipeline(source=None, engine=None)` → `Recorder(None)` → `AttributeError` on any engine method call.
2. **No preflight**: The old workflow ran 7-gate startup validation before recording. The pipeline command skips it entirely.
3. **No breaks**: Videos are recorded back-to-back with zero delay, which triggers bot-detection.
4. **No seen-file tracking**: Already-recorded URLs are re-recorded every run.
5. **No shuffle**: URLs are processed in strict queue order, which looks bot-like.
6. **No file move**: Recordings stay in OBS's default output location instead of moving to `BACKUP_DIR`.
7. **No Chrome focus**: Fullscreen recording requires Chrome to be the foreground window on Windows.
8. **No health checks**: Inter-video recovery (Chrome/OBS restart) is missing.
9. **Hardcoded corrections path**: `transcribe/corrections.txt` won't exist on the obs-machine.
10. **Transcribe output directory**: Uses recording parent instead of a configurable output dir.
11. **No `--output-dir` CLI flag**: No way to override the default `BACKUP_DIR`.
12. **No result summary**: Pipeline exits silently with no indication of what succeeded or failed.

## Solution Approach

- Wire up `OBSEngine` and `PatreonSource` in the CLI handler with proper instantiation.
- Add `--output-dir`, `--no-shuffle`, `--no-breaks`, and `--skip-preflight` flags to the pipeline subcommand.
- Integrate batch-orchestration features (breaks, seen-file, shuffle, preflight, health checks) into `Pipeline.run()` via a new `BatchConfig`-style parameter, reusing the existing `src/capture/batch.py` functions rather than duplicating them.
- Fix `_step_record` to focus Chrome, move files to backup, and mark URLs as seen.
- Fix `_step_correct` to search multiple correction file locations.
- Fix `_step_transcribe` to use `self._output_dir / "transcripts"`.
- Add result summary printing in the CLI handler.

## Relevant Files

- `cli.py` (lines 110-115, 218-228) — pipeline subcommand argument definition and command handler
- `src/pipeline/runner.py` — `Pipeline` class, `run()`, and all `_step_*` methods
- `src/engines/obs_engine.py` — `OBSEngine` class (already complete, just needs instantiation)
- `src/sources/patreon.py` — `PatreonSource` class (already complete, just needs instantiation)
- `src/capture/batch.py` — `load_queue`, `filter_unseen`, `mild_shuffle`, `human_break`, `mark_seen`, `load_seen` (reuse these)
- `src/capture/preflight.py` — `Preflight` class (already complete)
- `src/capture/window.py` — `focus_chrome()` (already complete)
- `src/capture/recorder.py` — `Recorder` class (already complete)
- `src/config.py` — `BACKUP_DIR`, `BREAK_MIN_SECONDS`, `BREAK_MAX_SECONDS`, `IS_WINDOWS`
- `src/sources/base.py` — `Post` dataclass
- `tests/test_pipeline.py` — existing pipeline tests (must not break)

## Implementation Phases

### Phase 1: Foundation — CLI wiring and Pipeline instantiation

Fix the immediate crash by properly instantiating `OBSEngine`, `PatreonSource`, and passing them to `Pipeline`. Add the missing CLI flags.

### Phase 2: Core — Batch orchestration in Pipeline.run()

Add breaks, seen-file tracking, shuffle, preflight, health checks, file move, and Chrome focus to the pipeline runner. Reuse `src/capture/batch.py` functions.

### Phase 3: Fixes — Corrections path, transcribe output dir, summary

Fix the corrections file lookup, transcribe output directory, and add result printing.

## Step by Step Tasks

### 1. Add CLI flags to pipeline subcommand

In `cli.py`, lines 110-115, add the missing arguments to the pipeline subparser:

- `--output-dir` — override `BACKUP_DIR` for recording output
- `--no-shuffle` — disable mild URL shuffling
- `--no-breaks` — skip human-like breaks between videos
- `--skip-preflight` — skip startup validation

```python
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
p.add_argument("--foreground", action="store_true",
    help="Run in foreground instead of backgrounding (default: background)")
```

### 2. Fix pipeline command handler in cli.py

Replace lines 218-228 with proper instantiation and orchestration. Key changes:

- Import and instantiate `OBSEngine` and `PatreonSource`
- Use `BACKUP_DIR` as default output dir, allow override via `--output-dir`
- Apply seen-file filtering and mild shuffle to the queue before passing to pipeline
- Run preflight if `record` step is active and `--skip-preflight` not set
- Pass batch config to `Pipeline.run()` for breaks and health checks
- Print result summary after completion

```python
elif args.command == "pipeline":
    import asyncio
    from src.pipeline.runner import Pipeline
    from src.capture.batch import load_queue, filter_unseen, mild_shuffle
    from src.sources.base import Post
    from src.config import BACKUP_DIR

    queue_data = load_queue(Path(args.queue))
    steps = args.steps.split(",") if args.steps else None
    has_record = not steps or "record" in steps

    # Filter seen and shuffle when recording
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

    posts = [Post(url=e["url"], title=e.get("title", e["filename"]),
                  filename=e["filename"]) for e in queue_data]

    # Instantiate engine/source only if recording
    engine = None
    source = None
    if has_record:
        from src.engines.obs_engine import OBSEngine
        from src.sources.patreon import PatreonSource
        engine = OBSEngine()
        source = PatreonSource()

    output_dir = Path(args.output_dir) if args.output_dir else BACKUP_DIR

    # Preflight
    if has_record and not args.skip_preflight:
        from src.capture.preflight import Preflight
        pf = Preflight()
        ok, gates = pf.run_all()
        if not ok:
            print("Preflight failed — aborting")
            return 1

    pipeline = Pipeline(
        source=source, engine=engine, output_dir=output_dir,
        enable_breaks=has_record and not args.no_breaks,
    )
    results = asyncio.run(pipeline.run(posts, steps=steps))

    # Summary
    ok_count = sum(1 for r in results if not r.steps_failed)
    fail_count = len(results) - ok_count
    print(f"\nResults: {ok_count}/{len(results)} succeeded")
    if skipped_seen:
        print(f"Skipped: {skipped_seen} (already recorded)")
    if fail_count:
        for r in results:
            if r.steps_failed:
                print(f"  FAILED: {r.post_title} — {r.steps_failed}")
```

### 3. Add `enable_breaks` parameter to Pipeline.__init__

In `src/pipeline/runner.py`, extend the constructor:

```python
def __init__(self, source, engine, output_dir: Path | None = None,
             enable_breaks: bool = False):
    self._source = source
    self._engine = engine
    self._output_dir = output_dir or Path(".")
    self._enable_breaks = enable_breaks
```

### 4. Add breaks and health checks to Pipeline.run()

In `src/pipeline/runner.py`, modify `run()` to add human-like breaks between videos when `self._enable_breaks` is True:

```python
async def run(self, queue, steps=None):
    active_steps = self._validate_steps(steps) if steps else STEPS
    results: list[PipelineResult] = []

    for i, post in enumerate(queue):
        try:
            result = await self._process_one(post, active_steps)
            results.append(result)
        except Exception as exc:
            log.error("Pipeline failed for %s: %s", getattr(post, 'url', post), exc)
            results.append(PipelineResult(
                post_url=getattr(post, 'url', str(post)),
                post_title=getattr(post, 'title', ''),
                steps_failed={"pipeline": str(exc)},
            ))

        # Human-like break between recordings (not after last)
        if self._enable_breaks and "record" in active_steps and i < len(queue) - 1:
            from src.capture.batch import human_break
            await asyncio.to_thread(human_break, i + 1, len(queue))

    return results
```

### 5. Fix _step_record — add Chrome focus, file move, seen tracking

In `src/pipeline/runner.py`, update `_step_record` to:

- Focus Chrome window before recording (Windows only)
- Move the recording file to `self._output_dir` with retry after stop
- Mark the URL as seen

```python
async def _step_record(self, post, result: PipelineResult) -> None:
    from src.capture.recorder import Recorder
    from src.capture.window import focus_chrome
    from src.capture.batch import mark_seen
    from src.cdp import CDPClient

    if IS_WINDOWS:
        focus_chrome()
        await asyncio.sleep(1)

    recorder = Recorder(self._engine)
    async with CDPClient() as cdp:
        rec = await recorder.record_one(cdp, post.url, post.filename)
        if rec.ok:
            # Move to backup dir with retry
            if rec.output_path and hasattr(self._engine, 'move_to_backup'):
                moved = self._engine.move_to_backup(rec.output_path, post.filename)
                result.output_paths["recording"] = moved or rec.output_path
            else:
                result.output_paths["recording"] = rec.output_path or ""
            mark_seen(post.url)
        else:
            raise RuntimeError(rec.error or "Recording failed")
```

Add `from src.config import IS_WINDOWS` to the top-level imports.

### 6. Fix _step_correct — search multiple correction file locations

In `src/pipeline/runner.py`, update `_step_correct` to try multiple paths for the corrections file:

```python
async def _step_correct(self, post, result: PipelineResult) -> None:
    from src.transcribe.corrections import apply_rules, load_rules
    srt_path = result.output_paths.get("transcript_srt")
    txt_path = result.output_paths.get("transcript_txt")
    if not srt_path or not txt_path:
        log.warning("No transcript paths — skipping correct")
        return

    corrections_file = None
    for candidate in [Path("corrections.txt"), Path("transcribe/corrections.txt")]:
        if candidate.exists():
            corrections_file = candidate
            break
    if not corrections_file:
        log.warning("No corrections file found — skipping")
        return

    rules = load_rules(corrections_file)
    if not rules:
        return
    for path_str in (srt_path, txt_path):
        p = Path(path_str)
        if p.exists():
            text = p.read_text(encoding="utf-8")
            corrected, counts = apply_rules(text, rules)
            if counts:
                p.write_text(corrected, encoding="utf-8")
                log.info("Applied %d corrections to %s", sum(counts.values()), p.name)
```

### 7. Fix _step_transcribe — use output_dir for transcripts

In `src/pipeline/runner.py`, update `_step_transcribe` to use `self._output_dir / "transcripts"` instead of the recording's parent directory:

```python
async def _step_transcribe(self, post, result: PipelineResult) -> None:
    from src.transcribe.whisper_runner import WhisperRunner
    recording = result.output_paths.get("recording")
    if not recording:
        log.warning("No recording path — skipping transcribe")
        return
    runner = WhisperRunner()
    out_dir = self._output_dir / "transcripts"
    out_dir.mkdir(parents=True, exist_ok=True)
    txt, srt = runner.transcribe_file(Path(recording), out_dir)
    result.output_paths["transcript_txt"] = str(txt)
    result.output_paths["transcript_srt"] = str(srt)
```

### 8. Update tests

Add new tests to `tests/test_pipeline.py`:

- **Test proper instantiation**: Verify `Pipeline` accepts engine/source/output_dir/enable_breaks
- **Test breaks are called**: When `enable_breaks=True` and `record` is in steps, verify `human_break` is called between videos (mock it)
- **Test seen tracking**: When `_step_record` succeeds, verify `mark_seen` is called
- **Test corrections fallback**: Verify `_step_correct` searches both paths
- **Test transcribe uses output_dir**: Verify `out_dir` is `self._output_dir / "transcripts"`
- **Test no-record mode**: Verify pipeline works with `steps=["transcribe", "correct"]` and `engine=None` (no crash)

All tests should mock `Recorder`, `CDPClient`, `OBSEngine`, `human_break`, `mark_seen`, etc. so they run on Linux without Windows dependencies.

### 9. Validate

- Run the full test suite to confirm no regressions
- Verify the pipeline command's `--help` shows all new flags
- Dry-check: confirm `Pipeline(source=MagicMock(), engine=MagicMock())` doesn't crash

## Testing Strategy

**Unit tests** (all mockable, run on Linux):
- Pipeline instantiation with all parameter combinations
- `run()` with `enable_breaks=True`: assert `human_break` is called `n-1` times for `n` posts
- `run()` with `enable_breaks=False`: assert `human_break` is never called
- `_step_record` success path: assert `move_to_backup` and `mark_seen` are called
- `_step_record` failure path: assert `RuntimeError` is raised, `mark_seen` is NOT called
- `_step_correct` with `corrections.txt` at repo root: loads from there
- `_step_correct` with `transcribe/corrections.txt`: loads from there
- `_step_correct` with neither file: logs warning, returns without error
- `_step_transcribe` uses `self._output_dir / "transcripts"`
- Post-processing mode (`steps=["transcribe","correct"]`, `engine=None`): no crash

**Existing tests**: All 4 existing tests in `test_pipeline.py` must continue passing — they use `MagicMock` for source/engine, which is still valid since the constructor accepts any truthy/falsy value.

## Acceptance Criteria

- `uv run cli.py pipeline --queue data/test_queue.json --foreground` runs without crashing
- `uv run cli.py pipeline --queue data/test_queue.json --steps transcribe,correct --foreground` runs without crashing (no engine/source needed)
- When `record` is in steps, preflight runs unless `--skip-preflight` is set
- Human-like breaks (300-1500s) occur between videos unless `--no-breaks` is set
- Already-seen URLs are skipped (seen-file tracking via `src/capture/batch.py`)
- Queue is mildly shuffled unless `--no-shuffle` is set
- Recordings are moved to `--output-dir` (or `BACKUP_DIR` default) with retry
- Chrome window is focused before recording on Windows
- Corrections file is found in either `corrections.txt` or `transcribe/corrections.txt`
- Transcripts go to `<output-dir>/transcripts/`
- Result summary is printed at the end
- All existing tests pass, new tests cover the fixed wiring

## Validation Commands

- `uv run python -m py_compile cli.py` — confirm CLI compiles
- `uv run python -m py_compile src/pipeline/runner.py` — confirm runner compiles
- `uv run pytest tests/test_pipeline.py -v` — pipeline-specific tests pass
- `uv run pytest tests/ -x -q` — full test suite, stop on first failure
- `uv run cli.py pipeline --help` — confirm new flags appear in help output

## Notes

- `OBSEngine`, `PatreonSource`, `Recorder`, and `Preflight` all use lazy imports for Windows-only modules (`obsws_python`, `ctypes.wintypes`). The pipeline must not import them at module level — only when the `record` step is active.
- `human_break` from `src/capture/batch.py` is synchronous (uses `time.sleep`). Wrap it in `asyncio.to_thread()` in the async `run()` method so it doesn't block the event loop.
- The `focus_chrome()` function already handles non-Windows gracefully (returns `False`, no crash).
- `mark_seen` from `src/capture/batch.py` uses the default `SEEN_FILE` path, which is on the Windows machine. This is correct for the obs-machine deployment.
