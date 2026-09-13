"""Tests for ContentWatcher — autonomous content discovery + recording loop."""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cli import build_parser, parse_interval
from src.pipeline.watcher import ContentWatcher


@pytest.fixture
def watcher():
    return ContentWatcher(
        source="patreon",
        interval_hours=24.0,
        steps=["record", "analyze", "transcribe", "correct"],
        max_per_run=3,
    )


@pytest.fixture
def status_dir(tmp_path):
    return tmp_path


# --- Interval enforcement ---

def test_interval_minimum_enforced():
    w = ContentWatcher(source="patreon", interval_hours=6.0, steps=["record"])
    assert w.interval_hours == 12.0


def test_interval_at_minimum_accepted():
    w = ContentWatcher(source="patreon", interval_hours=12.0, steps=["record"])
    assert w.interval_hours == 12.0


def test_interval_above_minimum_accepted():
    w = ContentWatcher(source="patreon", interval_hours=24.0, steps=["record"])
    assert w.interval_hours == 24.0


def test_interval_zero_clamped():
    w = ContentWatcher(source="patreon", interval_hours=0, steps=["record"])
    assert w.interval_hours == 12.0


# --- Batch capping ---

@pytest.mark.asyncio
async def test_max_per_run_caps_batch(tmp_path):
    from src.sources.discovery import DiscoveredPost
    posts = [
        DiscoveredPost(post_id=str(i), url=f"https://example.com/{i}",
                       title=f"Post {i}", created_at="2025-01-01",
                       post_type="video", has_video=True)
        for i in range(5)
    ]
    w = ContentWatcher(
        source="patreon", interval_hours=24.0,
        steps=["record"], max_per_run=3, status_dir=tmp_path,
    )
    w._shutdown = True
    pipeline_batches = []

    async def mock_discover():
        return posts

    async def mock_run_pipeline(batch):
        pipeline_batches.append(batch)
        return len(batch), 0

    with patch.object(w, "_discover", side_effect=mock_discover), \
         patch.object(w, "_run_pipeline", side_effect=mock_run_pipeline):
        await w.run_forever()

    assert len(pipeline_batches) == 1
    assert len(pipeline_batches[0]) == 3


@pytest.mark.asyncio
async def test_max_per_run_no_cap_needed(tmp_path):
    from src.sources.discovery import DiscoveredPost
    posts = [
        DiscoveredPost(post_id=str(i), url=f"https://example.com/{i}",
                       title=f"Post {i}", created_at="2025-01-01",
                       post_type="video", has_video=True)
        for i in range(2)
    ]
    w = ContentWatcher(
        source="patreon", interval_hours=24.0,
        steps=["record"], max_per_run=3, status_dir=tmp_path,
    )
    w._shutdown = True
    pipeline_batches = []

    async def mock_discover():
        return posts

    async def mock_run_pipeline(batch):
        pipeline_batches.append(batch)
        return len(batch), 0

    with patch.object(w, "_discover", side_effect=mock_discover), \
         patch.object(w, "_run_pipeline", side_effect=mock_run_pipeline):
        await w.run_forever()

    assert len(pipeline_batches) == 1
    assert len(pipeline_batches[0]) == 2


def test_max_per_run_default():
    w = ContentWatcher(source="patreon", interval_hours=24.0, steps=["record"])
    assert w.max_per_run == 3


# --- Status file ---

def test_write_status_creates_file(tmp_path):
    w = ContentWatcher(
        source="patreon", interval_hours=24.0, steps=["record"], status_dir=tmp_path,
    )
    w._write_status(running=True, last_result={"new_found": 0, "recorded": 0, "failed": 0}, next_run=None)
    status_path = tmp_path / "watch_status.json"
    assert status_path.exists()
    data = json.loads(status_path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)


def test_write_status_structure(tmp_path):
    w = ContentWatcher(
        source="patreon", interval_hours=24.0, steps=["record"], status_dir=tmp_path,
    )
    w._write_status(running=True, last_result={"new_found": 1, "recorded": 1, "failed": 0}, next_run="2026-09-02T22:00:00")
    status_path = tmp_path / "watch_status.json"
    data = json.loads(status_path.read_text(encoding="utf-8"))
    assert "running" in data
    assert "pid" in data
    assert "cycle" in data
    assert "last_run" in data
    assert "next_run" in data
    assert "last_result" in data
    assert "total_recorded" in data
    assert "started_at" in data


