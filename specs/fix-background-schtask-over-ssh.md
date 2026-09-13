# Plan: Fix background execution on Windows over SSH using scheduled tasks

## Task Description

`background_relaunch()` in `cli.py` uses `subprocess.Popen` with `CREATE_NO_WINDOW` to detach long-running commands. This breaks on Windows over SSH — the child process starts, connects to OBS, then dies silently. The asyncio event loop and/or CDP WebSocket connections fail in the detached process context.

Running via Windows scheduled tasks with the `/it` flag works reliably — the child runs in the interactive session with full console access and survives SSH disconnect. This pattern is already proven in `src/capture/environment.py` for launching Chrome and OBS.

## Objective

After this fix:
- `background_relaunch()` detects SSH sessions and uses `schtasks` instead of `subprocess.Popen`
- The child process runs in the interactive Windows session (session 1), not session 0
- Pipeline processes survive SSH disconnect
- Non-SSH and Linux execution remains unchanged (existing `Popen` path)
- A `status` subcommand shows running pipeline state
- Old batch files are cleaned up automatically

## Problem Statement

On the obs-machine, pipeline commands are launched via SSH:
```bash
ssh Matt@100.66.194.100 "cd C:\Users\Matt\transcribe; uv run cli.py pipeline --queue queue.json"
```

The current `background_relaunch()` (cli.py:34-70) spawns a child with `CREATE_NO_WINDOW`. This puts the child in Windows session 0 (the non-interactive service session), where:
- asyncio event loops may not function correctly
- CDP WebSocket connections to Chrome (running in session 1) fail
- OBS WebSocket connections may fail
- The process dies silently with 0-byte log files

The fix is to use Windows scheduled tasks with `/it` (interactive token), which launches the child in session 1 — the same session where Chrome and OBS are running. This pattern is already used successfully in `src/capture/environment.py:46-76` for launching Chrome and OBS over SSH.

## Solution Approach

1. Split `background_relaunch()` into two strategies: `_background_via_subprocess()` (existing) and `_background_via_scheduled_task()` (new)
2. Route based on `is_ssh_session()` + `IS_WINDOWS` — import the existing detection from `src/capture/environment`
3. Reuse the scheduled task conventions from config.py (`TEMP_BAT_DIR`, naming with `MediaTranscribe_` prefix)
4. Add a `status` subcommand that queries `schtasks` and reads the latest log
5. Add stale batch file cleanup

## Relevant Files

Use these files to complete the task:

- `cli.py` (lines 34-70) — `background_relaunch()`: the function to refactor
- `src/capture/environment.py` (lines 30-43) — `is_ssh_session()`: reuse this, don't duplicate
- `src/capture/environment.py` (lines 46-76) — `_launch_via_scheduled_task()`: reference pattern for schtasks usage
- `src/config.py` — `IS_WINDOWS`, `LOGS_DIR`, `TEMP_BAT_DIR`, `SCRIPTS_DIR`, schtask name constants
- `tests/test_cli.py` — existing CLI arg tests; extend with status subcommand test
- `AGENTS.md` — document the background execution behavior

### New Files

- `tests/test_schtask_background.py` — tests for the new scheduled task background path

## Implementation Phases

### Phase 1: Foundation
Add the `status` subcommand to the CLI parser and the scheduled task name constant to config.py. Import `is_ssh_session` from environment.py into cli.py.

### Phase 2: Core Implementation
Refactor `background_relaunch()` into the SSH-aware router with two strategy functions. Implement batch file generation with self-delete, PID detection, and stale file cleanup.

### Phase 3: Integration & Polish
Add the `status` command handler, write tests, update documentation.

## Step by Step Tasks
IMPORTANT: Execute every step in order, top to bottom.

### 1. Add scheduled task config constant

In `src/config.py`, add a constant for pipeline task naming alongside the existing Chrome/OBS task names:

