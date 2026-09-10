"""Win32 window management — platform-conditional, ctypes-based."""
from __future__ import annotations

import logging
import time

from src.config import IS_WINDOWS

log = logging.getLogger(__name__)


def _focus_chrome_win32() -> bool:
    """Focus the largest Chrome window via Win32 API."""
    import ctypes
    import ctypes.wintypes
    user32 = ctypes.windll.user32

    # Minimize all windows first (Win+D)
    user32.keybd_event(0x5B, 0, 0, 0)
    user32.keybd_event(0x44, 0, 0, 0)
    user32.keybd_event(0x44, 0, 2, 0)
    user32.keybd_event(0x5B, 0, 2, 0)
    time.sleep(1)

    # Find ALL Chrome windows, pick the largest
    candidates = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def enum_cb(hwnd, _):
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        if cls.value == "Chrome_WidgetWin_1":
            rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            candidates.append((hwnd, w * h))
        return True

    user32.EnumWindows(enum_cb, 0)

    if not candidates:
        log.warning("Chrome window not found")
        return False

    # Pick the largest window (main browser, not dialogs)
    best_hwnd = max(candidates, key=lambda x: x[1])[0]
    user32.ShowWindow(best_hwnd, 3)  # SW_MAXIMIZE
    user32.SetForegroundWindow(best_hwnd)
    time.sleep(0.5)
    log.info("Focused Chrome (hwnd=%s, %d candidates)", best_hwnd, len(candidates))
    return True


def focus_chrome() -> bool:
    """Find and focus the Chrome window using Win32 API."""
    if not IS_WINDOWS:
        log.debug("Not Windows — focus_chrome is a no-op")
        return False
    return _focus_chrome_win32()


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
        result = [None]

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def enum_callback(hwnd, _):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            if title_contains.lower() in buf.value.lower():
                result[0] = hwnd
                return False
            return True

        user32.EnumWindows(enum_callback, 0)
        return result[0]

    return None


def clean_chrome_tabs(cdp_url: str = "http://localhost:9222") -> int:
    """Close all Chrome tabs except one. Returns number of tabs closed.

    Sync function (uses urllib, not the CDP WebSocket) — call directly from
    sync code, or via `asyncio.to_thread(clean_chrome_tabs)` from async code.
    """
    import json
    import urllib.request

    try:
        data = urllib.request.urlopen(f"{cdp_url}/json", timeout=5).read()
        targets = json.loads(data)
    except Exception as e:
        log.warning("clean_chrome_tabs: failed to list targets: %s", e)
        return 0

    pages = [t for t in targets if t.get("type") == "page"]

    if len(pages) <= 1:
        return 0

    closed = 0
    # Keep the first page, close the rest
    for page in pages[1:]:
        try:
            target_id = page["id"]
            urllib.request.urlopen(f"{cdp_url}/json/close/{target_id}", timeout=5)
            closed += 1
            log.info("Closed stale tab: %s", page.get("title", "untitled")[:60])
        except Exception as e:
            log.warning("Failed to close tab %s: %s", page.get("id"), e)

    return closed


def minimize_window(hwnd: int) -> None:
    if not IS_WINDOWS or not hwnd:
        return
    import ctypes
    ctypes.windll.user32.ShowWindow(hwnd, 6)


def maximize_window(hwnd: int) -> None:
    if not IS_WINDOWS or not hwnd:
        return
    import ctypes
    ctypes.windll.user32.ShowWindow(hwnd, 3)
