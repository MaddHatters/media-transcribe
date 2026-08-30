"""Null capture engine — testing stub that records nothing."""
from __future__ import annotations

from src.engines.base import EngineStatus


class NullEngine:
    name = "null"

    def __init__(self):
        self._recording = False
        self._filename: str | None = None

    def start(self, filename: str) -> None:
        self._recording = True
        self._filename = filename

    def stop(self) -> str | None:
        self._recording = False
        path = f"/tmp/{self._filename}.mp4" if self._filename else None
        self._filename = None
        return path

    def is_recording(self) -> bool:
        return self._recording

    def get_status(self) -> EngineStatus:
        return EngineStatus(recording=self._recording)
