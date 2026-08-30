"""Batch orchestrator — multi-video recording with scheduling and tracking."""
from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from src.config import STATE_DIR, BREAK_MIN_SECONDS, BREAK_MAX_SECONDS

if TYPE_CHECKING:
    from src.capture.recorder import Recorder
    from src.capture.preflight import Preflight
    from src.cdp import CDPClient

log = logging.getLogger(__name__)

SEEN_FILE = STATE_DIR / "seen_urls.txt"


@dataclass
class BatchConfig:
    queue_path: Path = STATE_DIR / "record_queue.json"
    shuffle: bool = True
    breaks: bool = True
    skip_preflight: bool = False
    seen_file: Path = SEEN_FILE


def load_queue(queue_path: Path) -> list[dict]:
    if not queue_path.exists():
        raise FileNotFoundError(f"Queue file not found: {queue_path}")

    with queue_path.open(encoding="utf-8") as f:
        entries = json.load(f)

    if not isinstance(entries, list):
        raise ValueError(f"Queue must be a JSON array, got {type(entries).__name__}")

    valid = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            log.warning("Skipping entry %d: not a dict", i)
            continue
        if "url" not in entry or "filename" not in entry:
            log.warning("Skipping entry %d: missing 'url' or 'filename'", i)
            continue
        valid.append(entry)

    return valid


def load_seen(seen_file: Path = SEEN_FILE) -> set[str]:
    if not seen_file.exists():
        return set()
    return {
        ln.strip()
        for ln in seen_file.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    }


def mark_seen(url: str, seen_file: Path = SEEN_FILE) -> None:
    seen_file.parent.mkdir(parents=True, exist_ok=True)
    with seen_file.open("a", encoding="utf-8") as f:
        f.write(url.strip() + "\n")


def filter_unseen(
    entries: list[dict], seen_file: Path = SEEN_FILE,
) -> tuple[list[dict], int]:
    seen = load_seen(seen_file)
    unseen = [e for e in entries if e["url"] not in seen]
    return unseen, len(entries) - len(unseen)


def mild_shuffle(entries: list[dict]) -> list[dict]:
    """Swap ~30% of adjacent pairs to avoid bot-like sequential access."""
    if len(entries) <= 2:
        return entries[:]
    result = entries[:]
    for i in range(len(result) - 1):
        if random.random() < 0.3:
            result[i], result[i + 1] = result[i + 1], result[i]
    return result


def human_break(index: int, total: int) -> float:
    delay = random.randint(BREAK_MIN_SECONDS, BREAK_MAX_SECONDS)
    resume_at = datetime.now() + timedelta(seconds=delay)
    log.info(
        "[break] Waiting %.0f min (%d/%d done, resume at %s)",
        delay / 60, index, total,
        resume_at.strftime("%H:%M:%S"),
    )

    elapsed = 0
    while elapsed < delay:
        chunk = min(delay - elapsed, 60)
        time.sleep(chunk)
        elapsed += chunk
        remaining = delay - elapsed
        if remaining > 0 and elapsed % 300 == 0:
            log.info("[break] ... %.0f min remaining", remaining / 60)

    return float(delay)


def print_summary(
    results: list[dict],
    total_start: float,
    skipped_seen: int,
) -> dict:
    total_elapsed = time.monotonic() - total_start
    ok_count = sum(1 for r in results if r.get("ok"))
    fail_count = len(results) - ok_count

    log.info("=" * 60)
    log.info("BATCH RECORDING SUMMARY")
    log.info("  Results:  %d/%d succeeded", ok_count, len(results))
    if fail_count > 0:
        log.info("  Failures: %d", fail_count)
    if skipped_seen > 0:
        log.info("  Skipped:  %d (already seen)", skipped_seen)
    log.info("  Time:     %.1f hours", total_elapsed / 3600)
    log.info("=" * 60)

    return {
        "total": len(results),
        "ok": ok_count,
        "failed": fail_count,
        "skipped_seen": skipped_seen,
        "elapsed_seconds": total_elapsed,
    }


class BatchOrchestrator:
    """Multi-video recording orchestrator.

    Composes Preflight -> queue loading -> seen filtering -> shuffle ->
    recording loop -> health checks -> breaks -> summary.
    """

    def __init__(
        self,
        recorder: Recorder,
        preflight: Preflight | None = None,
    ):
        self.recorder = recorder
        self.preflight = preflight

    async def run(
        self,
        cdp: CDPClient,
        config: BatchConfig | None = None,
    ) -> dict:
        config = config or BatchConfig()

        if not config.skip_preflight and self.preflight:
            ok, gates = self.preflight.run_all()
            if not ok:
                log.error("Preflight failed — aborting batch")
                return {
                    "aborted": True,
                    "gates": [{"name": g.name, "passed": g.passed} for g in gates],
                }

        entries = load_queue(config.queue_path)
        entries, skipped_seen = filter_unseen(entries, config.seen_file)

        if not entries:
            log.info("No unseen entries in queue")
            return {"total": 0, "ok": 0, "failed": 0, "skipped_seen": skipped_seen}

        if config.shuffle:
            entries = mild_shuffle(entries)

        log.info("Batch: %d entries to record (%d already seen)", len(entries), skipped_seen)

        results: list[dict] = []
        total_start = time.monotonic()

        for i, entry in enumerate(entries):
            url = entry["url"]
            filename = entry["filename"]

            log.info("Recording %d/%d: %s", i + 1, len(entries), filename)
            result = await self.recorder.record_one(cdp, url, filename)
            results.append({
                "ok": result.ok,
                "filename": filename,
                "error": result.error,
            })

            if result.ok:
                mark_seen(url, config.seen_file)

            if i < len(entries) - 1:
                self._health_check()

                if config.breaks:
                    human_break(i + 1, len(entries))

        return print_summary(results, total_start, skipped_seen)

    def _health_check(self) -> None:
        if not self.preflight:
            return
        chrome_ok = self.preflight._ensure_chrome()
        if not chrome_ok:
            log.warning("[health] Chrome CDP lost — attempting recovery")
        obs_ok = self.preflight._ensure_obs()
        if not obs_ok:
            log.warning("[health] OBS WebSocket lost — attempting recovery")
