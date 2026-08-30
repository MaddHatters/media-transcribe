# Plan: Background-by-Default Execution for Long-Running CLI Commands

## Task Description
Add automatic background execution to long-running CLI commands (`record`, `transcribe`, `analyze`, `pipeline`) so that SSH session disconnects no longer kill running processes. When invoked without a `--foreground` flag, these commands re-launch themselves as a detached process with output redirected to a timestamped log file. Short commands (`correct`, `find-gaps`, `extract-frames`, `preflight`, `screenshot`, `transfer-transcripts`) remain foreground-only.

## Objective
When complete:
1. Running `uv run cli.py transcribe <folder>` over SSH immediately prints a PID and log path, then exits — the transcription continues in the background even if SSH drops.
2. Running `uv run cli.py transcribe <folder> --foreground` runs in the terminal as before.
3. Short commands behave exactly as they do today — no change.
4. All existing tests pass; new tests cover the background logic.

## Problem Statement
The pipeline runs on two machines accessed via SSH (`devbox-01` and `obs-machine`). Long-running commands like `transcribe` (hours), `pipeline` (hours), `analyze` (minutes–hours), and `record` (minutes–hours) can be killed when the SSH session drops — a network blip, laptop sleep, or accidental terminal close. This has caused multiple failed runs. Users currently have to remember to manually prefix commands with `nohup` or wrap them in `tmux`/`screen`, which is error-prone.

## Solution Approach
Intercept long-running commands before they execute and, unless `--foreground` is passed, re-launch the same CLI invocation as a fully detached subprocess with stdout/stderr redirected to a timestamped log file. The re-launched child includes `--foreground` to prevent infinite recursion. The parent prints the child PID and log path, then exits immediately.

This approach:
- Requires no external tools (no tmux, no systemd)
- Works on both Linux (`start_new_session=True`) and Windows (`CREATE_NO_WINDOW | DETACHED_PROCESS`)
- Is backwards-compatible — `--foreground` restores the previous behavior
- Uses `src/config.py`'s existing `LOGS_DIR` on Windows; `/tmp/` on Linux

## Relevant Files

- `cli.py` — The unified CLI entry point. Main file being modified.
- `src/config.py` — Has `LOGS_DIR` (Windows path) and `IS_WINDOWS` flag.
- `tests/test_cli.py` — Existing CLI arg-parsing tests. Must not break.

### New Files
- `tests/test_background.py` — Tests for the background relaunch logic.

## Implementation Phases

### Phase 1: Foundation
Define the `LONG_RUNNING_COMMANDS` set and `background_relaunch()` function in `cli.py`. These are pure additions — no existing code changes yet.

### Phase 2: Core Implementation
Add `--foreground` flag to the four long-running subcommand parsers. Wire the background check into `main()` between argument parsing and command dispatch.

### Phase 3: Integration & Polish
Write tests, update the module docstring, verify existing tests still pass.

## Step by Step Tasks

### 1. Add background relaunch function to `cli.py`

- Add imports at the top of `cli.py`: `import os`, `import subprocess`, `from datetime import datetime`
- Add a module-level constant:
  ```python
  LONG_RUNNING_COMMANDS = {"record", "transcribe", "analyze", "pipeline"}
  ```
- Add the `background_relaunch` function after the constant. It should:
  - Accept `args` (parsed argparse namespace) and `log_dir` (Path)
  - Build a timestamped log filename: `{command}_{YYYYMMDD_HHMMSS}.log`
  - Create `log_dir` with `mkdir(parents=True, exist_ok=True)`
  - Build the child command: `[sys.executable] + sys.argv + ["--foreground"]`
  - Open the log file for writing and pass it as `stdout`/`stderr` to `subprocess.Popen`
  - On Linux: pass `start_new_session=True`
  - On Windows: pass `creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS`
  - Print: PID, log path, the full command, and a `tail -f` hint
  - Return the child PID
- Determine the log directory: use `src.config.LOGS_DIR` if on Windows, otherwise `Path("/tmp")`. Import `IS_WINDOWS` from `src.config` at the top of the file (lazy import is fine too, but since `config.py` is lightweight, top-level is acceptable).

### 2. Add `--foreground` flag to long-running subcommand parsers

- In `build_parser()`, add to each of the four subcommand parsers (`t`, `a`, `r`, `p`):
  ```python
  .add_argument("--foreground", action="store_true",
                 help="Run in foreground instead of backgrounding (default: background)")
  ```
- Do NOT add this flag to `correct`, `find-gaps`, `extract-frames`, `preflight`, `screenshot`, or `transfer-transcripts`.

### 3. Wire background check into `main()`

- In `main()`, after `args = parser.parse_args()`, add the background guard:
  ```python
  if args.command in LONG_RUNNING_COMMANDS and not getattr(args, "foreground", False):
      from src.config import LOGS_DIR, IS_WINDOWS
      log_dir = LOGS_DIR if IS_WINDOWS else Path("/tmp")
      background_relaunch(args, log_dir)
      return 0
  ```
- This must come BEFORE the `if args.command == "transcribe":` dispatch block.
- Use `getattr` with a default of `False` as a safety net, even though long-running commands will always have the attribute.