def test_read_status_from_file(tmp_path):
    w = ContentWatcher(
        source="patreon", interval_hours=24.0, steps=["record"], status_dir=tmp_path,
    )
    w._write_status(running=True, last_result={"new_found": 0, "recorded": 0, "failed": 0}, next_run=None)
    status = ContentWatcher.read_status(status_dir=tmp_path)
    assert status is not None
    assert status["running"] is True


def test_read_status_no_file(tmp_path):
    status = ContentWatcher.read_status(status_dir=tmp_path)
    assert status is None


# --- CLI --status flag ---

def test_watch_status_flag_parsed():
    parser = build_parser()
    args = parser.parse_args(["watch", "--status"])
    assert args.status is True


def test_watch_every_flag_parsed():
    parser = build_parser()
    args = parser.parse_args(["watch", "--every", "24h"])
    assert args.every == "24h"


def test_watch_source_default():
    parser = build_parser()
    args = parser.parse_args(["watch", "--status"])
    assert args.source == "patreon"


def test_watch_max_per_run_default():
    parser = build_parser()
    args = parser.parse_args(["watch", "--status"])
    assert args.max_per_run == 3


def test_watch_dry_run_flag():
    parser = build_parser()
    args = parser.parse_args(["watch", "--status"])
    assert args.dry_run is False
    args2 = parser.parse_args(["watch", "--every", "24h", "--dry-run"])
    assert args2.dry_run is True


def test_watch_foreground_flag():
    parser = build_parser()
    args = parser.parse_args(["watch", "--every", "24h", "--foreground"])
    assert args.foreground is True


def test_watch_start_at_flag():
    parser = build_parser()
    args = parser.parse_args(["watch", "--every", "24h", "--start-at", "22:00"])
    assert args.start_at == "22:00"


# --- Shutdown ---

@pytest.mark.asyncio
async def test_shutdown_flag_stops_loop(tmp_path):
    w = ContentWatcher(
        source="patreon", interval_hours=24.0, steps=["record"], status_dir=tmp_path,
    )
    w._shutdown = True

    with patch.object(w, "_discover", new_callable=AsyncMock, return_value=[]):
        await w.run_forever()

    assert w._cycle == 1


@pytest.mark.asyncio
async def test_shutdown_writes_final_status(tmp_path):
    w = ContentWatcher(
        source="patreon", interval_hours=24.0, steps=["record"], status_dir=tmp_path,
    )
    w._shutdown = True

    with patch.object(w, "_discover", new_callable=AsyncMock, return_value=[]):
        await w.run_forever()

    status = ContentWatcher.read_status(status_dir=tmp_path)
    assert status is not None
    assert status["running"] is False


# --- Error resilience ---

@pytest.mark.asyncio
async def test_discovery_failure_doesnt_crash_loop(tmp_path):
    w = ContentWatcher(
        source="patreon", interval_hours=24.0, steps=["record"], status_dir=tmp_path,
    )
    call_count = 0

    async def failing_discover():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("discovery exploded")
        return []

    async def stop_after_sleep(seconds):
        w._shutdown = True

    with patch.object(w, "_discover", side_effect=failing_discover), \
         patch("asyncio.sleep", new_callable=AsyncMock, side_effect=stop_after_sleep):
        await w.run_forever()

    assert call_count >= 1
    status = ContentWatcher.read_status(status_dir=tmp_path)
    assert status is not None


@pytest.mark.asyncio
async def test_pipeline_failure_doesnt_crash_loop(tmp_path):
    from src.sources.discovery import DiscoveredPost
    posts = [
        DiscoveredPost(post_id="1", url="https://example.com/1",
                       title="Post 1", created_at="2025-01-01",
                       post_type="video", has_video=True)
    ]
    w = ContentWatcher(
        source="patreon", interval_hours=24.0, steps=["record"], status_dir=tmp_path,
    )
    call_count = 0

    async def discover_once():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return posts
        return []

    async def failing_pipeline(batch):
        raise Exception("pipeline exploded")

    async def stop_after_sleep(seconds):
        w._shutdown = True

    with patch.object(w, "_discover", side_effect=discover_once), \
         patch.object(w, "_run_pipeline", side_effect=failing_pipeline), \
         patch("asyncio.sleep", new_callable=AsyncMock, side_effect=stop_after_sleep):
        await w.run_forever()

    assert call_count >= 1
    status = ContentWatcher.read_status(status_dir=tmp_path)
    assert status is not None


