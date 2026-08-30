"""Tests for OBSEngine — OBS Studio WebSocket capture engine."""
from unittest.mock import MagicMock, patch, PropertyMock
import pytest

from src.engines.obs_engine import OBSEngine
from src.engines.base import EngineStatus


@pytest.fixture
def mock_obs_client():
    client = MagicMock()
    client.set_profile_parameter = MagicMock()
    client.start_record = MagicMock()
    client.stop_record = MagicMock()
    client.get_record_status = MagicMock()
    client.get_source_screenshot = MagicMock()
    client.base_client.ws.close = MagicMock()
    return client


@pytest.fixture
def engine(mock_obs_client):
    e = OBSEngine()
    e._client = mock_obs_client
    return e


def test_start_calls_set_profile_then_start_record(engine, mock_obs_client):
    with patch("time.sleep"):
        engine.start("my_video")
    mock_obs_client.set_profile_parameter.assert_called_once_with(
        "Output", "FilenameFormatting", "my_video",
    )
    mock_obs_client.start_record.assert_called_once()


def test_stop_calls_stop_record_and_returns_path(engine, mock_obs_client):
    resp = MagicMock()
    resp.output_path = "/videos/output.mp4"
    mock_obs_client.stop_record.return_value = resp
    path = engine.stop()
    mock_obs_client.stop_record.assert_called_once()
    assert path == "/videos/output.mp4"


def test_is_recording_checks_obs_status(engine, mock_obs_client):
    status = MagicMock()
    status.output_active = True
    mock_obs_client.get_record_status.return_value = status
    assert engine.is_recording() is True

    status.output_active = False
    assert engine.is_recording() is False


def test_get_status_returns_engine_status(engine, mock_obs_client):
    status_mock = MagicMock()
    status_mock.output_active = False
    mock_obs_client.get_record_status.return_value = status_mock
    status = engine.get_status()
    assert isinstance(status, EngineStatus)


def test_file_move_with_retry_succeeds_after_permission_errors(engine):
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        src_path = f.name

    try:
        with patch("shutil.move") as mock_move, \
             patch("os.path.getsize", return_value=1024 * 1024), \
             patch("time.sleep"):
            mock_move.side_effect = [
                PermissionError("locked"),
                PermissionError("locked"),
                PermissionError("locked"),
                None,
            ]
            result = engine.move_to_backup(src_path, "test_file")
            assert mock_move.call_count == 4
    finally:
        if os.path.exists(src_path):
            os.unlink(src_path)


def test_file_move_exhausts_retries(engine):
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        src_path = f.name

    try:
        with patch("shutil.move", side_effect=PermissionError("locked")), \
             patch("time.sleep"):
            result = engine.move_to_backup(src_path, "test_file")
            assert result == src_path
    finally:
        if os.path.exists(src_path):
            os.unlink(src_path)


def test_lazy_import_no_fail_at_creation():
    e = OBSEngine()
    assert e._client is None
    assert e.name == "obs"


def test_get_screenshot_returns_image_data(engine, mock_obs_client):
    resp = MagicMock()
    resp.image_data = "base64encodeddata"
    mock_obs_client.get_source_screenshot.return_value = resp
    data = engine.get_screenshot()
    assert data == "base64encodeddata"
    mock_obs_client.get_source_screenshot.assert_called_once()


def test_get_screenshot_without_client():
    e = OBSEngine()
    assert e.get_screenshot() is None


def test_disconnect(engine, mock_obs_client):
    engine.disconnect()
    mock_obs_client.base_client.ws.close.assert_called_once()
    assert engine._client is None


def test_stop_without_client():
    e = OBSEngine()
    assert e.stop() is None


def test_move_to_backup_nonexistent_file(engine):
    result = engine.move_to_backup("/nonexistent/file.mp4", "test")
    assert result is None


def test_move_to_backup_none_path(engine):
    result = engine.move_to_backup(None, "test")
    assert result is None
