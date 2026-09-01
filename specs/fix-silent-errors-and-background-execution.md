# Plan: Fix silent error swallowing and broken auto-background execution

## Task Description

Two critical reliability issues cause the media-transcribe pipeline to fail silently on the obs-machine:

1. **Auto-background is broken**: `background_relaunch()` in `cli.py` spawns a child process that dies silently — log files are 0 bytes. The pipeline never actually starts when invoked via SSH.

2. **No global error handling**: When the pipeline crashes (import errors, missing modules, unhandled exceptions), errors go to stderr which is lost in background mode. There is no crash recovery — OBS keeps recording orphaned sessions forever, and stuck recordings loop infinitely.

## Objective

After this fix:
- `uv run cli.py pipeline --queue test.json` (without `--foreground`) successfully backgrounds, writes all output to the log file, and captures any startup/runtime errors.
- If OBS is recording when the process crashes or is killed, the recording is stopped automatically.
- Stuck recordings (position not advancing for ~2.5 minutes) are detected and terminated instead of looping forever.
- All commands configure logging at startup, writing to both console (foreground) and file (always).

## Problem Statement

**Background execution**: The child process spawned by `background_relaunch()` (`cli.py:32-54`) dies silently because:
- `sys.executable` inside a `uv run` context may resolve to the ephemeral `uv`-managed Python interpreter, not the `uv` wrapper itself. The child invokes raw Python, bypassing `uv`'s virtual environment activation.
- The file handle opened for stdout/stderr may be garbage-collected in the parent after `Popen` returns, since nothing holds a reference.
- `DETACHED_PROCESS` combined with `CREATE_NO_WINDOW` may prevent the child from inheriting necessary environment variables.
- If the child fails at import time (e.g., can't find `src` package because `uv` hasn't set up `sys.path`), the error goes to the log file — but only if the file handle is actually writable and flushed. Currently errors are silently lost.

**Error handling**: There is no `sys.excepthook`, no `atexit` handler, no signal handling, and no stuck-detection. The recorder's monitor loop (`recorder.py:119-152`) uses `STALL_THRESHOLD=6` for nudging but never gives up — a truly stuck video loops forever. The pipeline runner (`runner.py:61-91`) catches per-video exceptions but has no top-level crash guard for process-level failures.

## Solution Approach

1. **Fix `background_relaunch()`** to use `uv run` as the launcher (not raw `sys.executable`), keep the file handle alive, flush on write, and wrap the child's entry point in a try/except that captures all startup errors.

2. **Add `src/logging_config.py`** — a single `setup_logging()` function called at the top of `main()` that configures Python logging to write to both file and console, installs `sys.excepthook`, and registers `atexit`/signal handlers for OBS crash recovery.

3. **Add stuck-detection** to the recorder's monitor loop — if `currentTime` hasn't advanced for 5 consecutive checks (~2.5 minutes), declare the recording stuck, stop OBS, and return an error.

4. **Add pipeline-level `finally` block** to `Pipeline.run()` that ensures OBS is stopped on unhandled exceptions.

## Relevant Files

