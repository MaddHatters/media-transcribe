"""Capture engine protocol — abstracts the recording mechanism."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class EngineStatus:
    recording: bool = False
    output_path: str | None = None
    duration_seconds: float = 0.0
    extra: dict = field(default_factory=dict)


@runtime_checkable
class CaptureEngine(Protocol):
    name: str

    def start(self, filename: str) -> None: ...
    def stop(self) -> str | None: ...
    def is_recording(self) -> bool: ...
    def get_status(self) -> EngineStatus: ...
