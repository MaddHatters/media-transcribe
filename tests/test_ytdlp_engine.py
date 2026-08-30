"""Tests for YtDlpEngine — yt-dlp subprocess capture engine."""
from unittest.mock import MagicMock, patch, PropertyMock
import pytest

from src.engines.ytdlp_engine import YtDlpEngine
from src.engines.base import EngineStatus


def test_start_launches_subprocess():
    e = YtDlpEngine(output_dir="/tmp/ytdlp_test")
    e.set_url("https://youtube.com/watch?v=abc123")
    with patch("subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock()
        e.start("my_video")
    mock_popen.assert_called_once()
    cmd = mock_popen.call_args[0][0]
    assert "yt-dlp" in cmd[1]
    assert "https://youtube.com/watch?v=abc123" in cmd
    assert "--no-playlist" in cmd


def test_start_without_url_raises():
    e = YtDlpEngine()
    with pytest.raises(ValueError, match="URL not set"):
        e.start("video")


def test_stop_waits_for_subprocess_and_returns_path(tmp_path):
    e = YtDlpEngine(output_dir=str(tmp_path))
    e.set_url("https://example.com/video")

    test_file = tmp_path / "my_video.mp4"
    test_file.write_text("fake")

    proc = MagicMock()
    proc.wait = MagicMock()
    proc.returncode = 0
    e._proc = proc
    e._output_path = str(tmp_path / "my_video.%(ext)s")

    path = e.stop()
    proc.wait.assert_called_once()
    assert path is not None
    assert "my_video" in path


def test_stop_returns_none_on_failure():
    e = YtDlpEngine()
    proc = MagicMock()
    proc.wait = MagicMock()
    proc.returncode = 1
    e._proc = proc
    e._output_path = "/tmp/test.%(ext)s"
    assert e.stop() is None


def test_is_recording_checks_subprocess():
    e = YtDlpEngine()
    assert e.is_recording() is False

    proc = MagicMock()
    proc.poll.return_value = None
    e._proc = proc
    assert e.is_recording() is True

    proc.poll.return_value = 0
    assert e.is_recording() is False


def test_get_status_returns_engine_status():
    e = YtDlpEngine()
    status = e.get_status()
    assert isinstance(status, EngineStatus)
    assert status.recording is False


def test_output_path_templating(tmp_path):
    e = YtDlpEngine(output_dir=str(tmp_path))
    e.set_url("https://example.com")
    with patch("subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock()
        e.start("lecture_01")
    assert e._output_path == str(tmp_path / "lecture_01.%(ext)s")


def test_stop_without_process():
    e = YtDlpEngine()
    assert e.stop() is None


def test_start_file_not_found_raises_runtime_error():
    e = YtDlpEngine(output_dir="/tmp/ytdlp_test")
    e.set_url("https://example.com/video")
    with patch("subprocess.Popen", side_effect=FileNotFoundError()):
        with pytest.raises(RuntimeError, match="yt-dlp not found"):
            e.start("video")


def test_name_attribute():
    assert YtDlpEngine.name == "ytdlp"
