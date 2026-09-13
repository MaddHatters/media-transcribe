"""Tests for src/sources/discovery — Patreon public API content discovery."""
import json
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.sources.discovery import (
    COOLDOWN_HOURS,
    MAX_PAGES,
    PAGE_DELAY_SECONDS,
    DiscoveredPost,
    PatreonDiscovery,
)


@pytest.fixture
def disc():
    return PatreonDiscovery(campaign_id="5008493")


@pytest.fixture
def fixture_response():
    fixture_path = Path(__file__).parent / "fixtures" / "patreon_api_response.json"
    return json.loads(fixture_path.read_text())


def _mock_urlopen(response_data):
    mock_resp = MagicMock()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = json.dumps(response_data).encode()
    return mock_resp


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


# --- DiscoveredPost dataclass ---

def test_discovered_post_defaults():
    p = DiscoveredPost(
        post_id="1", url="https://example.com", title="Test",
        created_at="2025-01-01", post_type="text", has_video=False,
    )
    assert p.recorded is False
    assert p.recording_date is None


def test_discovered_post_has_video_for_video_types():
    p1 = _sample_post(post_id="1", has_video=True)
    assert p1.has_video is True
    assert p1.post_type == "video_external_file"

    p2 = DiscoveredPost(
        post_id="2", url="https://example.com/2", title="Embed",
        created_at="2025-01-01", post_type="video_embed", has_video=True,
    )
    assert p2.has_video is True


def test_discovered_post_has_video_false_for_non_video():
    p1 = _sample_post(has_video=False)
    assert p1.has_video is False
    assert p1.post_type == "text_only"

    p2 = DiscoveredPost(
        post_id="2", url="https://example.com/2", title="Pod",
        created_at="2025-01-01", post_type="podcast", has_video=False,
    )
    assert p2.has_video is False


# --- fetch_posts ---

def test_fetch_posts_parses_response(disc, fixture_response):
    mock_resp = _mock_urlopen(fixture_response)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        posts = disc.fetch_posts()

    assert len(posts) == 4

    # Post 0: video_external_file with video_preview duration
    p0 = posts[0]
    assert p0.post_id == "119811238"
    assert p0.title == "Masterclass 19 - Munger Mental Models"
    assert p0.post_type == "video_external_file"
    assert p0.has_video is True
    assert p0.has_audio is False
    assert p0.created_at == "2025-01-15T18:30:00.000+00:00"
    assert p0.url == "https://www.patreon.com/firedupwealth/posts/masterclass-19-119811238"
    assert p0.published_at == "2025-01-15T18:45:00.000+00:00"
    assert p0.edited_at == "2025-01-16T10:00:00.000+00:00"
    assert p0.duration_seconds == 1651.0
    assert p0.like_count == 42
    assert p0.comment_count == 7
    assert p0.is_paid is True
    assert p0.min_cents_pledged_to_view == 7500
    assert p0.tags == ["masterclass", "stock market investing"]
    assert p0.embed_url is None
    assert p0.embed_provider is None
    assert "thumb.jpg" in p0.thumbnail_url

    # Post 1: video_embed with YouTube embed URL
    p1 = posts[1]
    assert p1.post_id == "119500001"
    assert p1.has_video is True
    assert p1.embed_url == "https://youtu.be/hMprXab8x8E?si=B-Wl3aUJiMBAWlsI"
    assert p1.embed_provider == "YouTube"
    assert p1.duration_seconds is None  # video_embed has no duration
    assert p1.tags == ["Chart day", "technical analysis"]

    # Post 2: text_only — no video, no audio
    p2 = posts[2]
    assert p2.post_id == "119200002"
    assert p2.has_video is False
    assert p2.has_audio is False
    assert p2.post_type == "text_only"
    assert p2.tags is None  # empty tag list becomes None

    # Post 3: podcast with post_file duration
    p3 = posts[3]
    assert p3.post_id == "118900003"
    assert p3.has_video is False
    assert p3.has_audio is True
    assert p3.post_type == "podcast"
    assert p3.duration_seconds == 4233.0
    assert p3.is_paid is True
    assert p3.min_cents_pledged_to_view == 6000
    assert p3.tags == ["dividend portfolio", "podcast"]


