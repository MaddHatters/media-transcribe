"""Autonomous content discovery + recording loop."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.sources.discovery import DiscoveredPost

log = logging.getLogger(__name__)

MIN_INTERVAL_HOURS = 12.0


class ContentWatcher:
    def __init__(
        self,
        source: str,
        interval_hours: float,
        steps: list[str],
        max_per_run: int = 3,
        dry_run: bool = False,
        status_dir: Path | None = None,
    ):
        self.source = source
        self.interval_hours = max(interval_hours, MIN_INTERVAL_HOURS)
        self.steps = steps
        self.max_per_run = max_per_run
        self.dry_run = dry_run

        from src.config import STATE_DIR
        self._status_dir = status_dir or STATE_DIR
        self._status_path = self._status_dir / "watch_status.json"

        self._shutdown = False
        self._sleeping = False
        self._cycle = 0
        self._total_recorded = 0
        self._started_at = datetime.now().isoformat()

    def _install_signal_handlers(self) -> None:
        def _handler(signum, frame):
            log.info("[watch] Received %s — shutting down gracefully", signal.Signals(signum).name)
            self._shutdown = True
            if self._sleeping:
                raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, _handler)
        signal.signal(signal.SIGINT, _handler)
        from src.config import IS_WINDOWS
        if IS_WINDOWS:
            signal.signal(signal.SIGBREAK, _handler)

    async def run_forever(self) -> None:
        self._install_signal_handlers()
        log.info("[watch] Starting autonomous watcher (interval=%.1fh, max_per_run=%d, dry_run=%s)",
                 self.interval_hours, self.max_per_run, self.dry_run)

        cycle_result = {"new_found": 0, "recorded": 0, "failed": 0}

        while True:
            self._cycle += 1
            log.info("[watch] Cycle %d starting at %s", self._cycle, datetime.now().isoformat())
            cycle_result = {"new_found": 0, "recorded": 0, "failed": 0}

            try:
                new_posts = await self._discover()
                cycle_result["new_found"] = len(new_posts) if new_posts else 0

                if new_posts and not self.dry_run:
                    batch = new_posts[:self.max_per_run]
                    if len(new_posts) > self.max_per_run:
                        log.info("[watch] Capping at %d (remaining saved for next cycle)", self.max_per_run)
                    ok, failed = await self._run_pipeline(batch)
                    cycle_result["recorded"] = ok
                    cycle_result["failed"] = failed
                    self._total_recorded += ok
                elif new_posts and self.dry_run:
                    log.info("[watch] Dry-run: found %d new video(s), skipping pipeline", len(new_posts))
                else:
                    log.info("[watch] No new content found")

            except Exception as exc:
                log.error("[watch] Cycle %d failed: %s", self._cycle, exc)

            next_run = datetime.now() + timedelta(hours=self.interval_hours)
            self._write_status(
                running=not self._shutdown,
                last_result=cycle_result,
                next_run=next_run.isoformat(),
            )

            if self._shutdown:
                break

            log.info("[watch] Next cycle at %s", next_run.isoformat())
            try:
                self._sleeping = True
                await asyncio.sleep(self.interval_hours * 3600)
            except (KeyboardInterrupt, asyncio.CancelledError):
                log.info("[watch] Sleep interrupted — shutting down")
                break
            finally:
                self._sleeping = False

        self._write_status(running=False, last_result=cycle_result, next_run=None)
        log.info("[watch] Watcher stopped after %d cycles (%d total recorded)",
                 self._cycle, self._total_recorded)

    async def _discover(self) -> list[DiscoveredPost]:
        from src.sources.discovery import PatreonDiscovery
        from src.catalog import CatalogManager
        from src.config import CATALOG_PATH

        discovery = PatreonDiscovery(cooldown_hours=0)
        catalog = CatalogManager(CATALOG_PATH)

        fetched = discovery.fetch_posts(media_type="video", max_pages=1)
        new_posts = discovery.diff_catalog(fetched, CATALOG_PATH)
        merged, _ = catalog.merge_discovered(fetched)
        catalog.save(merged)

        if new_posts:
            log.info("[watch] Found %d new video(s)", len(new_posts))
        return new_posts

    async def _run_pipeline(self, posts: list[DiscoveredPost]) -> tuple[int, int]:
        from src.pipeline.runner import Pipeline
        from src.engines.obs_engine import OBSEngine
        from src.sources.patreon import PatreonSource
        from src.sources.base import Post
        from src.catalog import CatalogManager
        from src.config import BACKUP_DIR, CATALOG_PATH
        from src.capture.environment import EnvironmentManager
        from src.capture.preflight import Preflight

        env = EnvironmentManager()
        env_ok, env_messages = env.setup()
        for msg in env_messages:
            log.info("[watch] %s", msg)
        if not env_ok:
            log.error("[watch] Environment setup failed")
            return 0, len(posts)

        pf = Preflight()
        pf_ok, _ = pf.run_all()
        if not pf_ok:
            log.error("[watch] Preflight failed")
            return 0, len(posts)

        catalog = CatalogManager(CATALOG_PATH)
        engine = OBSEngine()
        source = PatreonSource()
        pipeline = Pipeline(
            source=source, engine=engine, output_dir=BACKUP_DIR,
            enable_breaks=True, preflight=pf, catalog=catalog,
        )

        post_objects = [
            Post(url=p.url, title=p.title,
                 post_type=getattr(p, "post_type", ""))
            for p in posts
        ]

        results = await pipeline.run(post_objects, steps=self.steps)
        ok = sum(1 for r in results if not r.steps_failed)
        failed = len(results) - ok
        log.info("[watch] Pipeline complete: %d/%d succeeded", ok, len(results))
        return ok, failed

    def _write_status(self, running: bool, last_result: dict, next_run: str | None) -> None:
        status = {
            "running": running,
            "pid": os.getpid(),
            "cycle": self._cycle,
            "last_run": datetime.now().isoformat(),
            "next_run": next_run,
            "last_result": last_result,
            "total_recorded": self._total_recorded,
            "started_at": self._started_at,
        }
        self._status_dir.mkdir(parents=True, exist_ok=True)
        self._status_path.write_text(
            json.dumps(status, indent=2), encoding="utf-8",
        )

    @staticmethod
    def read_status(status_dir: Path | None = None) -> dict | None:
        from src.config import STATE_DIR
        path = (status_dir or STATE_DIR) / "watch_status.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