- Add `SCHTASK_NAME_PREFIX = "MediaTranscribe_"` (the existing Chrome/OBS names already use this prefix — making it a constant enables dynamic task names per command type)
- No other config changes needed — `TEMP_BAT_DIR` and `LOGS_DIR` already exist

### 2. Refactor `background_relaunch()` into SSH-aware router

In `cli.py`:

- Add imports at the top:
  ```python
  from src.capture.environment import is_ssh_session
  from src.config import IS_WINDOWS, LOGS_DIR, TEMP_BAT_DIR
  ```
  Note: `IS_WINDOWS` and `LOGS_DIR` are already imported inside `main()` — move them to top-level or keep the existing lazy import pattern and add the new import alongside it.

- Rename the existing `background_relaunch()` body to `_background_via_subprocess()`. Keep the signature identical:
  ```python
  def _background_via_subprocess(args: argparse.Namespace, log_dir: Path) -> int:
      """Background via subprocess.Popen — works locally but NOT over SSH on Windows."""
      # ... existing implementation from lines 35-70, unchanged
  ```

- Rename the existing function to a router:
  ```python
  def background_relaunch(args: argparse.Namespace, log_dir: Path) -> int:
      """Background a long-running command. SSH-aware on Windows."""
      if IS_WINDOWS and is_ssh_session():
          return _background_via_scheduled_task(args, log_dir)
      return _background_via_subprocess(args, log_dir)
  ```

### 3. Implement `_background_via_scheduled_task()`

Add a new function in `cli.py`:

```python
def _background_via_scheduled_task(args: argparse.Namespace, log_dir: Path) -> int:
    """Background via Windows scheduled task — works over SSH."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"{args.command}_{timestamp}.log"
    log_dir.mkdir(parents=True, exist_ok=True)

    # Clean up stale batch files from previous runs
    TEMP_BAT_DIR.mkdir(parents=True, exist_ok=True)
    for old_bat in TEMP_BAT_DIR.glob("_bg_*.bat"):
        try:
            old_bat.unlink()
        except OSError:
            pass  # In use by running pipeline

    # Build the foreground command (mirrors _background_via_subprocess logic)
    uv_path = shutil.which("uv")
    if uv_path:
        child_cmd = f'"{uv_path}" run {" ".join(sys.argv)} --foreground'
    else:
        child_cmd = f'"{sys.executable}" {" ".join(sys.argv)} --foreground'

    # Write batch file that runs the command and self-deletes
    bat_path = TEMP_BAT_DIR / f"_bg_{args.command}_{timestamp}.bat"
    bat_path.write_text(
        f"@echo off\n"
        f"cd /d {os.getcwd()}\n"
        f'{child_cmd} > "{log_file}" 2>&1\n'
        f'del "%~f0"\n',
        encoding="utf-8",
    )

    task_name = f"MediaTranscribe_{args.command}"

    # Create scheduled task (overwrite if exists)
    result = subprocess.run(
        ["schtasks", "/create", "/tn", task_name,
         "/tr", str(bat_path.resolve()),
         "/sc", "once", "/st", "00:00",
         "/f", "/rl", "highest", "/it"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: Failed to create scheduled task: {result.stderr}")
        return 1

    # Run the task immediately
    result = subprocess.run(
        ["schtasks", "/run", "/tn", task_name],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: Failed to run scheduled task: {result.stderr}")
        return 1

    time.sleep(3)
    pid = _find_pipeline_pid()

    print(f"PID:     {pid or 'detecting...'}")
    print(f"Log:     {log_file}")
    print(f"Task:    {task_name}")
    print(f"Command: {child_cmd}")
    print(f"Tail:    Get-Content '{log_file}' -Tail 20 -Wait")
    return 0
```

### 4. Implement `_find_pipeline_pid()`

```python
def _find_pipeline_pid() -> int | None:
    """Find the Python process started by our scheduled task."""
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "Get-Process -Name python,py -ErrorAction SilentlyContinue | "
             "Select-Object -ExpandProperty Id"],
            capture_output=True, text=True, timeout=5,
        )
        pids = [int(p.strip()) for p in result.stdout.strip().split("\n") if p.strip()]
        return pids[0] if pids else None
    except Exception:
        return None
```

