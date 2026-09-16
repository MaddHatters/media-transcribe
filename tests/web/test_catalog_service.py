from __future__ import annotations

import pytest

from web.lifecycle import StepStatus
from web.models import CatalogStats, PostDetail, PostSummary
from web.services.catalog_service import CatalogService


@pytest.mark.asyncio
async def test_list_posts_no_filters(seed_db):
    service = CatalogService(seed_db)
    posts, total = await service.list_posts()
    assert total == 5
    assert len(posts) == 5
    assert all(isinstance(p, PostSummary) for p in posts)


@pytest.mark.asyncio
async def test_list_posts_type_filter(seed_db):
    service = CatalogService(seed_db)
    posts, total = await service.list_posts(type="video_external_file")
    assert total == 5
    posts, total = await service.list_posts(type="nonexistent")
    assert total == 0


@pytest.mark.asyncio
async def test_list_posts_status_filter(seed_db):
    service = CatalogService(seed_db)
    posts, total = await service.list_posts(status="discovered")
    assert total == 5
    posts, total = await service.list_posts(status="completed")
    assert total == 0


@pytest.mark.asyncio
async def test_list_posts_source_id_filter(seed_db):
    service = CatalogService(seed_db)
    posts, total = await service.list_posts(source_id="fuw")
    assert total == 5
    posts, total = await service.list_posts(source_id="other")
    assert total == 0


@pytest.mark.asyncio
async def test_list_posts_search_filter(seed_db):
    service = CatalogService(seed_db)
    posts, total = await service.list_posts(search="Post 1")
    assert total == 1
    assert posts[0].title == "Test Post 1"


@pytest.mark.asyncio
async def test_list_posts_pagination(seed_db):
    service = CatalogService(seed_db)
    posts, total = await service.list_posts(page=1, per_page=2)
    assert total == 5
    assert len(posts) == 2

    posts2, total2 = await service.list_posts(page=2, per_page=2)
    assert total2 == 5
    assert len(posts2) == 2
    assert posts[0].post_id != posts2[0].post_id


@pytest.mark.asyncio
async def test_list_posts_sort_default(seed_db):
    service = CatalogService(seed_db)
    posts, _ = await service.list_posts()
    dates = [p.published_at for p in posts if p.published_at]
    assert dates == sorted(dates, reverse=True)


@pytest.mark.asyncio
async def test_get_post(seed_db):
    service = CatalogService(seed_db)
    post = await service.get_post("post_0")
    assert isinstance(post, PostDetail)
    assert post.post_id == "post_0"
    assert len(post.steps) == 7
    assert "record" in post.steps


@pytest.mark.asyncio
async def test_get_post_nonexistent(seed_db):
    service = CatalogService(seed_db)
    post = await service.get_post("nonexistent")
    assert post is None


@pytest.mark.asyncio
async def test_get_stats(seed_db):
    service = CatalogService(seed_db)
    stats = await service.get_stats()
    assert isinstance(stats, CatalogStats)
    assert stats.total_posts == 5
    assert stats.video_posts == 5
    assert stats.by_status.get("discovered") == 5


@pytest.mark.asyncio
async def test_update_step_status(seed_db):
    service = CatalogService(seed_db)
    await service.update_step_status("post_0", "record", StepStatus.RUNNING)

    post = await service.get_post("post_0")
    assert post.steps["record"].status == "running"
    assert post.overall_status == "in_progress"


@pytest.mark.asyncio
async def test_upsert_discovered(seed_db):
    service = CatalogService(seed_db)
    new_posts = [
        {"post_id": "new_1", "url": "https://example.com/new1", "title": "New Post 1",
         "post_type": "video", "has_video": True, "published_at": "2026-06-01T00:00:00Z"},
        {"post_id": "new_2", "url": "https://example.com/new2", "title": "New Post 2",
         "post_type": "video", "has_video": True, "published_at": "2026-06-02T00:00:00Z"},
    ]
    count = await service.upsert_discovered(new_posts)
    assert count == 2

    post = await service.get_post("new_1")
    assert post is not None
    assert post.overall_status == "discovered"
    assert len(post.steps) == 7

    count2 = await service.upsert_discovered(new_posts)
    assert count2 == 0
