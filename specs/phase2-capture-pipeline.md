# Plan: Phase 2 — Capture Pipeline (Engines, Recorder, Batch, Sources)

## Task Description
Build the capture pipeline layer on top of Phase 1's core abstractions (`src/config.py`, `src/cdp.py`, `src/players/`). This phase extracts the recording state machine, batch orchestration, preflight validation, content sources, and window management from the monolithic `acquire/record_one.py` and `acquire/record_batch.py` scripts into composable, testable modules under `src/`.

## Objective
When complete, the project has:
1. A `CaptureEngine` Protocol with three implementations: OBS (screen recording), yt-dlp (direct download), and Null (testing).
2. A `Recorder` that composes CDPClient + PlayerHandler + CaptureEngine into a 10-step state machine for single-video capture.
3. A `BatchOrchestrator` for multi-video sessions with queue management, seen-file tracking, mild shuffling, human-like breaks, health checks, and summary reporting.
4. A `Preflight` validator with 7 gates, auto-launch, and auto-login.
5. A `Source` Protocol with Patreon and YouTube implementations for content discovery and authentication.
6. Win32 window management extracted into a platform-conditional module.
7. Full test coverage for all new modules, with existing scripts untouched and runnable.

## Problem Statement
`record_one.py` (307 lines) and `record_batch.py` (1435 lines) contain interleaved concerns: OBS control, window management, CDP orchestration, player handling, credential reading, preflight validation, queue management, and batch scheduling. None of these can be tested in isolation. The recording state machine is hardcoded to a single engine (OBS) and a single source (Patreon), making it impossible to add YouTube yt-dlp downloads or mock recordings for testing without duplicating the orchestration logic.

## Solution Approach
Decompose into **four layers**, each depending only on the layer below and on Phase 1 abstractions:

```
Layer 4: src/capture/batch.py          — multi-video orchestration
Layer 3: src/capture/recorder.py       — single-video state machine
Layer 2: src/engines/, src/sources/    — capture engines + content sources
Layer 1: src/capture/preflight.py,     — validation, window mgmt, credentials
         src/capture/window.py
```

The `Recorder` accepts ANY engine + ANY player handler, so OBS screen-recording a Patreon Mux video, yt-dlp downloading a YouTube video, or a NullEngine test recording all use the same state machine. The `BatchOrchestrator` accepts ANY source, making it trivial to add new content providers.

## Relevant Files

### Phase 1 outputs (read-only reference — already implemented)
- `src/config.py` — Centralized constants (paths, ports, passwords, break times, platform detection)
- `src/cdp.py` — `CDPClient` async context-managed CDP WebSocket client
- `src/players/base.py` — `PlayerHandler` Protocol + `DetectionResult` dataclass
- `src/players/detector.py` — `detect_player()` — single JS eval → handler instance
- `src/players/mux.py` — `MuxPlayer` handler (shadow DOM video, TAC trick fullscreen)
- `src/players/vimeo.py` — `VimeoPlayer` handler (iframe, Vimeo Player.js SDK)
- `src/players/html5.py` — `HTML5Player` handler (generic `<video>`)
- `src/players/_common.py` — Shared TAC trick fullscreen logic

### Existing scripts (extract logic from — do NOT modify or delete)
- `acquire/record_one.py` — 10-step state machine (lines 51-306), `focus_chrome()` Win32 API (lines 28-48), OBS control (lines 210-215, 278-304), file move with retry (lines 286-304)
- `acquire/record_batch.py` — Credential reader (lines 118-169), Chrome/OBS management (lines 175-325), Patreon session check (lines 330-495), disk space check (lines 501-519), test recording (lines 525-686), ffmpeg analysis (lines 689-793), preflight orchestrator (lines 799-888), health check (lines 894-947), seen-file tracking (lines 953-968), queue loading (lines 974-1014), mild shuffle (lines 1020-1034), subprocess recording (lines 1040-1136), human break (lines 1142-1173), summary report (lines 1179-1227)
- `acquire/patreon_capture_remote.py` — `Recorder` OBS class (lines 112-147), monitor loop (lines 339-375), file move (lines 381-401)
- `acquire/patreon_catalog_remote.py` — Stealth behaviors: random scroll (lines 49-65), reading pauses (lines 59-62), mouse moves (lines 63-65)

### New files to create
- `src/engines/__init__.py` — Package marker
- `src/engines/base.py` — `CaptureEngine` Protocol
- `src/engines/obs_engine.py` — `OBSEngine` (obsws-python wrapper)
- `src/engines/ytdlp_engine.py` — `YtDlpEngine` (yt-dlp subprocess)
- `src/engines/null_engine.py` — `NullEngine` (testing stub)
- `src/capture/__init__.py` — Package marker
- `src/capture/window.py` — Win32 window management (platform-conditional)
- `src/capture/credentials.py` — Windows Credential Manager reader
- `src/capture/recorder.py` — `Recorder` single-video state machine
- `src/capture/preflight.py` — 7-gate preflight validation
- `src/capture/batch.py` — `BatchOrchestrator` multi-video scheduler
- `src/sources/__init__.py` — Package marker
- `src/sources/base.py` — `Source` Protocol + `Post` dataclass
- `src/sources/patreon.py` — `PatreonSource` (auth, search, stealth)
- `src/sources/youtube.py` — `YouTubeSource` (yt-dlp catalog)
- `tests/test_obs_engine.py` — OBSEngine mock tests
- `tests/test_ytdlp_engine.py` — YtDlpEngine subprocess tests
- `tests/test_recorder.py` — Recorder state machine tests
- `tests/test_batch.py` — BatchOrchestrator pure-logic tests
- `tests/test_preflight.py` — Preflight gate pass/fail tests
- `tests/test_window.py` — Platform-conditional window tests
- `tests/test_patreon_source.py` — PatreonSource URL/login tests

## Implementation Phases

### Phase 1: Foundation (engines + window + credentials)
Build the lowest-level building blocks that have no dependencies on other Phase 2 modules: capture engines, window management, and credential reading.

### Phase 2: Core Implementation (recorder + preflight + sources)
Build the single-video recorder (composes Phase 1 abstractions + engines), preflight validation (composes engines + credential reader), and content sources.

### Phase 3: Integration & Polish (batch orchestrator + wiring)
Build the batch orchestrator that composes recorder + sources + preflight, then validate end-to-end with the full test suite.

## Step by Step Tasks
IMPORTANT: Execute every step in order, top to bottom.

### 1. Create package structure

- Create directories: `src/engines/`, `src/capture/`, `src/sources/`
- Create empty `__init__.py` files in each new directory
- Verify with: `uv run python -c "import src.engines, src.capture, src.sources; print('OK')"`

### 2. Write `src/engines/base.py` — CaptureEngine Protocol

