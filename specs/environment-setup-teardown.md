# Plan: Environment Setup & Teardown Module

## Task Description
Add dedicated setup and teardown modules to the media-transcribe pipeline for managing the recording environment (Chrome + OBS) on the obs-machine (Windows). Currently, Chrome and OBS launch logic is scattered across `preflight.py` using direct `subprocess.Popen` calls, which silently fails when invoked over SSH because GUI apps cannot start in a non-interactive session. The new module centralizes this logic, auto-detects SSH sessions, and uses Windows scheduled tasks with `/it` to launch GUI apps in the interactive desktop session when needed.

## Objective
When this plan is complete:
1. A new `src/capture/environment.py` module handles all Chrome + OBS lifecycle management (launch, configure, verify, teardown).
2. `preflight.py` delegates its launch logic to the new module instead of inline `subprocess.Popen`.
3. Two new CLI commands (`setup`, `teardown`) expose environment management directly.
4. The `pipeline` command calls setup before preflight when the `record` step is active.
5. SSH-session detection ensures GUI apps launch correctly whether running locally or over SSH.
6. Comprehensive tests cover all new functionality while remaining cross-platform.

## Problem Statement
When the pipeline runs over SSH (the primary execution mode — devbox-01 SSHing into obs-machine), `subprocess.Popen` launches Chrome and OBS in session 0 (non-interactive). These GUI apps need the interactive desktop session to render and capture video. The current `preflight.py` has no awareness of this distinction, so launches fail silently. Additionally, Chrome is missing the `--autoplay-policy=no-user-gesture-required` flag, requiring manual intervention to start video playback.

## Solution Approach
1. **SSH detection**: Check `SSH_CLIENT`/`SSH_CONNECTION` env vars, plus Windows session ID via `kernel32.ProcessIdToSessionId` — session 0 means non-interactive.
2. **Scheduled task launch**: When in SSH, write a temp `.bat` file, create/update a Windows scheduled task with `/it` (interactive token), run it, poll for the process, verify the service endpoint.
3. **Direct launch**: When local/interactive, use `subprocess.Popen` as today.
4. **OBS configuration**: After launch, connect via obsws-python to set Window Capture source target and Desktop Audio device.
5. **Teardown**: Graceful shutdown via CDP `Browser.close` and OBS WebSocket `ExitStarted` event, with process-kill fallback.
6. **Refactor preflight**: Replace inline launch code with calls to the new module, keeping the 7-gate structure intact.

## Relevant Files
Use these files to complete the task:

- `src/config.py` — All constants: `CHROME_PATH`, `CHROME_PROFILE`, `OBS_PATH`, `OBS_HOST`, `OBS_PORT`, `OBS_PASSWORD`, `CDP_URL`, `IS_WINDOWS`, `SCRIPTS_DIR`
- `src/capture/preflight.py` — Current `_ensure_chrome()` (lines 92-119) and `_ensure_obs()` (lines 121-150) with inline launch logic to refactor
- `src/engines/obs_engine.py` — OBS WebSocket client pattern (connect/disconnect via `obsws_python.ReqClient`)
- `src/capture/window.py` — Win32 ctypes patterns (`ctypes.windll.user32`, `FindWindowW`) to follow for platform-conditional code
- `src/cdp.py` — CDP client with `_send()` method for `Browser.close` call
- `cli.py` — Command registration pattern (lines 57-134 for parser, 137-318 for dispatch)
- `src/pipeline/runner.py` — Pipeline orchestrator; `run()` method and `_health_check()` need environment integration
- `tests/test_preflight.py` — Test patterns: `_mock_preflight()` helper, patching `IS_WINDOWS`, mocking `urllib.request.urlopen`
- `tests/test_cli.py` — CLI test pattern: `build_parser()` + `parse_args()` assertions

### New Files
- `src/capture/environment.py` — Setup/teardown module (core of this plan)
- `tests/test_environment.py` — Tests for the new module

## Implementation Phases

### Phase 1: Foundation
- Add `is_ssh_session()` detection function
- Add constants to `src/config.py` (Chrome flags list, scheduled task name)
- Create the module skeleton with setup/teardown function signatures

### Phase 2: Core Implementation
- Implement `EnvironmentManager` class with `setup()` and `teardown()` methods
- Implement scheduled-task launch path for SSH sessions
- Implement direct-launch path for interactive sessions
- Implement OBS configuration (window capture + audio device)
- Implement verification (CDP health check, OBS WebSocket health check)
- Implement graceful teardown with fallback kill