def test_fetch_posts_pagination(disc):
    page1 = {
        "data": [{"id": "1", "attributes": {"title": "Post 1", "created_at": "2025-01-15", "post_type": "video_external_file"}, "type": "post"}],
        "meta": {"pagination": {"total": 2, "cursors": {"next": "cursor123"}}},
    }
    page2 = {
        "data": [{"id": "2", "attributes": {"title": "Post 2", "created_at": "2025-01-10", "post_type": "video_embed"}, "type": "post"}],
        "meta": {"pagination": {"total": 2}},
    }

    call_count = 0

    def mock_urlopen(req, timeout=30):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _mock_urlopen(page1)
        return _mock_urlopen(page2)

    with patch("urllib.request.urlopen", side_effect=mock_urlopen), \
         patch("time.sleep"):
        posts = disc.fetch_posts(max_pages=5)

    assert len(posts) == 2
    assert posts[0].post_id == "1"
    assert posts[1].post_id == "2"
    assert call_count == 2


def test_fetch_posts_media_type_filter(disc):
    resp = {"data": [], "meta": {}}
    mock_resp = _mock_urlopen(resp)

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
        disc.fetch_posts(media_type="video")

    call_args = mock_open.call_args
    req = call_args[0][0]
    assert "filter[media_types]=video" in req.full_url


def test_fetch_posts_no_media_type_filter(disc):
    resp = {"data": [], "meta": {}}
    mock_resp = _mock_urlopen(resp)

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
        disc.fetch_posts(media_type=None)

    call_args = mock_open.call_args
    req = call_args[0][0]
    assert "filter[media_types]" not in req.full_url


def test_fetch_posts_respects_max_pages(disc):
    page_with_cursor = {
        "data": [{"id": "1", "attributes": {"title": "Post", "created_at": "2025-01-15", "post_type": "video_external_file"}, "type": "post"}],
        "meta": {"pagination": {"total": 100, "cursors": {"next": "cursor123"}}},
    }
    mock_resp = _mock_urlopen(page_with_cursor)

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
        disc.fetch_posts(max_pages=1)

    assert mock_open.call_count == 1


def test_fetch_posts_network_error_returns_partial(disc):
    page1 = {
        "data": [{"id": "1", "attributes": {"title": "Post 1", "created_at": "2025-01-15", "post_type": "video_external_file"}, "type": "post"}],
        "meta": {"pagination": {"total": 2, "cursors": {"next": "cursor123"}}},
    }

    call_count = 0

    def mock_urlopen(req, timeout=30):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _mock_urlopen(page1)
        raise urllib.error.URLError("Connection refused")

    with patch("urllib.request.urlopen", side_effect=mock_urlopen), \
         patch("time.sleep"):
        posts = disc.fetch_posts(max_pages=5)

    assert len(posts) == 1
    assert posts[0].post_id == "1"


def test_fetch_posts_immediate_network_error_returns_empty(disc):
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
        posts = disc.fetch_posts()

    assert posts == []


def test_fetch_posts_cursor_url_encoded(disc):
    resp = {"data": [], "meta": {}}
    page1 = {
        "data": [{"id": "1", "attributes": {"title": "P", "created_at": "2025-01-15", "post_type": "video_external_file"}, "type": "post"}],
        "meta": {"pagination": {"total": 2, "cursors": {"next": "abc+def=123"}}},
    }

    call_count = 0

    def mock_urlopen(req, timeout=30):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _mock_urlopen(page1)
        assert "abc%2Bdef%3D123" in req.full_url
        return _mock_urlopen(resp)

    with patch("urllib.request.urlopen", side_effect=mock_urlopen), \
         patch("time.sleep"):
        disc.fetch_posts(max_pages=2)


def test_fetch_posts_page_delay(disc):
    page1 = {
        "data": [{"id": "1", "attributes": {"title": "P1", "created_at": "2025-01-15", "post_type": "video_external_file"}, "type": "post"}],
        "meta": {"pagination": {"total": 2, "cursors": {"next": "c1"}}},
    }
    page2 = {
        "data": [{"id": "2", "attributes": {"title": "P2", "created_at": "2025-01-10", "post_type": "video_embed"}, "type": "post"}],
        "meta": {"pagination": {"total": 2}},
    }

    call_count = 0

    def mock_urlopen(req, timeout=30):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _mock_urlopen(page1)
        return _mock_urlopen(page2)

    with patch("urllib.request.urlopen", side_effect=mock_urlopen), \
         patch("time.sleep") as mock_sleep:
        disc.fetch_posts(max_pages=5)

    mock_sleep.assert_called_once_with(PAGE_DELAY_SECONDS)


# --- check_cooldown ---

def test_check_cooldown_no_file(disc, tmp_path):
    assert disc.check_cooldown(tmp_path) is True


