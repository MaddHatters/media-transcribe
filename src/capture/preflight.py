"""Preflight validation — 7-gate startup check with auto-recovery."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from src.config import (
    CDP_URL, CHROME_PATH, CHROME_PROFILE,
    OBS_PATH, OBS_HOST, OBS_PORT, OBS_PASSWORD,
    CRED_TARGET, IS_WINDOWS,
)

if TYPE_CHECKING:
    from src.cdp import CDPClient

log = logging.getLogger(__name__)

DISK_MIN_GB = 5
PREFLIGHT_VIDEO_URL = "file:///C:/Users/Matt/agent-control/scripts/audio_test.html"


@dataclass
class GateResult:
    name: str
    passed: bool
    detail: str = ""


class Preflight:
    def __init__(self, cdp_url: str = CDP_URL):
        self._cdp_url = cdp_url

    def run_all(self) -> tuple[bool, list[GateResult]]:
        gates: list[GateResult] = []
        all_ok = True

        chrome_ok = self._ensure_chrome()
        gates.append(GateResult("Chrome CDP", chrome_ok))
        if not chrome_ok:
            all_ok = False

        obs_ok = self._ensure_obs()
        gates.append(GateResult("OBS WebSocket", obs_ok))
        if not obs_ok:
            all_ok = False

        if chrome_ok:
            patreon_ok = self._check_patreon_session()
            gates.append(GateResult("Patreon session", patreon_ok))
            if not patreon_ok:
                all_ok = False
        else:
            gates.append(GateResult("Patreon session", False, "skipped (no Chrome)"))
            all_ok = False

        disk_ok, disk_detail = self._check_disk_space()
        gates.append(GateResult("Disk space", disk_ok, disk_detail))
        if not disk_ok:
            all_ok = False

        if chrome_ok and obs_ok:
            video_ok, audio_ok, resolution = self._run_test_recording()
            gates.append(GateResult("Test recording (video)", video_ok))
            gates.append(GateResult("Test recording (audio)", audio_ok))
            res_str = f"{resolution[0]}x{resolution[1]}" if resolution else "unknown"
            gates.append(GateResult("Test recording (resolution)", True, res_str))
            if not video_ok or not audio_ok:
                all_ok = False
        else:
            for label in ("video", "audio", "resolution"):
                gates.append(GateResult(f"Test recording ({label})", False, "skipped"))
            all_ok = False

        for g in gates:
            status = "OK" if g.passed else "FAIL"
            detail = f" ({g.detail})" if g.detail else ""
            dots = "." * max(1, 35 - len(g.name))
            log.info("[preflight] %s %s %s%s", g.name, dots, status, detail)

        return all_ok, gates

    def _ensure_chrome(self) -> bool:
        try:
            data = urllib.request.urlopen(
                f"{self._cdp_url}/json", timeout=5,
            ).read()
            log.info("Chrome CDP is running")
            return True
        except Exception:
            log.warning("Chrome CDP not responding")

        if not IS_WINDOWS:
            return False

        try:
            cmd = [
                str(CHROME_PATH),
                f"--user-data-dir={CHROME_PROFILE}",
                "--remote-debugging-port=9222",
                "--start-maximized",
            ]
            subprocess.Popen(cmd)
            log.info("Launched Chrome, waiting for CDP...")
            time.sleep(5)
            urllib.request.urlopen(f"{self._cdp_url}/json", timeout=5)
            return True
        except Exception as exc:
            log.error("Chrome auto-launch failed: %s", exc)
            return False

    def _ensure_obs(self) -> bool:
        try:
            import obsws_python as obs
            client = obs.ReqClient(
                host=OBS_HOST, port=OBS_PORT,
                password=OBS_PASSWORD, timeout=5,
            )
            client.base_client.ws.close()
            log.info("OBS WebSocket is running")
            return True
        except Exception:
            log.warning("OBS WebSocket not responding")

        if not IS_WINDOWS:
            return False

        try:
            subprocess.Popen([str(OBS_PATH), "--minimize-to-tray"])
            log.info("Launched OBS, waiting for WebSocket...")
            time.sleep(8)
            import obsws_python as obs
            client = obs.ReqClient(
                host=OBS_HOST, port=OBS_PORT,
                password=OBS_PASSWORD, timeout=5,
            )
            client.base_client.ws.close()
            return True
        except Exception as exc:
            log.error("OBS auto-launch failed: %s", exc)
            return False

    def _check_patreon_session(self) -> bool:
        try:
            from src.cdp import CDPClient
            from src.sources.patreon import PatreonSource

            async def _check() -> bool:
                async with CDPClient(self._cdp_url) as cdp:
                    source = PatreonSource(cred_target=CRED_TARGET)
                    return await source.authenticate(cdp)

            return asyncio.run(_check())
        except Exception as exc:
            log.error("Patreon session check failed: %s", exc)
            return False

    def _check_disk_space(self) -> tuple[bool, str]:
        usage = shutil.disk_usage(".")
        free_gb = usage.free / (1024 ** 3)
        detail = f"{free_gb:.1f} GB free"
        if free_gb < DISK_MIN_GB:
            log.warning("Low disk space: %s", detail)
            return False, detail
        return True, detail

    def _run_test_recording(self) -> tuple[bool, bool, tuple[int, int] | None]:
        try:
            return asyncio.run(self._run_test_recording_async())
        except Exception as exc:
            log.error("[test-rec] Test recording failed: %s", exc)
            return False, False, None

    async def _run_test_recording_async(self) -> tuple[bool, bool, tuple[int, int] | None]:
        from src.cdp import CDPClient
        from src.engines.obs_engine import OBSEngine

        async with CDPClient(self._cdp_url) as cdp:
            await cdp.navigate(PREFLIGHT_VIDEO_URL, wait=8.0)

            await cdp.click(500, 400)
            await asyncio.sleep(1)

            await cdp.js(
                "(() => { const v = document.querySelector('video');"
                " if (v) { v.muted = false; v.volume = 1.0;"
                " v.play().catch(() => {}); } })()"
            )
            await asyncio.sleep(3)

        engine = OBSEngine()
        try:
            engine.connect()
            engine.start("_preflight_test")
        except Exception as exc:
            log.error("[test-rec] Failed to start OBS recording: %s", exc)
            engine.disconnect()
            return False, False, None

        await asyncio.sleep(10)

        output_path = engine.stop()
        engine.disconnect()

        async with CDPClient(self._cdp_url) as cdp:
            await cdp.navigate("about:blank", wait=0.0)

        if not output_path or not os.path.isfile(output_path):
            log.error("[test-rec] Recording file not found: %s", output_path)
            return False, False, None

        video_ok = _check_video_black(output_path)
        audio_ok = _check_audio_silence(output_path)
        resolution = _get_resolution(output_path)

        try:
            os.remove(output_path)
            log.debug("[test-rec] Deleted test file: %s", output_path)
        except OSError as exc:
            log.warning("[test-rec] Could not delete test file: %s", exc)

        return video_ok, audio_ok, resolution


def _get_media_duration(path: str) -> float:
    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format", path,
            ],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(proc.stdout)
        return float(data.get("format", {}).get("duration", 0))
    except Exception:
        return 0.0


def _check_video_black(path: str) -> bool:
    try:
        proc = subprocess.run(
            [
                "ffmpeg", "-i", path,
                "-vf", "blackdetect=d=0.5:pix_th=0.10",
                "-an", "-f", "null", "-",
            ],
            capture_output=True, text=True, timeout=60,
        )
        total_black = 0.0
        for m in re.finditer(
            r"black_start:([\d.]+)\s+black_end:([\d.]+)\s+black_duration:([\d.]+)",
            proc.stderr,
        ):
            total_black += float(m.group(3))

        total_duration = _get_media_duration(path)
        if total_duration <= 0:
            log.warning("[test-rec] Could not determine video duration")
            return True

        ratio = total_black / total_duration
        log.debug("[test-rec] Black ratio: %.2f (%.1fs / %.1fs)", ratio, total_black, total_duration)
        return ratio < 0.8
    except Exception as exc:
        log.warning("[test-rec] Black-frame check error: %s", exc)
        return True


def _check_audio_silence(path: str) -> bool:
    try:
        proc = subprocess.run(
            [
                "ffmpeg", "-i", path,
                "-af", "silencedetect=n=-40dB:d=2",
                "-vn", "-f", "null", "-",
            ],
            capture_output=True, text=True, timeout=60,
        )
        total_silence = 0.0
        starts = re.findall(r"silence_start:\s*([\d.]+)", proc.stderr)
        ends = re.findall(r"silence_end:\s*([\d.]+)", proc.stderr)
        for s, e in zip(starts, ends):
            total_silence += float(e) - float(s)

        total_duration = _get_media_duration(path)
        if total_duration <= 0:
            log.warning("[test-rec] Could not determine audio duration")
            return True

        ratio = total_silence / total_duration
        log.debug("[test-rec] Silence ratio: %.2f (%.1fs / %.1fs)", ratio, total_silence, total_duration)
        return ratio < 0.9
    except Exception as exc:
        log.warning("[test-rec] Silence check error: %s", exc)
        return True


def _get_resolution(path: str) -> tuple[int, int] | None:
    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_streams", path,
            ],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(proc.stdout)
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                w = int(stream["width"])
                h = int(stream["height"])
                return (w, h)
    except Exception as exc:
        log.warning("[test-rec] Resolution check error: %s", exc)
    return None
