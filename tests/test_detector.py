"""Tests for player detection with sample DOM outputs."""
import json
import pytest
from unittest.mock import AsyncMock
from src.players.detector import detect_player
from src.players.mux import MuxPlayer
from src.players.vimeo import VimeoPlayer
from src.players.html5 import HTML5Player


@pytest.fixture
def cdp():
    mock = AsyncMock()
    mock.js = AsyncMock()
    return mock


async def test_detect_vimeo_iframe(cdp):
    cdp.js.return_value = json.dumps({
        "player": "vimeo",
        "element": "iframe[src*='vimeo']",
        "meta": {"src": "https://player.vimeo.com/video/123"},
    })
    result, handler = await detect_player(cdp)
    assert result.player == "vimeo"
    assert isinstance(handler, VimeoPlayer)


async def test_detect_mux_player(cdp):
    cdp.js.return_value = json.dumps({
        "player": "mux",
        "element": "mux-player",
        "meta": {"duration": 1200, "readyState": 4},
    })
    result, handler = await detect_player(cdp)
    assert result.player == "mux"
    assert isinstance(handler, MuxPlayer)


async def test_detect_plain_video(cdp):
    cdp.js.return_value = json.dumps({
        "player": "html5",
        "element": "video",
        "meta": {"duration": 600, "src": "blob:https://example.com/abc"},
    })
    result, handler = await detect_player(cdp)
    assert result.player == "html5"
    assert isinstance(handler, HTML5Player)


async def test_detect_no_player(cdp):
    cdp.js.return_value = json.dumps({
        "player": None,
        "element": None,
        "meta": {},
    })
    result, handler = await detect_player(cdp)
    assert result.player is None
    assert handler is None


async def test_detect_youtube_iframe(cdp):
    """YouTube iframes are detected but no handler exists yet — returns None handler."""
    cdp.js.return_value = json.dumps({
        "player": "youtube",
        "element": "iframe[src*='youtube']",
        "meta": {},
    })
    result, handler = await detect_player(cdp)
    assert result.player == "youtube"
    assert handler is None
