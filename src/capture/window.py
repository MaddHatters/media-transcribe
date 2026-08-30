"""Win32 window management — platform-conditional, ctypes-based."""
from __future__ import annotations

import logging
import time

from src.config import IS_WINDOWS

log = logging.getLogger(__name__)


def _focus_chrome_win32() -> bool:
    """Internal: focus Chrome via Win32 API."""
    import ctypes
    user32 = ctypes.windll.user32

    user32.keybd_event(0x5B, 0, 0, 0)
    user32.keybd_event(0x44, 0, 0, 0)
    user32.keybd_event(0x44, 0, 2, 0)
    user32.keybd_event(0x5B, 0, 2, 0)
    time.sleep(1)

    hwnd = user32.FindWindowW("Chrome_WidgetWin_1", None)
    if hwnd:
        user32.ShowWindow(hwnd, 3)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.5)
        return True

    log.warning("Chrome window not found")
    return False


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
