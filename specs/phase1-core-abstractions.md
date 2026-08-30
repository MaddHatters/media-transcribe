# Plan: Phase 1 — Core Abstractions (Modular Python Package)

## Task Description
Refactor the media-transcribe project from scattered scripts with duplicated constants into a composable Python package (`src/`) with a centralized config, a reusable async CDP client, and a strategy-pattern player hierarchy. This is Phase 1 of 3 — laying the foundation without touching the existing scripts (they still run on the obs-machine).

## Objective
When complete, the project has:
1. A single `src/config.py` eliminating all constant duplication across 6+ scripts.
2. A `src/cdp.py` async CDP client replacing the 3+ inline implementations.
3. A `src/players/` package with a detection pipeline and Mux, Vimeo, and HTML5 player handlers behind a common Protocol.
4. Full test coverage for all new modules.
5. `pyproject.toml` updated so `src` is importable.
6. Zero regressions — existing scripts (`acquire/*`, `transcribe/*`) remain untouched and runnable.

## Problem Statement
Constants like `CDP_URL`, `OBS_PASSWORD`, `BACKUP_DIR`, `BREAK_MIN_SECONDS`, path literals, and SSH options are duplicated across `record_one.py`, `record_batch.py`, `patreon_capture_remote.py`, `record_patreon.py`, and `obs_capture.py`. The CDP WebSocket client is reimplemented at least 3 times (inline in `record_one.py`, in `record_batch.py`'s `_cdp_quick_eval_async`, and in `patreon_capture_remote.py`'s `get_ws_url`). Player handling logic (Vimeo vs Mux vs HTML5) is interleaved with orchestration code, making it impossible to test or compose independently.

## Solution Approach
Create a proper Python package at `src/` with:
- **Config module** — all constants in one file, platform-aware (`IS_WINDOWS`), importable from anywhere.
- **CDP client** — async context-managed class wrapping the WebSocket protocol, extracted from `record_one.py`'s inline functions.
- **Player strategy pattern** — a `PlayerHandler` Protocol with concrete implementations for Mux, Vimeo, and HTML5. A detector module runs a single JS eval to identify the player type and returns a `DetectionResult` that maps to the right handler.

Existing scripts are **not modified** in this phase — they continue to work with their inline constants. Phase 2 will migrate them to import from `src/`.

## Relevant Files