- Write the Protocol class:
  ```python
  """Capture engine protocol — abstracts the recording mechanism."""
  from __future__ import annotations

  from dataclasses import dataclass, field
  from typing import Protocol, runtime_checkable


  @dataclass
  class EngineStatus:
      recording: bool = False
      output_path: str | None = None
      duration_seconds: float = 0.0
      extra: dict = field(default_factory=dict)


  @runtime_checkable
  class CaptureEngine(Protocol):
      name: str

      def start(self, filename: str) -> None: ...
      def stop(self) -> str | None: ...
      def is_recording(self) -> bool: ...
      def get_status(self) -> EngineStatus: ...
  ```
- No dedicated test — the Protocol is tested implicitly by the concrete implementations.

### 3. Write `src/engines/null_engine.py` — NullEngine (testing stub)

- Write `tests/test_null_engine.py` first:
  - Test start sets recording state and filename
  - Test stop returns a dummy path and clears recording state
  - Test is_recording reflects current state
  - Test get_status returns correct EngineStatus
  - Test double-start raises or is idempotent (pick one, document it)
- Implement `NullEngine`:
  ```python
  class NullEngine:
      name = "null"

      def __init__(self):
          self._recording = False
          self._filename: str | None = None

      def start(self, filename: str) -> None:
          self._recording = True
          self._filename = filename

      def stop(self) -> str | None:
          self._recording = False
          path = f"/tmp/{self._filename}.mp4" if self._filename else None
          self._filename = None
          return path

      def is_recording(self) -> bool:
          return self._recording

      def get_status(self) -> EngineStatus:
          return EngineStatus(recording=self._recording)
  ```
- Run `uv run pytest tests/test_null_engine.py`

### 4. Write `src/engines/obs_engine.py` — OBSEngine

- Write `tests/test_obs_engine.py` first (mock `obsws_python`):
  - Test `start()` calls `set_profile_parameter` then `start_record`
  - Test `stop()` calls `stop_record` and returns `output_path` from response
  - Test `is_recording()` calls `get_record_status().output_active`
  - Test `get_status()` returns correct EngineStatus with OBS response fields
  - Test file move with retry: mock `shutil.move` raising `PermissionError` 3 times then succeeding
  - Test file move exhausting all 6 retries
  - Test lazy import of `obsws_python` — engine creation on non-Windows should not fail at import time, only when `connect()` is called
  - Test `get_screenshot()` returns base64 image data

- Implement `OBSEngine`:
  ```python
  """OBS Studio capture engine via obsws-python WebSocket."""
  from __future__ import annotations

  import logging
  import os
  import shutil
  import time
  from pathlib import Path

  from src.config import OBS_HOST, OBS_PORT, OBS_PASSWORD, BACKUP_DIR
  from src.engines.base import CaptureEngine, EngineStatus

  log = logging.getLogger(__name__)


  class OBSEngine:
      name = "obs"

      def __init__(
          self,
          host: str = OBS_HOST,
          port: int = OBS_PORT,
          password: str = OBS_PASSWORD,
          backup_dir: Path = BACKUP_DIR,
      ):
          self._host = host
          self._port = port
          self._password = password
          self._backup_dir = backup_dir
          self._client = None
          self._recording = False
          self._output_path: str | None = None

      def connect(self) -> None:
          import obsws_python as obs  # lazy — only on Windows/capture box
          self._client = obs.ReqClient(
              host=self._host,
              port=self._port,
              password=self._password,
              timeout=10,
          )

      def disconnect(self) -> None:
          if self._client:
              self._client.base_client.ws.close()
              self._client = None

      def start(self, filename: str) -> None:
          if not self._client:
              self.connect()
          self._client.set_profile_parameter(
              "Output", "FilenameFormatting", filename,
          )
          self._client.start_record()
          self._recording = True
          time.sleep(2)  # let OBS stabilise

      def stop(self) -> str | None:
          if not self._client:
              return None
          resp = self._client.stop_record()
          self._recording = False
          self._output_path = getattr(resp, "output_path", None)
          return self._output_path

      def is_recording(self) -> bool:
          if self._client:
              try:
                  return self._client.get_record_status().output_active
              except Exception:
                  pass
          return self._recording

      def get_status(self) -> EngineStatus:
          return EngineStatus(
              recording=self.is_recording(),
              output_path=self._output_path,
          )

      def get_screenshot(self, source: str = "Window Capture") -> str | None:
          """Get a base64-encoded screenshot from OBS."""
          if not self._client:
              return None
          try:
              resp = self._client.get_source_screenshot(
                  source, "png", 1920, 1080, 85,
              )
              return getattr(resp, "image_data", None)
          except Exception:
              return None

      def move_to_backup(self, src_path: str, filename: str) -> str | None:
          """Move recording to backup dir with retry for WinError 32.

          OBS holds the file handle briefly after stop_record.
          Retries up to 6 times with 5s between attempts.
          """
          if not src_path or not os.path.isfile(src_path):
              return None

          ext = os.path.splitext(src_path)[1] or ".mp4"
          dest = str(self._backup_dir / f"{filename}{ext}")
          self._backup_dir.mkdir(parents=True, exist_ok=True)

          for attempt in range(6):
              try:
                  shutil.move(src_path, dest)
                  size_mb = os.path.getsize(dest) / (1024 * 1024)
                  log.info("Moved: %s (%.1f MB)", dest, size_mb)
                  return dest
              except PermissionError:
                  if attempt < 5:
                      log.warning(
                          "File locked, retrying in 5s... (%d/6)", attempt + 1,
                      )
                      time.sleep(5)
                  else:
                      log.error("Could not move after 6 attempts: %s", src_path)

          return src_path  # return original path if move failed
  ```

- Reference: `acquire/record_one.py` lines 210-215 (OBS start), 278-304 (stop + move), `acquire/patreon_capture_remote.py` lines 112-147 (Recorder class), `acquire/record_batch.py` lines 276-324 (OBS ensure/alive checks)
- Run `uv run pytest tests/test_obs_engine.py`

### 5. Write `src/engines/ytdlp_engine.py` — YtDlpEngine

- Write `tests/test_ytdlp_engine.py` first (mock `subprocess`):
  - Test `start()` launches `uvx yt-dlp` subprocess with URL and output path
  - Test `stop()` waits for subprocess to complete and returns output path
  - Test `is_recording()` checks if subprocess is still running
  - Test subprocess failure raises or returns None
  - Test output path templating with filename

