from __future__ import annotations

import logging

import aiosqlite

from web.lifecycle import StepStatus
from web.services.catalog_service import CatalogService
from web.services.event_bus import EventBus
from web.services.obs_client import ObsClient

log = logging.getLogger(__name__)


class PipelineService:
    def __init__(
        self, db: aiosqlite.Connection, obs_client: ObsClient, event_bus: EventBus,
    ) -> None:
        self._db = db
        self._obs_client = obs_client
        self._event_bus = event_bus

    async def run(self, post_ids: list[str], steps: list[str] | None = None) -> dict:
        posts = []
        for post_id in post_ids:
            cursor = await self._db.execute(
                "SELECT post_id, url, title, post_type FROM posts WHERE post_id = ?",
                (post_id,),
            )
            row = await cursor.fetchone()
            if row:
                from src.sources.base import title_to_filename
                posts.append({
                    "post_id": row[0],
                    "url": row[1],
                    "title": row[2],
                    "filename": title_to_filename(row[2]),
                    "post_type": row[3] or "",
                })

        return await self._obs_client.run_pipeline(posts, steps)

    async def get_status(self) -> dict:
        status = await self._obs_client.get_status()
        return status.get("pipeline", {})

    async def handle_event(self, event: dict) -> None:
        event_type = event.get("type", "")
        post_id = event.get("post_id", "")
        step = event.get("step", "")

        if not post_id:
            return

        catalog_svc = CatalogService(self._db)

        if event_type == "step_started" and step:
            await catalog_svc.update_step_status(
                post_id, step, StepStatus.RUNNING,
                started_at=event.get("timestamp"),
            )
        elif event_type == "step_completed" and step:
            await catalog_svc.update_step_status(
                post_id, step, StepStatus.COMPLETED,
                completed_at=event.get("timestamp"),
                output_path=event.get("output_path"),
                duration_seconds=event.get("duration_seconds"),
            )
        elif event_type == "step_failed" and step:
            await catalog_svc.update_step_status(
                post_id, step, StepStatus.FAILED,
                completed_at=event.get("timestamp"),
                error=event.get("error"),
                duration_seconds=event.get("duration_seconds"),
            )
        elif event_type == "pipeline_complete":
            await self._db.execute(
                "UPDATE queue SET status = 'done', completed_at = datetime('now') "
                "WHERE post_id = ? AND status = 'processing'",
                (post_id,),
            )
            await self._db.commit()
