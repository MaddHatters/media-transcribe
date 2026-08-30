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

POLL_INTERVAL = 30
STALL_THRESHOLD = 6


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
        focus_fn=None,
    ) -> RecordResult:
        result = RecordResult(url=url, filename=filename)

        try:
            log.info("[1/10] Navigating to %s", url)
            await cdp.js(
                "if(document.fullscreenElement) document.exitFullscreen(); 'ok'"
            )
            await asyncio.sleep(1)
            await cdp.navigate(url, wait=10.0)

            log.info("[2/10] Detecting player...")
            detection, handler = await detect_player(cdp)
            if not handler:
                result.error = f"No supported player found (detected: {detection.player})"
                log.error(result.error)
                return result

            duration = await handler.get_duration(cdp, detection)
            if not duration or duration <= 0:
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

            log.info("[3/10] Reset to 0:00 + unmute")
            await handler.pause(cdp, detection)
            await handler.seek(cdp, 0.0)
            await handler.unmute(cdp)
            await asyncio.sleep(2)

            log.info("[4/10] Entering fullscreen...")
            if focus_fn:
                focus_fn()
                await asyncio.sleep(1)

            fs = await handler.fullscreen(cdp, detection)
            if not fs:
                result.error = "Fullscreen rejected after all attempts"
                log.error(result.error)
                return result

            log.info("[5/10] Re-pause at 0:00")
            await handler.pause(cdp, detection)
            await handler.seek(cdp, 0.0)
            await handler.unmute(cdp)
            await asyncio.sleep(2)

            log.info("[6/10] Hiding cursor")
            await cdp.move_mouse(0, 0)
            await asyncio.sleep(2)

            log.info("[7/10] Starting capture engine (%s)", self.engine.name)
            await asyncio.to_thread(self.engine.start, filename)

            log.info("[8/10] Playing...")
            await handler.seek(cdp, 0.0)
            await handler.unmute(cdp)
            await handler.play(cdp, detection)
            await asyncio.sleep(3)

            await cdp.move_mouse(0, 0)

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

                await handler.unmute(cdp)

                # Pause detection — auto-resume if video paused during monitoring
                is_paused = await cdp.js(
                    "(() => { const v = document.querySelector('video');"
                    " return v ? v.paused : false; })()"
                )
                if is_paused:
                    log.warning("  PAUSED — auto-resuming")
                    await handler.play(cdp, detection)

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

            log.info("[10/10] Stopping capture")
            await asyncio.sleep(3)
            output_path = await asyncio.to_thread(self.engine.stop)
            result.output_path = output_path
            result.ok = True

            await cdp.js(
                "if(document.fullscreenElement) document.exitFullscreen(); 'ok'"
            )

        except Exception as exc:
            result.error = str(exc)
            log.error("Recording failed: %s", exc)
            if self.engine.is_recording():
                try:
                    await asyncio.to_thread(self.engine.stop)
                except Exception:
                    pass

        return result