- Implement `YtDlpEngine`:
  ```python
  """yt-dlp capture engine — direct download, no screen recording."""
  from __future__ import annotations

  import logging
  import subprocess
  from pathlib import Path

  from src.engines.base import EngineStatus

  log = logging.getLogger(__name__)


  class YtDlpEngine:
      name = "ytdlp"

      def __init__(self, output_dir: Path | str = "."):
          self._output_dir = Path(output_dir)
          self._proc: subprocess.Popen | None = None
          self._output_path: str | None = None
          self._url: str | None = None

      def set_url(self, url: str) -> None:
          """Set the URL to download (must be called before start)."""
          self._url = url

      def start(self, filename: str) -> None:
          if not self._url:
              raise ValueError("URL not set — call set_url() before start()")
          self._output_dir.mkdir(parents=True, exist_ok=True)
          self._output_path = str(self._output_dir / f"{filename}.%(ext)s")
          cmd = [
              "uvx", "yt-dlp",
              self._url,
              "-o", self._output_path,
              "--no-playlist",
          ]
          log.info("Starting yt-dlp: %s", " ".join(cmd))
          self._proc = subprocess.Popen(
              cmd,
              stdout=subprocess.PIPE,
              stderr=subprocess.STDOUT,
              text=True,
          )

      def stop(self) -> str | None:
          if not self._proc:
              return None
          self._proc.wait()
          if self._proc.returncode != 0:
              log.error("yt-dlp exited with code %d", self._proc.returncode)
              return None
          # yt-dlp replaces %(ext)s with actual extension — find the file
          if self._output_path:
              base = self._output_path.replace(".%(ext)s", "")
              parent = Path(base).parent
              stem = Path(base).name
              for f in parent.iterdir():
                  if f.stem == stem or f.name.startswith(stem):
                      return str(f)
          return self._output_path

      def is_recording(self) -> bool:
          if self._proc:
              return self._proc.poll() is None
          return False

      def get_status(self) -> EngineStatus:
          return EngineStatus(
              recording=self.is_recording(),
              output_path=self._output_path,
          )
  ```
- Run `uv run pytest tests/test_ytdlp_engine.py`

### 6. Write `src/capture/credentials.py` — Windows Credential Manager

- Write `tests/test_credentials.py` first:
  - Test on non-Windows returns None (no ctypes.wintypes)
  - Test successful credential read returns (username, password) tuple
  - Test missing credential returns None
  - All tests mock ctypes — no real Win32 calls

- Extract from `acquire/record_batch.py` lines 118-169:
  ```python
  """Windows Credential Manager reader (ctypes / advapi32.dll)."""
  from __future__ import annotations

  import logging

  from src.config import IS_WINDOWS

  log = logging.getLogger(__name__)


  def read_credential(target: str) -> tuple[str, str] | None:
      """Read username + password from Windows Credential Manager.

      Returns (username, password) or None if not found or not on Windows.
      """
      if not IS_WINDOWS:
          log.debug("Not Windows — credential read skipped")
          return None

      try:
          import ctypes
          import ctypes.wintypes
      except ImportError:
          log.warning("ctypes.wintypes unavailable")
          return None

      class CREDENTIAL(ctypes.Structure):
          _fields_ = [
              ("Flags", ctypes.wintypes.DWORD),
              ("Type", ctypes.wintypes.DWORD),
              ("TargetName", ctypes.wintypes.LPWSTR),
              ("Comment", ctypes.wintypes.LPWSTR),
              ("LastWritten", ctypes.wintypes.FILETIME),
              ("CredentialBlobSize", ctypes.wintypes.DWORD),
              ("CredentialBlob", ctypes.POINTER(ctypes.c_char)),
              ("Persist", ctypes.wintypes.DWORD),
              ("AttributeCount", ctypes.wintypes.DWORD),
              ("Attributes", ctypes.c_void_p),
              ("TargetAlias", ctypes.wintypes.LPWSTR),
              ("UserName", ctypes.wintypes.LPWSTR),
          ]

      try:
          advapi32 = ctypes.windll.advapi32
      except AttributeError:
          log.warning("ctypes.windll unavailable")
          return None

      cred_ptr = ctypes.POINTER(CREDENTIAL)()
      ok = advapi32.CredReadW(target, 1, 0, ctypes.byref(cred_ptr))
      if not ok:
          log.warning("CredReadW failed for target=%s", target)
          return None
      try:
          cred = cred_ptr.contents
          username = cred.UserName or ""
          password = ctypes.string_at(
              cred.CredentialBlob, cred.CredentialBlobSize,
          ).decode("utf-16-le")
          return (username, password)
      finally:
          advapi32.CredFree(cred_ptr)
  ```
- Reference: `acquire/record_batch.py` lines 118-169
- Run `uv run pytest tests/test_credentials.py`

### 7. Write `src/capture/window.py` — Win32 window management

- Write `tests/test_window.py` first:
  - Test on non-Windows: all functions return False or skip gracefully
  - Test `focus_chrome()` calls Win+D, FindWindowW, ShowWindow, SetForegroundWindow in order (mock ctypes)
  - Test `find_window()` returns hwnd when window exists, None when not
  - Test `maximize_window()` calls ShowWindow with SW_MAXIMIZE (3)

- Extract from `acquire/record_one.py` lines 28-48:
  ```python
  """Win32 window management — platform-conditional, ctypes-based."""
  from __future__ import annotations

  import logging
  import time

  from src.config import IS_WINDOWS

  log = logging.getLogger(__name__)


  def focus_chrome() -> bool:
      """Find and focus the Chrome window using Win32 API.

      Minimizes all windows (Win+D), finds Chrome by class name,
      maximizes it, and brings it to foreground.
      Returns True if Chrome window was found and focused.
      """
      if not IS_WINDOWS:
          log.debug("Not Windows — focus_chrome is a no-op")
          return False

      import ctypes
      user32 = ctypes.windll.user32

      # Win+D to minimize all windows
      user32.keybd_event(0x5B, 0, 0, 0)  # Win key down
      user32.keybd_event(0x44, 0, 0, 0)  # D key down
      user32.keybd_event(0x44, 0, 2, 0)  # D key up
      user32.keybd_event(0x5B, 0, 2, 0)  # Win key up
      time.sleep(1)

      hwnd = user32.FindWindowW("Chrome_WidgetWin_1", None)
      if hwnd:
          user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
          user32.SetForegroundWindow(hwnd)
          time.sleep(0.5)
          return True

      log.warning("Chrome window not found")
      return False


  def find_window(class_name: str | None = None, title_contains: str | None = None) -> int | None:
      """Find a window by class name or title substring. Returns hwnd or None."""
      if not IS_WINDOWS:
          return None

      import ctypes
      user32 = ctypes.windll.user32

      if class_name:
          hwnd = user32.FindWindowW(class_name, None)
          return hwnd if hwnd else None

      if title_contains:
          # EnumWindows approach for substring matching
          result = [None]

          @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
          def enum_callback(hwnd, _):
              buf = ctypes.create_unicode_buffer(256)
              user32.GetWindowTextW(hwnd, buf, 256)
              if title_contains.lower() in buf.value.lower():
                  result[0] = hwnd
                  return False  # stop enumeration
              return True

          user32.EnumWindows(enum_callback, 0)
          return result[0]

      return None


  def minimize_window(hwnd: int) -> None:
      """Minimize a window by hwnd."""
      if not IS_WINDOWS or not hwnd:
          return
      import ctypes
      ctypes.windll.user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE


  def maximize_window(hwnd: int) -> None:
      """Maximize a window by hwnd."""
      if not IS_WINDOWS or not hwnd:
          return
      import ctypes
      ctypes.windll.user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
  ```
