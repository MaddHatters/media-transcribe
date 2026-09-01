"""Tests for crash guards, excepthook, stuck-detection, and logging config."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.logging_config import (
    _emergency_stop_obs,
    _unhandled_exception_hook,
    setup_logging,
)


# --- Crash guard tests ---


def test_emergency_stop_obs_no_crash_when_unreachable():
    mock_cls = MagicMock(side_effect=ConnectionRefusedError)
    with patch.dict("sys.modules", {"src.engines.obs_engine": MagicMock(OBSEngine=mock_cls)}):
        _emergency_stop_obs()


def test_emergency_stop_obs_stops_active_recording():
    mock_engine = MagicMock()
    mock_engine.is_recording.return_value = True
    mock_cls = MagicMock(return_value=mock_engine)

    with patch.dict("sys.modules", {"src.engines.obs_engine": MagicMock(OBSEngine=mock_cls)}):
        _emergency_stop_obs()

    mock_engine.stop.assert_called_once()


def test_emergency_stop_obs_no_stop_when_not_recording():
    mock_engine = MagicMock()
    mock_engine.is_recording.return_value = False
    mock_cls = MagicMock(return_value=mock_engine)

    with patch.dict("sys.modules", {"src.engines.obs_engine": MagicMock(OBSEngine=mock_cls)}):
        _emergency_stop_obs()

    mock_engine.stop.assert_not_called()


# --- Excepthook tests ---


def test_excepthook_logs_to_file(tmp_path):
    log_file = tmp_path / "test.log"
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)

    try:
        raise ValueError("test crash")
    except ValueError:
        import sys
        _unhandled_exception_hook(*sys.exc_info())

    handler.flush()
    handler.close()
    root.removeHandler(handler)

    content = log_file.read_text(encoding="utf-8")
    assert "test crash" in content
    assert "CRITICAL" in content


# --- Logging config tests ---


def test_setup_logging_creates_log_file(tmp_path):
    with patch("src.logging_config.LOGS_DIR", tmp_path, create=True), \
         patch("src.config.LOGS_DIR", tmp_path), \
         patch("src.config.IS_WINDOWS", False):
        root = logging.getLogger()
        original_handlers = root.handlers[:]

        log_path = setup_logging("test", foreground=True)

        assert log_path.exists()
        assert log_path.parent == tmp_path
        assert "test_" in log_path.name

        for h in root.handlers:
            if h not in original_handlers:
                root.removeHandler(h)
                h.close()

        import signal
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        signal.signal(signal.SIGINT, signal.SIG_DFL)

        import atexit
        atexit.unregister(_emergency_stop_obs)


def test_setup_logging_format(tmp_path):
    with patch("src.logging_config.LOGS_DIR", tmp_path, create=True), \
         patch("src.config.LOGS_DIR", tmp_path), \
         patch("src.config.IS_WINDOWS", False):
        root = logging.getLogger()
        original_handlers = root.handlers[:]

        log_path = setup_logging("fmttest", foreground=False)

        test_logger = logging.getLogger("test.format")
        test_logger.info("hello format check")

        for h in root.handlers:
            if h not in original_handlers:
                h.flush()

        content = log_path.read_text(encoding="utf-8")
        assert "INFO" in content
        assert "test.format" in content
        assert "hello format check" in content

        for h in root.handlers:
            if h not in original_handlers:
                root.removeHandler(h)
                h.close()

        import signal
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        signal.signal(signal.SIGINT, signal.SIG_DFL)

        import atexit
        atexit.unregister(_emergency_stop_obs)


# --- Stuck-detection tests ---


@pytest.mark.asyncio
async def test_stuck_detection_stops_recording():
    from src.capture.recorder import Recorder, STUCK_THRESHOLD

    mock_engine = MagicMock()
    mock_engine.stop = MagicMock(return_value="/tmp/stuck.mkv")
    recorder = Recorder(mock_engine)

    mock_cdp = AsyncMock()
    mock_handler = AsyncMock()
    mock_detection = MagicMock()

    mock_handler.get_duration = AsyncMock(return_value=600.0)
    mock_handler.get_position = AsyncMock(return_value=100.0)
    mock_handler.is_ended = AsyncMock(return_value=False)
    mock_handler.fullscreen = AsyncMock(return_value=True)

    with patch("src.capture.recorder.detect_player", return_value=(mock_detection, mock_handler)), \
         patch("asyncio.sleep", new_callable=AsyncMock), \
         patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
        mock_to_thread.return_value = None

        result = await recorder.record_one(mock_cdp, "http://test", "test")

    assert result.ok is False
    assert "stuck" in result.error.lower()


@pytest.mark.asyncio
async def test_stuck_detection_resets_on_advance():
    from src.capture.recorder import Recorder, STUCK_THRESHOLD

    mock_engine = MagicMock()
    mock_engine.stop = MagicMock(return_value="/tmp/ok.mkv")
    recorder = Recorder(mock_engine)

    mock_cdp = AsyncMock()
    mock_handler = AsyncMock()
    mock_detection = MagicMock()

    mock_handler.get_duration = AsyncMock(return_value=600.0)
    mock_handler.fullscreen = AsyncMock(return_value=True)

    positions = [100.0] * 4 + [200.0, 500.0, 599.0]
    call_count = 0

    async def position_side_effect(*a, **kw):
        nonlocal call_count
        idx = min(call_count, len(positions) - 1)
        call_count += 1
        return positions[idx]

    mock_handler.get_position = position_side_effect

    ended_calls = 0

    async def ended_side_effect(*a, **kw):
        nonlocal ended_calls
        ended_calls += 1
        return ended_calls >= len(positions)

    mock_handler.is_ended = ended_side_effect

    with patch("src.capture.recorder.detect_player", return_value=(mock_detection, mock_handler)), \
         patch("asyncio.sleep", new_callable=AsyncMock), \
         patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
        mock_to_thread.return_value = "/tmp/ok.mkv"

        result = await recorder.record_one(mock_cdp, "http://test", "test")

    assert result.error is None or "stuck" not in (result.error or "").lower()


# --- Pipeline guard tests ---


@pytest.mark.asyncio
async def test_pipeline_emergency_stop_on_crash():
    from src.pipeline.runner import Pipeline, PipelineResult

    mock_engine = MagicMock()
    mock_engine.is_recording.return_value = True
    pipeline = Pipeline(
        source=MagicMock(), engine=mock_engine, enable_breaks=True,
    )

    posts = [
        MagicMock(url="http://a", title="A", filename="a"),
        MagicMock(url="http://b", title="B", filename="b"),
    ]

    with patch.object(pipeline, "_process_one", new_callable=AsyncMock) as mock_p, \
         patch("asyncio.to_thread", side_effect=RuntimeError("process-level crash")):
        mock_p.return_value = PipelineResult(post_url="x", post_title="X")
        with pytest.raises(RuntimeError, match="process-level crash"):
            await pipeline.run(posts, steps=["record"])

    mock_engine.stop.assert_called_once()
