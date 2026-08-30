"""Cross-machine file transfer via SCP/SSH."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from src.config import SSH_HOST, SSH_OPTS

log = logging.getLogger(__name__)


class TransferClient:
    def __init__(self, host: str = SSH_HOST, ssh_opts: list[str] | None = None):
        self._host = host
        self._ssh_opts = ssh_opts if ssh_opts is not None else list(SSH_OPTS)

    def _ssh_run(self, command: str, timeout: int = 30) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["ssh", *self._ssh_opts, self._host, command],
            capture_output=True, text=True, timeout=timeout,
        )

    def upload(self, local: Path, remote: str) -> bool:
        result = subprocess.run(
            ["scp", *self._ssh_opts, str(local), f"{self._host}:{remote}"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            log.error("Upload failed: %s", result.stderr.strip()[:200])
            return False
        return True

    def download(self, remote: str, local: Path) -> Path | None:
        local.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["scp", *self._ssh_opts, f"{self._host}:{remote}", str(local)],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            log.error("Download failed: %s", result.stderr.strip()[:200])
            return None
        return local

    def sync_transcripts(
        self, remote_dir: str, local_dir: Path, force: bool = False,
    ) -> list[str]:
        """Sync transcript files from remote to local, skipping existing."""
        local_dir.mkdir(parents=True, exist_ok=True)

        result = self._ssh_run(
            f'Get-ChildItem -Path "{remote_dir}" -File -Include "*.srt","*.txt" -Name'
        )
        if result.returncode != 0:
            log.error("Could not list remote files: %s", result.stderr.strip()[:200])
            return []

        remote_files = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
        if not remote_files:
            return []

        local_existing = {f.name for f in local_dir.iterdir() if f.is_file()}
        to_transfer = remote_files if force else [f for f in remote_files if f not in local_existing]

        synced: list[str] = []
        for filename in to_transfer:
            remote_path = f"{remote_dir}{filename}"
            local_path = local_dir / filename
            dl = self.download(remote_path, local_path)
            if dl:
                synced.append(filename)

        return synced