### 5. Add `status` subcommand

In `cli.py`:

- Add to `build_parser()` after the `watch` subparser:
  ```python
  sub.add_parser("status", help="Check running pipeline status")
  ```

- Add handler in `main()` before the `release-info` branch:
  ```python
  elif args.command == "status":
      return _handle_status()
  ```

- Implement `_handle_status()`:
  ```python
  def _handle_status() -> int:
      """Show running pipeline status."""
      from src.config import LOGS_DIR

      # Check scheduled tasks
      for cmd in ("pipeline", "record", "transcribe", "analyze", "watch"):
          task_name = f"MediaTranscribe_{cmd}"
          result = subprocess.run(
              ["schtasks", "/query", "/tn", task_name, "/fo", "LIST"],
              capture_output=True, text=True,
          )
          if result.returncode == 0:
              print(f"Task: {task_name}")
              for line in result.stdout.strip().split("\n"):
                  line = line.strip()
                  if line.startswith("Status:") or line.startswith("Last Run Time:"):
                      print(f"  {line}")
              print()

      # Check latest log files
      logs = sorted(LOGS_DIR.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
      if logs:
          latest = logs[0]
          size = latest.stat().st_size
          lines = latest.read_text(encoding="utf-8", errors="replace").strip().split("\n")
          last_line = lines[-1] if lines and lines[0] else "(empty)"
          print(f"Latest log: {latest.name} ({size:,} bytes)")
          print(f"Last line:  {last_line[:120]}")
      else:
          print("No log files found")

      return 0
  ```

### 6. Write tests

Create `tests/test_schtask_background.py` with these test cases:

- **`test_is_ssh_session_with_ssh_client`**: Set `SSH_CLIENT` env var → `is_ssh_session()` returns True
- **`test_is_ssh_session_with_ssh_connection`**: Set `SSH_CONNECTION` env var → returns True
- **`test_is_ssh_session_no_ssh_env`**: No SSH env vars, not Windows → returns False
- **`test_background_relaunch_routes_to_schtask`**: Mock `IS_WINDOWS=True`, `is_ssh_session()=True` → verify `_background_via_scheduled_task` is called
- **`test_background_relaunch_routes_to_subprocess`**: Mock `is_ssh_session()=False` → verify `_background_via_subprocess` is called
- **`test_schtask_creates_batch_file`**: Mock `subprocess.run` → verify batch file is written with correct content (cd, command, redirect, self-delete)
- **`test_schtask_batch_file_content`**: Verify the batch file contains `cd /d`, the `--foreground` flag, log redirect, and `del "%~f0"`
- **`test_schtask_cleans_old_batch_files`**: Create stale `_bg_*.bat` files → verify they're removed
- **`test_schtask_locked_batch_file_skipped`**: Make a batch file unremovable → verify no exception raised
- **`test_schtask_create_failure`**: Mock `schtasks /create` returning non-zero → verify function returns 1
- **`test_schtask_run_failure`**: Mock `schtasks /run` returning non-zero → verify function returns 1
- **`test_find_pipeline_pid_with_results`**: Mock powershell returning PIDs → verify first PID returned
- **`test_find_pipeline_pid_no_results`**: Mock powershell returning empty → verify None returned
- **`test_find_pipeline_pid_timeout`**: Mock subprocess.run raising TimeoutExpired → verify None returned
- **`test_status_parser`**: Verify `status` subcommand parses correctly

All tests must mock `subprocess.run` — never create real scheduled tasks. Use `tmp_path` for batch file directories. Monkeypatch `TEMP_BAT_DIR` to point to `tmp_path`.

### 7. Update `tests/test_cli.py`

Add a parser test for the new `status` subcommand:
```python
def test_cli_status_args():
    from cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["status"])
    assert args.command == "status"
```