def test_check_cooldown_expired(disc, tmp_path):
    old_time = datetime.now(timezone.utc) - timedelta(hours=COOLDOWN_HOURS + 1)
    (tmp_path / "last_discovery.txt").write_text(old_time.isoformat(), encoding="utf-8")
    assert disc.check_cooldown(tmp_path) is True


def test_check_cooldown_active(disc, tmp_path):
    recent_time = datetime.now(timezone.utc) - timedelta(hours=1)
    (tmp_path / "last_discovery.txt").write_text(recent_time.isoformat(), encoding="utf-8")
    assert disc.check_cooldown(tmp_path) is False


# --- update_cooldown ---

def test_update_cooldown_writes_file(disc, tmp_path):
    disc.update_cooldown(tmp_path)
    cooldown_file = tmp_path / "last_discovery.txt"
    assert cooldown_file.exists()
    ts = cooldown_file.read_text(encoding="utf-8").strip()
    datetime.fromisoformat(ts)


# --- diff_catalog ---

def test_diff_catalog_no_existing(disc, tmp_path):
    posts = [_sample_post("1"), _sample_post("2")]
    catalog_path = tmp_path / "catalog.json"
    new_posts = disc.diff_catalog(posts, catalog_path)
    assert len(new_posts) == 2


def test_diff_catalog_some_new(disc, tmp_path):
    catalog_path = tmp_path / "catalog.json"
    existing = [_sample_post("1")]
    disc.save_catalog(existing, catalog_path)

    discovered = [_sample_post("1"), _sample_post("2"), _sample_post("3")]
    new_posts = disc.diff_catalog(discovered, catalog_path)
    assert len(new_posts) == 2
    assert {p.post_id for p in new_posts} == {"2", "3"}


def test_diff_catalog_none_new(disc, tmp_path):
    catalog_path = tmp_path / "catalog.json"
    existing = [_sample_post("1"), _sample_post("2")]
    disc.save_catalog(existing, catalog_path)

    discovered = [_sample_post("1"), _sample_post("2")]
    new_posts = disc.diff_catalog(discovered, catalog_path)
    assert len(new_posts) == 0


# --- save_catalog ---

def test_save_catalog_structure(disc, tmp_path):
    catalog_path = tmp_path / "catalog.json"
    posts = [_sample_post("1"), _sample_post("2", has_video=False)]
    disc.save_catalog(posts, catalog_path)

    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert data["creator"] == "Mr. FIRED Up Wealth"
    assert data["campaign_id"] == "5008493"
    assert "last_discovery" in data
    assert data["total_posts"] == 2
    assert "video_posts" in data
    assert "audio_posts" in data
    assert len(data["posts"]) == 2


def test_save_catalog_sorted_by_date(disc, tmp_path):
    catalog_path = tmp_path / "catalog.json"
    posts = [
        _sample_post("1", created_at="2025-01-01T00:00:00+00:00"),
        _sample_post("2", created_at="2025-01-15T00:00:00+00:00"),
        _sample_post("3", created_at="2025-01-10T00:00:00+00:00"),
    ]
    disc.save_catalog(posts, catalog_path)

    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    dates = [p["created_at"] for p in data["posts"]]
    assert dates == sorted(dates, reverse=True)


def test_save_catalog_roundtrip(disc, tmp_path):
    catalog_path = tmp_path / "catalog.json"
    posts = [_sample_post("1", title="Alpha"), _sample_post("2", title="Beta")]
    disc.save_catalog(posts, catalog_path)

    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    loaded = [DiscoveredPost(**p) for p in data["posts"]]
    assert len(loaded) == 2
    assert loaded[0].title in ("Alpha", "Beta")


def test_save_catalog_video_count(disc, tmp_path):
    catalog_path = tmp_path / "catalog.json"
    posts = [
        _sample_post("1", has_video=True),
        _sample_post("2", has_video=False),
        _sample_post("3", has_video=True),
    ]
    disc.save_catalog(posts, catalog_path)

    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert data["video_posts"] == 2


# --- Enriched fields ---

def test_discovered_post_has_audio():
    p1 = DiscoveredPost(
        post_id="1", url="u", title="Pod", created_at="2025-01-01",
        post_type="podcast", has_video=False, has_audio=True,
    )
    assert p1.has_audio is True
    p2 = DiscoveredPost(
        post_id="2", url="u", title="Audio", created_at="2025-01-01",
        post_type="audio_file", has_video=False, has_audio=True,
    )
    assert p2.has_audio is True
    p3 = _sample_post(has_video=True)
    assert p3.has_audio is False


