from __future__ import annotations

import json
from pathlib import Path

import aiosqlite

from web.database import migrate_from_json
from web.lifecycle import PIPELINE_STEPS, StepStatus, derive_post_status
from web.models import CatalogStats, PostDetail, PostSummary, StepStatusResponse

SORT_WHITELIST = {"published_at", "created_at", "title", "overall_status", "post_type"}


class CatalogService:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def list_posts(
        self,
        type: str | None = None,
        status: str | None = None,
        step_filter: str | None = None,
        search: str | None = None,
        tag: str | None = None,
        source_id: str | None = None,
        sort: str = "published_at",
        order: str = "desc",
        page: int = 1,
        per_page: int = 50,
    ) -> tuple[list[PostSummary], int]:
        where_clauses: list[str] = []
        params: list = []

        if type:
            where_clauses.append("p.post_type = ?")
            params.append(type)
        if status:
            where_clauses.append("p.overall_status = ?")
            params.append(status)
        if search:
            where_clauses.append("p.title LIKE ? COLLATE NOCASE")
            params.append(f"%{search}%")
        if tag:
            where_clauses.append("p.tags LIKE ?")
            params.append(f"%{tag}%")
        if source_id:
            where_clauses.append("p.source_id = ?")
            params.append(source_id)

        join_clause = ""
        if step_filter and ":" in step_filter:
            step_name, step_status = step_filter.split(":", 1)
            join_clause = "JOIN step_statuses ss ON p.post_id = ss.post_id"
            where_clauses.append("ss.step_name = ?")
            where_clauses.append("ss.status = ?")
            params.append(step_name)
            params.append(step_status)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        sort_col = sort if sort in SORT_WHITELIST else "published_at"
        order_dir = "ASC" if order.lower() == "asc" else "DESC"

        count_sql = f"SELECT COUNT(*) FROM posts p {join_clause} {where_sql}"
        cursor = await self._db.execute(count_sql, params)
        row = await cursor.fetchone()
        total = row[0] if row else 0

        offset = (page - 1) * per_page
        query_sql = (
            f"SELECT p.* FROM posts p {join_clause} {where_sql} "
            f"ORDER BY p.{sort_col} {order_dir} "
            f"LIMIT ? OFFSET ?"
        )
        cursor = await self._db.execute(query_sql, [*params, per_page, offset])
        rows = await cursor.fetchall()

        posts = []
        for row in rows:
            post = self._row_to_summary(row)
            post.steps = await self._get_steps(post.post_id)
            posts.append(post)

        return posts, total

    async def get_post(self, post_id: str) -> PostDetail | None:
        cursor = await self._db.execute("SELECT * FROM posts WHERE post_id = ?", (post_id,))
        row = await cursor.fetchone()
        if not row:
            return None

        steps = await self._get_steps(post_id)
        return self._row_to_detail(row, steps)

    async def get_stats(self) -> CatalogStats:
        cursor = await self._db.execute("SELECT COUNT(*) FROM posts")
        total_posts = (await cursor.fetchone())[0]

        cursor = await self._db.execute("SELECT COUNT(*) FROM posts WHERE has_video = 1")
        video_posts = (await cursor.fetchone())[0]

        cursor = await self._db.execute("SELECT COUNT(*) FROM posts WHERE has_audio = 1")
        audio_posts = (await cursor.fetchone())[0]

        by_status: dict[str, int] = {}
        cursor = await self._db.execute(
            "SELECT overall_status, COUNT(*) FROM posts GROUP BY overall_status"
        )
        async for row in cursor:
            by_status[row[0] or "unknown"] = row[1]

        by_type: dict[str, int] = {}
        cursor = await self._db.execute(
            "SELECT post_type, COUNT(*) FROM posts GROUP BY post_type"
        )
        async for row in cursor:
            by_type[row[0] or "unknown"] = row[1]

        by_step: dict[str, dict[str, int]] = {}
        cursor = await self._db.execute(
            "SELECT step_name, status, COUNT(*) FROM step_statuses GROUP BY step_name, status"
        )
        async for row in cursor:
            step_name = row[0]
            if step_name not in by_step:
                by_step[step_name] = {}
            by_step[step_name][row[1]] = row[2]

        return CatalogStats(
            total_posts=total_posts,
            video_posts=video_posts,
            audio_posts=audio_posts,
            by_status=by_status,
            by_type=by_type,
            by_step=by_step,
        )

    async def update_step_status(
        self,
        post_id: str,
        step: str,
        status: StepStatus,
        started_at: str | None = None,
        completed_at: str | None = None,
        error: str | None = None,
        output_path: str | None = None,
        duration_seconds: float | None = None,
    ) -> None:
        await self._db.execute(
            """UPDATE step_statuses
               SET status=?, started_at=?, completed_at=?, error=?, output_path=?, duration_seconds=?
               WHERE post_id=? AND step_name=?""",
            (status.value, started_at, completed_at, error, output_path, duration_seconds, post_id, step),
        )
        steps = await self._get_steps_raw(post_id)
        overall = derive_post_status(
            {name: StepStatus(s) for name, s in steps.items()}
        )
        await self._db.execute(
            "UPDATE posts SET overall_status=? WHERE post_id=?", (overall, post_id),
        )
        await self._db.commit()

    async def import_from_json(self, json_path: Path) -> int:
        return await migrate_from_json(self._db, json_path)

    async def upsert_discovered(self, posts: list[dict]) -> int:
        count = 0
        for post in posts:
            result = await self._db.execute(
                """INSERT OR IGNORE INTO posts
                   (post_id, source_id, url, title, post_type, has_video,
                    published_at, overall_status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    post.get("post_id", ""),
                    post.get("source_id", "fuw"),
                    post.get("url", ""),
                    post.get("title", ""),
                    post.get("post_type", ""),
                    post.get("has_video", False),
                    post.get("published_at", ""),
                    "discovered",
                ),
            )
            if result.rowcount and result.rowcount > 0:
                count += 1
                for step in PIPELINE_STEPS:
                    await self._db.execute(
                        "INSERT OR IGNORE INTO step_statuses (post_id, step_name, status) VALUES (?, ?, ?)",
                        (post["post_id"], step, "pending"),
                    )
        await self._db.commit()
        return count

    async def _get_steps(self, post_id: str) -> dict[str, StepStatusResponse]:
        cursor = await self._db.execute(
            "SELECT step_name, status, started_at, completed_at, error, output_path, duration_seconds, attempt "
            "FROM step_statuses WHERE post_id = ?",
            (post_id,),
        )
        steps: dict[str, StepStatusResponse] = {}
        async for row in cursor:
            steps[row[0]] = StepStatusResponse(
                status=row[1],
                started_at=row[2],
                completed_at=row[3],
                error=row[4],
                output_path=row[5],
                duration_seconds=row[6],
                attempt=row[7] or 0,
            )
        return steps

    async def _get_steps_raw(self, post_id: str) -> dict[str, str]:
        cursor = await self._db.execute(
            "SELECT step_name, status FROM step_statuses WHERE post_id = ?",
            (post_id,),
        )
        return {row[0]: row[1] async for row in cursor}

    def _row_to_summary(self, row) -> PostSummary:
        tags_raw = row["tags"] if isinstance(row, aiosqlite.Row) else row[18]
        tags = []
        if tags_raw:
            try:
                tags = json.loads(tags_raw)
            except (json.JSONDecodeError, TypeError):
                tags = []

        if isinstance(row, aiosqlite.Row):
            return PostSummary(
                post_id=row["post_id"],
                source_id=row["source_id"],
                url=row["url"],
                title=row["title"],
                published_at=row["published_at"],
                post_type=row["post_type"] or "",
                has_video=bool(row["has_video"]),
                has_audio=bool(row["has_audio"]),
                duration_seconds=row["duration_seconds"],
                thumbnail_url=row["thumbnail_url"],
                tags=tags,
                overall_status=row["overall_status"] or "discovered",
            )
        return PostSummary(
            post_id=row[0],
            source_id=row[1],
            url=row[2],
            title=row[3],
            published_at=row[5],
            post_type=row[7] or "",
            has_video=bool(row[8]),
            has_audio=bool(row[9]),
            duration_seconds=row[10],
            thumbnail_url=row[13],
            tags=tags,
            overall_status=row[23] or "discovered",
        )

    def _row_to_detail(self, row, steps: dict[str, StepStatusResponse]) -> PostDetail:
        tags_raw = row["tags"] if isinstance(row, aiosqlite.Row) else row[18]
        tags = []
        if tags_raw:
            try:
                tags = json.loads(tags_raw)
            except (json.JSONDecodeError, TypeError):
                tags = []

        if isinstance(row, aiosqlite.Row):
            return PostDetail(
                post_id=row["post_id"],
                source_id=row["source_id"],
                url=row["url"],
                title=row["title"],
                published_at=row["published_at"],
                post_type=row["post_type"] or "",
                has_video=bool(row["has_video"]),
                has_audio=bool(row["has_audio"]),
                duration_seconds=row["duration_seconds"],
                thumbnail_url=row["thumbnail_url"],
                tags=tags,
                overall_status=row["overall_status"] or "discovered",
                steps=steps,
                created_at=row["created_at"],
                edited_at=row["edited_at"],
                embed_url=row["embed_url"],
                embed_provider=row["embed_provider"],
                like_count=row["like_count"],
                comment_count=row["comment_count"],
                is_paid=bool(row["is_paid"]) if row["is_paid"] is not None else None,
                min_cents_pledged_to_view=row["min_cents_pledged_to_view"],
                discovered_at=row["discovered_at"],
                recording_mb=row["recording_mb"],
                transcript_words=row["transcript_words"],
                output_path=row["output_path"],
            )
        return PostDetail(
            post_id=row[0],
            source_id=row[1],
            url=row[2],
            title=row[3],
            published_at=row[5],
            post_type=row[7] or "",
            has_video=bool(row[8]),
            has_audio=bool(row[9]),
            duration_seconds=row[10],
            thumbnail_url=row[13],
            tags=tags,
            overall_status=row[23] or "discovered",
            steps=steps,
            created_at=row[4],
            edited_at=row[6],
            embed_url=row[11],
            embed_provider=row[12],
            like_count=row[14],
            comment_count=row[15],
            is_paid=bool(row[16]) if row[16] is not None else None,
            min_cents_pledged_to_view=row[17],
            discovered_at=row[19],
            recording_mb=row[20],
            transcript_words=row[21],
            output_path=row[22],
        )