- Reference: `acquire/record_one.py` lines 28-48
- Run `uv run pytest tests/test_window.py`

### 8. Write `src/sources/base.py` — Source Protocol + Post dataclass

- Define the abstractions:
  ```python
  """Content source protocol and Post dataclass."""
  from __future__ import annotations

  from dataclasses import dataclass, field
  from typing import Protocol, runtime_checkable, TYPE_CHECKING

  if TYPE_CHECKING:
      from src.cdp import CDPClient


  @dataclass
  class Post:
      url: str
      title: str
      filename: str = ""
      player_type: str | None = None
      duration: float | None = None
      recorded: bool = False
      meta: dict = field(default_factory=dict)

      def __post_init__(self):
          if not self.filename:
              bad = '<>:"/\\|?*'
              cleaned = "".join("_" if c in bad else c for c in self.title).strip()
              self.filename = cleaned if cleaned.strip("_ ") else "episode"


  @runtime_checkable
  class Source(Protocol):
      name: str

      async def authenticate(self, cdp: CDPClient) -> bool: ...
      async def get_posts(self, cdp: CDPClient, query: str | None = None) -> list[Post]: ...
      async def navigate_to(self, cdp: CDPClient, url: str) -> None: ...
  ```
- No dedicated test file — tested through concrete implementations.

### 9. Write `src/sources/patreon.py` — PatreonSource

- Write `tests/test_patreon_source.py` first:
  - Test `authenticate()` when session is valid (no login form) returns True
  - Test `authenticate()` detects login form, fills credentials, submits
  - Test `authenticate()` fails when credentials missing
  - Test search URL construction with query parameter
  - Test `navigate_to()` calls cdp.navigate
  - Test stealth behavior parameters (scroll range, delay range, pause chance)
  - All tests mock CDPClient

- Implement `PatreonSource`:
  ```python
  """Patreon content source — auth, search, navigation with stealth."""
  from __future__ import annotations

  import asyncio
  import json
  import logging
  import random
  from typing import TYPE_CHECKING

  from src.config import CRED_TARGET
  from src.sources.base import Post, Source

  if TYPE_CHECKING:
      from src.cdp import CDPClient

  log = logging.getLogger(__name__)

  # Stealth parameters (from patreon_catalog_remote.py)
  SCROLL_PX_MIN = 600
  SCROLL_PX_MAX = 1000
  SCROLL_DELAY_MIN = 1.5
  SCROLL_DELAY_MAX = 5.0
  READING_PAUSE_CHANCE = 0.20
  READING_PAUSE_MIN = 5.0
  READING_PAUSE_MAX = 12.0
  MOUSE_MOVE_CHANCE = 0.65


  class PatreonSource:
      name = "patreon"

      def __init__(self, cred_target: str = CRED_TARGET):
          self._cred_target = cred_target

      async def authenticate(self, cdp: CDPClient) -> bool:
          """Check Patreon session; auto-login if expired."""
          await cdp.navigate("https://www.patreon.com/home", wait=5.0)

          login_detected = await cdp.js(
              "!!document.querySelector("
              "'input[name=\"email\"], "
              "form[action*=\"login\"], "
              "input[type=\"email\"]')"
          )

          if not login_detected:
              log.info("Patreon session is valid")
              await cdp.navigate("about:blank", wait=0.0)
              return True

          log.info("Login form detected — attempting auto-login")
          from src.capture.credentials import read_credential
          creds = read_credential(self._cred_target)
          if not creds:
              log.error("No credentials for target=%s", self._cred_target)
              return False

          email, password = creds

          # Fill email
          await cdp.js(f"""(() => {{
              const el = document.querySelector('input[name="email"], input[type="email"]');
              if (el) {{
                  el.focus();
                  el.value = {json.dumps(email)};
                  el.dispatchEvent(new Event('input', {{bubbles: true}}));
                  el.dispatchEvent(new Event('change', {{bubbles: true}}));
              }}
          }})()""")
          await asyncio.sleep(1)

          # Click continue
          await cdp.js("""(() => {
              const btns = [...document.querySelectorAll('button')];
              const next = btns.find(b => /continue|next|log\\s*in|sign\\s*in/i.test(b.textContent));
              if (next) next.click();
          })()""")
          await asyncio.sleep(3)

          # Fill password
          await cdp.js(f"""(() => {{
              const el = document.querySelector('input[type="password"]');
              if (el) {{
                  el.focus();
                  el.value = {json.dumps(password)};
                  el.dispatchEvent(new Event('input', {{bubbles: true}}));
                  el.dispatchEvent(new Event('change', {{bubbles: true}}));
              }}
          }})()""")
          await asyncio.sleep(1)

          # Submit
          await cdp.js("""(() => {
              const btns = [...document.querySelectorAll('button')];
              const submit = btns.find(b => /log\\s*in|sign\\s*in|submit|continue/i.test(b.textContent));
              if (submit) submit.click();
          })()""")
          await asyncio.sleep(5)

          # Verify
          still_login = await cdp.js(
              "!!document.querySelector("
              "'input[name=\"email\"], form[action*=\"login\"]')"
          )
          if still_login:
              log.error("Login failed (form still present)")
              return False

          log.info("Login succeeded")
          await cdp.navigate("about:blank", wait=0.0)
          return True

      async def get_posts(self, cdp: CDPClient, query: str | None = None) -> list[Post]:
          """Search Patreon posts. Uses filter URL pattern for queries."""
          # Implementation uses the search URL pattern from patreon_catalog_remote.py
          # For now, return empty — catalog integration is Phase 3
          return []

      async def navigate_to(self, cdp: CDPClient, url: str) -> None:
          """Navigate to a post URL with stealth delays."""
          await cdp.navigate(url, wait=8.0)

          # Random mouse movement to appear human
          if random.random() < MOUSE_MOVE_CHANCE:
              await cdp.move_mouse(
                  random.randint(400, 1200),
                  random.randint(200, 700),
              )
              await asyncio.sleep(random.uniform(0.1, 0.4))
  ```
- Reference: `acquire/record_batch.py` lines 330-495 (session check + auto-login), `acquire/patreon_catalog_remote.py` lines 49-65 (stealth params)
- Run `uv run pytest tests/test_patreon_source.py`

### 10. Write `src/sources/youtube.py` — YouTubeSource

- Write `tests/test_youtube_source.py` first:
  - Test `authenticate()` always returns True (no auth needed)
  - Test `get_posts()` runs `yt-dlp --flat-playlist` and parses JSON output
  - Test `navigate_to()` calls cdp.navigate
  - Mock subprocess for yt-dlp

