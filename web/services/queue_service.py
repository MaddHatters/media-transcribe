from __future__ import annotations

import aiosqlite

from web.lifecycle import StepStatus, derive_post_status
from web.models import QueueEntry
from web.services.obs_client import ObsClient


class QueueService:
    def __init__(self, db: aiosqlite.Connection, obs_client: ObsClient) -> None:
        self._db = db
        self._obs_client = obs_client

    async def get_queue(self) -> list[QueueEntry]:
        cursor = await self._db.execute(
            "SELECT q.post_id, p.title, q.priority, q.added_at, q.status "
            "FROM queue q JOIN posts p ON q.post_id = p.post_id "
            "WHERE q.status IN ('waiting', 'processing') "
            "ORDER BY q.priority DESC, q.added_at ASC"
        )
        rows = await cursor.fetchall()
        return [
            QueueEntry(
                post_id=row[0], title=row[1], priority=row[2],
                added_at=row[3], status=row[4],
            )
            for row in rows
        ]

    async def add_to_queue(self, post_ids: list[str], priority: int = 0) -> int:
        count = 0
        for post_id in post_ids:
            result = await self._db.execute(
                "INSERT OR IGNORE INTO queue (post_id, priority, added_at, status) "
                "VALUES (?, ?, datetime('now'), 'waiting')",
                (post_id, priority),
            )
            if result.rowcount and result.rowcount > 0:
                count += 1
                await self._db.execute(
                    "UPDATE step_statuses SET status = ? WHERE post_id = ? AND step_name = 'record'",
                    (StepStatus.QUEUED.value, post_id),
                )
                await self._rederive_status(post_id)
        await self._db.commit()
        return count

    async def remove_from_queue(self, post_id: str) -> bool:
        cursor = await self._db.execute(
            "DELETE FROM queue WHERE post_id = ? AND status = 'waiting'", (post_id,),
        )
        await self._db.commit()
        removed = cursor.rowcount > 0 if cursor.rowcount else False
        if removed:
            await self._db.execute(
                "UPDATE step_statuses SET status = ? WHERE post_id = ? AND step_name = 'record'",
                (StepStatus.PENDING.value, post_id),
            )
            await self._rederive_status(post_id)
            await self._db.commit()
        return removed

    async def update_priority(self, post_id: str, priority: int) -> None:
        await self._db.execute(
            "UPDATE queue SET priority = ? WHERE post_id = ?", (priority, post_id),
        )
        await self._db.commit()

    async def reorder(self, post_ids: list[str]) -> None:
        total = len(post_ids)
        for i, post_id in enumerate(post_ids):
            await self._db.execute(
                "UPDATE queue SET priority = ? WHERE post_id = ?",
                (total - i, post_id),
            )
        await self._db.commit()

    async def start_queue(self) -> dict:
        cursor = await self._db.execute(
            "SELECT q.post_id, p.url, p.title, p.post_type "
            "FROM queue q JOIN posts p ON q.post_id = p.post_id "
            "WHERE q.status = 'waiting' "
            "ORDER BY q.priority DESC, q.added_at ASC"
        )
        rows = await cursor.fetchall()
        if not rows:
            return {"started": False, "run_id": "", "queue_size": 0, "error": "No waiting entries"}

        posts = []
        for row in rows:
            from src.sources.base import title_to_filename
            posts.append({
                "post_id": row[0],
                "url": row[1],
                "title": row[2],
                "filename": title_to_filename(row[2]),
                "post_type": row[3] or "",
            })

        result = await self._obs_client.run_pipeline(posts)

        if result.get("started"):
            for row in rows:
                await self._db.execute(
                    "UPDATE queue SET status = 'processing', started_at = datetime('now') "
                    "WHERE post_id = ?",
                    (row[0],),
                )
            await self._db.commit()

        return result

    async def pause_queue(self) -> None:
        await self._db.execute(
            "UPDATE queue SET status = 'waiting' WHERE status = 'processing'"
        )
        await self._db.commit()

    async def clear_completed(self) -> None:
        await self._db.execute(
            "DELETE FROM queue WHERE status IN ('done', 'cancelled')"
        )
        await self._db.commit()

    async def _rederive_status(self, post_id: str) -> None:
        cursor = await self._db.execute(
            "SELECT step_name, status FROM step_statuses WHERE post_id = ?", (post_id,),
        )
        step_map = {row[0]: StepStatus(row[1]) async for row in cursor}
        overall = derive_post_status(step_map)
        await self._db.execute(
            "UPDATE posts SET overall_status = ? WHERE post_id = ?", (overall, post_id),
        )
