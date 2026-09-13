from __future__ import annotations

import json
from pathlib import Path

import pytest

from web.database import init_db, migrate_from_json
from web.lifecycle import PIPELINE_STEPS


def _make_catalog(posts: list[dict]) -> dict:
    return {"creator": "test", "total_posts": len(posts), "posts": posts}


def _make_post(post_id: str, **overrides) -> dict:
    base = {
        "post_id": post_id,
        "url": f"https://www.patreon.com/posts/{post_id}",
        "title": f"Post {post_id}",
        "created_at": "2026-01-01T00:00:00.000+00:00",
        "post_type": "video_embed",
        "has_video": True,
        "has_audio": False,
    }
    base.update(overrides)
    return base


@pytest.fixture
async def db(tmp_path):
    conn = await init_db(tmp_path / "test.db")
    yield conn
    await conn.close()


class TestInitDb:
    async def test_creates_tables(self, db):
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in await cursor.fetchall()}
        expected = {"sources", "posts", "step_statuses", "queue", "watcher_config", "discovery_runs"}
        assert expected.issubset(tables)

    async def test_seeds_fuw_source(self, db):
        cursor = await db.execute("SELECT id, name, source_type FROM sources WHERE id='fuw'")
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "fuw"
        assert row[1] == "Fired Up Wealth"
        assert row[2] == "patreon"

    async def test_idempotent(self, tmp_path):
        db_path = tmp_path / "idem.db"
        db1 = await init_db(db_path)
        await db1.close()
        db2 = await init_db(db_path)
        cursor = await db2.execute("SELECT COUNT(*) FROM sources WHERE id='fuw'")
        row = await cursor.fetchone()
        assert row[0] == 1
        await db2.close()