### 4. Update `cli.py` module docstring

- Replace the existing module docstring with one that documents the background behavior:
  ```
  Long-running commands (record, transcribe, analyze, pipeline) run in the
  background by default — the process detaches and output goes to a log file.
  Use --foreground to run in the terminal instead.
  ```
- Keep the existing usage examples.

### 5. Create `tests/test_background.py`

- **`test_long_running_commands_identified`** — Assert `LONG_RUNNING_COMMANDS == {"record", "transcribe", "analyze", "pipeline"}`.
- **`test_foreground_flag_parsed`** — For each long-running command, parse args with `--foreground` and verify `args.foreground is True`. Parse without it and verify `args.foreground is False`.
- **`test_short_commands_no_foreground_flag`** — For each short command (`correct`, `find-gaps`, `preflight`, `screenshot`, `transfer-transcripts`), verify `hasattr(args, "foreground") is False`.
- **`test_foreground_flag_skips_relaunch`** — Patch `subprocess.Popen` in `cli`, call `main()` with e.g. `["transcribe", "/tmp/x", "--foreground"]` (also patch the actual transcribe import so it doesn't run). Verify `Popen` was NOT called.
- **`test_background_builds_correct_command`** — Call `background_relaunch()` with a mock args namespace and a tmp log dir. Verify the `Popen` call includes `sys.executable`, the original argv, AND `--foreground` appended. Verify `start_new_session=True` is passed (on Linux).
- **`test_log_file_naming`** — Call `background_relaunch()` with `args.command = "transcribe"` and check the log file path matches `transcribe_YYYYMMDD_HHMMSS.log` pattern.
- **`test_short_commands_stay_foreground`** — For a short command like `correct`, patch `subprocess.Popen`, run `main()` with appropriate args (patching the actual handler). Verify `Popen` was NOT called — the command runs directly in the foreground.

### 6. Validate

- Run `uv run pytest` and verify all existing tests in `tests/test_cli.py` still pass.
- Run `uv run pytest tests/test_background.py` and verify all new tests pass.
- Run `uv run python -m py_compile cli.py` to verify syntax.

## Testing Strategy

**Unit tests** (in `tests/test_background.py`):
- Mock `subprocess.Popen` to prevent actual process spawning.
- Mock/patch the actual command handlers (e.g., `WhisperRunner`) to prevent import-time failures in CI where dependencies like `faster-whisper` may not be installed.
- Use `tmp_path` fixture for log directory tests.
- Use `monkeypatch` to control `sys.argv` when testing `main()`.

**Edge cases to cover**:
- `--foreground` appended correctly even when other flags are present (e.g., `transcribe /tmp --model tiny --foreground`).
- Short commands with no `--foreground` attribute don't trigger background relaunch (use `getattr` safety).
- Log directory creation when it doesn't exist yet (`mkdir(parents=True, exist_ok=True)`).

**Manual verification** (post-implementation):
- SSH into `devbox-01`, run `uv run cli.py transcribe <folder>`, verify it prints PID/log and exits.
- Run `tail -f /tmp/transcribe_*.log` and confirm output appears.
- Kill the SSH session and verify the background process continues (check with `ps -p <PID>`).

## Acceptance Criteria

- [ ] `uv run cli.py transcribe <folder>` (no `--foreground`) prints PID and log path, then exits immediately.
- [ ] The spawned child process survives SSH disconnection.
- [ ] `uv run cli.py transcribe <folder> --foreground` runs in the terminal as before.
- [ ] `record`, `analyze`, and `pipeline` behave the same way (background by default).
- [ ] Short commands (`correct`, `find-gaps`, `preflight`, `screenshot`, `transfer-transcripts`, `extract-frames`) are unaffected.
- [ ] Log files are created at `/tmp/{command}_{timestamp}.log` (Linux) or `C:\Users\Matt\agent-control\logs\` (Windows).
- [ ] All existing tests pass (`uv run pytest`).
- [ ] New `tests/test_background.py` tests all pass.
- [ ] No new dependencies added.

## Validation Commands

- `uv run python -m py_compile cli.py` — Verify cli.py compiles without syntax errors
- `uv run pytest tests/test_cli.py -v` — Verify existing CLI tests still pass
- `uv run pytest tests/test_background.py -v` — Run the new background execution tests
- `uv run pytest -v` — Full test suite passes

## Notes

- `src/config.py` already defines `LOGS_DIR = Path(r"C:\Users\Matt\agent-control\logs")` and `IS_WINDOWS = sys.platform == "win32"` — reuse these rather than duplicating.
- The `--foreground` flag is the infinite-recursion prevention mechanism: the parent always appends it when spawning the child, so the child never re-launches itself.
- No new dependencies are needed — `subprocess`, `sys`, `os`, `datetime` are all stdlib.
- The log file handle intentionally stays open (owned by the child process) — it closes when the child exits. The parent does not close it because `Popen` inherits the fd.
- `extract-frames` is also excluded from backgrounding even though it can be slow, because it is typically run after `find-gaps` and produces files the user wants to inspect immediately.
