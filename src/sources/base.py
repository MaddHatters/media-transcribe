"""Content source protocol and Post dataclass."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable, TYPE_CHECKING

if TYPE_CHECKING:
    from src.cdp import CDPClient


def title_to_filename(title: str) -> str:
    bad = '<>:"/\\|?*'
    cleaned = "".join("_" if c in bad else c for c in title).strip()
    return cleaned if cleaned.strip("_ ") else "episode"


@dataclass
class Post:
    url: str
    title: str
    filename: str = ""
    post_type: str = ""
    player_type: str | None = None
    duration: float | None = None
    recorded: bool = False
    meta: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.filename:
            self.filename = title_to_filename(self.title)


@runtime_checkable
class Source(Protocol):
    name: str

    async def authenticate(self, cdp: CDPClient) -> bool: ...
    async def get_posts(self, cdp: CDPClient, query: str | None = None) -> list[Post]: ...
    async def navigate_to(self, cdp: CDPClient, url: str) -> None: ...