- Implement `YouTubeSource`:
  ```python
  """YouTube content source — catalog via yt-dlp, no auth needed."""
  from __future__ import annotations

  import json
  import logging
  import subprocess
  from typing import TYPE_CHECKING

  from src.sources.base import Post

  if TYPE_CHECKING:
      from src.cdp import CDPClient

  log = logging.getLogger(__name__)


  class YouTubeSource:
      name = "youtube"

      async def authenticate(self, cdp: CDPClient) -> bool:
          return True

      async def get_posts(self, cdp: CDPClient, query: str | None = None) -> list[Post]:
          """Catalog videos from a YouTube URL/playlist via yt-dlp."""
          if not query:
              return []
          try:
              proc = subprocess.run(
                  ["uvx", "yt-dlp", "--flat-playlist", "-J", query],
                  capture_output=True, text=True, timeout=60,
              )
              if proc.returncode != 0:
                  log.error("yt-dlp failed: %s", proc.stderr[:200])
                  return []
              data = json.loads(proc.stdout)
              entries = data.get("entries", [data]) if "entries" in data else [data]
              return [
                  Post(
                      url=e.get("webpage_url") or e.get("url", ""),
                      title=e.get("title", "Untitled"),
                      duration=e.get("duration"),
                      player_type="youtube",
                  )
                  for e in entries
                  if e.get("webpage_url") or e.get("url")
              ]
          except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as exc:
              log.error("yt-dlp catalog error: %s", exc)
              return []

      async def navigate_to(self, cdp: CDPClient, url: str) -> None:
          await cdp.navigate(url, wait=8.0)
  ```
- Run `uv run pytest tests/test_youtube_source.py`

### 11. Write `src/capture/recorder.py` — Single-video Recorder

- Write `tests/test_recorder.py` first (mock CDPClient + NullEngine):
  - **Happy path**: Test all 10 steps complete successfully with NullEngine
  - **Player not found**: Test early abort when detect_player returns None
  - **Fullscreen failure**: Test abort when fullscreen fails after retries
  - **Mute guard**: Test re-unmute during monitoring when muted=true detected
  - **Stall detection**: Test stall nudge after 6 stalled polls
  - **Pause detection**: Test auto-resume when paused during monitoring
  - **Engine start failure**: Test error handling when engine.start raises
  - **End detection**: Test normal completion when `is_ended` returns True
  - **End detection by position**: Test completion when position >= duration - 2

- Implement `Recorder` — the 10-step state machine extracted from `record_one.py`:
  ```python
  """Single-video recorder — composes CDP + player handler + capture engine."""
  from __future__ import annotations

  import asyncio
  import logging
  from dataclasses import dataclass, field
  from typing import TYPE_CHECKING

  from src.players.detector import detect_player

  if TYPE_CHECKING:
      from src.cdp import CDPClient
      from src.engines.base import CaptureEngine

  log = logging.getLogger(__name__)

  POLL_INTERVAL = 30  # seconds between monitoring polls
  STALL_THRESHOLD = 6  # consecutive stalled polls before nudge


  @dataclass
  class RecordResult:
      ok: bool = False
      url: str = ""
      filename: str = ""
      output_path: str | None = None
      duration_seconds: float = 0.0
      error: str | None = None
      extra: dict = field(default_factory=dict)


  class Recorder:
      def __init__(self, engine: CaptureEngine):
          self.engine = engine

      async def record_one(
          self,
          cdp: CDPClient,
          url: str,
          filename: str,
          *,
          focus_fn=None,  # Optional window focus callable
      ) -> RecordResult:
          result = RecordResult(url=url, filename=filename)

          try:
              # 1. Navigate
              log.info("[1/10] Navigating to %s", url)
              await cdp.js(
                  "if(document.fullscreenElement) document.exitFullscreen(); 'ok'"
              )
              await asyncio.sleep(1)
              await cdp.navigate(url, wait=10.0)

              # 2. Detect player
              log.info("[2/10] Detecting player...")
              detection, handler = await detect_player(cdp)
              if not handler:
                  result.error = f"No supported player found (detected: {detection.player})"
                  log.error(result.error)
                  return result

              # Get duration
              duration = await handler.get_duration(cdp, detection)
              if not duration or duration <= 0:
                  # Poll for duration
                  for _ in range(15):
                      duration = await handler.get_duration(cdp, detection)
                      if duration and duration > 0:
                          break
                      await asyncio.sleep(2)

              if not duration or duration <= 0:
                  result.error = "Could not determine video duration"
                  log.error(result.error)
                  return result

              result.duration_seconds = duration
              log.info("  Duration: %.0fs (%.1f min)", duration, duration / 60)

              # 3. Pause + reset + unmute
              log.info("[3/10] Reset to 0:00 + unmute")
              await handler.pause(cdp, detection)
              await handler.seek(cdp, 0.0)
              await handler.unmute(cdp)
              await asyncio.sleep(2)

              # 4. Fullscreen
              log.info("[4/10] Entering fullscreen...")
              if focus_fn:
                  focus_fn()
                  await asyncio.sleep(1)

              fs = await handler.fullscreen(cdp, detection)
              if not fs:
                  result.error = "Fullscreen rejected after all attempts"
                  log.error(result.error)
                  return result

              # 5. Re-pause + confirm unmuted
              log.info("[5/10] Re-pause at 0:00")
              await handler.pause(cdp, detection)
              await handler.seek(cdp, 0.0)
              await handler.unmute(cdp)
              await asyncio.sleep(2)

              # 6. Hide cursor
              log.info("[6/10] Hiding cursor")
              await cdp.move_mouse(0, 0)
              await asyncio.sleep(2)

              # 7. Start engine
              log.info("[7/10] Starting capture engine (%s)", self.engine.name)
              self.engine.start(filename)

              # 8. Play from beginning
              log.info("[8/10] Playing...")
              await handler.seek(cdp, 0.0)
              await handler.unmute(cdp)
              await handler.play(cdp, detection)
              await asyncio.sleep(3)

              # Hide cursor again
              await cdp.move_mouse(0, 0)

              # 9. Monitor
              log.info("[9/10] Monitoring (~%.0f min)...", duration / 60)
              stall_count = 0
              last_pos = -1.0

              while True:
                  pos = await handler.get_position(cdp)
                  ended = await handler.is_ended(cdp)

                  pct = (pos / duration * 100) if duration > 0 else 0
                  log.info("  %.0fs / %.0fs (%.1f%%)", pos, duration, pct)

                  if ended or (pos >= duration - 2 and duration > 0):
                      log.info("  VIDEO ENDED")
                      break

                  # Mute guard
                  await handler.unmute(cdp)

                  # Stall detection
                  if abs(pos - last_pos) < 0.5:
                      stall_count += 1
                      if stall_count > STALL_THRESHOLD:
                          log.warning("  STALLED — nudging")
                          await handler.seek(cdp, pos + 0.5)
                          await handler.play(cdp, detection)
                          stall_count = 0
                  else:
                      stall_count = 0
                  last_pos = pos

                  await asyncio.sleep(POLL_INTERVAL)

              # 10. Stop engine + cleanup
              log.info("[10/10] Stopping capture")
              await asyncio.sleep(3)
              output_path = self.engine.stop()
              result.output_path = output_path
              result.ok = True

              # Exit fullscreen
              await cdp.js(
                  "if(document.fullscreenElement) document.exitFullscreen(); 'ok'"
              )

          except Exception as exc:
              result.error = str(exc)
              log.error("Recording failed: %s", exc)
              if self.engine.is_recording():
                  try:
                      self.engine.stop()
                  except Exception:
                      pass

          return result
  ```
