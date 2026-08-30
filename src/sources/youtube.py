"""YouTube content source — catalog via yt-dlp, no auth needed."""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from typing import TYPE_CHECKING

from src.sources.base import Post

if TYPE_CHECKING:
    from src.cdp import CDPClient

log = logging.getLogger(__name__)


class YouTubeSource:
    name = "youtube"

    async def authenticate(self, cdp: CDPClient) -> bool:
        return True

    async def get_posts(self, cdp: CDPClient, query: str | None = None) -> list[Post]:
        if not query:
            return []
        try:
            proc = await asyncio.to_thread(
                subprocess.run,
                ["uvx", "yt-dlp", "--flat-playlist", "-J", query],
                capture_output=True, text=True, timeout=60,
            )
            if proc.returncode != 0:
                log.error("yt-dlp failed: %s", proc.stderr[:200])
                return []
            data = json.loads(proc.stdout)
            entries = data.get("entries", [data]) if "entries" in data else [data]
            return [
                Post(
                    url=e.get("webpage_url") or e.get("url", ""),
                    title=e.get("title", "Untitled"),
                    duration=e.get("duration"),
                    player_type="youtube",
                )
                for e in entries
                if e.get("webpage_url") or e.get("url")
            ]
        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as exc:
            log.error("yt-dlp catalog error: %s", exc)
            return []

    async def navigate_to(self, cdp: CDPClient, url: str) -> None:
        await cdp.navigate(url, wait=8.0)
