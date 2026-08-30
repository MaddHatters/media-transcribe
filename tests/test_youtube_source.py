"""Tests for YouTubeSource — catalog via yt-dlp."""
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.sources.youtube import YouTubeSource
from src.sources.base import Post


@pytest.fixture
def cdp():
    mock = AsyncMock()
    mock.js = AsyncMock()
    mock.navigate = AsyncMock()
    return mock


async def test_authenticate_always_true(cdp):
    source = YouTubeSource()
    assert await source.authenticate(cdp) is True


async def test_get_posts_parses_playlist(cdp):
    playlist_data = {
        "entries": [
            {
                "webpage_url": "https://youtube.com/watch?v=abc",
                "title": "Lecture 1",
                "duration": 3600,
            },
            {
                "webpage_url": "https://youtube.com/watch?v=def",
                "title": "Lecture 2",
                "duration": 1800,
            },
        ]
    }
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = json.dumps(playlist_data)
    proc.stderr = ""

    with patch("asyncio.to_thread", new_callable=AsyncMock, return_value=proc):
        source = YouTubeSource()
        posts = await source.get_posts(cdp, "https://youtube.com/playlist?list=PL123")

    assert len(posts) == 2
    assert isinstance(posts[0], Post)
    assert posts[0].title == "Lecture 1"
    assert posts[0].duration == 3600
    assert posts[1].url == "https://youtube.com/watch?v=def"


async def test_get_posts_no_query(cdp):
    source = YouTubeSource()
    posts = await source.get_posts(cdp)
    assert posts == []


async def test_get_posts_single_video(cdp):
    video_data = {
        "webpage_url": "https://youtube.com/watch?v=xyz",
        "title": "Single Video",
        "duration": 600,
    }
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = json.dumps(video_data)
    proc.stderr = ""

    with patch("asyncio.to_thread", new_callable=AsyncMock, return_value=proc):
        source = YouTubeSource()
        posts = await source.get_posts(cdp, "https://youtube.com/watch?v=xyz")

    assert len(posts) == 1
    assert posts[0].title == "Single Video"


async def test_get_posts_subprocess_failure(cdp):
    proc = MagicMock()
    proc.returncode = 1
    proc.stdout = ""
    proc.stderr = "ERROR: Video not found"

    with patch("asyncio.to_thread", new_callable=AsyncMock, return_value=proc):
        source = YouTubeSource()
        posts = await source.get_posts(cdp, "https://youtube.com/watch?v=bad")

    assert posts == []


async def test_get_posts_timeout(cdp):
    import subprocess
    with patch("asyncio.to_thread", new_callable=AsyncMock, side_effect=subprocess.TimeoutExpired("cmd", 60)):
        source = YouTubeSource()
        posts = await source.get_posts(cdp, "https://youtube.com/playlist?list=PL123")
    assert posts == []


async def test_navigate_to(cdp):
    source = YouTubeSource()
    await source.navigate_to(cdp, "https://youtube.com/watch?v=abc")
    cdp.navigate.assert_called_once_with("https://youtube.com/watch?v=abc", wait=8.0)


def test_name_attribute():
    assert YouTubeSource.name == "youtube"