- Reference: `acquire/record_one.py` lines 51-306 (entire state machine)
- Run `uv run pytest tests/test_recorder.py`

### 12. Write `src/capture/preflight.py` — Preflight validation

- Write `tests/test_preflight.py` first:
  - Test all 7 gates pass → returns True
  - Test Chrome CDP down → auto-launch, then pass
  - Test Chrome CDP down → auto-launch fails → returns False
  - Test OBS WebSocket down → auto-launch, then pass
  - Test Patreon session expired → auto-login via credentials
  - Test disk space insufficient → returns False
  - Test test recording with black video → video_ok=False
  - Test test recording with silent audio → audio_ok=False
  - Test gate skip when dependency failed (e.g., skip Patreon when Chrome failed)
  - All tests mock subprocess, obsws_python, urllib, CDPClient

- Implement `Preflight`:
  ```python
  """Preflight validation — 7-gate startup check with auto-recovery."""
  from __future__ import annotations

  import asyncio
  import json
  import logging
  import os
  import re
  import shutil
  import subprocess
  import time
  import urllib.request
  from pathlib import Path
  from typing import TYPE_CHECKING

  from src.config import (
      CDP_URL, CHROME_PATH, CHROME_PROFILE,
      OBS_PATH, OBS_HOST, OBS_PORT, OBS_PASSWORD,
      IS_WINDOWS,
  )

  if TYPE_CHECKING:
      from src.cdp import CDPClient

  log = logging.getLogger(__name__)

  DISK_MIN_GB = 5
  PREFLIGHT_VIDEO_URL = "file:///C:/Users/Matt/agent-control/scripts/audio_test.html"


  @dataclass
  class GateResult:
      name: str
      passed: bool
      detail: str = ""


  class Preflight:
      def __init__(self, cdp_url: str = CDP_URL):
          self._cdp_url = cdp_url

      def run_all(self) -> tuple[bool, list[GateResult]]:
          """Run all preflight gates. Returns (all_ok, gate_results)."""
          gates: list[GateResult] = []
          all_ok = True

          # Gate 1: Chrome CDP
          chrome_ok = self._ensure_chrome()
          gates.append(GateResult("Chrome CDP", chrome_ok))
          if not chrome_ok:
              all_ok = False

          # Gate 2: OBS WebSocket
          obs_ok = self._ensure_obs()
          gates.append(GateResult("OBS WebSocket", obs_ok))
          if not obs_ok:
              all_ok = False

          # Gate 3: Patreon session (requires Chrome)
          if chrome_ok:
              patreon_ok = self._check_patreon_session()
              gates.append(GateResult("Patreon session", patreon_ok))
              if not patreon_ok:
                  all_ok = False
          else:
              gates.append(GateResult("Patreon session", False, "skipped (no Chrome)"))
              all_ok = False

          # Gate 4: Disk space
          disk_ok, disk_detail = self._check_disk_space()
          gates.append(GateResult("Disk space", disk_ok, disk_detail))
          if not disk_ok:
              all_ok = False

          # Gates 5-7: Test recording (requires Chrome + OBS)
          if chrome_ok and obs_ok:
              video_ok, audio_ok, resolution = self._run_test_recording()
              gates.append(GateResult("Test recording (video)", video_ok))
              gates.append(GateResult("Test recording (audio)", audio_ok))
              res_str = f"{resolution[0]}x{resolution[1]}" if resolution else "unknown"
              gates.append(GateResult("Test recording (resolution)", True, res_str))
              if not video_ok or not audio_ok:
                  all_ok = False
          else:
              for label in ("video", "audio", "resolution"):
                  gates.append(GateResult(f"Test recording ({label})", False, "skipped"))
              all_ok = False

          # Print status table
          for g in gates:
              status = "OK" if g.passed else "FAIL"
              detail = f" ({g.detail})" if g.detail else ""
              dots = "." * max(1, 35 - len(g.name))
              log.info("[preflight] %s %s %s%s", g.name, dots, status, detail)

          return all_ok, gates

      def _ensure_chrome(self) -> bool:
          # ... extract from record_batch.py ensure_chrome() lines 175-225
          ...

      def _ensure_obs(self) -> bool:
          # ... extract from record_batch.py ensure_obs() lines 276-311
          ...

      def _check_patreon_session(self) -> bool:
          # ... delegates to PatreonSource.authenticate()
          ...

      def _check_disk_space(self) -> tuple[bool, str]:
          # ... extract from record_batch.py check_disk_space() lines 501-519
          ...

      def _run_test_recording(self) -> tuple[bool, bool, tuple[int, int] | None]:
          # ... extract from record_batch.py run_test_recording() lines 525-686
          ...
  ```

  Implementation notes:
  - Each gate method is self-contained and testable
  - `_ensure_chrome()` / `_ensure_obs()` include auto-launch via `subprocess.Popen`
  - `_check_patreon_session()` delegates to `PatreonSource.authenticate()` to avoid duplication
  - `_run_test_recording()` includes ffmpeg/ffprobe analysis for black frames and silence
  - The `GateResult` dataclass enables structured reporting

- Reference: `acquire/record_batch.py` lines 175-888 (entire preflight section)
- Run `uv run pytest tests/test_preflight.py`

### 13. Write `src/capture/batch.py` — Batch orchestrator

- Write `tests/test_batch.py` first (pure logic tests, no mocks needed for most):
  - **Queue loading**: Test valid JSON array, invalid JSON, missing file, missing keys
  - **Queue validation**: Test entries without `url` or `filename` are skipped with warning
  - **Seen-file tracking**: Test load_seen from file, mark_seen appends, filter_unseen removes seen
  - **Mild shuffle**: Test that ~30% of adjacent pairs are swapped, preserves elements, list length unchanged
  - **Mild shuffle edge cases**: Empty list, single item, two items
  - **Human break**: Test delay is within BREAK_MIN/MAX range (mock time.sleep, verify arg)
  - **Summary reporting**: Test result aggregation (ok count, fail count, timing)
  - **Filtering**: Test filter_unseen correctly identifies and removes already-recorded URLs
  - **Dry run**: Test dry_run outputs correct information without recording