### Phase 3: Integration & Polish
- Refactor `preflight.py` to delegate to `EnvironmentManager`
- Add `setup` and `teardown` CLI commands
- Wire setup into the pipeline command's record path
- Write all tests

## Step by Step Tasks
IMPORTANT: Execute every step in order, top to bottom.

### 1. Add new constants to src/config.py
- Add `CHROME_FLAGS` list constant:
  ```python
  CHROME_FLAGS = [
      f"--user-data-dir={CHROME_PROFILE}",
      "--remote-debugging-port=9222",
      "--start-maximized",
      "--autoplay-policy=no-user-gesture-required",
  ]
  ```
- Add `SCHTASK_NAME_CHROME = "MediaTranscribe_Chrome"` and `SCHTASK_NAME_OBS = "MediaTranscribe_OBS"` for the scheduled task names
- Add `TEMP_BAT_DIR = SCRIPTS_DIR / "temp"` for temp batch file storage

### 2. Create src/capture/environment.py with SSH detection
- Create the file with imports from `src.config`
- Implement `is_ssh_session() -> bool`:
  - Check `os.environ.get("SSH_CLIENT")` or `os.environ.get("SSH_CONNECTION")` — return `True` if either is set
  - On Windows (`IS_WINDOWS`), additionally check session ID via `ctypes.windll.kernel32.ProcessIdToSessionId` — session 0 is non-interactive
  - Return `False` on Linux (if no SSH env vars — running locally on devbox-01, not relevant)
- Guard all `ctypes.windll` usage behind `IS_WINDOWS` checks so code imports cleanly on Linux

### 3. Implement scheduled task launch helper
- Add `_launch_via_scheduled_task(exe_path: str, args: list[str], task_name: str) -> bool`:
  - Create `TEMP_BAT_DIR` if it doesn't exist
  - Write a temp `.bat` file with the full command (`@echo off`, `start "" "exe_path" args...`)
  - Use `subprocess.run` to create/update the scheduled task:
    ```
    schtasks /create /tn <task_name> /tr <bat_path> /sc once /st 00:00 /f /it /ru Matt
    ```
    - `/f` forces overwrite if task exists
    - `/it` runs in interactive session
    - `/ru Matt` runs as the logged-in user
  - Use `subprocess.run` to execute the task:
    ```
    schtasks /run /tn <task_name>
    ```
  - Return `True` if both commands succeeded (returncode 0)
- Add `_cleanup_scheduled_task(task_name: str) -> None`:
  - `schtasks /delete /tn <task_name> /f` (ignore errors)
  - Remove the temp `.bat` file if it exists

### 4. Implement _launch_app helper
- Add `_launch_app(exe_path: Path, args: list[str], task_name: str) -> bool`:
  - If `is_ssh_session()` → call `_launch_via_scheduled_task()`
  - Else → use `subprocess.Popen([str(exe_path)] + args)` directly
  - Return `True` on success, `False` on exception

### 5. Implement EnvironmentManager class — setup
- Create `EnvironmentManager` class:
  ```python
  class EnvironmentManager:
      def __init__(self, cdp_url: str = CDP_URL):
          self._cdp_url = cdp_url
          self._temp_bat_files: list[Path] = []
  ```
- Implement `setup() -> tuple[bool, list[str]]` that returns `(success, messages)`:
  - Step 1: `_setup_chrome()` — launch Chrome with all flags, wait up to 15s for CDP to respond on `localhost:9222/json`
  - Step 2: `_setup_obs()` — launch OBS with `--minimize-to-tray`, wait up to 15s for WebSocket on `localhost:4455`
  - Step 3: `_configure_obs()` — connect via obsws-python, set Window Capture to target Chrome, set Desktop Audio to 'default'
  - Return `(True, messages)` if all steps succeed, `(False, messages)` with details on first failure
