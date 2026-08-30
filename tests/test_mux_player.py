"""Tests for MuxPlayer handler."""
import json
import pytest
from unittest.mock import AsyncMock, patch
from src.players.mux import MuxPlayer
from src.players.base import DetectionResult


@pytest.fixture
def cdp():
    mock = AsyncMock()
    mock.js = AsyncMock()
    mock.click = AsyncMock()
    mock.key = AsyncMock()
    mock.move_mouse = AsyncMock()
    return mock


@pytest.fixture
def detection():
    return DetectionResult(
        player="mux",
        element="video",
        meta={"cx": 960, "cy": 540, "duration": 1800},
    )


async def test_get_duration(cdp, detection):
    cdp.js.return_value = 1800.5
    player = MuxPlayer()
    dur = await player.get_duration(cdp, detection)
    assert dur == 1800.5


async def test_play_calls_js(cdp, detection):
    player = MuxPlayer()
    await player.play(cdp, detection)
    cdp.js.assert_called_once()
    assert "play()" in cdp.js.call_args[0][0]


async def test_unmute_sets_volume(cdp):
    player = MuxPlayer()
    await player.unmute(cdp)
    call_expr = cdp.js.call_args[0][0]
    assert "muted = false" in call_expr
    assert "volume = 1.0" in call_expr


async def test_fullscreen_tac_trick_succeeds(cdp, detection):
    """Fullscreen should use TAC trick: inject click handler, CDP click at bbox center."""
    cdp.js.side_effect = [
        None,                                    # inject click handler
        json.dumps({"x": 960, "y": 540}),       # get bbox
        True,                                    # check fullscreenElement
    ]
    player = MuxPlayer()
    result = await player.fullscreen(cdp, detection)
    assert result is True
    cdp.click.assert_called_once_with(960, 540)


async def test_fullscreen_retries_three_times(cdp, detection):
    """Fullscreen retries up to 3 times before trying F11 fallback."""
    cdp.js.side_effect = [
        None, json.dumps({"x": 960, "y": 540}), False,   # attempt 1
        None, json.dumps({"x": 960, "y": 540}), False,   # attempt 2
        None, json.dumps({"x": 960, "y": 540}), False,   # attempt 3
        None,                                              # F11 fallback inject
        json.dumps({"x": 960, "y": 540}),                # F11 fallback bbox
        True,                                              # F11 check
    ]
    player = MuxPlayer()
    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await player.fullscreen(cdp, detection)
    assert result is True
    cdp.key.assert_called()


async def test_fullscreen_all_attempts_fail(cdp, detection):
    """If all fullscreen attempts fail, return False."""
    returns = []
    for _ in range(3):
        returns.extend([None, json.dumps({"x": 960, "y": 540}), False])
    returns.extend([None, json.dumps({"x": 960, "y": 540}), False])
    cdp.js.side_effect = returns
    player = MuxPlayer()
    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await player.fullscreen(cdp, detection)
    assert result is False
