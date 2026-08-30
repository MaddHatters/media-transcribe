"""Tests for Recorder — 10-step single-video state machine."""
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock, PropertyMock

from src.capture.recorder import Recorder, RecordResult, POLL_INTERVAL, STALL_THRESHOLD
from src.engines.null_engine import NullEngine
from src.players.base import DetectionResult


def _make_cdp(duration=1800.0, position_sequence=None, ended_sequence=None):
    """Create a mock CDPClient with configurable behavior."""
    cdp = AsyncMock()
    cdp.navigate = AsyncMock()
    cdp.move_mouse = AsyncMock()

    if position_sequence is None:
        position_sequence = [0.0, 900.0, 1798.0]
    if ended_sequence is None:
        ended_sequence = [False] * (len(position_sequence) - 1) + [True]

    return cdp, duration, position_sequence, ended_sequence


def _make_handler(duration=1800.0, position_sequence=None, ended_sequence=None):
    """Create a mock PlayerHandler."""
    if position_sequence is None:
        position_sequence = [0.0, 900.0, 1798.0]
    if ended_sequence is None:
        ended_sequence = [False] * (len(position_sequence) - 1) + [True]

    handler = AsyncMock()
    handler.get_duration = AsyncMock(return_value=duration)
    handler.get_position = AsyncMock(side_effect=position_sequence)
    handler.is_ended = AsyncMock(side_effect=ended_sequence)
    handler.play = AsyncMock()
    handler.pause = AsyncMock()
    handler.seek = AsyncMock()
    handler.fullscreen = AsyncMock(return_value=True)
    handler.unmute = AsyncMock()
    return handler


@pytest.fixture
def cdp():
    mock = AsyncMock()
    mock.js = AsyncMock(return_value="ok")
    mock.navigate = AsyncMock()
    mock.move_mouse = AsyncMock()
    return mock


async def test_happy_path(cdp):
    handler = _make_handler(
        duration=100.0,
        position_sequence=[0.0, 50.0, 99.0],
        ended_sequence=[False, False, True],
    )
    engine = NullEngine()

    with patch("src.capture.recorder.detect_player") as mock_detect, \
         patch("asyncio.sleep", new_callable=AsyncMock):
        mock_detect.return_value = (
            DetectionResult(player="mux", element="video", meta={}),
            handler,
        )
        recorder = Recorder(engine)
        result = await recorder.record_one(cdp, "https://example.com/video", "test_video")

    assert result.ok is True
    assert result.output_path == "/tmp/test_video.mp4"
    assert result.error is None
    handler.fullscreen.assert_called_once()
    handler.play.assert_called()


async def test_player_not_found(cdp):
    with patch("src.capture.recorder.detect_player") as mock_detect, \
         patch("asyncio.sleep", new_callable=AsyncMock):
        mock_detect.return_value = (
            DetectionResult(player=None, element=None, meta={}),
            None,
        )
        recorder = Recorder(NullEngine())
        result = await recorder.record_one(cdp, "https://example.com", "test")

    assert result.ok is False
    assert "No supported player" in result.error


async def test_fullscreen_failure(cdp):
    handler = _make_handler()
    handler.fullscreen.return_value = False

    with patch("src.capture.recorder.detect_player") as mock_detect, \
         patch("asyncio.sleep", new_callable=AsyncMock):
        mock_detect.return_value = (
            DetectionResult(player="mux", element="video", meta={}),
            handler,
        )
        recorder = Recorder(NullEngine())
        result = await recorder.record_one(cdp, "https://example.com", "test")

    assert result.ok is False
    assert "Fullscreen" in result.error


async def test_mute_guard_calls_unmute(cdp):
    handler = _make_handler(
        duration=100.0,
        position_sequence=[0.0, 50.0, 99.0],
        ended_sequence=[False, False, True],
    )

    with patch("src.capture.recorder.detect_player") as mock_detect, \
         patch("asyncio.sleep", new_callable=AsyncMock):
        mock_detect.return_value = (
            DetectionResult(player="mux", element="video", meta={}),
            handler,
        )
        recorder = Recorder(NullEngine())
        await recorder.record_one(cdp, "https://example.com", "test")

    # unmute is called in setup (steps 3, 5, 8) and during each monitor poll
    assert handler.unmute.call_count >= 3


