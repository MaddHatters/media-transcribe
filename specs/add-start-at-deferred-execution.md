# Plan: Add --start-at flag for deferred execution

## Task Description
Add a `--start-at` CLI flag to the `pipeline` and `record` subcommands in `cli.py` that defers execution until a specified time. The process sleeps until the target time, then runs normally. This enables scheduling overnight runs via SSH without external schedulers.

## Objective
When complete, users can run:
```bash
uv run cli.py pipeline --queue queue.json --start-at "22:00"
uv run cli.py record --queue queue.json --start-at "2026-09-05 03:00"
```
The process waits until the specified time, then proceeds with the normal command flow. Works with auto-background (the child process inherits `--start-at` via `sys.argv`).

## Problem Statement
Pipeline and record runs sometimes need to start at specific times (e.g., late night when the obs-machine is idle, or after a scheduled event). Currently the only option is manual timing or external cron. A built-in `--start-at` flag keeps scheduling self-contained in the CLI.

## Solution Approach
1. Extract a reusable `wait_until(start_at: str) -> int` helper in `cli.py` that parses the time string, calculates the delta, and sleeps.
2. Add `--start-at` to the `pipeline` and `record` argument parsers.
3. Call `wait_until()` early in both command handlers — after queue loading (for informational output) but before preflight/environment setup (no point validating OBS if we're sleeping for 6 hours).
4. The flag passes through to the backgrounded child automatically since `background_relaunch()` copies `sys.argv`.

## Relevant Files
Use these files to complete the task:

- **`cli.py`** — Add `--start-at` argument to `pipeline` (line 127) and `record` (line 121) parsers. Add `wait_until()` helper. Insert wait calls in both command handlers.
- **`AGENTS.md`** — Add `--start-at` usage example under the Execution section (line 53-75).
- **`tests/test_cli.py`** — Reference for argument parsing test patterns (lines 40-44, 78-83).
- **`tests/test_background.py`** — Reference for how background relaunch tests work; verifies `--start-at` passes through `sys.argv`.

### New Files
- **`tests/test_start_at.py`** — All tests for the `--start-at` feature: parsing, delta calculation, sleep behavior, error handling, argument parser presence.

## Implementation Phases

### Phase 1: Foundation
Add the `wait_until()` helper function and the `--start-at` argument to both parsers.

### Phase 2: Core Implementation
Wire the wait logic into the `pipeline` and `record` command handlers at the correct insertion points.

### Phase 3: Integration & Polish
Write tests, update docstring and docs, validate end-to-end with the existing test suite.

## Step by Step Tasks
IMPORTANT: Execute every step in order, top to bottom.

### 1. Write tests first (TDD)
Create `tests/test_start_at.py` with these test cases:

- **Argument parser tests:**
  - `--start-at` is accepted by the `pipeline` subparser
  - `--start-at` is accepted by the `record` subparser
  - `--start-at` defaults to `None` when omitted
  - `--start-at` stores the string value when provided

- **Parsing tests (test `wait_until` helper):**
  - `"HH:MM"` format produces correct target datetime (today, same year/month/day)
  - `"HH:MM"` in the past rolls forward to tomorrow
  - `"YYYY-MM-DD HH:MM"` format produces correct target datetime
  - `"YYYY-MM-DD HH:MM"` in the past results in immediate start (delta ≤ 0, sleep not called)
  - Invalid format (e.g., `"not-a-time"`) returns error code 1

- **Sleep behavior tests (mock `time.sleep` and `datetime.now`):**
  - When delta > 0, `time.sleep` is called with the correct number of seconds
  - When delta ≤ 0, `time.sleep` is NOT called
  - Verify informational print output includes target time, delta, and PID

- **Edge cases:**
  - `"HH:MM"` rollover at month boundary (e.g., Jan 31 23:00 when it's Jan 31 23:30 → rolls to Feb 1) — use `timedelta(days=1)` not `replace(day=day+1)`
  - `"00:00"` (midnight) works correctly

### 2. Add `wait_until()` helper to `cli.py`
Add a module-level function after the `background_relaunch()` function (around line 71):

```python
def wait_until(start_at: str) -> int:
    """Sleep until the specified time. Returns 0 on success, 1 on parse error."""
    from datetime import datetime, timedelta
    import time as _time

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
        _time.sleep(delta)
        print(f"Wake up! Starting at {datetime.now().strftime('%H:%M:%S')}")
    return 0
```

Key difference from the requirements' code example: use `timedelta(days=1)` instead of `replace(day=now.day + 1)` to avoid a crash on the last day of the month.

### 3. Add `--start-at` to the pipeline parser
In `build_parser()`, add to the pipeline subparser (after `--test-mode`, before `--foreground`, around line 139):

```python
p.add_argument("--start-at", default=None,
    help="Delay start until this time (format: 'YYYY-MM-DD HH:MM' or 'HH:MM' for today)")
```

### 4. Add `--start-at` to the record parser
In `build_parser()`, add to the record subparser (after `--queue`, before `--foreground`, around line 123):

```python
r.add_argument("--start-at", default=None,
    help="Delay start until this time (format: 'YYYY-MM-DD HH:MM' or 'HH:MM' for today)")
```

### 5. Wire `wait_until` into the pipeline handler
In `main()`, inside the `elif args.command == "pipeline":` block, insert the wait call **after** queue loading and before environment/preflight setup. Specifically, insert after line 289 (`return 0` for empty queue) and before line 291 (`if args.test_mode:`):

```python
        if args.start_at:
            print(f"   Queue: {args.queue} ({len(queue_data)} videos)")
            rc = wait_until(args.start_at)
            if rc:
                return rc
```

This placement means:
- Queue is already loaded → we can show how many videos
- `filter_unseen` and `mild_shuffle` already ran → queue is final
- Preflight hasn't run → no wasted validation hours before the target time

### 6. Wire `wait_until` into the record handler
In the `elif args.command == "record":` block (line 263), insert after queue loading:

```python
    elif args.command == "record":
        from src.capture.batch import load_queue
        queue = load_queue(Path(args.queue))
        print(f"Loaded {len(queue)} entries from {args.queue}")
        if args.start_at:
            rc = wait_until(args.start_at)
            if rc:
                return rc
```

### 7. Update the cli.py docstring
Add `--start-at` to the usage examples at the top of the file (line 16-17 area):

```python
    uv run cli.py pipeline --queue <file> [--steps record,transcribe,correct] [--start-at "HH:MM"]
    uv run cli.py record --queue data/queues/conference.json [--start-at "22:00"]
```

### 8. Update AGENTS.md
Add a scheduling example under the Execution section (after line 65, before the "Short commands" comment):

```markdown
# Schedule for later:
ssh Matt@100.66.194.100 "cd C:\Users\Matt\transcribe; uv run cli.py pipeline --queue queue.json --start-at '22:00'"
```

### 9. Validate
- Run `uv run pytest tests/test_start_at.py -v` to confirm new tests pass
- Run `uv run pytest` to confirm the full suite (303+ tests) still passes
- Run `uv run python -m py_compile cli.py` to verify no syntax errors

## Testing Strategy

All tests go in `tests/test_start_at.py`. The strategy:

1. **Argument parsing** — use `build_parser()` directly, assert `args.start_at` is set/unset.
2. **`wait_until()` logic** — mock `datetime.now()` to a fixed time, call `wait_until()` with various inputs, assert return code and `time.sleep` call args. Use `@patch` on the `time` module imported inside the function (or on `cli.time`).
3. **No real sleeping** — always mock `time.sleep`. Verify it's called with the expected delta (within 1 second tolerance to account for test execution time).
4. **Print output** — use `capsys` to verify informational messages contain expected substrings.
5. **Error path** — verify invalid format returns 1 and prints an error message.

Mock pattern for datetime:
```python
from unittest.mock import patch, MagicMock
import cli

with patch("cli.time.sleep") as mock_sleep:
    # For testing wait_until, we need to mock datetime inside the function.
    # Since wait_until imports datetime locally, mock at the module level
    # or restructure to make it testable.
```

Note: Since `wait_until()` uses `from datetime import datetime` at module scope (the import is already at line 29 of cli.py), mocking should target the module-level `datetime` in `cli`. However, `wait_until()` as written in step 2 does a local import. **Decision: use the module-level `datetime` already imported in cli.py** — remove the local import from `wait_until()` and use `time` from the module-level import (also already at line 27). This makes mocking straightforward:

```python
@patch("cli.time.sleep")
@patch("cli.datetime")
def test_wait_future(mock_dt, mock_sleep):
    mock_dt.now.return_value = datetime(2026, 9, 1, 14, 0)
    mock_dt.strptime.side_effect = datetime.strptime
    result = wait_until("22:00")
    assert result == 0
    mock_sleep.assert_called_once()
    delta = mock_sleep.call_args[0][0]
    assert 28700 < delta < 28900  # ~8 hours
```

## Acceptance Criteria
- `uv run cli.py pipeline --queue q.json --start-at "22:00"` defers execution until 22:00
- `uv run cli.py record --queue q.json --start-at "2026-12-25 06:00"` defers until Dec 25 6 AM
- `--start-at` with a past full-date starts immediately (no error, no sleep)
- `--start-at` with a past `HH:MM` time rolls to tomorrow
- Invalid format prints an error and returns exit code 1
- Auto-background passes `--start-at` through to the child process (no code change needed — verify only)
- All existing tests continue to pass
- New tests in `tests/test_start_at.py` cover all cases listed in step 1

## Validation Commands
Execute these commands to validate the task is complete:

- `uv run python -m py_compile cli.py` — Verify cli.py compiles without errors
- `uv run pytest tests/test_start_at.py -v` — Run new start-at tests
- `uv run pytest tests/test_cli.py -v` — Verify existing CLI arg parsing tests still pass
- `uv run pytest tests/test_background.py -v` — Verify background relaunch tests still pass
- `uv run pytest` — Run full test suite, all tests must pass

## Notes
- No new dependencies needed — only `datetime`, `time`, and `os` (all stdlib, already imported).
- The `wait_until()` function uses `time.sleep()` (already imported at module level in cli.py) rather than any async mechanism, keeping it simple.
- The `background_relaunch()` function copies `sys.argv + ["--foreground"]`, so `--start-at "22:00"` in the original argv is automatically forwarded to the child. No changes to `background_relaunch()` are needed — just verify this in a test.
- The `timedelta(days=1)` approach for HH:MM rollover is critical — `replace(day=now.day + 1)` would crash on the last day of every month.