class TestMigrateFromJson:
    async def test_basic_migration(self, db, tmp_path):
        posts = [_make_post(str(i)) for i in range(5)]
        catalog_path = tmp_path / "catalog.json"
        catalog_path.write_text(json.dumps(_make_catalog(posts)))

        count = await migrate_from_json(db, catalog_path)
        assert count == 5

        cursor = await db.execute("SELECT COUNT(*) FROM posts")
        assert (await cursor.fetchone())[0] == 5

        cursor = await db.execute("SELECT COUNT(*) FROM step_statuses")
        assert (await cursor.fetchone())[0] == 35

        cursor = await db.execute("SELECT DISTINCT status FROM step_statuses")
        statuses = {row[0] for row in await cursor.fetchall()}
        assert statuses == {"pending"}

        cursor = await db.execute("SELECT DISTINCT overall_status FROM posts")
        assert (await cursor.fetchone())[0] == "discovered"

        cursor = await db.execute("SELECT DISTINCT source_id FROM posts")
        assert (await cursor.fetchone())[0] == "fuw"

    async def test_preserves_ingested_complete(self, db, tmp_path):
        posts = [_make_post("100", ingested_status="complete")]
        catalog_path = tmp_path / "catalog.json"
        catalog_path.write_text(json.dumps(_make_catalog(posts)))

        await migrate_from_json(db, catalog_path)

        cursor = await db.execute("SELECT overall_status FROM posts WHERE post_id='100'")
        assert (await cursor.fetchone())[0] == "completed"

        cursor = await db.execute(
            "SELECT DISTINCT status FROM step_statuses WHERE post_id='100'"
        )
        statuses = {row[0] for row in await cursor.fetchall()}
        assert statuses == {"completed"}

    async def test_preserves_ingested_failed(self, db, tmp_path):
        posts = [_make_post("200", ingested_status="failed")]
        catalog_path = tmp_path / "catalog.json"
        catalog_path.write_text(json.dumps(_make_catalog(posts)))

        await migrate_from_json(db, catalog_path)

        cursor = await db.execute("SELECT overall_status FROM posts WHERE post_id='200'")
        assert (await cursor.fetchone())[0] == "failed"

        cursor = await db.execute(
            "SELECT status FROM step_statuses WHERE post_id='200' AND step_name='record'"
        )
        assert (await cursor.fetchone())[0] == "failed"

    async def test_preserves_ingested_skipped(self, db, tmp_path):
        posts = [_make_post("300", ingested_status="skipped")]
        catalog_path = tmp_path / "catalog.json"
        catalog_path.write_text(json.dumps(_make_catalog(posts)))

        await migrate_from_json(db, catalog_path)

        cursor = await db.execute("SELECT overall_status FROM posts WHERE post_id='300'")
        assert (await cursor.fetchone())[0] == "completed"

        cursor = await db.execute(
            "SELECT DISTINCT status FROM step_statuses WHERE post_id='300'"
        )
        statuses = {row[0] for row in await cursor.fetchall()}
        assert statuses == {"skipped"}

    async def test_null_ingested_status(self, db, tmp_path):
        posts = [_make_post("400")]
        catalog_path = tmp_path / "catalog.json"
        catalog_path.write_text(json.dumps(_make_catalog(posts)))

        await migrate_from_json(db, catalog_path)

        cursor = await db.execute("SELECT overall_status FROM posts WHERE post_id='400'")
        assert (await cursor.fetchone())[0] == "discovered"

        cursor = await db.execute(
            "SELECT DISTINCT status FROM step_statuses WHERE post_id='400'"
        )
        statuses = {row[0] for row in await cursor.fetchall()}
        assert statuses == {"pending"}

    async def test_idempotent(self, db, tmp_path):
        posts = [_make_post("500"), _make_post("501")]
        catalog_path = tmp_path / "catalog.json"
        catalog_path.write_text(json.dumps(_make_catalog(posts)))

        count1 = await migrate_from_json(db, catalog_path)
        count2 = await migrate_from_json(db, catalog_path)
        assert count1 == 2
        assert count2 == 0

        cursor = await db.execute("SELECT COUNT(*) FROM posts")
        assert (await cursor.fetchone())[0] == 2

    async def test_serializes_tags(self, db, tmp_path):
        posts = [_make_post("600", tags=["finance", "stocks"])]
        catalog_path = tmp_path / "catalog.json"
        catalog_path.write_text(json.dumps(_make_catalog(posts)))

        await migrate_from_json(db, catalog_path)

        cursor = await db.execute("SELECT tags FROM posts WHERE post_id='600'")
        tags_str = (await cursor.fetchone())[0]
        assert json.loads(tags_str) == ["finance", "stocks"]

    async def test_null_tags(self, db, tmp_path):
        posts = [_make_post("700", tags=None)]
        catalog_path = tmp_path / "catalog.json"
        catalog_path.write_text(json.dumps(_make_catalog(posts)))

        await migrate_from_json(db, catalog_path)

        cursor = await db.execute("SELECT tags FROM posts WHERE post_id='700'")
        assert (await cursor.fetchone())[0] is None

    async def test_empty_tags_list(self, db, tmp_path):
        posts = [_make_post("800", tags=[])]
        catalog_path = tmp_path / "catalog.json"
        catalog_path.write_text(json.dumps(_make_catalog(posts)))

        await migrate_from_json(db, catalog_path)

        cursor = await db.execute("SELECT tags FROM posts WHERE post_id='800'")
        tags_str = (await cursor.fetchone())[0]
        assert json.loads(tags_str) == []

    async def test_missing_optional_fields(self, db, tmp_path):
        post = {"post_id": "900", "url": "https://example.com/900", "title": "Minimal", "post_type": "text", "has_video": False, "has_audio": False}
        catalog_path = tmp_path / "catalog.json"
        catalog_path.write_text(json.dumps(_make_catalog([post])))

        count = await migrate_from_json(db, catalog_path)
        assert count == 1

        cursor = await db.execute("SELECT published_at, duration_seconds FROM posts WHERE post_id='900'")
        row = await cursor.fetchone()
        assert row[0] is None
        assert row[1] is None