# --- Dry-run ---

@pytest.mark.asyncio
async def test_dry_run_discovers_but_skips_pipeline(tmp_path):
    from src.sources.discovery import DiscoveredPost
    posts = [
        DiscoveredPost(post_id="1", url="https://example.com/1",
                       title="Post 1", created_at="2025-01-01",
                       post_type="video", has_video=True)
    ]
    w = ContentWatcher(
        source="patreon", interval_hours=24.0, steps=["record"],
        dry_run=True, status_dir=tmp_path,
    )
    w._shutdown = True
    pipeline_called = False

    async def mock_discover():
        return posts

    async def mock_pipeline(batch):
        nonlocal pipeline_called
        pipeline_called = True
        return len(batch), 0

    with patch.object(w, "_discover", side_effect=mock_discover), \
         patch.object(w, "_run_pipeline", side_effect=mock_pipeline):
        await w.run_forever()

    assert not pipeline_called


@pytest.mark.asyncio
async def test_dry_run_still_writes_status(tmp_path):
    from src.sources.discovery import DiscoveredPost
    posts = [
        DiscoveredPost(post_id="1", url="https://example.com/1",
                       title="Post 1", created_at="2025-01-01",
                       post_type="video", has_video=True)
    ]
    w = ContentWatcher(
        source="patreon", interval_hours=24.0, steps=["record"],
        dry_run=True, status_dir=tmp_path,
    )
    w._shutdown = True

    with patch.object(w, "_discover", new_callable=AsyncMock, return_value=posts):
        await w.run_forever()

    status = ContentWatcher.read_status(status_dir=tmp_path)
    assert status is not None
    assert status["last_result"]["new_found"] == 1


# --- Catalog merge in _discover ---

@pytest.mark.asyncio
async def test_discover_merges_with_existing_catalog(tmp_path):
    from src.sources.discovery import DiscoveredPost
    from dataclasses import asdict

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    catalog_path = data_dir / "patreon_catalog_firedupwealth.json"
    existing_posts = [
        DiscoveredPost(post_id="old1", url="https://www.patreon.com/posts/old1",
                       title="Old Post 1", created_at="2024-06-01T00:00:00+00:00",
                       post_type="video_external_file", has_video=True),
        DiscoveredPost(post_id="old2", url="https://www.patreon.com/posts/old2",
                       title="Old Post 2", created_at="2024-05-01T00:00:00+00:00",
                       post_type="video_external_file", has_video=True),
    ]
    catalog = {
        "creator": "Mr. FIRED Up Wealth",
        "campaign_id": "5008493",
        "last_discovery": "2024-06-01T00:00:00+00:00",
        "total_posts": 2,
        "video_posts": 2,
        "posts": [asdict(p) for p in existing_posts],
    }
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

    api_response = {
        "data": [{"id": "new1", "attributes": {"title": "New Post", "created_at": "2025-01-15T00:00:00+00:00", "post_type": "video_external_file"}}],
        "meta": {"pagination": {"total": 1}},
    }
    mock_resp = MagicMock()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = json.dumps(api_response).encode()

    w = ContentWatcher(
        source="patreon", interval_hours=24.0, steps=["record"], status_dir=tmp_path,
    )
    w._shutdown = True

    with patch("urllib.request.urlopen", return_value=mock_resp), \
         patch("src.config.CATALOG_PATH", catalog_path):
        new = await w._discover()

    saved = json.loads(catalog_path.read_text(encoding="utf-8"))
    saved_ids = {p["post_id"] for p in saved["posts"]}
    assert "old1" in saved_ids, "existing posts must be preserved"
    assert "old2" in saved_ids, "existing posts must be preserved"
    assert "new1" in saved_ids, "new post must be added"
    assert saved["total_posts"] == 3


# --- Interval parsing ---

def test_parse_interval_24h():
    assert parse_interval("24h") == 24.0


def test_parse_interval_12h():
    assert parse_interval("12h") == 12.0


def test_parse_interval_6h():
    assert parse_interval("6h") == 6.0


def test_parse_interval_invalid():
    with pytest.raises(ValueError):
        parse_interval("foo")