- Implement `BatchOrchestrator`:
  ```python
  """Batch orchestrator — multi-video recording with scheduling and tracking."""
  from __future__ import annotations

  import json
  import logging
  import random
  import time
  from dataclasses import dataclass, field
  from datetime import datetime, timedelta
  from pathlib import Path

  from src.config import (
      STATE_DIR, BREAK_MIN_SECONDS, BREAK_MAX_SECONDS,
  )

  log = logging.getLogger(__name__)

  SEEN_FILE = STATE_DIR / "seen_urls.txt"


  @dataclass
  class BatchConfig:
      queue_path: Path = STATE_DIR / "record_queue.json"
      shuffle: bool = True
      breaks: bool = True
      skip_preflight: bool = False
      seen_file: Path = SEEN_FILE


  def load_queue(queue_path: Path) -> list[dict]:
      """Load and validate the recording queue JSON file."""
      if not queue_path.exists():
          raise FileNotFoundError(f"Queue file not found: {queue_path}")

      with queue_path.open(encoding="utf-8") as f:
          entries = json.load(f)

      if not isinstance(entries, list):
          raise ValueError(f"Queue must be a JSON array, got {type(entries).__name__}")

      valid = []
      for i, entry in enumerate(entries):
          if not isinstance(entry, dict):
              log.warning("Skipping entry %d: not a dict", i)
              continue
          if "url" not in entry or "filename" not in entry:
              log.warning("Skipping entry %d: missing 'url' or 'filename'", i)
              continue
          valid.append(entry)

      return valid


  def load_seen(seen_file: Path = SEEN_FILE) -> set[str]:
      if not seen_file.exists():
          return set()
      return {
          ln.strip()
          for ln in seen_file.read_text(encoding="utf-8").splitlines()
          if ln.strip()
      }


  def mark_seen(url: str, seen_file: Path = SEEN_FILE) -> None:
      seen_file.parent.mkdir(parents=True, exist_ok=True)
      with seen_file.open("a", encoding="utf-8") as f:
          f.write(url.strip() + "\n")


  def filter_unseen(
      entries: list[dict], seen_file: Path = SEEN_FILE,
  ) -> tuple[list[dict], int]:
      seen = load_seen(seen_file)
      unseen = [e for e in entries if e["url"] not in seen]
      return unseen, len(entries) - len(unseen)


  def mild_shuffle(entries: list[dict]) -> list[dict]:
      """Swap ~30% of adjacent pairs to avoid bot-like sequential access."""
      if len(entries) <= 2:
          return entries[:]
      result = entries[:]
      for i in range(len(result) - 1):
          if random.random() < 0.3:
              result[i], result[i + 1] = result[i + 1], result[i]
      return result


  def human_break(index: int, total: int) -> float:
      """Wait a random interval between captures. Returns actual delay."""
      delay = random.randint(BREAK_MIN_SECONDS, BREAK_MAX_SECONDS)
      resume_at = datetime.now() + timedelta(seconds=delay)
      log.info(
          "[break] Waiting %.0f min (%d/%d done, resume at %s)",
          delay / 60, index, total,
          resume_at.strftime("%H:%M:%S"),
      )

      remaining = delay
      while remaining > 0:
          chunk = min(remaining, 60)
          time.sleep(chunk)
          remaining -= chunk
          if remaining > 0 and remaining % 300 < 60:
              log.info("[break] ... %.0f min remaining", remaining / 60)

      return float(delay)


  def print_summary(
      results: list[dict],
      total_start: float,
      skipped_seen: int,
  ) -> dict:
      """Print and return batch summary."""
      total_elapsed = time.monotonic() - total_start
      ok_count = sum(1 for r in results if r.get("ok"))
      fail_count = len(results) - ok_count

      log.info("=" * 60)
      log.info("BATCH RECORDING SUMMARY")
      log.info("  Results:  %d/%d succeeded", ok_count, len(results))
      if fail_count > 0:
          log.info("  Failures: %d", fail_count)
      if skipped_seen > 0:
          log.info("  Skipped:  %d (already seen)", skipped_seen)
      log.info("  Time:     %.1f hours", total_elapsed / 3600)
      log.info("=" * 60)

      return {
          "total": len(results),
          "ok": ok_count,
          "failed": fail_count,
          "skipped_seen": skipped_seen,
          "elapsed_seconds": total_elapsed,
      }
  ```

  Implementation notes:
  - Pure functions for queue/seen/shuffle logic — easily testable without mocks
  - `human_break()` separated from the orchestration loop so it can be replaced or skipped
  - The `BatchOrchestrator` class (not shown in full) will compose: `Preflight` → queue loading → seen filtering → shuffle → recording loop → health checks → breaks → summary
  - Health check delegates to `Preflight` methods for Chrome/OBS/CDP tab checks

- Reference: `acquire/record_batch.py` lines 953-1034 (seen/queue/shuffle), 1142-1173 (breaks), 1179-1227 (summary), 1268-1434 (main loop)
- Run `uv run pytest tests/test_batch.py`

### 14. Wire up `__init__.py` exports

- `src/engines/__init__.py`:
  ```python
  from src.engines.base import CaptureEngine, EngineStatus
  from src.engines.null_engine import NullEngine

  __all__ = ["CaptureEngine", "EngineStatus", "NullEngine"]

  # Lazy imports for platform-specific engines
  def get_obs_engine(**kwargs):
      from src.engines.obs_engine import OBSEngine
      return OBSEngine(**kwargs)

  def get_ytdlp_engine(**kwargs):
      from src.engines.ytdlp_engine import YtDlpEngine
      return YtDlpEngine(**kwargs)
  ```

- `src/capture/__init__.py`:
  ```python
  from src.capture.recorder import Recorder, RecordResult

  __all__ = ["Recorder", "RecordResult"]
  ```

- `src/sources/__init__.py`:
  ```python
  from src.sources.base import Post, Source

  __all__ = ["Post", "Source"]
  ```

### 15. Run full test suite and validate

- Run `uv run pytest` — all tests (Phase 1 + Phase 2 + existing) must pass
- Run `uv run python -m py_compile` on all new modules
- Verify existing scripts still compile: `uv run python -m py_compile acquire/record_batch.py acquire/record_one.py`
- Verify all imports:
  ```bash
  uv run python -c "
  from src.engines import CaptureEngine, NullEngine
  from src.engines.obs_engine import OBSEngine
  from src.engines.ytdlp_engine import YtDlpEngine
  from src.capture import Recorder, RecordResult
  from src.capture.window import focus_chrome
  from src.capture.credentials import read_credential
  from src.sources import Post, Source
  from src.sources.patreon import PatreonSource
  from src.sources.youtube import YouTubeSource
  print('All Phase 2 imports OK')
  "
  ```

## Testing Strategy

All new code uses **TDD** — tests are written before implementation for each module.

