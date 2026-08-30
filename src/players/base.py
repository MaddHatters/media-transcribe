"""Player handler protocol and detection result dataclass."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable, TYPE_CHECKING

if TYPE_CHECKING:
    from src.cdp import CDPClient


@dataclass
class DetectionResult:
    player: str | None
    element: str | None
    meta: dict = field(default_factory=dict)


@runtime_checkable
class PlayerHandler(Protocol):
    name: str

    async def get_duration(self, cdp: CDPClient, detection: DetectionResult) -> float: ...
    async def play(self, cdp: CDPClient, detection: DetectionResult) -> None: ...
    async def pause(self, cdp: CDPClient, detection: DetectionResult) -> None: ...
    async def seek(self, cdp: CDPClient, position: float) -> None: ...
    async def fullscreen(self, cdp: CDPClient, detection: DetectionResult) -> bool: ...
    async def get_position(self, cdp: CDPClient) -> float: ...
    async def is_ended(self, cdp: CDPClient) -> bool: ...
    async def unmute(self, cdp: CDPClient) -> None: ...
