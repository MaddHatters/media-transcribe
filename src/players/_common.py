"""Shared fullscreen TAC trick logic for video-element-based players."""
from __future__ import annotations

import asyncio
import json


async def video_fullscreen(cdp, video_selector: str = "document.querySelector('video')") -> bool:
    """TAC trick fullscreen with 3 retries + F11 fallback."""

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
        return bool(await cdp.js("!!document.fullscreenElement"))

    for _ in range(3):
        if await _tac_trick():
            return True
        await asyncio.sleep(2)

    await cdp.key("F11", "F11")
    await asyncio.sleep(2)
    if await _tac_trick():
        return True
    return False
