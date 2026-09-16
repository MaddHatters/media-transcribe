from __future__ import annotations

import pytest
import pytest_asyncio
import aiosqlite
from unittest.mock import AsyncMock

from web.database import init_db
from web.models import AgentHealth


@pytest_asyncio.fixture
async def db(tmp_path):
    conn = await init_db(tmp_path / "test.db")
    conn.row_factory = aiosqlite.Row
    yield conn
    await conn.close()


@pytest.fixture
def mock_obs_client():
    client = AsyncMock()
    client.health_check.return_value = AgentHealth(
        healthy=True, obs_connected=True, chrome_available=True,
        disk_ok=True, obs_version="30.2", error=None,
    )
    client.get_status.return_value = {
        "health": {
            "healthy": True, "obs_connected": True, "chrome_available": True,
            "disk_ok": True, "obs_version": "30.2", "error": "",
        },
        "watcher": {"running": False, "pid": 0, "cycle": 0, "interval_hours": 24.0,
                     "last_run": "", "next_run": "", "total_recorded": 0},
        "pipeline": {"running": False, "run_id": "", "total": 0, "completed": 0,
                      "failed": 0, "current_post": "", "current_step": ""},
        "disk": {"total_bytes": 1000000000000, "free_bytes": 500000000000, "drive": "D:"},
    }
    client.run_pipeline.return_value = {
        "started": True, "run_id": "run_test_001", "queue_size": 2, "error": "",
    }
    client.trigger_discovery.return_value = {
        "total_found": 100, "new_posts": 3, "video_posts": 80,
        "new_post_list": [], "error": "",
    }
    client.start_watcher.return_value = {"success": True, "message": "Watcher started"}
    client.stop_watcher.return_value = {"success": True, "message": "Watcher stopped"}
    return client


@pytest_asyncio.fixture
async def seed_db(db):
    for i in range(5):
        await db.execute(
            "INSERT INTO posts (post_id, source_id, url, title, post_type, has_video, published_at, overall_status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (f"post_{i}", "fuw", f"https://patreon.com/posts/{i}",
             f"Test Post {i}", "video_external_file", True,
             f"2026-01-0{i+1}T00:00:00Z", "discovered"),
        )
        for step in ["record", "analyze", "transcribe", "correct", "find_gaps", "extract_frames", "ocr"]:
            await db.execute(
                "INSERT INTO step_statuses (post_id, step_name, status) VALUES (?, ?, ?)",
                (f"post_{i}", step, "pending"),
            )
    await db.commit()
    return db
