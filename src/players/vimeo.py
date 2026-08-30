"""VimeoPlayer handler — Vimeo iframe with Player.js SDK."""
from __future__ import annotations


VIMEO_SDK_URL = "https://player.vimeo.com/api/player.js"


class VimeoPlayer:
    name = "vimeo"

    async def play(self, cdp, detection) -> None:
        await cdp.js(
            "(function() {"
            "  if (!document.querySelector('script[src*=\"vimeo\"]')) {"
            "    var s = document.createElement('script');"
            f"    s.src = '{VIMEO_SDK_URL}';"
            "    document.head.appendChild(s);"
            "  }"
            "})()"
        )
        await cdp.js(
            "(function() {"
            "  const iframe = document.querySelector(\"iframe[src*='vimeo']\");"
            "  window.__p = new Vimeo.Player(iframe);"
            "  window.__ended = false;"
            "  window.__p.on('ended', () => { window.__ended = true; });"
            "})()"
        )
        await cdp.js("window.__p.play()")

    async def pause(self, cdp, detection) -> None:
        await cdp.js("window.__p.pause()")

    async def get_duration(self, cdp, detection) -> float:
        return await cdp.js("window.__p.getDuration()")

    async def get_position(self, cdp) -> float:
        return await cdp.js("window.__p.getCurrentTime()")

    async def seek(self, cdp, position: float) -> None:
        await cdp.js(f"window.__p.setCurrentTime({position})")

    async def fullscreen(self, cdp, detection) -> bool:
        r = await cdp.js(
            "(function() {"
            "  var el = document.querySelector(\"iframe[src*='vimeo']\");"
            "  if (el) { el.requestFullscreen(); return true; }"
            "  return false;"
            "})()"
        )
        return bool(r)

    async def unmute(self, cdp) -> None:
        await cdp.js("window.__p.setVolume(1.0)")

    async def is_ended(self, cdp) -> bool:
        return await cdp.js("window.__ended")
