"""Tests for CatalogManager — catalog I/O, merge, filtering, and update."""
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.catalog import CatalogManager, INGESTION_FIELDS
from src.sources.discovery import DiscoveredPost


def _sample_post(post_id="123", title="Test Post", has_video=True,
                 created_at="2025-01-15T12:00:00+00:00", post_type=None,
                 has_audio=False):
    if post_type is None:
        post_type = "video_external_file" if has_video else "text_only"
    return DiscoveredPost(
        post_id=post_id,
        url=f"https://www.patreon.com/posts/{post_id}",
        title=title,
        created_at=created_at,
        post_type=post_type,
        has_video=has_video,
        has_audio=has_audio,
    )


def _catalog_dict(posts, **meta):
    base = {
        "creator": "Mr. FIRED Up Wealth",
        "campaign_id": "5008493",
        "last_discovery": "2025-01-01T00:00:00+00:00",
        "total_posts": len(posts),
        "video_posts": sum(1 for p in posts if p.get("has_video")),
        "audio_posts": sum(1 for p in posts if p.get("has_audio")),
        "posts": posts,
    }
    base.update(meta)
    return base


# --- load ---

def test_load_missing_file(tmp_path):
    cm = CatalogManager(tmp_path / "missing.json")
    assert cm.load() == []