def test_discovered_post_enriched_defaults():
    p = _sample_post()
    assert p.published_at is None
    assert p.edited_at is None
    assert p.duration_seconds is None
    assert p.embed_url is None
    assert p.embed_provider is None
    assert p.thumbnail_url is None
    assert p.like_count is None
    assert p.comment_count is None
    assert p.is_paid is None
    assert p.min_cents_pledged_to_view is None
    assert p.tags is None


def test_has_video_includes_livestream_youtube():
    """livestream_youtube posts should be classified as video."""
    resp = {
        "data": [{"id": "99", "attributes": {
            "title": "Live Stream",
            "created_at": "2025-06-01",
            "post_type": "livestream_youtube",
        }, "type": "post"}],
        "meta": {},
    }
    mock_resp = _mock_urlopen(resp)
    disc = PatreonDiscovery()
    with patch("urllib.request.urlopen", return_value=mock_resp):
        posts = disc.fetch_posts()
    assert len(posts) == 1
    assert posts[0].has_video is True
    assert posts[0].has_audio is False


def test_fetch_posts_uses_canonical_url():
    """When the API provides a 'url' attribute, use it instead of constructing one."""
    resp = {
        "data": [{"id": "42", "attributes": {
            "title": "Test",
            "created_at": "2025-01-01",
            "post_type": "text_only",
            "url": "https://www.patreon.com/creator/posts/test-42",
        }, "type": "post"}],
        "meta": {},
    }
    mock_resp = _mock_urlopen(resp)
    disc = PatreonDiscovery()
    with patch("urllib.request.urlopen", return_value=mock_resp):
        posts = disc.fetch_posts()
    assert posts[0].url == "https://www.patreon.com/creator/posts/test-42"


def test_fetch_posts_fallback_url_when_no_attr():
    """When 'url' attribute is missing, fall back to constructed URL."""
    resp = {
        "data": [{"id": "42", "attributes": {
            "title": "Test",
            "created_at": "2025-01-01",
            "post_type": "text_only",
        }, "type": "post"}],
        "meta": {},
    }
    mock_resp = _mock_urlopen(resp)
    disc = PatreonDiscovery()
    with patch("urllib.request.urlopen", return_value=mock_resp):
        posts = disc.fetch_posts()
    assert posts[0].url == "https://www.patreon.com/posts/42"


def test_fetch_posts_extracts_tags():
    """Tags from relationships are extracted with prefix stripped."""
    resp = {
        "data": [{"id": "55", "attributes": {
            "title": "Tagged",
            "created_at": "2025-01-01",
            "post_type": "text_only",
        }, "relationships": {
            "user_defined_tags": {"data": [
                {"id": "user_defined;masterclass", "type": "post_tag"},
                {"id": "user_defined;Chart day", "type": "post_tag"},
            ]},
        }, "type": "post"}],
        "meta": {},
    }
    mock_resp = _mock_urlopen(resp)
    disc = PatreonDiscovery()
    with patch("urllib.request.urlopen", return_value=mock_resp):
        posts = disc.fetch_posts()
    assert posts[0].tags == ["masterclass", "Chart day"]


def test_fetch_posts_empty_tags_become_none():
    """Empty tag lists become None (not an empty list)."""
    resp = {
        "data": [{"id": "56", "attributes": {
            "title": "No Tags",
            "created_at": "2025-01-01",
            "post_type": "text_only",
        }, "relationships": {
            "user_defined_tags": {"data": []},
        }, "type": "post"}],
        "meta": {},
    }
    mock_resp = _mock_urlopen(resp)
    disc = PatreonDiscovery()
    with patch("urllib.request.urlopen", return_value=mock_resp):
        posts = disc.fetch_posts()
    assert posts[0].tags is None


def test_save_catalog_audio_count(disc, tmp_path):
    catalog_path = tmp_path / "catalog.json"
    posts = [
        _sample_post("1", has_video=True),
        _sample_post("2", has_video=False, post_type="podcast", has_audio=True),
        _sample_post("3", has_video=False, post_type="audio_file", has_audio=True),
    ]
    disc.save_catalog(posts, catalog_path)

    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert data["video_posts"] == 1
    assert data["audio_posts"] == 2


# --- Constants ---

def test_constants_reasonable():
    assert COOLDOWN_HOURS >= 1
    assert PAGE_DELAY_SECONDS > 0
    assert MAX_PAGES <= 100
