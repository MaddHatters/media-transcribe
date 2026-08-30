"""MuxPlayer handler — Mux <mux-player> with shadow DOM <video>."""
from __future__ import annotations

from src.players._common import video_fullscreen

VIDEO = "document.querySelector('video')"


class MuxPlayer:
    name = "mux"

    async def get_duration(self, cdp, detection) -> float:
        return await cdp.js(
            f"(v => (v && isFinite(v.duration)) ? v.duration : 0)({VIDEO})"
        )

    async def play(self, cdp, detection) -> None:
        await cdp.js(f"{VIDEO}.play()")

    async def pause(self, cdp, detection) -> None:
        await cdp.js(f"{VIDEO}.pause()")

    async def seek(self, cdp, position: float) -> None:
        await cdp.js(f"{VIDEO}.currentTime = {position}")

    async def fullscreen(self, cdp, detection) -> bool:
        return await video_fullscreen(cdp, VIDEO)

    async def get_position(self, cdp) -> float:
        return await cdp.js(f"{VIDEO}.currentTime")

    async def is_ended(self, cdp) -> bool:
        return await cdp.js(f"{VIDEO}.ended")

    async def unmute(self, cdp) -> None:
        await cdp.js(
            f"var v = {VIDEO}; v.muted = false; v.volume = 1.0"
        )