- `cli.py` (lines 32-54) — `background_relaunch()`: the broken backgrounding logic
- `cli.py` (lines 146-154) — `main()`: where logging setup and crash guards must be installed
- `src/capture/recorder.py` (lines 116-152) — monitor loop: needs stuck-detection with a hard limit
- `src/pipeline/runner.py` (lines 61-91) — `Pipeline.run()`: needs a `finally` block for OBS cleanup
- `src/engines/obs_engine.py` — `OBSEngine`: used by the crash guard to stop orphaned recordings
- `src/config.py` — `LOGS_DIR`, `IS_WINDOWS`: path constants for log file placement
- `tests/test_background.py` — existing background tests (extend, don't break)
- `tests/test_pipeline.py` — existing pipeline tests (extend, don't break)

### New Files

- `src/logging_config.py` — centralized logging setup, excepthook, atexit/signal handlers
- `tests/test_error_handling.py` — tests for crash guard, excepthook, stuck-detection, logging config

## Implementation Phases

### Phase 1: Foundation — Logging and crash guards

Create `src/logging_config.py` with `setup_logging()`, `sys.excepthook`, `atexit` OBS crash guard, and signal handlers. Wire it into `cli.py main()`.

### Phase 2: Core — Fix background execution

Rewrite `background_relaunch()` to use `uv run` as the child command, keep file handles alive, and add a startup error wrapper in the child process path.

### Phase 3: Integration — Stuck-detection and pipeline safety

Add stuck-detection to the recorder monitor loop and a `finally` block to `Pipeline.run()`.

## Step by Step Tasks

### 1. Create `src/logging_config.py` — centralized logging and crash guards

- Create a new module `src/logging_config.py` with the following functions:

- **`setup_logging(command: str, foreground: bool = False) -> Path`**:
  - Compute log file path: `LOGS_DIR / f"{command}_{timestamp}.log"` (use `LOGS_DIR` from `src.config`)
  - Create `LOGS_DIR` if it doesn't exist
  - Configure `logging.basicConfig` with format `%(asctime)s %(levelname)-8s %(name)s: %(message)s` and level `INFO`
  - Add a `FileHandler` that always writes to the log file
  - If `foreground` is `True`, also add a `StreamHandler` for console output
  - If `foreground` is `False`, only use the file handler (no console spam in background)
  - Return the log file path

- **`_unhandled_exception_hook(exc_type, exc_value, exc_tb)`**:
  - Log the exception using `logging.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))`
  - Call the original `sys.__excepthook__` as fallback
  - Install via `sys.excepthook = _unhandled_exception_hook`

- **`_emergency_stop_obs()`**:
  - Import `OBSEngine` lazily (inside the function) to avoid import-time failures
  - Create an `OBSEngine` instance, connect, check `get_record_status().output_active`
  - If recording, call `stop()` and log a warning: `"[crash-guard] Stopped orphaned OBS recording"`
  - Disconnect
  - Wrap everything in `try/except Exception: pass` — never crash in the crash handler
  - Register via `atexit.register(_emergency_stop_obs)`

- **`_signal_handler(signum, frame)`**:
  - Call `_emergency_stop_obs()`
  - Log `"[crash-guard] Received signal %s, exiting"` with signal name
  - Call `sys.exit(128 + signum)`
  - Register for `signal.SIGTERM`, `signal.SIGINT`
  - On Windows (`IS_WINDOWS`), also register `signal.SIGBREAK`

### 2. Wire logging setup into `cli.py main()`

- At the top of `main()`, before the background/foreground decision:
  - Import `setup_logging` from `src.logging_config`
  - Determine if foreground: `is_foreground = getattr(args, "foreground", False) or args.command not in LONG_RUNNING_COMMANDS`
  - Call `setup_logging(args.command, foreground=is_foreground)` immediately after `parser.parse_args()`
  - This ensures that even if the process crashes during import of a subcommand, the error is logged

- Move the `setup_logging` call to happen **before** the `background_relaunch` check, so the parent process also has logging configured (it will log the PID and log file path)

### 3. Fix `background_relaunch()` in `cli.py`

- **Fix the child command**: Replace `[sys.executable] + sys.argv + ["--foreground"]` with a `uv run`-based command:
  ```python
  import shutil
  uv_path = shutil.which("uv")
  if uv_path:
      child_cmd = [uv_path, "run"] + sys.argv + ["--foreground"]
  else:
      child_cmd = [sys.executable] + sys.argv + ["--foreground"]
  ```
  - This ensures the child process uses `uv run` which properly activates the virtual environment and sets up `sys.path`
  - Fall back to `sys.executable` if `uv` is not found (defensive)

- **Keep the file handle alive**: The current code opens `fh = open(log_file, "w")` but nothing prevents GC. Fix:
  ```python
  fh = open(log_file, "w", buffering=1)  # line-buffered
  ```
  - The parent process exits immediately after `Popen`, but the child inherits the file descriptor. The parent's `fh` variable going out of scope only closes the parent's fd — the child's inherited copy stays open. However, on Windows with `DETACHED_PROCESS`, fd inheritance is not guaranteed. The real fix is the `uv run` approach above.

- **Add `env` passthrough**: Explicitly pass `os.environ.copy()` to `Popen` to ensure the child inherits the full environment:
  ```python
  kwargs["env"] = os.environ.copy()
  kwargs["cwd"] = os.getcwd()
  ```

- **Remove `DETACHED_PROCESS`**: On Windows, use only `CREATE_NO_WINDOW` without `DETACHED_PROCESS`. `DETACHED_PROCESS` prevents the child from inheriting the parent's console AND disables standard handle inheritance. `CREATE_NO_WINDOW` alone is sufficient for SSH-backgrounding:
  ```python
  if sys.platform == "win32":
      kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
  ```

- **Add startup verification**: After spawning, wait briefly and check if the child is still alive:
  ```python
  import time
  time.sleep(1)
  if proc.poll() is not None:
      print(f"ERROR: child exited immediately with code {proc.returncode}")
      print(f"Check log: {log_file}")
      return proc.returncode
  ```

### 4. Add child startup wrapper

- In `cli.py main()`, when running in foreground mode (i.e., the child process re-launched by `background_relaunch`), wrap the entire command dispatch in a try/except that catches ALL exceptions and logs them:
  ```python
  if args.command in LONG_RUNNING_COMMANDS and getattr(args, "foreground", False):
      # This is the child process — ensure all errors are captured
      import logging
      log = logging.getLogger("cli")
      log.info("Child process started: %s", " ".join(sys.argv))
  ```
  - The `setup_logging` call in step 2 already ensures logging is configured before this point
  - The `sys.excepthook` from step 1 catches anything that falls through

### 5. Add stuck-detection to recorder monitor loop

- In `src/capture/recorder.py`, add a constant:
  ```python
  STUCK_THRESHOLD = 5  # consecutive checks with no position advance → declare stuck
  ```

- In the monitor loop (lines 119-152), add a separate counter for stuck detection (distinct from `stall_count` which is for nudging):
  ```python
  stuck_count = 0
  ```

- After the stall-nudge logic, add stuck detection:
  ```python
  if abs(pos - last_pos) < 0.5:
      stuck_count += 1
      if stuck_count >= STUCK_THRESHOLD:
          log.error("  STUCK — position hasn't advanced for %d checks (%.0fs). Aborting.",
                    STUCK_THRESHOLD, STUCK_THRESHOLD * POLL_INTERVAL)
          result.error = f"Recording stuck at {pos:.0f}s for {STUCK_THRESHOLD * POLL_INTERVAL}s"
          await asyncio.to_thread(self.engine.stop)
          return result
  else:
      stuck_count = 0
  ```

- Note: `stall_count` resets after nudging (existing behavior). `stuck_count` only resets when position actually advances. This means after `STALL_THRESHOLD` nudges don't help, `stuck_count` keeps incrementing until it hits `STUCK_THRESHOLD`.

- Wait — re-read the existing code. `stall_count` resets to 0 after nudging. So `stall_count` and `stuck_count` need to be separate. `stuck_count` tracks the absolute number of consecutive no-advance polls, regardless of nudges. The existing `stall_count` is fine for its nudge purpose. Add `stuck_count` as a parallel counter:
  ```python
  if abs(pos - last_pos) < 0.5:
      stall_count += 1
      stuck_count += 1
      if stuck_count >= STUCK_THRESHOLD:
          # ... abort
      elif stall_count > STALL_THRESHOLD:
          # ... nudge (existing)
          stall_count = 0
  else:
      stall_count = 0
      stuck_count = 0
  ```

### 6. Add pipeline-level OBS safety in `Pipeline.run()`

- In `src/pipeline/runner.py`, wrap the main loop in `Pipeline.run()` with a try/finally that stops OBS recording on any unhandled exception:

  ```python
  async def run(self, queue, steps=None):
      active_steps = self._validate_steps(steps) if steps else STEPS
      results = []
      try:
          for i, post in enumerate(queue):
              # ... existing loop body ...
      except Exception:
          log.critical("PIPELINE FAILED — stopping OBS recording", exc_info=True)
          self._emergency_stop_engine()
          raise
      return results
  ```

- Add `_emergency_stop_engine()` method:
  ```python
  def _emergency_stop_engine(self) -> None:
      if self._engine is None:
          return
      try:
          if self._engine.is_recording():
              self._engine.stop()
              log.warning("[pipeline-guard] Stopped recording after crash")
      except Exception:
          pass
  ```

### 7. Write tests in `tests/test_error_handling.py`

- **`test_emergency_stop_obs_no_crash_when_unreachable`**: Mock `OBSEngine` to raise `ConnectionRefusedError` on `connect()`. Call `_emergency_stop_obs()`. Assert it does not raise.

- **`test_emergency_stop_obs_stops_active_recording`**: Mock `OBSEngine` with `get_record_status().output_active = True`. Call `_emergency_stop_obs()`. Assert `stop()` was called.

- **`test_emergency_stop_obs_no_stop_when_not_recording`**: Mock `OBSEngine` with `get_record_status().output_active = False`. Call `_emergency_stop_obs()`. Assert `stop()` was NOT called.

- **`test_excepthook_logs_to_file`**: Configure logging to a `StringIO` or temp file handler. Call `_unhandled_exception_hook` with a fake exception. Assert the log contains the exception message.

- **`test_setup_logging_creates_log_file`**: Call `setup_logging("test", foreground=True)` with a patched `LOGS_DIR` pointing to tmp_path. Assert the log file was created.

- **`test_setup_logging_format`**: After `setup_logging`, emit a log message and read the file. Assert the format matches `YYYY-MM-DD HH:MM:SS,mmm LEVEL    name: message`.

- **`test_stuck_detection_stops_recording`**: Create a `Recorder` with a mock engine. Mock the handler to return the same position for `STUCK_THRESHOLD` polls. Assert the result has `ok=False` and an error about being stuck. Assert `engine.stop()` was called.

- **`test_stuck_detection_resets_on_advance`**: Return same position for 4 polls, then advance. Assert recording continues (no error).

- **`test_pipeline_emergency_stop_on_crash`**: Create a `Pipeline` with a mock engine. Patch `_process_one` to raise an exception. Call `pipeline.run(...)`. Assert `engine.stop()` was called (or `is_recording` was checked).

### 8. Extend tests in `tests/test_background.py`

- **`test_child_command_uses_uv_run`**: Patch `shutil.which("uv")` to return `/usr/bin/uv`. Call `background_relaunch()`. Assert the child command starts with `["/usr/bin/uv", "run"]`.

- **`test_child_command_falls_back_to_sys_executable`**: Patch `shutil.which("uv")` to return `None`. Call `background_relaunch()`. Assert the child command starts with `sys.executable`.

- **`test_windows_no_detached_process`**: On Windows (mock `sys.platform`), assert `creationflags` does NOT include `DETACHED_PROCESS` — only `CREATE_NO_WINDOW`.

- **`test_env_and_cwd_passed_to_popen`**: Call `background_relaunch()`. Assert the Popen kwargs include `env` and `cwd`.

- **`test_log_file_line_buffered`**: Call `background_relaunch()`. Inspect the `open()` call to verify `buffering=1`.

### 9. Run full test suite

- Run `uv run pytest` and verify all existing tests plus new tests pass
- Specifically verify the existing tests in `tests/test_background.py` still pass (they mock `subprocess.Popen` and check the child command)

## Testing Strategy

**Unit tests** (all run on devbox-01, no Windows/OBS required):

1. **Crash guard tests**: Mock `OBSEngine` entirely — verify `_emergency_stop_obs()` is safe when OBS is unreachable, stops recording when active, and is a no-op when not recording.
2. **Excepthook tests**: Install the hook, trigger it with a synthetic exception, verify the log file captures it.
3. **Logging config tests**: Verify `setup_logging()` creates the expected file, configures the right format, and handles both foreground and background modes.
4. **Stuck-detection tests**: Mock the CDP handler to return fixed positions, verify the recorder aborts after `STUCK_THRESHOLD` polls and stops the engine.
5. **Background command tests**: Verify the child command uses `uv run`, falls back correctly, passes env/cwd, and uses correct Windows flags.
6. **Pipeline guard tests**: Verify `_emergency_stop_engine()` is called when `_process_one` raises.

**Integration verification** (manual, on obs-machine after deploy):

1. `ssh Matt@100.66.194.100 "cd C:\Users\Matt\transcribe; uv run cli.py pipeline --queue test.json"` — verify log file has content, pipeline starts
2. Kill the pipeline mid-recording — verify OBS recording stops via atexit
3. Check log file format matches expected pattern

## Acceptance Criteria

- `uv run cli.py pipeline --queue test.json` (without `--foreground`) successfully backgrounds and writes output to the log file
- If the child process fails at startup (e.g., import error), the error is captured in the log file, not lost
- The `atexit` OBS cleanup handler does not crash when OBS is unreachable
- The `atexit` handler stops OBS recording if it is active when the process exits
- `sys.excepthook` logs unhandled exceptions to the log file before the process exits
- Stuck recordings (position unchanged for 5 consecutive 30-second polls = 2.5 minutes) are detected and terminated
- `Pipeline.run()` stops OBS recording on unhandled exceptions via a `finally` block
- All existing tests pass (`uv run pytest`)
- New tests cover: crash guard (3 cases), excepthook (1), logging config (2), stuck-detection (2), background command (4+), pipeline guard (1)
- Works when invoked via SSH: `ssh Matt@100.66.194.100 "cd C:\Users\Matt\transcribe; uv run cli.py pipeline --queue test.json"`

## Validation Commands

- `uv run pytest tests/test_error_handling.py -v` — run new error handling tests
- `uv run pytest tests/test_background.py -v` — run extended background tests
- `uv run pytest` — full test suite passes (303+ tests)
- `uv run python -m py_compile src/logging_config.py` — verify new module compiles
- `uv run python -m py_compile cli.py` — verify cli.py compiles
- `uv run python -c "from src.logging_config import setup_logging; print('OK')"` — verify import works

## Notes

- No new dependencies required — all functionality uses stdlib (`logging`, `atexit`, `signal`, `shutil`).
- `obsws_python` is only imported lazily inside `_emergency_stop_obs()`, so devbox-01 tests work without it installed.
- The `STUCK_THRESHOLD = 5` at `POLL_INTERVAL = 30` seconds gives ~2.5 minutes before declaring stuck. This prevents the infinite PAUSED-resuming loop seen with Conference 4.
- Removing `DETACHED_PROCESS` from the Windows creation flags is the key fix for background execution. `CREATE_NO_WINDOW` alone is sufficient to prevent a console window from appearing, while `DETACHED_PROCESS` actively prevents standard handle inheritance which breaks log file writing.
- The `uv run` child command approach solves the virtual environment problem: raw `sys.executable` points to `uv`'s ephemeral Python which doesn't have `src` on its path. Using `uv run cli.py` ensures the project's virtual environment is activated.