### Existing files (read-only reference — do NOT modify)
- `acquire/record_one.py` — CDP client pattern (`cdp()`, `js()`, `real_click()`), fullscreen TAC trick with retry + F11 fallback, unmute logic, 10-step recording state machine
- `acquire/record_batch.py` — Constant declarations (lines 47-79), `_cdp_quick_eval_async()`, preflight/health-check patterns
- `acquire/obs_capture.py` — Playwright-based Vimeo/native player detection (`find_player`), `start_vimeo_playback()`, `start_native_playback()`, `_RESOLVE_VIDEO` shadow DOM helper
- `acquire/patreon_capture_remote.py` — Another set of duplicated constants (lines 35-41), `get_ws_url()`, `safe_filename()`
- `acquire/record_patreon.py` — SSH/SCP constants (lines 51-71), `BREAK_MIN_SECONDS`/`BREAK_MAX_SECONDS` duplication
- `AGENTS.md` — Development guidelines (TDD, `uv run`, no new deps beyond what's in pyproject.toml)
- `pyproject.toml` — Current project config (Python 3.11+, faster-whisper core, capture/ocr extras, pytest in dev group)
- `tests/conftest.py` — Current sys.path hacking to import script dirs

### New files to create
- `src/__init__.py` — Empty package marker
- `src/config.py` — Centralized constants
- `src/cdp.py` — Async CDP WebSocket client
- `src/players/__init__.py` — Empty subpackage marker
- `src/players/base.py` — `DetectionResult` dataclass + `PlayerHandler` Protocol
- `src/players/detector.py` — Single-query player detection, maps to handler
- `src/players/mux.py` — `MuxPlayer` handler
- `src/players/vimeo.py` — `VimeoPlayer` handler
- `src/players/html5.py` — `HTML5Player` handler
- `tests/test_config.py` — Config constants and platform detection tests
- `tests/test_cdp.py` — CDPClient tests with mocked WebSocket
- `tests/test_detector.py` — Player detection tests with sample DOM outputs
- `tests/test_mux_player.py` — Mux fullscreen retry, unmute, play/pause tests
- `tests/test_vimeo_player.py` — Vimeo API injection, iframe detection tests

## Implementation Phases

### Phase 1: Foundation
Set up the package structure, `pyproject.toml` changes, and `config.py`.

### Phase 2: Core Implementation
Build `cdp.py`, then the player base/detector/handlers — each with tests written first.

### Phase 3: Integration & Polish
Wire up the detector to return concrete handler instances, ensure all tests pass, validate backward compatibility.

## Step by Step Tasks
IMPORTANT: Execute every step in order, top to bottom.

### 1. Create package structure and update pyproject.toml

- Create directories: `src/`, `src/players/`
- Create empty `src/__init__.py` and `src/players/__init__.py`
- Update `pyproject.toml` to make `src` importable:
  ```toml
  [tool.setuptools.packages.find]
  include = ["src*"]
  ```
  Or, since this project uses `uv` (which uses hatchling by default), add:
  ```toml
  [tool.hatch.build.targets.wheel]
  packages = ["src"]
  ```
  Verify which build backend is in use first. If none is specified, `uv` defaults to hatchling. Check if a `[build-system]` section exists; if not, adding `packages = ["src"]` under hatch config is the right approach.
- Add `websockets` to the `[capture]` extra if not already present (it's used by `record_one.py` but may only be installed ad-hoc on the obs-machine).
- Verify with: `uv run python -c "import src; print(src.__file__)"`

### 2. Write `src/config.py` — centralized constants

- Write `tests/test_config.py` first (TDD):
  ```python
  """Tests for src/config.py constants and platform detection."""
  import sys
  from src.config import (
      SCRIPTS_DIR, STATE_DIR, LOGS_DIR, BACKUP_DIR,
      CHROME_PATH, CHROME_PROFILE, OBS_PATH,
      LOCAL_TRANSCRIPTS, LOCAL_DATA,
      CDP_URL, OBS_HOST, OBS_PORT, OBS_PASSWORD,
      SSH_HOST, SSH_OPTS,
      BREAK_MIN_SECONDS, BREAK_MAX_SECONDS,
      CRED_TARGET, IS_WINDOWS,
  )
  from pathlib import Path

  def test_all_paths_are_path_objects():
      for p in (SCRIPTS_DIR, STATE_DIR, LOGS_DIR, BACKUP_DIR,
                CHROME_PATH, CHROME_PROFILE, OBS_PATH,
                LOCAL_TRANSCRIPTS, LOCAL_DATA):
          assert isinstance(p, Path), f"{p!r} is not a Path"

  def test_cdp_url_format():
      assert CDP_URL.startswith("http://")
      assert ":9222" in CDP_URL

  def test_obs_port_is_int():
      assert isinstance(OBS_PORT, int)
      assert OBS_PORT == 4455

  def test_break_range_valid():
      assert BREAK_MIN_SECONDS < BREAK_MAX_SECONDS
      assert BREAK_MIN_SECONDS == 300
      assert BREAK_MAX_SECONDS == 1500

  def test_ssh_opts_is_list():
      assert isinstance(SSH_OPTS, list)
      assert all(isinstance(o, str) for o in SSH_OPTS)

  def test_is_windows_matches_platform():
      assert IS_WINDOWS == (sys.platform == "win32")
  ```

- Implement `src/config.py` with all constants extracted from:
  - `record_batch.py` lines 47-79 (Windows paths, OBS password, CDP URL, break times)
  - `record_patreon.py` lines 51-71 (SSH host, SSH opts, remote paths)
  - `patreon_capture_remote.py` lines 35-41 (CDP, OBS, backup dir)
  - `record_one.py` lines 17-20 (CDP URL, OBS password, dest dir)

  Structure the constants by category with section comments:
  ```python
  """Single source of truth for paths, network endpoints, and behavior constants."""
  from __future__ import annotations
  import sys
  from pathlib import Path

  # -- Paths: obs-machine (Windows) --
  SCRIPTS_DIR = Path(r"C:\Users\Matt\agent-control\scripts")
  STATE_DIR = Path(r"C:\Users\Matt\agent-control\state")
  LOGS_DIR = Path(r"C:\Users\Matt\agent-control\logs")
  BACKUP_DIR = Path(r"D:\MasterClass Video Backup")
  CHROME_PATH = Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe")
  CHROME_PROFILE = Path(r"C:\Users\Matt\agent-control\chrome-profile")
  OBS_PATH = Path(r"C:\Program Files\obs-studio\bin\64bit\obs64.exe")

  # -- Paths: devbox-01 (Linux) --
  LOCAL_TRANSCRIPTS = Path("/mnt/secondary/media/patreon/FIRE Investing Masterclass/transcripts")
  LOCAL_DATA = Path("/home/tuna/repos/media-transcribe/data")

  # -- Network --
  CDP_URL = "http://localhost:9222"
  OBS_HOST = "localhost"
  OBS_PORT = 4455
  OBS_PASSWORD = "DK4HLJPKgslAhEgD"
  SSH_HOST = "Matt@100.66.194.100"
  SSH_OPTS = ["-o", "ConnectTimeout=15", "-o", "StrictHostKeyChecking=no"]

  # -- Recording behavior --
  BREAK_MIN_SECONDS = 300
  BREAK_MAX_SECONDS = 1500
  CRED_TARGET = "patreon_02_ai"

  # -- Platform detection --
  IS_WINDOWS = sys.platform == "win32"
  ```

- Run `uv run pytest tests/test_config.py` — must pass.

### 3. Write `src/cdp.py` — async CDP WebSocket client

- Write `tests/test_cdp.py` first (TDD). Mock the websockets library — do NOT require a real browser:
  ```python
  """Tests for src/cdp.CDPClient with mocked WebSocket."""
  import json
  import pytest
  from unittest.mock import AsyncMock, patch, MagicMock
  from src.cdp import CDPClient

  @pytest.fixture
  def mock_ws():
      ws = AsyncMock()
      ws.send = AsyncMock()
      ws.close = AsyncMock()
      return ws

  @pytest.mark.asyncio
  async def test_connect_gets_ws_url(mock_ws):
      """CDPClient.connect() fetches /json and connects to the first page's webSocketDebuggerUrl."""
      pages_json = json.dumps([{
          "type": "page",
          "webSocketDebuggerUrl": "ws://localhost:9222/devtools/page/ABC123",
      }]).encode()
      with patch("src.cdp.urllib.request.urlopen") as mock_urlopen, \
           patch("src.cdp.websockets.connect") as mock_connect:
          mock_urlopen.return_value.read.return_value = pages_json
          mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_ws)
          mock_connect.return_value.__aexit__ = AsyncMock(return_value=False)
          client = CDPClient()
          await client.connect()
          mock_connect.assert_called_once()

  @pytest.mark.asyncio
  async def test_js_sends_runtime_evaluate(mock_ws):
      """CDPClient.js() sends Runtime.evaluate and returns the value."""
      mock_ws.recv = AsyncMock(return_value=json.dumps({
          "id": 1,
          "result": {"result": {"value": 42}},
      }))
      client = CDPClient.__new__(CDPClient)
      client._ws = mock_ws
      client._msg_id = 0
      result = await client.js("1 + 1")
      assert result == 42
      call_data = json.loads(mock_ws.send.call_args[0][0])
      assert call_data["method"] == "Runtime.evaluate"
      assert call_data["params"]["expression"] == "1 + 1"

  @pytest.mark.asyncio
  async def test_click_dispatches_mouse_events(mock_ws):
      """CDPClient.click() sends mousePressed then mouseReleased."""
      mock_ws.recv = AsyncMock(side_effect=[
          json.dumps({"id": 1, "result": {}}),
          json.dumps({"id": 2, "result": {}}),
      ])
      client = CDPClient.__new__(CDPClient)
      client._ws = mock_ws
      client._msg_id = 0
      await client.click(100.0, 200.0)
      assert mock_ws.send.call_count == 2
      first_call = json.loads(mock_ws.send.call_args_list[0][0][0])
      assert first_call["params"]["type"] == "mousePressed"
      assert first_call["params"]["x"] == 100.0

  @pytest.mark.asyncio
  async def test_navigate_sends_page_navigate(mock_ws):
      """CDPClient.navigate() sends Page.navigate and sleeps."""
      mock_ws.recv = AsyncMock(return_value=json.dumps({"id": 1, "result": {}}))
      client = CDPClient.__new__(CDPClient)
      client._ws = mock_ws
      client._msg_id = 0
      with patch("asyncio.sleep", new_callable=AsyncMock):
          await client.navigate("https://example.com", wait=0.0)
      call_data = json.loads(mock_ws.send.call_args[0][0])
      assert call_data["method"] == "Page.navigate"
      assert call_data["params"]["url"] == "https://example.com"

  @pytest.mark.asyncio
  async def test_key_dispatches_key_events(mock_ws):
      """CDPClient.key() sends keyDown then keyUp."""
      mock_ws.recv = AsyncMock(side_effect=[
          json.dumps({"id": 1, "result": {}}),
          json.dumps({"id": 2, "result": {}}),
      ])
      client = CDPClient.__new__(CDPClient)
      client._ws = mock_ws
      client._msg_id = 0
      await client.key("F11", "F11")
      assert mock_ws.send.call_count == 2

  @pytest.mark.asyncio
  async def test_get_ws_url_returns_first_page():
      """get_ws_url() parses /json and returns the first page's WS URL."""
      pages_json = json.dumps([
          {"type": "background_page", "webSocketDebuggerUrl": "ws://bg"},
          {"type": "page", "webSocketDebuggerUrl": "ws://page1"},
      ]).encode()
      with patch("src.cdp.urllib.request.urlopen") as mock_urlopen:
          mock_urlopen.return_value.read.return_value = pages_json
          url = CDPClient.get_ws_url()
          assert url == "ws://page1"
  ```

- Implement `src/cdp.py`:
  ```python
  """Reusable async Chrome DevTools Protocol client via WebSocket."""
  from __future__ import annotations

  import asyncio
  import json
  import urllib.request
  from typing import Any

  import websockets

  from src.config import CDP_URL

  class CDPClient:
      """Chrome DevTools Protocol client via WebSocket."""

      def __init__(self, cdp_url: str = CDP_URL):
          self._cdp_url = cdp_url
          self._ws = None
          self._msg_id = 0

      async def connect(self) -> None:
          ws_url = self.get_ws_url(self._cdp_url)
          self._ws = await websockets.connect(
              ws_url, max_size=50 * 1024 * 1024, ping_interval=30,
          )

      async def disconnect(self) -> None:
          if self._ws:
              await self._ws.close()
              self._ws = None

      async def __aenter__(self) -> CDPClient:
          await self.connect()
          return self

      async def __aexit__(self, *exc) -> None:
          await self.disconnect()

      async def _send(self, method: str, params: dict | None = None) -> dict:
          self._msg_id += 1
          mid = self._msg_id
          await self._ws.send(json.dumps({
              "id": mid, "method": method, "params": params or {},
          }))
          while True:
              resp = json.loads(await self._ws.recv())
              if resp.get("id") == mid:
                  return resp

      async def navigate(self, url: str, wait: float = 8.0) -> None:
          await self._send("Page.navigate", {"url": url})
          if wait > 0:
              await asyncio.sleep(wait)

      async def js(self, expression: str) -> Any:
          r = await self._send("Runtime.evaluate", {
              "expression": expression, "returnByValue": True,
          })
          return r.get("result", {}).get("result", {}).get("value")

      async def click(self, x: float, y: float) -> None:
          await self._send("Input.dispatchMouseEvent", {
              "type": "mousePressed", "x": x, "y": y,
              "button": "left", "clickCount": 1,
          })
          await self._send("Input.dispatchMouseEvent", {
              "type": "mouseReleased", "x": x, "y": y,
              "button": "left", "clickCount": 1,
          })

      async def key(self, key: str, code: str) -> None:
          await self._send("Input.dispatchKeyEvent", {
              "type": "keyDown", "key": key, "code": code,
          })
          await self._send("Input.dispatchKeyEvent", {
              "type": "keyUp", "key": key, "code": code,
          })

      async def move_mouse(self, x: float, y: float) -> None:
          await self._send("Input.dispatchMouseEvent", {
              "type": "mouseMoved", "x": x, "y": y,
          })

      @staticmethod
      def get_ws_url(cdp_url: str = CDP_URL) -> str:
          data = urllib.request.urlopen(f"{cdp_url}/json", timeout=5).read()
          pages = json.loads(data)
          page = next(p for p in pages if p["type"] == "page")
          return page["webSocketDebuggerUrl"]
  ```

- Add `pytest-asyncio` to the dev dependency group in `pyproject.toml`:
  ```toml
  [dependency-groups]
  dev = [
      "pytest>=8",
      "pytest-asyncio>=0.23",
  ]
  ```
- Run `uv run pytest tests/test_cdp.py` — must pass.

### 4. Write `src/players/base.py` — Protocol and DetectionResult

- Create `src/players/base.py`:
  ```python
  """Player handler protocol and detection result dataclass."""
  from __future__ import annotations

  from dataclasses import dataclass, field
  from typing import Any, Protocol, runtime_checkable

  from src.cdp import CDPClient

  @dataclass
  class DetectionResult:
      player: str | None  # 'vimeo', 'mux', 'youtube', 'html5', None
      element: str | None  # CSS selector that matched
      meta: dict = field(default_factory=dict)  # bbox center, duration, readyState, src

  @runtime_checkable
  class PlayerHandler(Protocol):
      name: str

      async def get_duration(self, cdp: CDPClient, detection: DetectionResult) -> float: ...
      async def play(self, cdp: CDPClient, detection: DetectionResult) -> None: ...
      async def pause(self, cdp: CDPClient, detection: DetectionResult) -> None: ...
      async def seek(self, cdp: CDPClient, position: float) -> None: ...
      async def fullscreen(self, cdp: CDPClient, detection: DetectionResult) -> bool: ...
      async def get_position(self, cdp: CDPClient) -> float: ...
      async def is_ended(self, cdp: CDPClient) -> bool: ...
      async def unmute(self, cdp: CDPClient) -> None: ...
  ```

  No separate test file needed — the Protocol and dataclass are tested implicitly through the concrete handler tests. But verify they're importable:
  ```python
  # in test_config.py or a quick smoke test
  def test_base_imports():
      from src.players.base import DetectionResult, PlayerHandler
      d = DetectionResult(player="mux", element="video", meta={"duration": 120})
      assert d.player == "mux"
  ```

### 5. Write `src/players/mux.py` — MuxPlayer handler

- Write `tests/test_mux_player.py` first:
  ```python
  """Tests for MuxPlayer handler."""
  import json
  import pytest
  from unittest.mock import AsyncMock, patch
  from src.players.mux import MuxPlayer
  from src.players.base import DetectionResult

  @pytest.fixture
  def cdp():
      mock = AsyncMock()
      mock.js = AsyncMock()
      mock.click = AsyncMock()
      mock.key = AsyncMock()
      mock.move_mouse = AsyncMock()
      return mock

  @pytest.fixture
  def detection():
      return DetectionResult(
          player="mux",
          element="video",
          meta={"cx": 960, "cy": 540, "duration": 1800},
      )

  @pytest.mark.asyncio
  async def test_get_duration(cdp, detection):
      cdp.js.return_value = 1800.5
      player = MuxPlayer()
      dur = await player.get_duration(cdp, detection)
      assert dur == 1800.5

  @pytest.mark.asyncio
  async def test_play_calls_js(cdp, detection):
      player = MuxPlayer()
      await player.play(cdp, detection)
      cdp.js.assert_called_once()
      assert "play()" in cdp.js.call_args[0][0]

  @pytest.mark.asyncio
  async def test_unmute_sets_volume(cdp):
      player = MuxPlayer()
      await player.unmute(cdp)
      call_expr = cdp.js.call_args[0][0]
      assert "muted = false" in call_expr
      assert "volume = 1.0" in call_expr

  @pytest.mark.asyncio
  async def test_fullscreen_tac_trick_succeeds(cdp, detection):
      """Fullscreen should use TAC trick: inject click handler, CDP click at bbox center."""
      cdp.js.side_effect = [
          None,  # inject click handler
          json.dumps({"x": 960, "y": 540}),  # get bbox
          True,  # check fullscreenElement
      ]
      player = MuxPlayer()
      result = await player.fullscreen(cdp, detection)
      assert result is True
      cdp.click.assert_called_once_with(960, 540)

  @pytest.mark.asyncio
  async def test_fullscreen_retries_three_times(cdp, detection):
      """Fullscreen retries up to 3 times before trying F11 fallback."""
      cdp.js.side_effect = [
          None, json.dumps({"x": 960, "y": 540}), False,   # attempt 1
          None, json.dumps({"x": 960, "y": 540}), False,   # attempt 2
          None, json.dumps({"x": 960, "y": 540}), False,   # attempt 3
          None,                                              # F11 fallback inject
          json.dumps({"x": 960, "y": 540}),                # F11 fallback bbox
          True,                                              # F11 check
      ]
      player = MuxPlayer()
      with patch("asyncio.sleep", new_callable=AsyncMock):
          result = await player.fullscreen(cdp, detection)
      assert result is True
      cdp.key.assert_called()  # F11 was sent

  @pytest.mark.asyncio
  async def test_fullscreen_all_attempts_fail(cdp, detection):
      """If all fullscreen attempts fail, return False."""
      cdp.js.return_value = False  # fullscreenElement always False
      # Need to handle the bbox calls too
      returns = []
      for _ in range(3):
          returns.extend([None, json.dumps({"x": 960, "y": 540}), False])
      returns.extend([None, json.dumps({"x": 960, "y": 540}), False])
      cdp.js.side_effect = returns
      player = MuxPlayer()
      with patch("asyncio.sleep", new_callable=AsyncMock):
          result = await player.fullscreen(cdp, detection)
      assert result is False
  ```

- Implement `src/players/mux.py`:
  - Extract fullscreen TAC trick from `record_one.py` lines 120-193
  - Extract unmute from `record_one.py` line 114 and `obs_capture.py` line 229
  - Use `document.querySelector('video')` for the video element (Mux's `<mux-player>` shadow DOM contains a `<video>`)
  - `get_duration`: `js("(v => (v && isFinite(v.duration)) ? v.duration : 0)(document.querySelector('video'))")`
  - `play`: `js("document.querySelector('video').play()")`
  - `pause`: `js("document.querySelector('video').pause()")`
  - `seek`: `js(f"document.querySelector('video').currentTime = {position}")`
  - `get_position`: `js("document.querySelector('video').currentTime")`
  - `is_ended`: `js("document.querySelector('video').ended")`
  - `unmute`: `js("var v = document.querySelector('video'); v.muted = false; v.volume = 1.0")`
  - `fullscreen`: TAC trick with 3 retries + F11 fallback:
    1. Inject click→requestFullscreen handler on the video element
    2. Get bounding box center via `getBoundingClientRect()`
    3. CDP `click()` at that center
    4. Check `document.fullscreenElement`
    5. If failed after 3 attempts, send F11 key, then retry TAC trick once more

- Run `uv run pytest tests/test_mux_player.py` — must pass.

### 6. Write `src/players/vimeo.py` — VimeoPlayer handler

- Write `tests/test_vimeo_player.py` first:
  ```python
  """Tests for VimeoPlayer handler."""
  import pytest
  from unittest.mock import AsyncMock, patch
  from src.players.vimeo import VimeoPlayer
  from src.players.base import DetectionResult

  VIMEO_SDK = "https://player.vimeo.com/api/player.js"

  @pytest.fixture
  def cdp():
      mock = AsyncMock()
      mock.js = AsyncMock()
      mock.click = AsyncMock()
      return mock

  @pytest.fixture
  def detection():
      return DetectionResult(
          player="vimeo",
          element="iframe[src*='vimeo']",
          meta={},
      )

  @pytest.mark.asyncio
  async def test_play_injects_vimeo_sdk_and_calls_play(cdp, detection):
      player = VimeoPlayer()
      await player.play(cdp, detection)
      calls = [c[0][0] for c in cdp.js.call_args_list]
      assert any("Vimeo.Player" in c for c in calls), "Should create Vimeo.Player"
      assert any("play()" in c for c in calls), "Should call play()"

  @pytest.mark.asyncio
  async def test_get_duration_uses_vimeo_api(cdp, detection):
      cdp.js.return_value = 3600.0
      player = VimeoPlayer()
      dur = await player.get_duration(cdp, detection)
      assert dur == 3600.0
      assert "getDuration" in cdp.js.call_args[0][0]

  @pytest.mark.asyncio
  async def test_get_position_uses_vimeo_api(cdp):
      cdp.js.return_value = 120.5
      player = VimeoPlayer()
      pos = await player.get_position(cdp)
      assert pos == 120.5
      assert "getCurrentTime" in cdp.js.call_args[0][0]

  @pytest.mark.asyncio
  async def test_fullscreen_on_iframe(cdp, detection):
      cdp.js.return_value = True
      player = VimeoPlayer()
      result = await player.fullscreen(cdp, detection)
      assert result is True
      assert "requestFullscreen" in cdp.js.call_args[0][0]

  @pytest.mark.asyncio
  async def test_unmute_sets_volume(cdp):
      player = VimeoPlayer()
      await player.unmute(cdp)
      assert "setVolume(1.0)" in cdp.js.call_args[0][0]
  ```

- Implement `src/players/vimeo.py`:
  - Extract from `obs_capture.py` `start_vimeo_playback()` (lines 129-149) and `patreon_capture_remote.py`
  - `play()`: Inject Vimeo SDK script tag, create `window.__p = new Vimeo.Player(iframe)`, call `window.__p.play()`
  - `pause()`: `window.__p.pause()`
  - `get_duration()`: `window.__p.getDuration()`
  - `get_position()`: `window.__p.getCurrentTime()`
  - `seek(position)`: `window.__p.setCurrentTime(position)`
  - `fullscreen()`: `document.querySelector("iframe[src*='vimeo']").requestFullscreen()`
  - `unmute()`: `window.__p.setVolume(1.0)`
  - `is_ended()`: `window.__ended` (set via the `'ended'` event listener)
  - Store `VIMEO_SDK_URL` as class constant

- Run `uv run pytest tests/test_vimeo_player.py` — must pass.

### 7. Write `src/players/html5.py` — HTML5Player handler

- No dedicated test file needed — the HTML5Player is nearly identical to MuxPlayer but without shadow DOM handling. Add a small test in `tests/test_mux_player.py` or create `tests/test_html5_player.py` with smoke tests:
  ```python
  """Tests for generic HTML5Player handler."""
  import pytest
  from unittest.mock import AsyncMock
  from src.players.html5 import HTML5Player
  from src.players.base import DetectionResult

  @pytest.fixture
  def cdp():
      mock = AsyncMock()
      mock.js = AsyncMock()
      mock.click = AsyncMock()
      mock.key = AsyncMock()
      return mock

  @pytest.mark.asyncio
  async def test_play_calls_video_play(cdp):
      player = HTML5Player()
      det = DetectionResult(player="html5", element="video", meta={})
      await player.play(cdp, det)
      assert "play()" in cdp.js.call_args[0][0]

  @pytest.mark.asyncio
  async def test_name_is_html5():
      assert HTML5Player().name == "html5"
  ```

- Implement `src/players/html5.py`:
  - Same JS expressions as MuxPlayer but targeting `document.querySelector('video')` directly
  - Fullscreen: same TAC trick (inject click handler, CDP click at bbox, retry + F11 fallback)
  - Consider having MuxPlayer and HTML5Player share a base class or helper to avoid duplication of the fullscreen retry logic. A private `_video_fullscreen()` async function in a `src/players/_common.py` helper would work.

### 8. Write `src/players/detector.py` — single-query player detection

- Write `tests/test_detector.py` first:
  ```python
  """Tests for player detection with sample DOM outputs."""
  import json
  import pytest
  from unittest.mock import AsyncMock
  from src.players.detector import detect_player
  from src.players.mux import MuxPlayer
  from src.players.vimeo import VimeoPlayer
  from src.players.html5 import HTML5Player

  @pytest.fixture
  def cdp():
      mock = AsyncMock()
      mock.js = AsyncMock()
      return mock

  @pytest.mark.asyncio
  async def test_detect_vimeo_iframe(cdp):
      cdp.js.return_value = json.dumps({
          "player": "vimeo",
          "element": "iframe[src*='vimeo']",
          "meta": {"src": "https://player.vimeo.com/video/123"},
      })
      result, handler = await detect_player(cdp)
      assert result.player == "vimeo"
      assert isinstance(handler, VimeoPlayer)

  @pytest.mark.asyncio
  async def test_detect_mux_player(cdp):
      cdp.js.return_value = json.dumps({
          "player": "mux",
          "element": "mux-player",
          "meta": {"duration": 1200, "readyState": 4},
      })
      result, handler = await detect_player(cdp)
      assert result.player == "mux"
      assert isinstance(handler, MuxPlayer)

  @pytest.mark.asyncio
  async def test_detect_plain_video(cdp):
      cdp.js.return_value = json.dumps({
          "player": "html5",
          "element": "video",
          "meta": {"duration": 600, "src": "blob:https://example.com/abc"},
      })
      result, handler = await detect_player(cdp)
      assert result.player == "html5"
      assert isinstance(handler, HTML5Player)

  @pytest.mark.asyncio
  async def test_detect_no_player(cdp):
      cdp.js.return_value = json.dumps({
          "player": None,
          "element": None,
          "meta": {},
      })
      result, handler = await detect_player(cdp)
      assert result.player is None
      assert handler is None

  @pytest.mark.asyncio
  async def test_detect_youtube_iframe(cdp):
      """YouTube iframes are detected but no handler exists yet — returns None handler."""
      cdp.js.return_value = json.dumps({
          "player": "youtube",
          "element": "iframe[src*='youtube']",
          "meta": {},
      })
      result, handler = await detect_player(cdp)
      assert result.player == "youtube"
      assert handler is None  # no YouTubePlayer yet
  ```

- Implement `src/players/detector.py`:
  - `detect_player(cdp: CDPClient, timeout: float = 30.0) -> tuple[DetectionResult, PlayerHandler | None]`
  - Runs a single JS eval that checks the DOM in priority order:
    1. `iframe[src*='vimeo']` → `"vimeo"`
    2. `mux-player` → `"mux"` (also grabs shadow DOM video metadata)
    3. `iframe[src*='youtube']` → `"youtube"`
    4. `video` → `"html5"`
    5. None found → `null`
  - Returns both the `DetectionResult` and the corresponding handler instance (or None)
  - The JS snippet returns a JSON string with `{player, element, meta}` — meta includes bbox center (`cx`, `cy`), duration, readyState, src where available
  - Handler mapping: `{"vimeo": VimeoPlayer(), "mux": MuxPlayer(), "html5": HTML5Player()}`
  - Polls with configurable timeout (like `obs_capture.py`'s 30s wait)

- Run `uv run pytest tests/test_detector.py` — must pass.

### 9. Wire up `src/players/__init__.py` exports

- Update `src/players/__init__.py` to re-export the public API:
  ```python
  from src.players.base import DetectionResult, PlayerHandler
  from src.players.detector import detect_player
  from src.players.mux import MuxPlayer
  from src.players.vimeo import VimeoPlayer
  from src.players.html5 import HTML5Player

  __all__ = [
      "DetectionResult", "PlayerHandler", "detect_player",
      "MuxPlayer", "VimeoPlayer", "HTML5Player",
  ]
  ```

### 10. Update conftest.py and run full test suite

- Update `tests/conftest.py` to keep the existing `sys.path` hacking for old tests AND ensure `src` is importable:
  ```python
  """Put the (non-package) script dirs on sys.path so tests can import them."""
  import sys
  from pathlib import Path

  ROOT = Path(__file__).resolve().parent.parent
  for sub in ("transcribe", "acquire"):
      sys.path.insert(0, str(ROOT / sub))
  ```
  The `src` package should already be importable via the `pyproject.toml` changes. Verify.

- Run the full test suite: `uv run pytest`
- All existing tests (`test_obs_capture.py`, `test_corrections.py`, etc.) must still pass.
- All new tests (`test_config.py`, `test_cdp.py`, `test_detector.py`, `test_mux_player.py`, `test_vimeo_player.py`) must pass.

## Testing Strategy

All new code uses **TDD** — tests are written before implementation for each module.

| Module | Test File | What's Tested | Mocking Strategy |
|--------|-----------|---------------|------------------|
| `src/config.py` | `tests/test_config.py` | Constants are correct types/values, `IS_WINDOWS` matches platform | No mocks |
| `src/cdp.py` | `tests/test_cdp.py` | connect, navigate, js, click, key, get_ws_url | Mock `websockets.connect`, `urllib.request.urlopen` |
| `src/players/detector.py` | `tests/test_detector.py` | Detection for vimeo/mux/html5/youtube/none, correct handler returned | Mock `CDPClient.js` with sample JSON |
| `src/players/mux.py` | `tests/test_mux_player.py` | Fullscreen retry (3 attempts + F11), unmute, play/pause, duration | Mock `CDPClient` entirely |
| `src/players/vimeo.py` | `tests/test_vimeo_player.py` | Vimeo SDK injection, API calls, fullscreen on iframe | Mock `CDPClient` entirely |
| `src/players/html5.py` | `tests/test_html5_player.py` | Play/pause, name property | Mock `CDPClient` entirely |

Edge cases to cover:
- `CDPClient.get_ws_url` when no `"page"` type exists (should raise `StopIteration`)
- `CDPClient.js` when the response has `exceptionDetails` (should return `None`)
- Detection when DOM has multiple players (priority: vimeo > mux > youtube > html5)
- Fullscreen when all 3 attempts + F11 fallback all fail (returns `False`)
- Duration returning `NaN` or `0` from JS (handle gracefully)

## Acceptance Criteria

1. `uv run python -c "from src.config import CDP_URL, OBS_PORT; print(CDP_URL, OBS_PORT)"` prints `http://localhost:9222 4455`
2. `uv run python -c "from src.cdp import CDPClient; print(CDPClient)"` imports without error
3. `uv run python -c "from src.players import detect_player, MuxPlayer, VimeoPlayer, HTML5Player; print('OK')"` prints `OK`
4. `uv run pytest tests/test_config.py tests/test_cdp.py tests/test_detector.py tests/test_mux_player.py tests/test_vimeo_player.py` — all pass
5. `uv run pytest` — full suite passes (no regressions in existing tests)
6. Existing scripts run unchanged: `uv run python -m py_compile acquire/obs_capture.py acquire/record_batch.py`
7. No new dependencies beyond what's in `pyproject.toml` except `pytest-asyncio` (dev) and `websockets` (capture extra)

## Validation Commands
Execute these commands to validate the task is complete:

- `uv run pytest` — Full test suite (new + existing) passes
- `uv run python -c "from src.config import CDP_URL, OBS_PORT, IS_WINDOWS; print(f'{CDP_URL=} {OBS_PORT=} {IS_WINDOWS=}')"` — Config imports work
- `uv run python -c "from src.cdp import CDPClient; print('CDPClient OK')"` — CDP client imports
- `uv run python -c "from src.players import detect_player, MuxPlayer, VimeoPlayer, HTML5Player, DetectionResult; print('Players OK')"` — All player modules import
- `uv run python -m py_compile acquire/obs_capture.py acquire/record_batch.py acquire/record_patreon.py` — Existing scripts still compile
- `uv run pytest --tb=short -q` — Quick confirmation of pass count

## Notes

- **Package naming**: `src/` as a Python package name is non-standard (usually `src/` is a layout directory containing a named package like `src/media_transcribe/`). This is acceptable for Phase 1 since the package is internal-only. Phase 2 or 3 may rename to `media_transcribe/` if the project is ever pip-installed.
- **`websockets` dependency**: Already used by `record_one.py` and `patreon_capture_remote.py` on the obs-machine. Add it to the `[capture]` optional dependency group since it's only needed for CDP communication on the capture box. On devbox-01, tests mock it out.
- **`pytest-asyncio` dependency**: Add to the `dev` dependency group for async test support. Use `asyncio_mode = "auto"` in `pyproject.toml` to avoid decorating every test with `@pytest.mark.asyncio` (or use it explicitly if preferred).
- **OBS_PASSWORD in config.py**: This is a local-network WebSocket password, not a cloud credential. It's already committed in `record_one.py` and `record_batch.py`. Acceptable for this private repo. If this changes, consider reading from an environment variable or the existing `obs_config.toml`.
- **Backward compatibility**: Do NOT modify or delete any existing files in `acquire/` or `transcribe/`. They continue to run independently with their inline constants until Phase 2 migrates them.
- **Build backend**: Check whether `pyproject.toml` has a `[build-system]` section. If not, `uv` uses hatchling by default. Add the appropriate config to ensure `src/` is discoverable as a package.
