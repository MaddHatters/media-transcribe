"""Test source — local video files, no authentication needed."""
from __future__ import annotations

from typing import TYPE_CHECKING

from src.sources.base import Post

if TYPE_CHECKING:
    from src.cdp import CDPClient


class TestSource:
    name = "test"

    async def authenticate(self, cdp: CDPClient) -> bool:
        return True

    async def get_posts(self, cdp: CDPClient, query: str | None = None) -> list[Post]:
        return []

    async def navigate_to(self, cdp: CDPClient, url: str) -> None:
        await cdp.navigate(url, wait=10.0)
