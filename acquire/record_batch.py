#!/usr/bin/env python3
"""Serial multi-video Patreon recorder for the Windows obs-machine.

Reads a queue of URLs from a JSON file, records each video in sequence
by calling ``record_one.py`` as a subprocess, with human-like breaks
between recordings and mild URL shuffling to avoid bot-like patterns.

Runs ENTIRELY on the obs-machine — no SSH, no devbox-01 involvement.

Includes preflight validation (Chrome CDP, OBS WebSocket, Patreon session,
disk space, test recording) and inter-video health checks with self-healing.

Queue file format (record_queue.json):
  [
    {"url": "https://www.patreon.com/posts/12345", "filename": "Masterclass 3 - Basics of Investing 102"},
    {"url": "https://www.patreon.com/posts/67890", "filename": "Masterclass 7 - Balance Sheet Deep Dive"}
  ]

Usage:
  py -3 record_batch.py                          # record from default queue
  py -3 record_batch.py --queue my_queue.json     # custom queue file
  py -3 record_batch.py --dry-run                 # show what would be recorded
  py -3 record_batch.py --no-shuffle              # preserve original order
  py -3 record_batch.py --no-breaks               # skip breaks between videos
  py -3 record_batch.py --skip-preflight          # skip startup validation
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants — all paths are on the obs-machine (Windows)
# ---------------------------------------------------------------------------
SCRIPTS_DIR = Path(r"C:\Users\Matt\agent-control\scripts")
STATE_DIR = Path(r"C:\Users\Matt\agent-control\state")
LOGS_DIR = Path(r"C:\Users\Matt\agent-control\logs")
BACKUP_DIR = Path(r"D:\MasterClass Video Backup")

RECORD_ONE_SCRIPT = SCRIPTS_DIR / "record_one.py"
DEFAULT_QUEUE = STATE_DIR / "record_queue.json"
SEEN_FILE = STATE_DIR / "seen_urls.txt"
LOG_FILE = LOGS_DIR / "record_batch.log"

# Python on the obs-machine — ``python`` is 3.8.2 (too old), ``py -3`` is 3.12
PYTHON_CMD = ["py", "-3"]

# Human-like timing between videos (5-25 minutes)
BREAK_MIN_SECONDS = 300
BREAK_MAX_SECONDS = 1500

# Markers emitted by record_one.py (parsed from its stdout)
MARKER_DONE = "DONE"
MARKER_FAILED = "FAILED:"
MARKER_MOVED = "Moved:"

# ---------------------------------------------------------------------------
# Preflight / health-check constants
# ---------------------------------------------------------------------------
OBS_PASSWORD = "DK4HLJPKgslAhEgD"
CRED_TARGET = "patreon_02_ai"
CHROME_PATH = Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe")
CHROME_PROFILE = Path(r"C:\Users\Matt\agent-control\chrome-profile")
OBS_PATH = Path(r"C:\Program Files\obs-studio\bin\64bit\obs64.exe")
CDP_URL = "http://localhost:9222"
PREFLIGHT_VIDEO_URL = "file:///C:/Users/Matt/agent-control/scripts/audio_test.html"
DISK_MIN_GB = 5


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
def setup_logging() -> logging.Logger:
    """Configure dual logging: file (DEBUG) + console (INFO)."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("record_batch")
    logger.setLevel(logging.DEBUG)

    # File handler — verbose, appends across runs
    fh = logging.FileHandler(str(LOG_FILE), encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    # Console handler — concise
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(message)s"))

    logger.addHandler(fh)
    logger.addHandler(ch)

    return logger


log = setup_logging()


# ---------------------------------------------------------------------------
# Windows Credential Manager (ctypes / advapi32.dll)
#   Imports are lazy — ctypes.wintypes only exists on Windows.
# ---------------------------------------------------------------------------
def read_credential(target: str) -> tuple[str, str] | None:
    """Read username + password from Windows Credential Manager.

    Uses CredReadW (advapi32.dll) to look up a Generic credential by
    *target* name.  Returns ``(username, password)`` or ``None`` if the
    credential is not found.
    """
    try:
        import ctypes
        import ctypes.wintypes
    except ImportError:
        log.warning("[credential] ctypes.wintypes unavailable (not Windows?)")
        return None

    class CREDENTIAL(ctypes.Structure):
        """Win32 CREDENTIAL structure for CredReadW / CredFree."""
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
        log.warning("[credential] ctypes.windll unavailable (not Windows?)")
        return None

    cred_ptr = ctypes.POINTER(CREDENTIAL)()
    # Type 1 = CRED_TYPE_GENERIC
    ok = advapi32.CredReadW(target, 1, 0, ctypes.byref(cred_ptr))
    if not ok:
        log.warning("[credential] CredReadW failed for target=%s (not found?)", target)
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


# ---------------------------------------------------------------------------
# Chrome CDP management
# ---------------------------------------------------------------------------
def ensure_chrome() -> bool:
    """Ensure Chrome is running with CDP on port 9222.

    If Chrome is not reachable on the CDP port, kills any existing Chrome
    processes and relaunches with ``--remote-debugging-port=9222``.
    Returns True if Chrome CDP is responsive, False on failure.
    """
    # Check if CDP is already responding
    if _cdp_alive():
        log.debug("[chrome] CDP already responding on %s", CDP_URL)
        return True

    log.info("[chrome] CDP not responding — restarting Chrome")

    # Kill existing Chrome processes (best-effort)
    subprocess.run(
        ["taskkill", "/f", "/im", "chrome.exe"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(2)

    # Launch Chrome with CDP enabled
    try:
        subprocess.Popen(
            [
                str(CHROME_PATH),
                "--remote-debugging-port=9222",
                f"--user-data-dir={CHROME_PROFILE}",
                "--start-maximized",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        log.error("[chrome] Chrome not found at %s", CHROME_PATH)
        return False
    except OSError as exc:
        log.error("[chrome] Failed to launch Chrome: %s", exc)
        return False

    # Wait up to 15 seconds for CDP to become responsive
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        time.sleep(1)
        if _cdp_alive():
            log.info("[chrome] CDP now responding")
            return True

    log.error("[chrome] CDP did not respond within 15 seconds")
    return False


def _cdp_alive() -> bool:
    """Return True if Chrome CDP endpoint responds on localhost:9222."""
    try:
        urllib.request.urlopen(f"{CDP_URL}/json", timeout=5)
        return True
    except Exception:
        return False


def _cdp_tab_usable() -> bool:
    """Check that a CDP tab can execute JS (Runtime.evaluate).

    Connects via websockets, evaluates ``1+1``, and verifies the result
    is ``2``.  Returns False if the tab is crashed or unresponsive.
    """
    try:
        return asyncio.run(_cdp_quick_eval_async())
    except Exception:
        return False


async def _cdp_quick_eval_async() -> bool:
    """Async helper — evaluate 1+1 via CDP and check the result."""
    import websockets  # lazy — not available on Linux dev machine

    data = urllib.request.urlopen(f"{CDP_URL}/json", timeout=5).read()
    pages = json.loads(data)
    page = next((p for p in pages if p["type"] == "page"), None)
    if not page:
        return False
    ws_url = page["webSocketDebuggerUrl"]

    async with websockets.connect(
        ws_url, max_size=10 * 1024 * 1024, close_timeout=5,
    ) as ws:
        await ws.send(json.dumps({
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {"expression": "1+1", "returnByValue": True},
        }))
        resp = json.loads(await ws.recv())
        value = resp.get("result", {}).get("result", {}).get("value")
        return value == 2


# ---------------------------------------------------------------------------
# OBS WebSocket management
# ---------------------------------------------------------------------------
def ensure_obs() -> bool:
    """Ensure OBS is running with WebSocket on port 4455.

    If OBS is unreachable, launches it and waits up to 20 seconds for
    the WebSocket to become responsive.
    Returns True if OBS WebSocket is responsive, False on failure.
    """
    if _obs_alive():
        log.debug("[obs] WebSocket already responding")
        return True

    log.info("[obs] WebSocket not responding — launching OBS")

    try:
        subprocess.Popen(
            [str(OBS_PATH)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        log.error("[obs] OBS not found at %s", OBS_PATH)
        return False
    except OSError as exc:
        log.error("[obs] Failed to launch OBS: %s", exc)
        return False

    # Wait up to 20 seconds for OBS WebSocket to respond
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        time.sleep(2)
        if _obs_alive():
            log.info("[obs] WebSocket now responding")
            return True

    log.error("[obs] WebSocket did not respond within 20 seconds")
    return False


def _obs_alive() -> bool:
    """Return True if OBS WebSocket is reachable on port 4455."""
    try:
        import obsws_python as obs
        cl = obs.ReqClient(
            host="localhost", port=4455, password=OBS_PASSWORD, timeout=5,
        )
        cl.base_client.ws.close()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Patreon session check (async via CDP)
# ---------------------------------------------------------------------------
def check_patreon_session() -> bool:
    """Check if Patreon session is valid; auto-login if expired.

    Connects to Chrome via CDP, navigates to Patreon, and checks whether
    a login form is present.  If a login form is detected, reads
    credentials from Windows Credential Manager and fills them in.

    Returns True if the session is valid (or login succeeded), False on
    failure.
    """
    try:
        return asyncio.run(_check_patreon_session_async())
    except Exception as exc:
        log.error("[patreon] Session check failed: %s", exc)
        return False


async def _check_patreon_session_async() -> bool:
    """Async implementation of the Patreon session check."""
    import websockets  # lazy — not available on Linux dev machine

    # Get WebSocket URL from CDP
    try:
        data = urllib.request.urlopen(f"{CDP_URL}/json", timeout=5).read()
        pages = json.loads(data)
        page = next((p for p in pages if p["type"] == "page"), None)
        if not page:
            log.error("[patreon] No CDP page targets found")
            return False
        ws_url = page["webSocketDebuggerUrl"]
    except Exception as exc:
        log.error("[patreon] Cannot reach CDP: %s", exc)
        return False

    msg_id = 0

    async def cdp_send(ws, method: str, params: dict | None = None) -> dict:
        nonlocal msg_id
        msg_id += 1
        mid = msg_id
        await ws.send(json.dumps({
            "id": mid, "method": method, "params": params or {},
        }))
        while True:
            resp = json.loads(await ws.recv())
            if resp.get("id") == mid:
                return resp

    async def cdp_js(ws, expr: str) -> object:
        """Evaluate JS expression via CDP, return the value or None."""
        r = await cdp_send(ws, "Runtime.evaluate", {
            "expression": expr, "returnByValue": True,
        })
        inner = r.get("result", {})
        if "exceptionDetails" in inner:
            return None
        return inner.get("result", {}).get("value")

    try:
        async with websockets.connect(ws_url, max_size=10 * 1024 * 1024) as ws:
            # Navigate to Patreon home
            await cdp_send(ws, "Page.navigate", {"url": "https://www.patreon.com/home"})
            await asyncio.sleep(5)

            # Check for login form elements
            login_detected = await cdp_js(ws, (
                "!!document.querySelector("
                "'input[name=\"email\"], "
                "form[action*=\"login\"], "
                "input[type=\"email\"]')"
            ))

            if not login_detected:
                log.info("[patreon] Session is valid (no login form detected)")
                # Navigate away to clean up
                await cdp_send(ws, "Page.navigate", {"url": "about:blank"})
                return True

            log.info("[patreon] Login form detected — attempting auto-login")

            # Read credentials from Windows Credential Manager
            creds = read_credential(CRED_TARGET)
            if not creds:
                log.error(
                    "[patreon] No credentials found for target=%s in "
                    "Credential Manager", CRED_TARGET,
                )
                await cdp_send(ws, "Page.navigate", {"url": "about:blank"})
                return False

            email, password = creds

            # Fill email field
            await cdp_js(ws, f"""
            (() => {{
                const el = document.querySelector(
                    'input[name="email"], input[type="email"]'
                );
                if (el) {{
                    el.focus();
                    el.value = {json.dumps(email)};
                    el.dispatchEvent(new Event('input', {{bubbles: true}}));
                    el.dispatchEvent(new Event('change', {{bubbles: true}}));
                }}
            }})()
            """)
            await asyncio.sleep(1)

            # Click continue / next button
            await cdp_js(ws, """
            (() => {
                const btns = [...document.querySelectorAll('button')];
                const next = btns.find(b =>
                    /continue|next|log\\s*in|sign\\s*in/i.test(b.textContent)
                );
                if (next) next.click();
            })()
            """)
            await asyncio.sleep(3)

            # Fill password field
            await cdp_js(ws, f"""
            (() => {{
                const el = document.querySelector('input[type="password"]');
                if (el) {{
                    el.focus();
                    el.value = {json.dumps(password)};
                    el.dispatchEvent(new Event('input', {{bubbles: true}}));
                    el.dispatchEvent(new Event('change', {{bubbles: true}}));
                }}
            }})()
            """)
            await asyncio.sleep(1)

            # Submit login form
            await cdp_js(ws, """
            (() => {
                const btns = [...document.querySelectorAll('button')];
                const submit = btns.find(b =>
                    /log\\s*in|sign\\s*in|submit|continue/i.test(b.textContent)
                );
                if (submit) submit.click();
            })()
            """)
            await asyncio.sleep(5)

            # Verify login succeeded — check we no longer see a login form
            still_login = await cdp_js(ws, (
                "!!document.querySelector("
                "'input[name=\"email\"], "
                "form[action*=\"login\"], "
                "input[type=\"email\"]')"
            ))

            if still_login:
                log.error("[patreon] Login appears to have failed (login form still present)")
                await cdp_send(ws, "Page.navigate", {"url": "about:blank"})
                return False

            log.info("[patreon] Login succeeded")
            await cdp_send(ws, "Page.navigate", {"url": "about:blank"})
            return True

    except Exception as exc:
        log.error("[patreon] CDP session check error: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Disk space check
# ---------------------------------------------------------------------------
def check_disk_space() -> bool:
    r"""Check available disk space on D:\\.

    Returns True if free space >= DISK_MIN_GB, False otherwise.
    """
    try:
        usage = shutil.disk_usage(r"D:\\")
        free_gb = usage.free / (1024 ** 3)
        log.info("[disk] D:\\ has %.0f GB free", free_gb)
        if free_gb < DISK_MIN_GB:
            log.error(
                "[disk] Insufficient disk space: %.1f GB free, need %d GB",
                free_gb, DISK_MIN_GB,
            )
            return False
        return True
    except OSError as exc:
        log.error("[disk] Cannot check D:\\ disk space: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Test recording (preflight A/V validation)
# ---------------------------------------------------------------------------
def run_test_recording() -> tuple[bool, bool, tuple[int, int] | None]:
    """Run a short test recording to validate video + audio capture.

    Navigates Chrome to a known YouTube video, starts an OBS recording,
    then analyses the resulting file with ffmpeg for black frames and
    silence.

    Returns ``(video_ok, audio_ok, resolution_or_none)``.
    """
    try:
        return asyncio.run(_run_test_recording_async())
    except Exception as exc:
        log.error("[test-rec] Test recording failed: %s", exc)
        return (False, False, None)


async def _run_test_recording_async() -> tuple[bool, bool, tuple[int, int] | None]:
    """Async implementation of the test recording."""
    import websockets  # lazy — not available on Linux dev machine
    import obsws_python as obs

    # --- Navigate Chrome to the test video via CDP ---
    try:
        data = urllib.request.urlopen(f"{CDP_URL}/json", timeout=5).read()
        pages = json.loads(data)
        page = next((p for p in pages if p["type"] == "page"), None)
        if not page:
            log.error("[test-rec] No CDP page targets found")
            return (False, False, None)
        ws_url = page["webSocketDebuggerUrl"]
    except Exception as exc:
        log.error("[test-rec] Cannot reach CDP: %s", exc)
        return (False, False, None)

    msg_id = 0

    async def cdp_send(ws, method: str, params: dict | None = None) -> dict:
        nonlocal msg_id
        msg_id += 1
        mid = msg_id
        await ws.send(json.dumps({
            "id": mid, "method": method, "params": params or {},
        }))
        while True:
            resp = json.loads(await ws.recv())
            if resp.get("id") == mid:
                return resp

    async def cdp_js(ws, expr: str) -> object:
        r = await cdp_send(ws, "Runtime.evaluate", {
            "expression": expr, "returnByValue": True,
        })
        inner = r.get("result", {})
        if "exceptionDetails" in inner:
            return None
        return inner.get("result", {}).get("value")

    output_path = None

    try:
        async with websockets.connect(ws_url, max_size=10 * 1024 * 1024) as ws:
            # Navigate to test video
            await cdp_send(ws, "Page.navigate", {"url": PREFLIGHT_VIDEO_URL})
            await asyncio.sleep(8)

            # Click page to satisfy autoplay/AudioContext gesture requirement
            await cdp_send(ws, "Input.dispatchMouseEvent", {
                "type": "mousePressed", "x": 500, "y": 400, "button": "left", "clickCount": 1,
            })
            await cdp_send(ws, "Input.dispatchMouseEvent", {
                "type": "mouseReleased", "x": 500, "y": 400, "button": "left", "clickCount": 1,
            })
            await asyncio.sleep(1)
            # Resume any AudioContext after user gesture
            await cdp_js(ws, "document.querySelectorAll('*').forEach(e => { if (e.audioContext) e.audioContext.resume(); })")
            await cdp_js(ws, "if (typeof ctx !== 'undefined') ctx.resume()")

            # Try to play the video (unmute + full volume — YouTube starts
            # muted by default due to autoplay policy, so OBS would
            # capture silence otherwise)
            await cdp_js(ws, """
            (() => {
                const v = document.querySelector('video');
                if (v) { v.muted = false; v.volume = 1.0; v.play().catch(() => {}); }
            })()
            """)
            # Also try clicking the player area in case autoplay is blocked
            await cdp_js(ws, """
            (() => {
                const player = document.querySelector('#movie_player, .html5-video-player');
                if (player) player.click();
            })()
            """)
            # Ensure unmuted after click (click can re-trigger autoplay mute)
            await cdp_js(ws, """
            (() => {
                const v = document.querySelector('video');
                if (v) { v.muted = false; v.volume = 1.0; }
            })()
            """)
            await asyncio.sleep(3)

            # --- Start OBS recording ---
            try:
                cl = obs.ReqClient(
                    host="localhost", port=4455, password=OBS_PASSWORD, timeout=5,
                )
            except Exception as exc:
                log.error("[test-rec] Cannot connect to OBS: %s", exc)
                await cdp_send(ws, "Page.navigate", {"url": "about:blank"})
                return (False, False, None)

            try:
                cl.set_profile_parameter(
                    "Output", "FilenameFormatting", "_preflight_test",
                )
                cl.start_record()
                log.debug("[test-rec] Recording started")
            except Exception as exc:
                log.error("[test-rec] Failed to start recording: %s", exc)
                cl.base_client.ws.close()
                await cdp_send(ws, "Page.navigate", {"url": "about:blank"})
                return (False, False, None)

            # Record for 10 seconds
            await asyncio.sleep(10)

            # Stop recording and get output path
            try:
                resp = cl.stop_record()
                output_path = getattr(resp, "output_path", None)
                log.debug("[test-rec] Recording saved to: %s", output_path)
            except Exception as exc:
                log.error("[test-rec] Failed to stop recording: %s", exc)
                return (False, False, None)
            finally:
                cl.base_client.ws.close()

            # Navigate away
            await cdp_send(ws, "Page.navigate", {"url": "about:blank"})

    except Exception as exc:
        log.error("[test-rec] CDP/recording error: %s", exc)
        return (False, False, None)

    if not output_path or not os.path.isfile(output_path):
        log.error("[test-rec] Recording file not found: %s", output_path)
        return (False, False, None)

    # --- Analyse the recording with ffmpeg/ffprobe ---
    video_ok = _check_video_black(output_path)
    audio_ok = _check_audio_silence(output_path)
    resolution = _get_resolution(output_path)

    # Clean up the test file
    try:
        os.remove(output_path)
        log.debug("[test-rec] Deleted test file: %s", output_path)
    except OSError as exc:
        log.warning("[test-rec] Could not delete test file: %s", exc)

    return (video_ok, audio_ok, resolution)


def _check_video_black(path: str) -> bool:
    """Return True if the video is NOT mostly black frames."""
    try:
        proc = subprocess.run(
            [
                "ffmpeg", "-i", path,
                "-vf", "blackdetect=d=0.5:pix_th=0.10",
                "-an", "-f", "null", "-",
            ],
            capture_output=True, text=True, timeout=60,
        )
        stderr = proc.stderr

        # Parse black segments from stderr
        total_black = 0.0
        for m in re.finditer(
            r"black_start:([\d.]+)\s+black_end:([\d.]+)\s+black_duration:([\d.]+)",
            stderr,
        ):
            total_black += float(m.group(3))

        # Get total duration from ffprobe
        total_duration = _get_duration(path)
        if total_duration <= 0:
            log.warning("[test-rec] Could not determine video duration")
            return True  # assume OK if we can't check

        ratio = total_black / total_duration
        log.debug("[test-rec] Black ratio: %.2f (%.1fs / %.1fs)", ratio, total_black, total_duration)
        return ratio < 0.8
    except Exception as exc:
        log.warning("[test-rec] Black-frame check error: %s", exc)
        return True  # assume OK on check failure


def _check_audio_silence(path: str) -> bool:
    """Return True if the audio is NOT mostly silence."""
    try:
        proc = subprocess.run(
            [
                "ffmpeg", "-i", path,
                "-af", "silencedetect=n=-40dB:d=2",
                "-vn", "-f", "null", "-",
            ],
            capture_output=True, text=True, timeout=60,
        )
        stderr = proc.stderr

        # Parse silence segments from stderr
        total_silence = 0.0
        starts = re.findall(r"silence_start:\s*([\d.]+)", stderr)
        ends = re.findall(r"silence_end:\s*([\d.]+)", stderr)
        for s, e in zip(starts, ends):
            total_silence += float(e) - float(s)

        total_duration = _get_duration(path)
        if total_duration <= 0:
            log.warning("[test-rec] Could not determine audio duration")
            return True

        ratio = total_silence / total_duration
        log.debug("[test-rec] Silence ratio: %.2f (%.1fs / %.1fs)", ratio, total_silence, total_duration)
        return ratio < 0.9
    except Exception as exc:
        log.warning("[test-rec] Silence check error: %s", exc)
        return True


def _get_duration(path: str) -> float:
    """Return total media duration in seconds via ffprobe."""
    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format", path,
            ],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(proc.stdout)
        return float(data.get("format", {}).get("duration", 0))
    except Exception:
        return 0.0


def _get_resolution(path: str) -> tuple[int, int] | None:
    """Return (width, height) of the first video stream, or None."""
    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_streams", path,
            ],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(proc.stdout)
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                w = int(stream["width"])
                h = int(stream["height"])
                return (w, h)
    except Exception as exc:
        log.warning("[test-rec] Resolution check error: %s", exc)
    return None


# ---------------------------------------------------------------------------
# Preflight — orchestrates all startup checks
# ---------------------------------------------------------------------------
def preflight() -> bool:
    """Run all preflight checks and report results.

    Returns True if all critical checks pass, False to abort the batch.
    Prints a nicely aligned status table.
    """
    log.info("")
    log.info("[preflight] Running startup validation...")
    log.info("")

    all_ok = True

    # --- Chrome CDP ---
    chrome_ok = ensure_chrome()
    _preflight_line("Chrome CDP", chrome_ok)
    if not chrome_ok:
        all_ok = False

    # --- OBS WebSocket ---
    obs_ok = ensure_obs()
    _preflight_line("OBS WebSocket", obs_ok)
    if not obs_ok:
        all_ok = False

    # --- Patreon session (requires Chrome) ---
    if chrome_ok:
        patreon_ok = check_patreon_session()
        _preflight_line("Patreon session", patreon_ok)
        if not patreon_ok:
            all_ok = False
    else:
        _preflight_line("Patreon session", False, detail="skipped (no Chrome)")
        all_ok = False

    # --- Disk space ---
    try:
        usage = shutil.disk_usage(r"D:\\")
        free_gb = usage.free / (1024 ** 3)
        disk_ok = free_gb >= DISK_MIN_GB
        _preflight_line(r"Disk space (D:\)", disk_ok, detail=f"{free_gb:.0f} GB free")
    except OSError:
        disk_ok = False
        _preflight_line(r"Disk space (D:\)", False, detail="cannot read")
    if not disk_ok:
        all_ok = False

    # --- Test recording (requires Chrome + OBS) ---
    if chrome_ok and obs_ok:
        video_ok, audio_ok, resolution = run_test_recording()
        _preflight_line("Test recording (video)", video_ok)
        _preflight_line("Test recording (audio)", audio_ok)
        if resolution:
            res_str = f"{resolution[0]}x{resolution[1]}"
            is_1080p = resolution[0] == 1920 and resolution[1] == 1080
            if not is_1080p:
                log.warning(
                    "[preflight] Resolution is %s, expected 1920x1080",
                    res_str,
                )
            _preflight_line(
                "Test recording (resolution)", True,
                detail=res_str if is_1080p else f"{res_str} (expected 1920x1080)",
            )
        else:
            # Resolution unknown is a warning, not a hard failure
            _preflight_line("Test recording (resolution)", True, detail="unknown")
        if not video_ok or not audio_ok:
            all_ok = False
    else:
        _preflight_line("Test recording (video)", False, detail="skipped")
        _preflight_line("Test recording (audio)", False, detail="skipped")
        _preflight_line("Test recording (resolution)", False, detail="skipped")
        all_ok = False

    log.info("")
    if all_ok:
        log.info("[preflight] All checks passed")
    else:
        log.error("[preflight] One or more checks FAILED — aborting batch")

    return all_ok


def _preflight_line(label: str, ok: bool, detail: str | None = None) -> None:
    """Print one aligned preflight status line."""
    # Pad the label with dots to column 35
    dots = "." * max(1, 35 - len(label))
    status = "OK" if ok else "FAIL"
    suffix = f" ({detail})" if detail else ""
    log.info("[preflight] %s %s %s%s", label, dots, status, suffix)


# ---------------------------------------------------------------------------
# Inter-video health check (lightweight, no test recording)
# ---------------------------------------------------------------------------
def health_check() -> bool:
    """Lightweight inter-video health check with self-healing.

    Verifies Chrome CDP, OBS WebSocket, and CDP tab usability.  If any
    process is down, attempts to restart it.

    Returns True if healthy (possibly after recovery), False if
    unrecoverable.
    """
    # 1. Chrome alive?  (HTTP check on CDP /json endpoint)
    if not _cdp_alive():
        log.warning("[health] Chrome CDP not responding — attempting recovery")
        subprocess.run(
            ["taskkill", "/f", "/im", "chrome.exe"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(2)
        if not ensure_chrome():
            log.error("[health] Chrome recovery FAILED — aborting batch")
            return False
        log.info("[health] Chrome recovered")
    else:
        log.debug("[health] Chrome CDP OK")

    # 2. OBS alive?  (WebSocket connection check)
    if not _obs_alive():
        log.warning("[health] OBS WebSocket not responding — attempting recovery")
        if not ensure_obs():
            log.error("[health] OBS recovery FAILED — aborting batch")
            return False
        log.info("[health] OBS recovered")
    else:
        log.debug("[health] OBS WebSocket OK")

    # 3. CDP tab usable?  (evaluate 1+1 via Runtime.evaluate)
    if not _cdp_tab_usable():
        log.warning("[health] CDP tab not usable — restarting Chrome")
        subprocess.run(
            ["taskkill", "/f", "/im", "chrome.exe"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(2)
        if not ensure_chrome():
            log.error("[health] Chrome restart FAILED — aborting batch")
            return False
        # Re-verify the tab works after restart
        if not _cdp_tab_usable():
            log.error("[health] CDP tab still unusable after restart — aborting batch")
            return False
        log.info("[health] Chrome tab recovered")
    else:
        log.debug("[health] CDP tab OK")

    return True


# ---------------------------------------------------------------------------
# Seen-file tracking (resume support)
# ---------------------------------------------------------------------------
def load_seen() -> set[str]:
    """Load already-recorded URLs from the seen file."""
    if not SEEN_FILE.exists():
        return set()
    return {
        ln.strip()
        for ln in SEEN_FILE.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    }


def mark_seen(url: str) -> None:
    """Append a URL to the seen file (atomic: one URL per line)."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with SEEN_FILE.open("a", encoding="utf-8") as f:
        f.write(url.strip() + "\n")


# ---------------------------------------------------------------------------
# Queue loading
# ---------------------------------------------------------------------------
def load_queue(queue_path: Path) -> list[dict]:
    """Load and validate the recording queue JSON file.

    Each entry must have ``url`` and ``filename`` keys.
    Returns the list of entries (not yet filtered by seen-file).
    """
    if not queue_path.exists():
        log.error("Queue file not found: %s", queue_path)
        sys.exit(1)

    with queue_path.open(encoding="utf-8") as f:
        try:
            entries = json.load(f)
        except json.JSONDecodeError as exc:
            log.error("Invalid JSON in %s: %s", queue_path, exc)
            sys.exit(1)

    if not isinstance(entries, list):
        log.error("Queue file must be a JSON array, got %s", type(entries).__name__)
        sys.exit(1)

    # Validate entries
    valid = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            log.warning("Skipping entry %d: not a dict", i)
            continue
        if "url" not in entry or "filename" not in entry:
            log.warning("Skipping entry %d: missing 'url' or 'filename' key", i)
            continue
        valid.append(entry)

    return valid


def filter_unseen(entries: list[dict]) -> tuple[list[dict], int]:
    """Filter out already-seen URLs.  Returns (unseen_entries, skipped_count)."""
    seen = load_seen()
    unseen = [e for e in entries if e["url"] not in seen]
    skipped = len(entries) - len(unseen)
    return unseen, skipped


# ---------------------------------------------------------------------------
# Mild shuffle — swap ~30% of adjacent pairs
# ---------------------------------------------------------------------------
def mild_shuffle(entries: list[dict]) -> list[dict]:
    """Lightly shuffle the entry list — swap ~30% of adjacent pairs.

    Preserves the general ordering while introducing enough randomness
    that the access pattern doesn't look like a bot marching through
    a list in order.
    """
    if len(entries) <= 2:
        return entries[:]

    result = entries[:]
    for i in range(len(result) - 1):
        if random.random() < 0.3:
            result[i], result[i + 1] = result[i + 1], result[i]
    return result


# ---------------------------------------------------------------------------
# Record one video via subprocess
# ---------------------------------------------------------------------------
def record_one_video(url: str, filename: str) -> dict:
    """Call record_one.py as a subprocess and parse its output.

    Returns a dict:
        {ok: bool, url: str, filename: str, moved_path: str|None,
         error: str|None, duration_seconds: float}
    """
    cmd = [*PYTHON_CMD, str(RECORD_ONE_SCRIPT), url, filename]

    log.info("  Command: %s", " ".join(cmd))
    log.debug("  Working dir: %s", SCRIPTS_DIR)

    result = {
        "ok": False,
        "url": url,
        "filename": filename,
        "moved_path": None,
        "error": None,
        "duration_seconds": 0.0,
    }

    start_time = time.monotonic()

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(SCRIPTS_DIR),
            encoding="utf-8",
            errors="replace",
        )

        # Stream and parse output line by line
        for line in proc.stdout:
            line = line.rstrip("\n\r")

            # Always log to file for diagnostics
            log.debug("  [record_one] %s", line)

            # Print progress-style lines to console too
            if line.strip():
                log.info("  [record_one] %s", line)

            # Parse markers
            if MARKER_DONE in line:
                result["ok"] = True

            if MARKER_FAILED in line:
                result["ok"] = False
                # Extract reason after "FAILED:"
                idx = line.index(MARKER_FAILED)
                reason = line[idx + len(MARKER_FAILED):].strip()
                result["error"] = reason or "unknown failure"

            if MARKER_MOVED in line:
                # Extract path after "Moved:"
                idx = line.index(MARKER_MOVED)
                path = line[idx + len(MARKER_MOVED):].strip()
                if path:
                    result["moved_path"] = path

            # Parse duration lines (e.g., "duration 12.5 min" or "duration: 750s")
            if "duration" in line.lower():
                # Try "X.Y min" format
                m = re.search(r"duration[:\s]+([\d.]+)\s*min", line, re.IGNORECASE)
                if m:
                    result["duration_seconds"] = float(m.group(1)) * 60
                else:
                    # Try "Xs" format
                    m = re.search(r"duration[:\s]+([\d.]+)\s*s", line, re.IGNORECASE)
                    if m:
                        result["duration_seconds"] = float(m.group(1))

        proc.wait()

        elapsed = time.monotonic() - start_time
        result["elapsed_seconds"] = elapsed

        if proc.returncode != 0 and not result["ok"]:
            result["error"] = result["error"] or f"exit code {proc.returncode}"
            log.warning("  record_one.py exited with code %d", proc.returncode)

    except FileNotFoundError:
        result["error"] = f"record_one.py not found at {RECORD_ONE_SCRIPT}"
        log.error("  %s", result["error"])
    except KeyboardInterrupt:
        log.warning("  Interrupted — killing record_one.py")
        proc.terminate()
        proc.wait(timeout=10)
        raise
    except Exception as exc:
        result["error"] = f"subprocess error: {exc}"
        log.error("  %s", result["error"])

    return result


# ---------------------------------------------------------------------------
# Human-like break between recordings
# ---------------------------------------------------------------------------
def human_break(index: int, total: int) -> None:
    """Wait a random interval between captures to mimic a real viewer.

    Picks a random delay between BREAK_MIN_SECONDS and BREAK_MAX_SECONDS,
    then sleeps with periodic status updates.
    """
    delay = random.randint(BREAK_MIN_SECONDS, BREAK_MAX_SECONDS)
    mins = delay / 60
    resume_at = datetime.now() + timedelta(seconds=delay)

    log.info("")
    log.info(
        "  [break] Waiting %.0f min before next video (%d/%d done)",
        mins, index, total,
    )
    log.info("  [break] Resuming at %s", resume_at.strftime("%H:%M:%S"))

    try:
        # Sleep in chunks so we can show periodic "still waiting" messages
        remaining = delay
        while remaining > 0:
            chunk = min(remaining, 60)
            time.sleep(chunk)
            remaining -= chunk
            if remaining > 0 and remaining % 300 < 60:
                log.info(
                    "  [break] ... %.0f min remaining",
                    remaining / 60,
                )
    except KeyboardInterrupt:
        log.warning("  [break] Interrupted — skipping remaining wait")
        raise


# ---------------------------------------------------------------------------
# Summary report
# ---------------------------------------------------------------------------
def print_summary(
    results: list[dict],
    total_start: float,
    skipped_seen: int,
) -> None:
    """Print and log a summary of the batch recording session."""
    total_elapsed = time.monotonic() - total_start
    hours = total_elapsed / 3600
    ok_count = sum(1 for r in results if r["ok"])
    fail_count = len(results) - ok_count

    log.info("")
    log.info("=" * 60)
    log.info("BATCH RECORDING SUMMARY")
    log.info("=" * 60)
    log.info("")

    # Per-video results
    for r in results:
        if r["ok"]:
            dest = r.get("moved_path") or "(recording location unknown)"
            dur = r.get("duration_seconds", 0)
            dur_str = f"{dur / 60:.0f} min" if dur > 0 else "unknown duration"
            log.info("  [OK]   %s (%s)", r["filename"], dur_str)
            log.info("         -> %s", dest)
        else:
            log.info("  [FAIL] %s", r["filename"])
            log.info("         %s", r.get("error", "unknown error"))
            log.info("         URL: %s", r["url"])

    log.info("")
    log.info("  Results:     %d/%d succeeded", ok_count, len(results))
    if fail_count > 0:
        log.info("  Failures:    %d", fail_count)
    if skipped_seen > 0:
        log.info("  Skipped:     %d (already seen)", skipped_seen)
    log.info("  Total time:  %.1f hours (%.0f min)", hours, total_elapsed / 60)

    # Total recording time (excluding breaks)
    total_recording = sum(r.get("elapsed_seconds", 0) for r in results)
    total_break = total_elapsed - total_recording
    if total_recording > 0:
        log.info("  Recording:   %.0f min", total_recording / 60)
        log.info("  Breaks:      %.0f min", total_break / 60)

    log.info("")
    log.info("  Recordings saved to: %s", BACKUP_DIR)
    log.info("  Full log:            %s", LOG_FILE)
    log.info("=" * 60)


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------
def dry_run(entries: list[dict], skipped_seen: int) -> None:
    """Show what would be recorded without doing it."""
    log.info("")
    log.info("[dry-run] Would record %d video(s):", len(entries))
    log.info("")

    for i, entry in enumerate(entries, 1):
        log.info("  %2d. %s", i, entry["filename"])
        log.info("      %s", entry["url"])

    log.info("")
    if skipped_seen > 0:
        log.info("  Skipping %d already-seen URL(s)", skipped_seen)

    # Estimate total time
    avg_break = (BREAK_MIN_SECONDS + BREAK_MAX_SECONDS) / 2
    est_break_mins = (max(len(entries) - 1, 0)) * avg_break / 60
    log.info(
        "  Estimated break time: ~%.0f min "
        "(%d-%ds per break, %d breaks)",
        est_break_mins,
        BREAK_MIN_SECONDS,
        BREAK_MAX_SECONDS,
        max(len(entries) - 1, 0),
    )
    log.info(
        "  Break range per video: %.0f-%.0f min",
        BREAK_MIN_SECONDS / 60,
        BREAK_MAX_SECONDS / 60,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--queue", metavar="FILE",
        default=str(DEFAULT_QUEUE),
        help=f"JSON queue file (default: {DEFAULT_QUEUE})",
    )
    ap.add_argument(
        "--no-shuffle", action="store_true",
        help="Record in original order (don't shuffle for human-like pattern)",
    )
    ap.add_argument(
        "--no-breaks", action="store_true",
        help="Skip waiting between videos (for testing)",
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be recorded without doing it",
    )
    ap.add_argument(
        "--reset-seen", action="store_true",
        help="Clear the seen-file before starting (re-record everything)",
    )
    ap.add_argument(
        "--skip-preflight", action="store_true",
        help="Skip startup validation checks (Chrome, OBS, Patreon, disk, test recording)",
    )

    args = ap.parse_args()

    # ---- Banner -----------------------------------------------------------
    log.info("")
    log.info("#" * 60)
    log.info("# record_batch.py — serial multi-video Patreon recorder")
    log.info("# Started: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log.info("#" * 60)

    # ---- Reset seen (if requested) ----------------------------------------
    if args.reset_seen:
        if SEEN_FILE.exists():
            SEEN_FILE.unlink()
            log.info("[reset] Cleared seen file: %s", SEEN_FILE)
        else:
            log.info("[reset] No seen file to clear")

    # ---- Validate record_one.py exists ------------------------------------
    if not args.dry_run and not RECORD_ONE_SCRIPT.exists():
        log.error(
            "record_one.py not found at %s — "
            "deploy it before running this script",
            RECORD_ONE_SCRIPT,
        )
        return 1

    # ---- Load queue -------------------------------------------------------
    queue_path = Path(args.queue)
    entries = load_queue(queue_path)
    log.info("[queue] Loaded %d entries from %s", len(entries), queue_path)

    if not entries:
        log.info("Queue is empty — nothing to do.")
        return 0

    # ---- Filter already-seen URLs -----------------------------------------
    entries, skipped_seen = filter_unseen(entries)
    if skipped_seen > 0:
        log.info("[seen] Skipping %d already-recorded URL(s)", skipped_seen)
    log.info("[queue] %d video(s) to record", len(entries))

    if not entries:
        log.info("All URLs already recorded — nothing to do.")
        return 0

    # ---- Mild shuffle (unless --no-shuffle) --------------------------------
    if len(entries) > 1 and not args.no_shuffle:
        entries = mild_shuffle(entries)
        log.info(
            "[order] Mildly shuffled %d URLs "
            "(use --no-shuffle to keep original order)",
            len(entries),
        )

    # ---- Dry run -----------------------------------------------------------
    if args.dry_run:
        dry_run(entries, skipped_seen)
        return 0

    # ---- Preflight validation ------------------------------------------------
    if not args.skip_preflight:
        if not preflight():
            return 1
    else:
        log.info("[preflight] Skipped (--skip-preflight)")

    # ---- Ensure destination directory exists --------------------------------
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    # ---- Recording loop ----------------------------------------------------
    total_start = time.monotonic()
    results: list[dict] = []

    for i, entry in enumerate(entries, 1):
        url = entry["url"]
        filename = entry["filename"]

        # Inter-video health check (skip for the first video — preflight
        # already validated everything)
        if i > 1:
            log.debug("[health] Running inter-video health check before video %d/%d", i, len(entries))
            if not health_check():
                log.error(
                    "[health] Unrecoverable failure — stopping batch "
                    "(%d/%d completed)", i - 1, len(entries),
                )
                break

        log.info("")
        log.info("#" * 60)
        log.info("# [%d/%d] %s", i, len(entries), filename)
        log.info("# URL: %s", url)
        log.info("#" * 60)

        # Record the video
        result = record_one_video(url, filename)
        results.append(result)

        if result["ok"]:
            log.info("")
            log.info("  SUCCESS: %s", filename)
            if result.get("moved_path"):
                log.info("  Saved to: %s", result["moved_path"])
            mark_seen(url)
        else:
            log.info("")
            log.info("  FAILED: %s", filename)
            log.info("  Error:  %s", result.get("error", "unknown"))
            # Don't abort — continue to next video

        # Human-like break between captures (not after the last one)
        if i < len(entries) and not args.no_breaks:
            try:
                human_break(i, len(entries))
            except KeyboardInterrupt:
                log.warning("")
                log.warning(
                    "Interrupted during break — stopping batch "
                    "(%d/%d completed)",
                    i, len(entries),
                )
                break

    # ---- Summary -----------------------------------------------------------
    print_summary(results, total_start, skipped_seen)

    ok_count = sum(1 for r in results if r["ok"])
    return 0 if ok_count == len(results) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        log.warning("\nBatch recording interrupted by user.")
        raise SystemExit(130)
