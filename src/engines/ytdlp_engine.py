"""yt-dlp capture engine — direct download, no screen recording."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from src.engines.base import EngineStatus

log = logging.getLogger(__name__)


class YtDlpEngine:
    name = "ytdlp"

    def __init__(self, output_dir: Path | str = "."):
        self._output_dir = Path(output_dir)
        self._proc: subprocess.Popen | None = None
        self._output_path: str | None = None
        self._url: str | None = None

    def set_url(self, url: str) -> None:
        self._url = url

    def start(self, filename: str) -> None:
        if not self._url:
            raise ValueError("URL not set — call set_url() before start()")
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._output_path = str(self._output_dir / f"{filename}.%(ext)s")
        cmd = [
            "uvx", "yt-dlp",
            self._url,
            "-o", self._output_path,
            "--no-playlist",
        ]
        log.info("Starting yt-dlp: %s", " ".join(cmd))
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except FileNotFoundError:
            raise RuntimeError(
                "yt-dlp not found — install via 'pip install yt-dlp' or ensure 'uvx' is on PATH"
            )

    def stop(self) -> str | None:
        if not self._proc:
            return None
        self._proc.wait()
        if self._proc.returncode != 0:
            log.error("yt-dlp exited with code %d", self._proc.returncode)
            return None
        if self._output_path:
            base = self._output_path.replace(".%(ext)s", "")
            parent = Path(base).parent
            stem = Path(base).name
            for f in parent.iterdir():
                if f.stem == stem or f.name.startswith(stem):
                    return str(f)
        return self._output_path

    def is_recording(self) -> bool:
        if self._proc:
            return self._proc.poll() is None
        return False

    def get_status(self) -> EngineStatus:
        return EngineStatus(
            recording=self.is_recording(),
            output_path=self._output_path,
        )
