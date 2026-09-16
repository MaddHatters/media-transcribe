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
async def test_list_catalog(app_client):
    resp = await app_client.get("/api/catalog/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 5
    assert len(data["posts"]) == 5
    assert data["page"] == 1


@pytest.mark.asyncio
async def test_list_catalog_type_filter(app_client):
    resp = await app_client.get("/api/catalog/?type=video_external_file")
    assert resp.status_code == 200
    assert resp.json()["total"] == 5


@pytest.mark.asyncio
async def test_list_catalog_source_filter(app_client):
    resp = await app_client.get("/api/catalog/?source_id=fuw")
    assert resp.status_code == 200
    assert resp.json()["total"] == 5

    resp2 = await app_client.get("/api/catalog/?source_id=other")
    assert resp2.json()["total"] == 0


@pytest.mark.asyncio
async def test_catalog_stats(app_client):
    resp = await app_client.get("/api/catalog/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_posts"] == 5
    assert data["video_posts"] == 5


@pytest.mark.asyncio
async def test_get_post_detail(app_client):
    resp = await app_client.get("/api/catalog/post_0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["post_id"] == "post_0"
    assert len(data["steps"]) == 7


@pytest.mark.asyncio
async def test_get_post_not_found(app_client):
    resp = await app_client.get("/api/catalog/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_chat_stub(app_client):
    resp = await app_client.post("/api/chat")
    assert resp.status_code == 501
    assert "Phase 2" in resp.json()["detail"]
