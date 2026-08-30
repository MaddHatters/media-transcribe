"""Tests for generic HTML5Player handler."""
import pytest
from unittest.mock import AsyncMock
from src.players.html5 import HTML5Player
from src.players.base import DetectionResult


@pytest.fixture
def cdp():
    mock = AsyncMock()
    mock.js = AsyncMock()
    mock.click = AsyncMock()
    mock.key = AsyncMock()
    return mock


async def test_play_calls_video_play(cdp):
    player = HTML5Player()
    det = DetectionResult(player="html5", element="video", meta={})
    await player.play(cdp, det)
    assert "play()" in cdp.js.call_args[0][0]


async def test_name_is_html5():
    assert HTML5Player().name == "html5"
