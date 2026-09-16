from __future__ import annotations

import pytest
import pytest_asyncio
import aiosqlite
from httpx import ASGITransport, AsyncClient

from web.app import create_app
from web.database import init_db


@pytest_asyncio.fixture
async def app_client(tmp_path, mock_obs_client):
    db = await init_db(tmp_path / "test.db")
    db.row_factory = aiosqlite.Row

    for i in range(3):
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

    app = create_app()
    app.state.db = db
    app.state.obs_client = mock_obs_client

    from web.services.event_bus import EventBus
    app.state.event_bus = EventBus()

    from web.database import get_db as _original_get_db

    async def _override_get_db():
        yield db

    app.dependency_overrides[_original_get_db] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    await db.close()


@pytest.mark.asyncio
async def test_get_queue_empty(app_client):
    resp = await app_client.get("/api/queue/")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_add_to_queue(app_client):
    resp = await app_client.post("/api/queue/", json={"post_ids": ["post_0", "post_1"], "priority": 5})
    assert resp.status_code == 200
    assert resp.json()["added"] == 2

    resp2 = await app_client.get("/api/queue/")
    data = resp2.json()
    assert len(data) == 2


@pytest.mark.asyncio
async def test_add_duplicate_is_idempotent(app_client):
    await app_client.post("/api/queue/", json={"post_ids": ["post_0"]})
    resp = await app_client.post("/api/queue/", json={"post_ids": ["post_0"]})
    assert resp.json()["added"] == 0


@pytest.mark.asyncio
async def test_remove_from_queue(app_client):
    await app_client.post("/api/queue/", json={"post_ids": ["post_0"]})
    resp = await app_client.delete("/api/queue/post_0")
    assert resp.status_code == 200
    assert resp.json()["removed"] is True

    resp2 = await app_client.get("/api/queue/")
    assert resp2.json() == []


@pytest.mark.asyncio
async def test_update_priority(app_client):
    await app_client.post("/api/queue/", json={"post_ids": ["post_0"]})
    resp = await app_client.patch("/api/queue/post_0", json={"priority": 10})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_reorder(app_client):
    await app_client.post("/api/queue/", json={"post_ids": ["post_0", "post_1", "post_2"]})
    resp = await app_client.post("/api/queue/reorder", json={"post_ids": ["post_2", "post_0", "post_1"]})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_start_queue(app_client):
    await app_client.post("/api/queue/", json={"post_ids": ["post_0", "post_1"]})
    resp = await app_client.post("/api/queue/start")
    assert resp.status_code == 200
    data = resp.json()
    assert data["started"] is True
    assert data["run_id"] == "run_test_001"


@pytest.mark.asyncio
async def test_clear_completed(app_client):
    await app_client.post("/api/queue/", json={"post_ids": ["post_0"]})
    resp = await app_client.post("/api/queue/clear")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
