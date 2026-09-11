"""Environment setup & teardown — Chrome + OBS lifecycle management."""
from __future__ import annotations

import ctypes
import json
import logging
import os
import subprocess
import time
import urllib.request
from pathlib import Path

from src.config import (
    CDP_URL,
    CHROME_FLAGS,
    CHROME_PATH,
    IS_WINDOWS,
    OBS_HOST,
    OBS_PASSWORD,
    OBS_PATH,
    OBS_PORT,
    SCHTASK_NAME_CHROME,
    SCHTASK_NAME_OBS,
    TEMP_BAT_DIR,
)

log = logging.getLogger(__name__)


def is_ssh_session() -> bool:
    if os.environ.get("SSH_CLIENT") or os.environ.get("SSH_CONNECTION"):
        return True
    if IS_WINDOWS:
        try:
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            pid = kernel32.GetCurrentProcessId()
            session_id = ctypes.c_ulong(0)
            kernel32.ProcessIdToSessionId(pid, ctypes.byref(session_id))
            if session_id.value == 0:
                return True
        except Exception:
            pass
    return False


def _launch_via_scheduled_task(exe_path: str, args: list[str], task_name: str) -> bool:
    TEMP_BAT_DIR.mkdir(parents=True, exist_ok=True)
    bat_path = TEMP_BAT_DIR / f"{task_name}.bat"

    args_str = " ".join(f'"{a}"' if " " in a else a for a in args)
    bat_path.write_text(
        f'@echo off\nstart "" "{exe_path}" {args_str}\n',
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "schtasks", "/create", "/tn", task_name,
            "/tr", str(bat_path), "/sc", "once",
            "/st", "00:00", "/f", "/it", "/ru", "Matt",
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        log.error("schtasks /create failed: %s", result.stderr)
        return False

    result = subprocess.run(
        ["schtasks", "/run", "/tn", task_name],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        log.error("schtasks /run failed: %s", result.stderr)
        return False

    return True


def _cleanup_scheduled_task(task_name: str) -> None:
    try:
        subprocess.run(
            ["schtasks", "/delete", "/tn", task_name, "/f"],
            capture_output=True, text=True,
        )
    except Exception:
        pass
    bat_path = TEMP_BAT_DIR / f"{task_name}.bat"
    if bat_path.exists():
        try:
            bat_path.unlink()
        except Exception:
            pass


def _launch_app(exe_path: Path, args: list[str], task_name: str) -> bool:
    try:
        if is_ssh_session():
            return _launch_via_scheduled_task(str(exe_path), args, task_name)
        subprocess.Popen([str(exe_path)] + args)
        return True
    except Exception as exc:
        log.error("Failed to launch %s: %s", exe_path, exc)
        return False


def restart_chrome() -> bool:
    """Kill all Chrome processes and relaunch fresh with correct flags.

    Used at the start of each pipeline run so recordings never inherit
    stale windows, restore dialogs, or cached session state from a prior
    run. Relaunch reuses `_launch_app` — the same SSH-aware mechanism
    `EnvironmentManager._setup_chrome` uses (scheduled task with `/it`
    when running over SSH, direct `Popen` when local) — so the relaunched
    Chrome behaves identically to a normal setup() launch.

    Returns True if Chrome CDP is responding after restart.
    """
    if not IS_WINDOWS:
        log.debug("Not Windows — restart_chrome is a no-op")
        return False

    log.info("Restarting Chrome (clean slate)...")

    try:
        subprocess.run(
            ["taskkill", "/f", "/im", "chrome.exe"],
            capture_output=True, timeout=10,
        )
        log.info("Chrome processes killed")
    except Exception as e:
        log.warning("Chrome kill failed (may not be running): %s", e)

    time.sleep(2)  # let processes fully exit

    launched = _launch_app(CHROME_PATH, list(CHROME_FLAGS), SCHTASK_NAME_CHROME)
    if not launched:
        log.error("Failed to relaunch Chrome")
        return False

    for _ in range(30):
        try:
            urllib.request.urlopen(f"{CDP_URL}/json", timeout=2)
            log.info("Chrome CDP ready after restart")
            return True
        except Exception:
            time.sleep(1)

    log.error("Chrome CDP not responding after restart")
    return False


def restart_obs() -> bool:
    """Kill OBS and relaunch fresh. Returns True if OBS WebSocket responds after restart.

    Used at the start of each pipeline run so recordings never inherit
    stuck recordings, stale window-capture sources, or orphaned state
    from a prior run. Mirrors ``restart_chrome`` — same SSH-aware launch
    mechanism and same poll-until-ready pattern.

    Returns True if OBS WebSocket is responding after restart.
    """
    if not IS_WINDOWS:
        log.debug("Not Windows — restart_obs is a no-op")
        return False

    log.info("Restarting OBS (clean slate)...")

    # 1. Stop any active recording first (graceful)
    try:
        client = _obs_connect()
        try:
            status = client.get_record_status()
            if status.output_active:
                client.stop_record()
                log.info("Stopped active OBS recording before restart")
        finally:
            client.base_client.ws.close()
    except Exception:
        pass  # OBS may not be running or WebSocket may be dead

    # 2. Kill obs64.exe process
    try:
        subprocess.run(
            ["taskkill", "/f", "/im", "obs64.exe"],
            capture_output=True, timeout=10,
        )
        log.info("OBS processes killed")
    except Exception as e:
        log.warning("OBS kill failed (may not be running): %s", e)

    # 3. Wait for processes to fully exit
    time.sleep(2)

    # 4. Relaunch via _launch_app()
    launched = _launch_app(OBS_PATH, ["--minimize-to-tray"], SCHTASK_NAME_OBS)
    if not launched:
        log.error("Failed to relaunch OBS")
        return False

    # 5. Poll OBS WebSocket for up to 30s
    for _ in range(30):
        try:
            client = _obs_connect()
            client.base_client.ws.close()
            log.info("OBS WebSocket ready after restart")
            return True
        except Exception:
            time.sleep(1)

    log.error("OBS WebSocket not responding after restart")
    return False


def _obs_connect():
    import obsws_python as obs
    return obs.ReqClient(
        host=OBS_HOST, port=OBS_PORT,
        password=OBS_PASSWORD, timeout=5,
    )


def _configure_obs_window(client) -> bool:
    """Set OBS Window Capture to the current (non-blank) Chrome window.

    Re-resolves from OBS's live window list every call — the class name
    'Chrome_WidgetWin_1' is present in every Chrome window string, so a
    substring check against the currently-set value can never detect that
    the target has gone stale (e.g. pinned to an about:blank window).
    """
    settings = client.get_input_settings("Window Capture")
    current = settings.input_settings.get("window", "")

    props = client.get_input_properties_list_property_items("Window Capture", "window")
    chrome_windows = [
        p for p in props.property_items
        if p.get("itemEnabled") and "chrome.exe" in p.get("itemValue", "").lower()
    ]

    if not chrome_windows:
        log.warning("No Chrome windows available in OBS")
        return False

    # Pick the one that is NOT about:blank (prefer the page with content)
    best = None
    for w in chrome_windows:
        name = w.get("itemName", "")
        if "about:blank" not in name.lower() and "about#3ablank" not in name.lower():
            best = w
            break

    # Fallback to first available if all are about:blank
    if not best:
        best = chrome_windows[0]

    new_window = best["itemValue"]
    if new_window != current:
        client.set_input_settings("Window Capture", {"window": new_window}, True)
        log.info("OBS Window Capture -> %s", best.get("itemName", "")[:60])

    return True


class EnvironmentManager:
    def __init__(self, cdp_url: str = CDP_URL):
        self._cdp_url = cdp_url

    def setup(self) -> tuple[bool, list[str]]:
        """Launch Chrome + OBS with a clean slate and configure OBS sources.

        Always kills and restarts both Chrome and OBS fresh so recordings
        never inherit ghost processes, stale OBS Window Capture sources,
        or stuck recordings from a prior run.
        """
        messages: list[str] = []

        chrome_ok = restart_chrome()
        messages.append(f"Chrome: {'OK' if chrome_ok else 'FAILED'}")
        if not chrome_ok:
            return False, messages

        obs_ok = restart_obs()
        messages.append(f"OBS: {'OK' if obs_ok else 'FAILED'}")
        if not obs_ok:
            return False, messages

        config_ok = self._configure_obs()
        messages.append(f"OBS config: {'OK' if config_ok else 'FAILED'}")
        if not config_ok:
            return False, messages

        return True, messages

    def teardown(self) -> tuple[bool, list[str]]:
        messages: list[str] = []

        self._stop_obs_recording()
        messages.append("OBS recording stopped")

        self._close_chrome()
        messages.append("Chrome closed")

        self._close_obs()
        messages.append("OBS closed")

        self._cleanup_temp_files()
        messages.append("Temp files cleaned up")

        return True, messages

    def _setup_chrome(self) -> bool:
        try:
            urllib.request.urlopen(f"{self._cdp_url}/json", timeout=5)
            log.info("Chrome CDP already running")
            return True
        except Exception:
            pass

        if not IS_WINDOWS:
            return False

        launched = _launch_app(CHROME_PATH, list(CHROME_FLAGS), SCHTASK_NAME_CHROME)
        if not launched:
            return False

        for _ in range(8):
            time.sleep(2)
            try:
                urllib.request.urlopen(f"{self._cdp_url}/json", timeout=5)
                log.info("Chrome CDP is now responding")
                return True
            except Exception:
                pass

        log.error("Chrome CDP did not respond within 15s")
        return False

    def _setup_obs(self) -> bool:
        try:
            client = _obs_connect()
            client.base_client.ws.close()
            log.info("OBS WebSocket already running")
            return True
        except Exception:
            pass

        if not IS_WINDOWS:
            return False

        launched = _launch_app(OBS_PATH, ["--minimize-to-tray"], SCHTASK_NAME_OBS)
        if not launched:
            return False

        for _ in range(8):
            time.sleep(2)
            try:
                client = _obs_connect()
                client.base_client.ws.close()
                log.info("OBS WebSocket is now responding")
                return True
            except Exception:
                pass

        log.error("OBS WebSocket did not respond within 15s")
        return False

    def _configure_obs(self) -> bool:
        try:
            client = _obs_connect()
            try:
                _configure_obs_window(client)
                client.set_input_settings(
                    "Desktop Audio",
                    {"device_id": "default"},
                    True,
                )
            finally:
                client.base_client.ws.close()
            return True
        except Exception as exc:
            log.error("OBS configuration failed: %s", exc)
            return False

    def _stop_obs_recording(self) -> None:
        try:
            client = _obs_connect()
            try:
                status = client.get_record_status()
                if status.output_active:
                    client.stop_record()
                    log.info("Stopped OBS recording")
            finally:
                client.base_client.ws.close()
        except Exception as exc:
            log.warning("Could not stop OBS recording: %s", exc)

    def _close_chrome(self) -> None:
        try:
            data = urllib.request.urlopen(
                f"{self._cdp_url}/json/version", timeout=5,
            ).read()
            info = json.loads(data)
            ws_url = info.get("webSocketDebuggerUrl", "")
            if ws_url:
                import websockets.sync.client as ws_sync
                conn = ws_sync.connect(ws_url)
                conn.send(json.dumps({"id": 1, "method": "Browser.close"}))
                conn.close()
                log.info("Chrome closed via CDP")
                return
        except Exception as exc:
            log.warning("CDP Browser.close failed: %s", exc)

        if IS_WINDOWS:
            try:
                subprocess.run(
                    ["taskkill", "/im", "chrome.exe", "/f"],
                    capture_output=True, text=True,
                )
                log.info("Chrome killed via taskkill")
            except Exception as exc:
                log.warning("taskkill chrome failed: %s", exc)

    def _close_obs(self) -> None:
        if IS_WINDOWS:
            try:
                subprocess.run(
                    ["taskkill", "/im", "obs64.exe", "/f"],
                    capture_output=True, text=True,
                )
                log.info("OBS killed via taskkill")
            except Exception as exc:
                log.warning("taskkill obs failed: %s", exc)

    def _cleanup_temp_files(self) -> None:
        _cleanup_scheduled_task(SCHTASK_NAME_CHROME)
        _cleanup_scheduled_task(SCHTASK_NAME_OBS)
        if TEMP_BAT_DIR.exists():
            for f in TEMP_BAT_DIR.iterdir():
                try:
                    f.unlink()
                except Exception:
                    pass