- `_setup_chrome() -> bool`:
  - First check if CDP already responding (`urllib.request.urlopen(f"{cdp_url}/json", timeout=5)`) — if yes, return `True` immediately
  - If not Windows, return `False` (can't launch Chrome on Linux)
  - Build args from `CHROME_FLAGS`
  - Call `_launch_app(CHROME_PATH, args, SCHTASK_NAME_CHROME)`
  - Poll CDP endpoint every 2s for up to 15s total
  - Return `True` if CDP responds, `False` if timeout
- `_setup_obs() -> bool`:
  - First check if OBS WebSocket already responding (try `obsws_python.ReqClient` connect) — if yes, return `True` immediately
  - If not Windows, return `False`
  - Call `_launch_app(OBS_PATH, ["--minimize-to-tray"], SCHTASK_NAME_OBS)`
  - Poll OBS WebSocket every 2s for up to 15s
  - Return `True` if WebSocket responds, `False` if timeout
- `_configure_obs() -> bool`:
  - Connect via `obsws_python.ReqClient`
  - Use `set_input_settings` to configure Window Capture source:
    - `input_name="Window Capture"`, settings: `{"window": "Chrome_WidgetWin_1"}`
    - Use the `get_input_settings` first to check current state; only update if needed
  - Use `set_input_settings` to configure Desktop Audio:
    - `input_name="Desktop Audio"`, settings: `{"device_id": "default"}`
  - Disconnect the client
  - Return `True` on success, `False` on exception

### 6. Implement EnvironmentManager class — teardown
- Implement `teardown() -> tuple[bool, list[str]]` that returns `(success, messages)`:
  - Step 1: `_stop_obs_recording()` — stop recording if active
  - Step 2: `_close_chrome()` — graceful via CDP, fallback process kill
  - Step 3: `_close_obs()` — graceful via WebSocket, fallback process kill
  - Step 4: `_cleanup_temp_files()` — remove temp bat files and scheduled tasks
  - Return `(True, messages)` — teardown should not fail hard; log warnings on individual step failures
- `_stop_obs_recording() -> None`:
  - Connect via `obsws_python.ReqClient`
  - Check `get_record_status().output_active`
  - If recording, call `stop_record()`
  - Disconnect
- `_close_chrome() -> None`:
  - Try CDP `Browser.close`:
    - Open WebSocket to `ws_url` from `localhost:9222/json/version`
    - Send `{"method": "Browser.close"}` and don't wait for response
  - If that fails, fallback to `subprocess.run(["taskkill", "/im", "chrome.exe", "/f"])` on Windows
- `_close_obs() -> None`:
  - Try OBS WebSocket — there's no clean exit command in obsws-python, so fallback to `taskkill`
  - `subprocess.run(["taskkill", "/im", "obs64.exe", "/f"])` on Windows
- `_cleanup_temp_files() -> None`:
  - Call `_cleanup_scheduled_task(SCHTASK_NAME_CHROME)`
  - Call `_cleanup_scheduled_task(SCHTASK_NAME_OBS)`
  - Remove any temp bat files in `TEMP_BAT_DIR`

### 7. Refactor src/capture/preflight.py
- Import `EnvironmentManager` from `src.capture.environment`
- Replace `_ensure_chrome()` body:
  - First try `urllib.request.urlopen(f"{self._cdp_url}/json", timeout=5)` — return `True` if responding
  - Otherwise instantiate `EnvironmentManager(cdp_url=self._cdp_url)` and call `env._setup_chrome()`
  - Return the result
- Replace `_ensure_obs()` body:
  - First try obsws connect — return `True` if responding
  - Otherwise call `env._setup_obs()`
  - Return the result
- Keep `_check_patreon_session()`, `_check_disk_space()`, `_run_test_recording()` unchanged
- Add `--autoplay-policy=no-user-gesture-required` to Chrome flags is handled automatically since Chrome flags now come from `CHROME_FLAGS` constant

### 8. Add setup and teardown CLI commands
- In `build_parser()`, add two new subcommands:
  ```python
  # --- setup ---
  sub.add_parser("setup", help="Launch Chrome + OBS and configure recording environment")

  # --- teardown ---
  sub.add_parser("teardown", help="Stop recording and close Chrome + OBS")
  ```
- In `main()`, add handlers:
  ```python
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
  ```
- These are short commands — do NOT add them to `LONG_RUNNING_COMMANDS`

### 9. Wire setup into pipeline command
- In the `pipeline` command handler in `cli.py` (around line 262, before the Preflight block):
  ```python
  if has_record:
      from src.capture.environment import EnvironmentManager
      env = EnvironmentManager()
      env_ok, env_messages = env.setup()
      for msg in env_messages:
          print(msg)
      if not env_ok:
          print("Environment setup failed — aborting")
          return 1
  ```
- Place this BEFORE the preflight block so Chrome + OBS are running when preflight gates check them
- Do NOT call teardown at the end — user may want to keep the environment running

### 10. Write tests in tests/test_environment.py
- **Test `is_ssh_session()` — SSH env vars**:
  ```python
  def test_is_ssh_session_with_ssh_client():
      with patch.dict(os.environ, {"SSH_CLIENT": "192.168.1.1 12345 22"}):
          assert is_ssh_session() is True

  def test_is_ssh_session_with_ssh_connection():
      with patch.dict(os.environ, {"SSH_CONNECTION": "192.168.1.1 12345 10.0.0.1 22"}):
          assert is_ssh_session() is True

  def test_is_ssh_session_local(monkeypatch):
      monkeypatch.delenv("SSH_CLIENT", raising=False)
      monkeypatch.delenv("SSH_CONNECTION", raising=False)
      with patch("src.capture.environment.IS_WINDOWS", False):
          assert is_ssh_session() is False
  ```
- **Test `is_ssh_session()` — Windows session ID**:
  ```python
  def test_is_ssh_session_windows_session_zero(monkeypatch):
      monkeypatch.delenv("SSH_CLIENT", raising=False)
      monkeypatch.delenv("SSH_CONNECTION", raising=False)
      with patch("src.capture.environment.IS_WINDOWS", True):
          mock_kernel32 = MagicMock()
          def fake_session_id(pid, ref):
              ref.value = 0
          mock_kernel32.ProcessIdToSessionId = fake_session_id
          mock_kernel32.GetCurrentProcessId.return_value = 1234
          with patch("ctypes.windll", create=True) as mock_windll:
              mock_windll.kernel32 = mock_kernel32
              assert is_ssh_session() is True
  ```
- **Test Chrome flags generation**:
  ```python
  def test_chrome_launch_flags():
      from src.config import CHROME_FLAGS
      assert "--remote-debugging-port=9222" in CHROME_FLAGS
      assert "--start-maximized" in CHROME_FLAGS
      assert "--autoplay-policy=no-user-gesture-required" in CHROME_FLAGS
      assert any("--user-data-dir=" in f for f in CHROME_FLAGS)
  ```
- **Test batch file content for scheduled task method**:
  ```python
  def test_scheduled_task_bat_content(tmp_path):
      with patch("src.capture.environment.TEMP_BAT_DIR", tmp_path):
          # Call the internal function that generates the bat file
          # Verify it contains @echo off, start command, correct exe path
          pass  # flesh out with actual _launch_via_scheduled_task mock
  ```
- **Test setup — already running**:
  ```python
  def test_setup_chrome_already_running():
      env = EnvironmentManager()
      with patch("urllib.request.urlopen") as mock_url:
          mock_url.return_value.read.return_value = b'[{"type":"page"}]'
          result = env._setup_chrome()
      assert result is True
  ```
- **Test setup — not running, not Windows**:
  ```python
  def test_setup_chrome_not_running_linux():
      env = EnvironmentManager()
      with patch("urllib.request.urlopen", side_effect=Exception("refused")), \
           patch("src.capture.environment.IS_WINDOWS", False):
          result = env._setup_chrome()
      assert result is False
  ```
- **Test teardown sequence** (mock OBS client, mock CDP):
  ```python
  def test_teardown_stops_recording():
      env = EnvironmentManager()
      mock_client = MagicMock()
      mock_client.get_record_status.return_value.output_active = True
      with patch("src.capture.environment.IS_WINDOWS", True), \
           patch.dict("sys.modules", {"obsws_python": MagicMock()}):
          # Verify stop_record is called before close
          pass
  ```
- **Test OBS configure** (Window Capture + audio):
  ```python
  def test_configure_obs_sets_window_capture():
      env = EnvironmentManager()
      mock_client = MagicMock()
      with patch("src.capture.environment._obs_connect", return_value=mock_client):
          result = env._configure_obs()
      mock_client.set_input_settings.assert_any_call(
          "Window Capture", {"window": ...}, True
      )
      assert result is True
  ```
- **Test CLI commands parse**:
  ```python
  def test_cli_setup_args():
      from cli import build_parser
      parser = build_parser()
      args = parser.parse_args(["setup"])
      assert args.command == "setup"

  def test_cli_teardown_args():
      from cli import build_parser
      parser = build_parser()
      args = parser.parse_args(["teardown"])
      assert args.command == "teardown"
  ```
- All platform-specific code behind `IS_WINDOWS` guards; mock `IS_WINDOWS` in tests so they pass on Linux

### 11. Validate the implementation
- Run `uv run python -m py_compile src/capture/environment.py` to verify syntax
- Run `uv run python -m py_compile src/capture/preflight.py` to verify refactored code compiles
- Run `uv run python -m py_compile cli.py` to verify CLI changes compile
- Run `uv run pytest tests/test_environment.py -v` to verify all new tests pass
- Run `uv run pytest tests/test_preflight.py -v` to verify preflight tests still pass
- Run `uv run pytest tests/test_cli.py -v` to verify CLI tests still pass
- Run `uv run pytest` to verify full suite (303+ tests) passes with no regressions

## Testing Strategy

**Unit tests** (all in `tests/test_environment.py`):

| Area | What to test | Mocking strategy |
|------|-------------|-----------------|
| SSH detection | SSH_CLIENT env var, SSH_CONNECTION env var, no env vars, Windows session 0, Windows session 1 | `patch.dict(os.environ)`, mock `ctypes.windll.kernel32` |
| Chrome setup | Already running (CDP responds), not running on Linux, launch via Popen, launch via scheduled task | Mock `urllib.request.urlopen`, mock `subprocess.Popen`, mock `subprocess.run` |
| OBS setup | Already running (WebSocket responds), not running on Linux, launch paths | Mock `obsws_python.ReqClient`, mock subprocess |
| OBS config | Sets window capture, sets audio device, handles connection failure | Mock `obsws_python.ReqClient` |
| Teardown | Stops recording if active, closes Chrome via CDP, closes OBS via taskkill, cleans up temp files | Mock WebSocket, mock subprocess |
| Batch file | Correct `.bat` content, correct `schtasks` arguments | `tmp_path` fixture, mock subprocess |
| CLI | `setup` and `teardown` parse correctly | `build_parser()` directly |
| Integration | Preflight delegates to EnvironmentManager | Mock EnvironmentManager methods |

**Platform safety**: Every test that touches Windows APIs (`ctypes.windll`, `taskkill`, `schtasks`) must be guarded with `patch("src.capture.environment.IS_WINDOWS", True/False)` so the full test suite passes on Linux (devbox-01).

## Acceptance Criteria
- [ ] `is_ssh_session()` correctly detects SSH sessions via env vars and Windows session ID
- [ ] Chrome launches with all 4 flags including `--autoplay-policy=no-user-gesture-required`
- [ ] When over SSH, Chrome and OBS launch via Windows scheduled tasks with `/it` flag
- [ ] When local, Chrome and OBS launch via direct `subprocess.Popen`
- [ ] OBS Window Capture is configured to target Chrome window after launch
- [ ] OBS Desktop Audio is set to 'default' device after launch
- [ ] CDP health check verifies Chrome on `localhost:9222`
- [ ] OBS WebSocket health check verifies OBS on `localhost:4455`
- [ ] `uv run cli.py setup` launches and configures the environment
- [ ] `uv run cli.py teardown` stops recording, closes Chrome and OBS
- [ ] Pipeline command calls setup before preflight when `record` step is active
- [ ] Pipeline does NOT call teardown at the end
- [ ] `preflight.py` `_ensure_chrome()` and `_ensure_obs()` delegate to the new module
- [ ] Teardown closes Chrome gracefully via CDP `Browser.close`, falls back to `taskkill`
- [ ] Teardown closes OBS, falls back to `taskkill`
- [ ] Temp batch files and scheduled tasks are cleaned up
- [ ] All new tests pass on Linux (devbox-01)
- [ ] Existing test suite (303+ tests) passes with no regressions

## Validation Commands
Execute these commands to validate the task is complete:

- `uv run python -m py_compile src/capture/environment.py` — Verify new module compiles
- `uv run python -m py_compile src/capture/preflight.py` — Verify refactored preflight compiles
- `uv run python -m py_compile cli.py` — Verify CLI changes compile
- `uv run pytest tests/test_environment.py -v` — Run all new environment tests
- `uv run pytest tests/test_preflight.py -v` — Verify preflight tests still pass
- `uv run pytest tests/test_cli.py -v` — Verify CLI tests still pass (including new setup/teardown)
- `uv run pytest` — Full test suite, verify no regressions

## Notes
- **No new dependencies needed.** `obsws_python`, `websockets`, and `ctypes` (stdlib) are already available. `subprocess` and `os` are stdlib.
- **OBS WebSocket API quirk**: The `set_input_settings` call for Window Capture uses the window class name `Chrome_WidgetWin_1` (see `window.py:24`). The exact settings schema depends on the OBS version — test with `get_input_settings` first to confirm field names.
- **Teardown is opt-in.** It's a separate CLI command and is never called automatically by the pipeline. The user explicitly decides when to tear down.
- **Scheduled task user**: The `/ru Matt` flag must match the logged-in Windows user. This is already hardcoded in the SSH patterns in `AGENTS.md`.
- **Polling vs. sleeping**: Setup uses polling loops (check every 2s, up to 15s) rather than a single `time.sleep(15)` to return as fast as possible when the app is ready.
- **Error handling in teardown**: Teardown should be best-effort — log warnings but don't raise. If Chrome is already closed, that's fine. If OBS can't connect, try `taskkill` anyway.
