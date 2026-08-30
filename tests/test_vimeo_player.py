"""Tests for VimeoPlayer handler."""
import pytest
from unittest.mock import AsyncMock
from src.players.vimeo import VimeoPlayer
from src.players.base import DetectionResult


@pytest.fixture
def cdp():
    mock = AsyncMock()
    mock.js = AsyncMock()
    mock.click = AsyncMock()
    return mock


@pytest.fixture
def detection():
    return DetectionResult(
        player="vimeo",
        element="iframe[src*='vimeo']",
        meta={},
    )


async def test_play_injects_vimeo_sdk_and_calls_play(cdp, detection):
    player = VimeoPlayer()
    await player.play(cdp, detection)
    calls = [c[0][0] for c in cdp.js.call_args_list]
    assert any("Vimeo.Player" in c for c in calls), "Should create Vimeo.Player"
    assert any("play()" in c for c in calls), "Should call play()"


async def test_get_duration_uses_vimeo_api(cdp, detection):
    cdp.js.return_value = 3600.0
    player = VimeoPlayer()
    dur = await player.get_duration(cdp, detection)
    assert dur == 3600.0
    assert "getDuration" in cdp.js.call_args[0][0]


async def test_get_position_uses_vimeo_api(cdp):
    cdp.js.return_value = 120.5
    player = VimeoPlayer()
    pos = await player.get_position(cdp)
    assert pos == 120.5
    assert "getCurrentTime" in cdp.js.call_args[0][0]


async def test_fullscreen_on_iframe(cdp, detection):
    cdp.js.return_value = True
    player = VimeoPlayer()
    result = await player.fullscreen(cdp, detection)
    assert result is True
    assert "requestFullscreen" in cdp.js.call_args[0][0]


async def test_unmute_sets_volume(cdp):
    player = VimeoPlayer()
    await player.unmute(cdp)
    assert "setVolume(1.0)" in cdp.js.call_args[0][0]