| Module | Test File | What's Tested | Mocking Strategy |
|--------|-----------|---------------|------------------|
| `src/engines/null_engine.py` | `tests/test_null_engine.py` | Start/stop/is_recording/get_status lifecycle | No mocks (pure logic) |
| `src/engines/obs_engine.py` | `tests/test_obs_engine.py` | OBS connect, start, stop, screenshot, file move retry | Mock `obsws_python`, `shutil.move` |
| `src/engines/ytdlp_engine.py` | `tests/test_ytdlp_engine.py` | Subprocess launch, wait, output path resolution | Mock `subprocess.Popen` |
| `src/capture/credentials.py` | `tests/test_credentials.py` | Non-Windows skip, credential read, missing cred | Mock `ctypes`, guard with `IS_WINDOWS` |
| `src/capture/window.py` | `tests/test_window.py` | Non-Windows no-op, focus_chrome Win32 calls | Mock `ctypes.windll.user32` |
| `src/capture/recorder.py` | `tests/test_recorder.py` | 10-step state machine: happy path, player not found, fullscreen fail, mute guard, stall detection, pause resume | Mock `CDPClient`, `NullEngine`, `detect_player` |
| `src/capture/preflight.py` | `tests/test_preflight.py` | All 7 gates pass/fail, auto-launch, auto-login, dependency skipping | Mock `subprocess`, `obsws_python`, `urllib`, `CDPClient` |
| `src/capture/batch.py` | `tests/test_batch.py` | Queue load/validate, seen tracking, shuffle, filter, break timing, summary | No mocks for pure functions; mock `time.sleep` for breaks |
| `src/sources/patreon.py` | `tests/test_patreon_source.py` | Auth flow (valid session, login form, credential fill), search URL, stealth params | Mock `CDPClient`, `read_credential` |
| `src/sources/youtube.py` | `tests/test_youtube_source.py` | yt-dlp subprocess, JSON parsing, Post construction | Mock `subprocess.run` |

### Edge cases to cover
- **OBSEngine**: File move `PermissionError` retry exhaustion (6 attempts), OBS not connected
- **YtDlpEngine**: `start()` without `set_url()` raises `ValueError`, subprocess timeout
- **Recorder**: Player detection returns `None`, duration stays `0` after 15 polls, stall count > 6
- **Recorder**: Engine raises during `start()` — cleanup must still run
- **Preflight**: Gate 3 (Patreon) skipped when Gate 1 (Chrome) failed — no false positive
- **Batch**: Empty queue file, all URLs already seen, JSON decode error
- **Mild shuffle**: Deterministic with `random.seed` — verify invariant (same elements, length preserved)
- **Window management**: All functions return False on non-Windows (Linux CI)
- **Credentials**: `read_credential` on non-Windows returns None without importing ctypes.wintypes

## Acceptance Criteria

1. `uv run python -c "from src.engines import NullEngine; e = NullEngine(); e.start('test'); print(e.stop())"` prints `/tmp/test.mp4`
2. `uv run python -c "from src.engines.obs_engine import OBSEngine; print(OBSEngine.name)"` prints `obs`
3. `uv run python -c "from src.capture import Recorder; print(Recorder)"` imports without error
4. `uv run python -c "from src.sources import Post; p = Post(url='https://x.com', title='Test'); print(p.filename)"` prints `Test`
5. `uv run python -c "from src.capture.window import focus_chrome; print(focus_chrome())"` prints `False` on Linux
6. `uv run python -c "from src.capture.credentials import read_credential; print(read_credential('test'))"` prints `None` on Linux
7. `uv run pytest tests/test_null_engine.py tests/test_obs_engine.py tests/test_ytdlp_engine.py tests/test_recorder.py tests/test_batch.py tests/test_preflight.py tests/test_window.py tests/test_patreon_source.py` — all pass
8. `uv run pytest` — full suite passes (no regressions in Phase 1 or existing tests)
9. Existing scripts compile: `uv run python -m py_compile acquire/record_batch.py acquire/record_one.py acquire/patreon_capture_remote.py`
10. The `Recorder` class works with NullEngine + any PlayerHandler — verified by test_recorder.py

## Validation Commands
Execute these commands to validate the task is complete:

- `uv run pytest` — Full test suite passes (Phase 1 + Phase 2 + existing)
- `uv run pytest tests/test_null_engine.py tests/test_obs_engine.py tests/test_recorder.py tests/test_batch.py tests/test_preflight.py tests/test_patreon_source.py -v` — All Phase 2 tests pass with verbose output
- `uv run python -c "from src.engines import NullEngine; from src.capture import Recorder; print('Phase 2 OK')"` — Core imports work
- `uv run python -c "from src.sources.patreon import PatreonSource; from src.sources.youtube import YouTubeSource; print('Sources OK')"` — Source imports work
- `uv run python -c "from src.capture.window import focus_chrome; from src.capture.credentials import read_credential; print('Platform OK')"` — Platform modules import on Linux
- `uv run python -m py_compile acquire/record_batch.py acquire/record_one.py` — Existing scripts still compile

## Notes

- **Lazy imports for Windows-only modules**: `ctypes`, `ctypes.wintypes`, `obsws_python` are imported inside functions, never at module level. This ensures all modules are importable on Linux (devbox-01) even though the actual capture runs on the Windows obs-machine. Guard with `if IS_WINDOWS` where appropriate.
- **The recorder works with ANY engine**: `Recorder(NullEngine())` for testing, `Recorder(OBSEngine())` for screen capture, `Recorder(YtDlpEngine())` for direct download. The engine is injected at construction, not hardcoded.
- **The recorder works with ANY player**: The `detect_player()` function returns the appropriate handler. New player types (e.g., YouTube player) can be added to Phase 1's detector without changing the recorder.
- **Keep existing scripts working**: Do NOT modify or delete anything in `acquire/`. The old scripts run on the obs-machine independently. Phase 3 will optionally migrate them to use `src/`.
- **Async methods**: All `Recorder` and `Source` methods are async. The `CaptureEngine` protocol methods are sync (OBS WebSocket calls are blocking, yt-dlp is a subprocess). This matches the existing pattern where CDP calls are async but OBS calls are sync.
- **No new dependencies**: All modules use only what's already in `pyproject.toml`. `obsws_python` and `websockets` are in the `[capture]` extra. `subprocess`, `ctypes`, `json`, `shutil` are stdlib. `yt-dlp` is invoked via `uvx` (not a Python dependency).
- **`dataclasses` over `TypedDict`**: Use `@dataclass` for `Post`, `RecordResult`, `EngineStatus`, `GateResult` — they're more explicit, support defaults, and work with `isinstance()` checks.
- **Test recording in preflight**: The test recording gate uses `OBSEngine` directly (not the `Recorder` state machine) because it records a known test page, not a real video. The ffmpeg analysis functions (`_check_video_black`, `_check_audio_silence`, `_get_resolution`) are extracted unchanged from `record_batch.py`.
- **Missing `dataclass` import in preflight**: The `GateResult` dataclass in `src/capture/preflight.py` needs `from dataclasses import dataclass` at the top of the file.
