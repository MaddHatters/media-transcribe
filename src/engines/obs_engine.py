"""OBS Studio capture engine via obsws-python WebSocket."""
from __future__ import annotations

import logging
import os
import shutil
import time
from pathlib import Path

from src.config import OBS_HOST, OBS_PORT, OBS_PASSWORD, BACKUP_DIR
from src.engines.base import EngineStatus

log = logging.getLogger(__name__)


class OBSEngine:
    name = "obs"

    def __init__(
        self,
        host: str = OBS_HOST,
        port: int = OBS_PORT,
        password: str = OBS_PASSWORD,
        backup_dir: Path = BACKUP_DIR,
    ):
        self._host = host
        self._port = port
        self._password = password
        self._backup_dir = backup_dir
        self._client = None
        self._recording = False
        self._output_path: str | None = None

    def connect(self) -> None:
        import obsws_python as obs
        self._client = obs.ReqClient(
            host=self._host,
            port=self._port,
            password=self._password,
            timeout=10,
        )

    def disconnect(self) -> None:
        if self._client:
            self._client.base_client.ws.close()
            self._client = None

    def start(self, filename: str) -> None:
        if not self._client:
            self.connect()
        self._client.set_profile_parameter(
            "Output", "FilenameFormatting", filename,
        )
        self._client.start_record()
        self._recording = True
        time.sleep(2)

    def stop(self) -> str | None:
        if not self._client:
            return None
        resp = self._client.stop_record()
        self._recording = False
        self._output_path = getattr(resp, "output_path", None)
        return self._output_path

    def is_recording(self) -> bool:
        if self._client:
            try:
                return self._client.get_record_status().output_active
            except Exception:
                pass
        return self._recording

    def get_status(self) -> EngineStatus:
        return EngineStatus(
            recording=self.is_recording(),
            output_path=self._output_path,
        )

    def get_screenshot(self, source: str = "Window Capture") -> str | None:
        if not self._client:
            return None
        try:
            resp = self._client.get_source_screenshot(
                source, "png", 1920, 1080, 85,
            )
            return getattr(resp, "image_data", None)
        except Exception:
            return None

    def move_to_backup(self, src_path: str, filename: str) -> str | None:
        """Move recording to backup dir with retry for WinError 32."""
        if not src_path or not os.path.isfile(src_path):
            return None

        ext = os.path.splitext(src_path)[1] or ".mp4"
        dest = str(self._backup_dir / f"{filename}{ext}")
        self._backup_dir.mkdir(parents=True, exist_ok=True)

        for attempt in range(6):
            try:
                shutil.move(src_path, dest)
                size_mb = os.path.getsize(dest) / (1024 * 1024)
                log.info("Moved: %s (%.1f MB)", dest, size_mb)
                return dest
            except PermissionError:
                if attempt < 5:
                    log.warning(
                        "File locked, retrying in 5s... (%d/6)", attempt + 1,
                    )
                    time.sleep(5)
                else:
                    log.error("Could not move after 6 attempts: %s", src_path)

        return src_path