### 8. Update AGENTS.md

Add a "Background Execution" subsection under the "Execution" section:

```markdown
### Background Execution

Long-running commands (record, transcribe, analyze, pipeline, watch) auto-background.

- **Over SSH on Windows**: Uses Windows scheduled task with `/it` flag (runs in interactive session, survives SSH disconnect)
- **Local/interactive**: Uses `subprocess.Popen` with `CREATE_NO_WINDOW` (Windows) or `start_new_session` (Linux)
- **Force foreground**: Add `--foreground` flag

Check status: `uv run cli.py status`
```

### 9. Validate

- Run `uv run pytest` — all existing tests must pass
- Run `uv run pytest tests/test_schtask_background.py -v` — all new tests must pass
- Run `uv run python -m py_compile cli.py` — verify syntax

## Testing Strategy

All tests are unit tests that run on devbox-01 (Linux). They mock:
- `subprocess.run` — to simulate `schtasks` commands without Windows
- `os.environ` — to simulate SSH environment variables
- `IS_WINDOWS` — to test Windows-specific code paths on Linux
- `shutil.which` — to control uv path resolution
- `TEMP_BAT_DIR` — redirected to `tmp_path` for batch file creation/cleanup tests

Integration testing happens manually on the obs-machine after deploy:
```bash
# Test SSH background via scheduled task:
ssh Matt@100.66.194.100 "cd C:\Users\Matt\transcribe; uv run cli.py pipeline --queue test.json"
# Then check:
ssh Matt@100.66.194.100 "cd C:\Users\Matt\transcribe; uv run cli.py status"
```

Edge cases to test:
- Task name collision (same command backgrounded twice) — `/f` flag overwrites
- Batch file locked by running process — `OSError` caught and skipped
- `schtasks /create` fails (permissions) — returns error code 1
- `schtasks /run` fails — returns error code 1
- No Python/py processes found — PID shows "detecting..."

## Acceptance Criteria

- `background_relaunch()` detects SSH sessions and uses `schtasks` on Windows
- Non-SSH execution path is unchanged (existing `Popen` logic untouched)
- `is_ssh_session()` is imported from `src/capture/environment.py`, not duplicated
- Batch files are written to `TEMP_BAT_DIR` (consistent with Chrome/OBS pattern)
- Batch files self-delete on completion
- Stale batch files from prior runs are cleaned up
- `uv run cli.py status` shows scheduled task state and latest log
- All existing tests pass (`uv run pytest`)
- New tests cover routing, batch file content, cleanup, error cases, and PID detection
- AGENTS.md documents the SSH vs local background behavior

## Validation Commands

Execute these commands to validate the task is complete:

- `uv run python -m py_compile cli.py` — Verify cli.py compiles
- `uv run pytest tests/test_schtask_background.py -v` — Run new scheduled task tests
- `uv run pytest tests/test_cli.py -v` — Run CLI parser tests (including new status test)
- `uv run pytest` — Full test suite passes with no regressions

## Notes

- The `/it` flag on `schtasks` requires the task to run under a user that has an active interactive session. On the obs-machine, user `Matt` is always logged in (HDMI dongle keeps the session alive). If the machine is rebooted without an interactive login, the scheduled task will fail — this matches the existing Chrome/OBS launch behavior.
- The `/ru` flag used in `environment.py` for Chrome/OBS (`/ru Matt`) is omitted here because `/rl highest` with `/it` inherits the creating user's context. If testing reveals the task runs in the wrong session, add `/ru Matt` to match the environment.py pattern.
- `schtasks /create` with `/f` overwrites an existing task of the same name. This means if you background `pipeline` twice, the second call overwrites the first task definition. The first process keeps running (it was already launched), but you lose the ability to query its task status. This is acceptable — the log file and PID are the primary monitoring path.
- The `status` command runs `schtasks /query` which only works on Windows. On Linux, it will show "No pipeline task found" — this is fine since scheduled tasks only apply to the obs-machine.
