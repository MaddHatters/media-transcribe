from __future__ import annotations

import aiosqlite

from web.models import DiscoveryRunResponse, PostSummary
from web.services.catalog_service import CatalogService
from web.services.obs_client import ObsClient


class DiscoveryService:
    def __init__(self, db: aiosqlite.Connection, obs_client: ObsClient) -> None:
        self._db = db
        self._obs_client = obs_client

    async def trigger(
        self, full_catalog: bool = False, force: bool = False,
    ) -> DiscoveryRunResponse:
        cursor = await self._db.execute(
            "INSERT INTO discovery_runs (started_at, status) VALUES (datetime('now'), 'running')"
        )
        run_id = cursor.lastrowid
        await self._db.commit()

        try:
            result = await self._obs_client.trigger_discovery(full_catalog, force)
        except Exception as e:
            await self._db.execute(
                "UPDATE discovery_runs SET status='failed', completed_at=datetime('now') WHERE id=?",
                (run_id,),
            )
            await self._db.commit()
            return DiscoveryRunResponse(
                id=run_id, started_at="", status="failed",
            )

        if result.get("error"):
            await self._db.execute(
                "UPDATE discovery_runs SET status='failed', completed_at=datetime('now') WHERE id=?",
                (run_id,),
            )
            await self._db.commit()
            return DiscoveryRunResponse(
                id=run_id, started_at="", status="failed",
            )

        catalog_svc = CatalogService(self._db)
        new_count = await catalog_svc.upsert_discovered(result.get("new_post_list", []))

        await self._db.execute(
            "UPDATE discovery_runs SET completed_at=datetime('now'), posts_found=?, new_posts=?, status='completed' WHERE id=?",
            (result.get("total_found", 0), new_count, run_id),
        )
        await self._db.commit()

        cursor = await self._db.execute("SELECT * FROM discovery_runs WHERE id=?", (run_id,))
        row = await cursor.fetchone()

        return DiscoveryRunResponse(
            id=row[0],
            started_at=row[2] or "",
            completed_at=row[3],
            posts_found=row[4] or 0,
            new_posts=row[5] or 0,
            source=row[6] or "patreon",
            status=row[7] or "completed",
        )

    async def get_new_posts(self) -> list[PostSummary]:
        catalog_svc = CatalogService(self._db)
        cursor = await self._db.execute(
            "SELECT p.* FROM posts p "
            "LEFT JOIN queue q ON p.post_id = q.post_id "
            "WHERE p.overall_status = 'discovered' AND q.id IS NULL "
            "ORDER BY p.published_at DESC"
        )
        rows = await cursor.fetchall()
        posts = []
        for row in rows:
            post = catalog_svc._row_to_summary(row)
            posts.append(post)
        return posts

    async def get_history(self) -> list[DiscoveryRunResponse]:
        cursor = await self._db.execute(
            "SELECT * FROM discovery_runs ORDER BY started_at DESC LIMIT 20"
        )
        rows = await cursor.fetchall()
        return [
            DiscoveryRunResponse(
                id=row[0],
                started_at=row[2] or "",
                completed_at=row[3],
                posts_found=row[4] or 0,
                new_posts=row[5] or 0,
                source=row[6] or "patreon",
                status=row[7] or "running",
            )
            for row in rows
        ]
