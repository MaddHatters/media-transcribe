"""Shared fullscreen TAC trick logic for video-element-based players."""
from __future__ import annotations

import asyncio
import json
import logging

log = logging.getLogger(__name__)


async def video_fullscreen(cdp, video_selector: str = "document.querySelector('video')") -> bool:
    """TAC trick fullscreen with 3 retries + Win32 F11 fallback."""

    async def _tac_trick() -> bool:
        await cdp.js(
            "(function() {"
            f"  var v = {video_selector};"
            "  v.addEventListener('click', function handler() {"
            "    v.requestFullscreen();"
            "    v.removeEventListener('click', handler);"
            "  }, {once: true});"
            "})()"
        )
        bbox_json = await cdp.js(
            "(function() {"
            f"  var v = {video_selector};"
            "  var r = v.getBoundingClientRect();"
            "  return JSON.stringify({x: r.x + r.width/2, y: r.y + r.height/2});"
            "})()"
        )
        bbox = json.loads(bbox_json)
        await cdp.click(bbox["x"], bbox["y"])
        await asyncio.sleep(1)
        return bool(await cdp.js("!!document.fullscreenElement"))

    # Try TAC trick 3 times
    for attempt in range(3):
        if await _tac_trick():
            return True
        await asyncio.sleep(2)

    # Fallback: Win32 F11 keypress (works when CDP key doesn't)
    from src.config import IS_WINDOWS
    if IS_WINDOWS:
        from src.capture.window import focus_chrome
        log.info("TAC trick failed, trying Win32 F11 fallback")

        focus_chrome()  # Focus the largest Chrome window
        await asyncio.sleep(1)

        import ctypes
        user32 = ctypes.windll.user32
        VK_F11 = 0x7A
        user32.keybd_event(VK_F11, 0, 0, 0)   # F11 down
        user32.keybd_event(VK_F11, 0, 2, 0)   # F11 up
        await asyncio.sleep(2)

        # Verify we're fullscreen (browser fullscreen, not element fullscreen)
        is_fs = await cdp.js("window.innerHeight >= screen.height - 10")
        if is_fs:
            log.info("Win32 F11 fullscreen succeeded")
            return True
        log.warning("Win32 F11 fallback also failed")
    else:
        # Non-Windows: try CDP F11 as before
        await cdp.key("F11", "F11")
        await asyncio.sleep(2)
        if await _tac_trick():
            return True

    return False