async def test_stall_detection_nudge(cdp):
    stall_positions = [50.0] * (STALL_THRESHOLD + 2) + [99.0]
    stall_ended = [False] * (STALL_THRESHOLD + 2) + [True]

    handler = _make_handler(
        duration=100.0,
        position_sequence=stall_positions,
        ended_sequence=stall_ended,
    )

    with patch("src.capture.recorder.detect_player") as mock_detect, \
         patch("asyncio.sleep", new_callable=AsyncMock):
        mock_detect.return_value = (
            DetectionResult(player="mux", element="video", meta={}),
            handler,
        )
        recorder = Recorder(NullEngine())
        result = await recorder.record_one(cdp, "https://example.com", "test")

    assert result.ok is True
    # seek should be called for nudge (plus the setup seeks)
    seek_calls = handler.seek.call_args_list
    nudge_seeks = [c for c in seek_calls if c[0][1] == 50.5]
    assert len(nudge_seeks) >= 1


async def test_engine_start_failure(cdp):
    handler = _make_handler()

    engine = MagicMock()
    engine.name = "broken"
    engine.start = MagicMock(side_effect=RuntimeError("Engine exploded"))
    engine.is_recording = MagicMock(return_value=False)

    with patch("src.capture.recorder.detect_player") as mock_detect, \
         patch("asyncio.sleep", new_callable=AsyncMock):
        mock_detect.return_value = (
            DetectionResult(player="mux", element="video", meta={}),
            handler,
        )
        recorder = Recorder(engine)
        result = await recorder.record_one(cdp, "https://example.com", "test")

    assert result.ok is False
    assert "Engine exploded" in result.error


async def test_end_detection_by_ended(cdp):
    handler = _make_handler(
        duration=100.0,
        position_sequence=[50.0],
        ended_sequence=[True],
    )

    with patch("src.capture.recorder.detect_player") as mock_detect, \
         patch("asyncio.sleep", new_callable=AsyncMock):
        mock_detect.return_value = (
            DetectionResult(player="mux", element="video", meta={}),
            handler,
        )
        recorder = Recorder(NullEngine())
        result = await recorder.record_one(cdp, "https://example.com", "test")

    assert result.ok is True


async def test_end_detection_by_position(cdp):
    handler = _make_handler(
        duration=100.0,
        position_sequence=[99.0],
        ended_sequence=[False],
    )

    with patch("src.capture.recorder.detect_player") as mock_detect, \
         patch("asyncio.sleep", new_callable=AsyncMock):
        mock_detect.return_value = (
            DetectionResult(player="mux", element="video", meta={}),
            handler,
        )
        recorder = Recorder(NullEngine())
        result = await recorder.record_one(cdp, "https://example.com", "test")

    assert result.ok is True


async def test_duration_not_found(cdp):
    handler = _make_handler()
    handler.get_duration = AsyncMock(return_value=0)

    with patch("src.capture.recorder.detect_player") as mock_detect, \
         patch("asyncio.sleep", new_callable=AsyncMock):
        mock_detect.return_value = (
            DetectionResult(player="mux", element="video", meta={}),
            handler,
        )
        recorder = Recorder(NullEngine())
        result = await recorder.record_one(cdp, "https://example.com", "test")

    assert result.ok is False
    assert "duration" in result.error.lower()


async def test_pause_detection_auto_resume(cdp):
    positions = [0.0, 50.0, 50.0, 99.0]
    ended = [False, False, False, True]

    handler = _make_handler(
        duration=100.0,
        position_sequence=positions,
        ended_sequence=ended,
    )

    # First pause check returns True (paused), rest return False
    cdp.js = AsyncMock(side_effect=[
        "ok",  # exit fullscreen
        None,  # pause check poll 1 - not paused
        True,  # pause check poll 2 - PAUSED
        False,  # pause check poll 3 - not paused
    ])

    with patch("src.capture.recorder.detect_player") as mock_detect, \
         patch("asyncio.sleep", new_callable=AsyncMock):
        mock_detect.return_value = (
            DetectionResult(player="mux", element="video", meta={}),
            handler,
        )
        recorder = Recorder(NullEngine())
        result = await recorder.record_one(cdp, "https://example.com", "test")

    assert result.ok is True
    # play should be called extra time for auto-resume
    play_calls = handler.play.call_count
    assert play_calls >= 2  # at least 1 for step 8, 1 for auto-resume


async def test_record_result_defaults():
    r = RecordResult()
    assert r.ok is False
    assert r.url == ""
    assert r.output_path is None
    assert r.error is None
