"""Tests for TransferClient — mock SSH/SCP subprocess calls."""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from src.transfer.sync import TransferClient


@pytest.fixture
def client():
    return TransferClient(host="testhost")


@patch("src.transfer.sync.subprocess.run")
def test_upload_success(mock_run, client, tmp_path):
    mock_run.return_value = MagicMock(returncode=0)
    local = tmp_path / "test.txt"
    local.write_text("hello")
    assert client.upload(local, "/remote/test.txt") is True


@patch("src.transfer.sync.subprocess.run")
def test_upload_failure(mock_run, client, tmp_path):
    mock_run.return_value = MagicMock(returncode=1, stderr="connection refused")
    local = tmp_path / "test.txt"
    local.write_text("hello")
    assert client.upload(local, "/remote/test.txt") is False


@patch("src.transfer.sync.subprocess.run")
def test_download_success(mock_run, client, tmp_path):
    mock_run.return_value = MagicMock(returncode=0)
    result = client.download("/remote/test.txt", tmp_path / "test.txt")
    assert result == tmp_path / "test.txt"


@patch("src.transfer.sync.subprocess.run")
def test_download_failure(mock_run, client, tmp_path):
    mock_run.return_value = MagicMock(returncode=1, stderr="not found")
    result = client.download("/remote/test.txt", tmp_path / "test.txt")
    assert result is None


@patch("src.transfer.sync.subprocess.run")
def test_sync_transcripts_filters_existing(mock_run, client, tmp_path):
    ls_result = MagicMock(returncode=0, stdout="file1.srt\nfile2.txt\nfile3.srt\n")
    scp_result = MagicMock(returncode=0)
    mock_run.side_effect = [ls_result, scp_result, scp_result]

    (tmp_path / "file1.srt").write_text("existing")

    synced = client.sync_transcripts("/remote/dir/", tmp_path)
    assert "file2.txt" in synced
    assert "file3.srt" in synced
    assert "file1.srt" not in synced