def test_load_empty_file(tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text("", encoding="utf-8")
    cm = CatalogManager(path)
    assert cm.load() == []


def test_load_corrupt_json(tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text("{invalid json", encoding="utf-8")
    cm = CatalogManager(path)
    assert cm.load() == []


def test_load_valid_file(tmp_path):
    path = tmp_path / "catalog.json"
    posts = [{"post_id": "1", "title": "A", "has_video": True}]
    path.write_text(json.dumps(_catalog_dict(posts)), encoding="utf-8")
    cm = CatalogManager(path)
    result = cm.load()
    assert len(result) == 1
    assert result[0]["post_id"] == "1"


def test_load_sessions_key(tmp_path):
    path = tmp_path / "catalog.json"
    data = {"sessions": [{"post_id": "s1", "title": "Session"}]}
    path.write_text(json.dumps(data), encoding="utf-8")
    cm = CatalogManager(path)
    result = cm.load()
    assert len(result) == 1
    assert result[0]["post_id"] == "s1"


# --- save ---

def test_save_produces_valid_json(tmp_path):
    path = tmp_path / "catalog.json"
    cm = CatalogManager(path)
    posts = [{"post_id": "1", "title": "A", "has_video": True}]
    cm.save(posts)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["total_posts"] == 1
    assert data["video_posts"] == 1
    assert data["audio_posts"] == 0
    assert len(data["posts"]) == 1


def test_save_counts_audio_posts(tmp_path):
    path = tmp_path / "catalog.json"
    cm = CatalogManager(path)
    posts = [
        {"post_id": "1", "title": "A", "has_video": True, "has_audio": False},
        {"post_id": "2", "title": "B", "has_video": False, "has_audio": True},
        {"post_id": "3", "title": "C", "has_video": False, "has_audio": True},
    ]
    cm.save(posts)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["video_posts"] == 1
    assert data["audio_posts"] == 2


def test_save_preserves_metadata(tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(_catalog_dict([], campaign_id="999")), encoding="utf-8")
    cm = CatalogManager(path)
    cm.save([{"post_id": "1", "title": "A", "has_video": False}])
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["campaign_id"] == "999"
    assert data["total_posts"] == 1


def test_save_atomic_write(tmp_path):
    path = tmp_path / "catalog.json"
    cm = CatalogManager(path)
    cm.save([{"post_id": "1", "title": "A", "has_video": True}])
    assert path.exists()
    assert not path.with_suffix(".tmp").exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)


def test_save_creates_parent_dirs(tmp_path):
    path = tmp_path / "sub" / "dir" / "catalog.json"
    cm = CatalogManager(path)
    cm.save([])
    assert path.exists()


# --- merge_discovered ---

def test_merge_new_posts_added(tmp_path):
    path = tmp_path / "catalog.json"
    cm = CatalogManager(path)
    posts = [_sample_post("1"), _sample_post("2")]
    merged, new_count = cm.merge_discovered(posts)
    assert len(merged) == 2
    assert new_count == 2
    assert all(p.get("discovered_at") for p in merged)


def test_merge_existing_keeps_ingestion(tmp_path):
    path = tmp_path / "catalog.json"
    existing = [{
        "post_id": "1", "url": "https://www.patreon.com/posts/1",
        "title": "Old Title", "created_at": "2025-01-01",
        "post_type": "video_external_file", "has_video": True,
        "ingested_status": "complete", "ingested_at": "2025-06-01",
        "recording_mb": 500.0,
    }]
    path.write_text(json.dumps(_catalog_dict(existing)), encoding="utf-8")
    cm = CatalogManager(path)

    updated = _sample_post("1", title="New Title")
    merged, new_count = cm.merge_discovered([updated])

    assert new_count == 0
    assert len(merged) == 1
    entry = merged[0]
    assert entry["title"] == "New Title"
    assert entry["ingested_status"] == "complete"
    assert entry["ingested_at"] == "2025-06-01"
    assert entry["recording_mb"] == 500.0


def test_merge_deduplicates_by_post_id(tmp_path):
    path = tmp_path / "catalog.json"
    cm = CatalogManager(path)
    posts = [_sample_post("1", title="A"), _sample_post("1", title="B")]
    merged, new_count = cm.merge_discovered(posts)
    assert len(merged) == 1
    assert new_count == 1


def test_merge_adds_discovered_at_for_new(tmp_path):
    path = tmp_path / "catalog.json"
    cm = CatalogManager(path)
    posts = [_sample_post("1")]
    merged, _ = cm.merge_discovered(posts)
    assert merged[0].get("discovered_at") is not None


# --- get_pending ---

def test_get_pending_filters_ingested(tmp_path):
    path = tmp_path / "catalog.json"
    posts = [
        {"post_id": "1", "title": "A", "has_video": True, "created_at": "2025-01-01", "ingested_status": None},
        {"post_id": "2", "title": "B", "has_video": True, "created_at": "2025-01-02", "ingested_status": "complete"},
        {"post_id": "3", "title": "C", "has_video": True, "created_at": "2025-01-03", "ingested_status": None},
    ]
    path.write_text(json.dumps(_catalog_dict(posts)), encoding="utf-8")
    cm = CatalogManager(path)
    pending = cm.get_pending()
    assert len(pending) == 2
    assert all(p["ingested_status"] is None for p in pending)


def test_get_pending_ordered_by_created_at_desc(tmp_path):
    path = tmp_path / "catalog.json"
    posts = [
        {"post_id": "1", "title": "Old", "has_video": True, "created_at": "2025-01-01"},
        {"post_id": "2", "title": "New", "has_video": True, "created_at": "2025-06-01"},
    ]
    path.write_text(json.dumps(_catalog_dict(posts)), encoding="utf-8")
    cm = CatalogManager(path)
    pending = cm.get_pending()
    assert pending[0]["post_id"] == "2"
    assert pending[1]["post_id"] == "1"


def test_get_pending_filtered_by_post_types(tmp_path):
    path = tmp_path / "catalog.json"
    posts = [
        {"post_id": "1", "title": "A", "has_video": True, "created_at": "2025-01-01", "post_type": "video_external_file"},
        {"post_id": "2", "title": "B", "has_video": False, "created_at": "2025-01-02", "post_type": "text_only"},
        {"post_id": "3", "title": "C", "has_video": True, "created_at": "2025-01-03", "post_type": "video_embed"},
    ]
    path.write_text(json.dumps(_catalog_dict(posts)), encoding="utf-8")
    cm = CatalogManager(path)
    pending = cm.get_pending(post_types=["video_external_file", "video_embed"])
    assert len(pending) == 2
    assert all(p["post_type"].startswith("video") for p in pending)


# --- update_post ---

def test_update_post_modifies_entry(tmp_path):
    path = tmp_path / "catalog.json"
    posts = [{"post_id": "1", "title": "A", "has_video": True}]
    path.write_text(json.dumps(_catalog_dict(posts)), encoding="utf-8")
    cm = CatalogManager(path)
    cm.update_post("1", {"ingested_status": "complete", "ingested_at": "2025-06-01"})

    reloaded = cm.load()
    assert reloaded[0]["ingested_status"] == "complete"
    assert reloaded[0]["ingested_at"] == "2025-06-01"


def test_update_post_writes_immediately(tmp_path):
    path = tmp_path / "catalog.json"
    posts = [{"post_id": "1", "title": "A", "has_video": True}]
    path.write_text(json.dumps(_catalog_dict(posts)), encoding="utf-8")
    cm = CatalogManager(path)
    cm.update_post("1", {"ingested_status": "failed"})

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["posts"][0]["ingested_status"] == "failed"


def test_update_post_unknown_raises(tmp_path):
    path = tmp_path / "catalog.json"
    posts = [{"post_id": "1", "title": "A", "has_video": True}]
    path.write_text(json.dumps(_catalog_dict(posts)), encoding="utf-8")
    cm = CatalogManager(path)
    with pytest.raises(KeyError, match="999"):
        cm.update_post("999", {"ingested_status": "complete"})


# --- find_by_url ---

def test_find_by_url_found(tmp_path):
    path = tmp_path / "catalog.json"
    posts = [{"post_id": "1", "title": "A", "url": "https://example.com/1", "has_video": True}]
    path.write_text(json.dumps(_catalog_dict(posts)), encoding="utf-8")
    cm = CatalogManager(path)
    result = cm.find_by_url("https://example.com/1")
    assert result is not None
    assert result["post_id"] == "1"


def test_find_by_url_not_found(tmp_path):
    path = tmp_path / "catalog.json"
    posts = [{"post_id": "1", "title": "A", "url": "https://example.com/1", "has_video": True}]
    path.write_text(json.dumps(_catalog_dict(posts)), encoding="utf-8")
    cm = CatalogManager(path)
    result = cm.find_by_url("https://example.com/missing")
    assert result is None


# --- Post-type routing ---

def test_video_posts_are_pending(tmp_path):
    path = tmp_path / "catalog.json"
    posts = [
        {"post_id": "1", "title": "Vid", "has_video": True, "created_at": "2025-01-01",
         "post_type": "video_external_file"},
    ]
    path.write_text(json.dumps(_catalog_dict(posts)), encoding="utf-8")
    cm = CatalogManager(path)
    pending = cm.get_pending()
    assert len(pending) == 1


def test_skipped_posts_not_pending(tmp_path):
    path = tmp_path / "catalog.json"
    posts = [
        {"post_id": "1", "title": "A", "has_video": False, "created_at": "2025-01-01",
         "post_type": "poll", "ingested_status": "skipped",
         "error": "poll posts not ingested"},
        {"post_id": "2", "title": "B", "has_video": False, "created_at": "2025-01-02",
         "post_type": "text_only", "ingested_status": "skipped",
         "error": "text_only handler not yet implemented"},
    ]
    path.write_text(json.dumps(_catalog_dict(posts)), encoding="utf-8")
    cm = CatalogManager(path)
    pending = cm.get_pending()
    assert len(pending) == 0


# --- Crash safety ---

def test_save_no_tmp_leftover(tmp_path):
    path = tmp_path / "catalog.json"
    cm = CatalogManager(path)
    cm.save([{"post_id": "1", "title": "A", "has_video": True}])
    assert not path.with_suffix(".tmp").exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["posts"][0]["post_id"] == "1"
