"""Tests for NullEngine — testing stub for CaptureEngine protocol."""
from src.engines.null_engine import NullEngine
from src.engines.base import EngineStatus


def test_start_sets_recording_state():
    e = NullEngine()
    assert not e.is_recording()
    e.start("test_video")
    assert e.is_recording()


def test_stop_returns_path_and_clears_state():
    e = NullEngine()
    e.start("test_video")
    path = e.stop()
    assert path == "/tmp/test_video.mp4"
    assert not e.is_recording()


def test_stop_without_start_returns_none():
    e = NullEngine()
    path = e.stop()
    assert path is None
    assert not e.is_recording()


def test_is_recording_reflects_state():
    e = NullEngine()
    assert e.is_recording() is False
    e.start("vid")
    assert e.is_recording() is True
    e.stop()
    assert e.is_recording() is False


def test_get_status_returns_engine_status():
    e = NullEngine()
    status = e.get_status()
    assert isinstance(status, EngineStatus)
    assert status.recording is False

    e.start("vid")
    status = e.get_status()
    assert status.recording is True


def test_double_start_is_idempotent():
    e = NullEngine()
    e.start("first")
    e.start("second")
    assert e.is_recording()
    path = e.stop()
    assert path == "/tmp/second.mp4"


def test_name_attribute():
    assert NullEngine.name == "null"
