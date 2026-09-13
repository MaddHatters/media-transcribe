"""Tests for SSH-aware background execution via Windows scheduled tasks."""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _make_args(command: str = "pipeline") -> argparse.Namespace:
    return argparse.Namespace(command=command)


# --- is_ssh_session detection ---

def test_is_ssh_session_with_ssh_client(monkeypatch):
    monkeypatch.setenv("SSH_CLIENT", "1.2.3.4 5678 22")
    from src.capture.environment import is_ssh_session
    assert is_ssh_session() is True


def test_is_ssh_session_with_ssh_connection(monkeypatch):
    monkeypatch.setenv("SSH_CONNECTION", "1.2.3.4 5678 5.6.7.8 22")
    monkeypatch.delenv("SSH_CLIENT", raising=False)
    from src.capture.environment import is_ssh_session
    assert is_ssh_session() is True


def test_is_ssh_session_no_ssh_env(monkeypatch):
    monkeypatch.delenv("SSH_CLIENT", raising=False)
    monkeypatch.delenv("SSH_CONNECTION", raising=False)
    monkeypatch.setattr("src.capture.environment.IS_WINDOWS", False)
    from src.capture.environment import is_ssh_session
    assert is_ssh_session() is False


# --- background_relaunch routing ---

def test_background_relaunch_routes_to_schtask(monkeypatch, tmp_path):
    mock_schtask = MagicMock(return_value=0)
    monkeypatch.setattr("src.config.IS_WINDOWS", True)
    monkeypatch.setattr("src.capture.environment.is_ssh_session", lambda: True)
    monkeypatch.setattr("cli._background_via_scheduled_task", mock_schtask)
    from cli import background_relaunch
    args = _make_args()
    background_relaunch(args, tmp_path)
    mock_schtask.assert_called_once_with(args, tmp_path)


def test_background_relaunch_routes_to_subprocess(monkeypatch, tmp_path):
    mock_sub = MagicMock(return_value=0)
    monkeypatch.setattr("src.capture.environment.is_ssh_session", lambda: False)
    monkeypatch.setattr("cli._background_via_subprocess", mock_sub)
    from cli import background_relaunch
    args = _make_args()
    background_relaunch(args, tmp_path)
    mock_sub.assert_called_once_with(args, tmp_path)


# --- _background_via_scheduled_task ---

def _mock_subprocess_run_success(*args, **kwargs):
    mock = MagicMock()
    mock.returncode = 0
    mock.stdout = ""
    mock.stderr = ""
    return mock


def test_schtask_creates_batch_file(monkeypatch, tmp_path):
    monkeypatch.setattr("src.config.TEMP_BAT_DIR", tmp_path)
    monkeypatch.setattr("subprocess.run", _mock_subprocess_run_success)
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/uv")
    monkeypatch.setattr("cli.time.sleep", lambda x: None)
    monkeypatch.setattr("cli._find_pipeline_pid", lambda: 1234)

    from cli import _background_via_scheduled_task
    args = _make_args()
    log_dir = tmp_path / "logs"

    rc = _background_via_scheduled_task(args, log_dir)
    assert rc == 0

    bat_files = list(tmp_path.glob("_bg_pipeline_*.bat"))
    assert len(bat_files) == 1


def test_schtask_batch_file_content(monkeypatch, tmp_path):
    monkeypatch.setattr("src.config.TEMP_BAT_DIR", tmp_path)
    monkeypatch.setattr("subprocess.run", _mock_subprocess_run_success)
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/uv")
    monkeypatch.setattr("cli.time.sleep", lambda x: None)
    monkeypatch.setattr("cli._find_pipeline_pid", lambda: None)

    from cli import _background_via_scheduled_task
    rc = _background_via_scheduled_task(_make_args(), tmp_path / "logs")
    assert rc == 0

    bat_files = list(tmp_path.glob("_bg_pipeline_*.bat"))
    content = bat_files[0].read_text(encoding="utf-8")
    assert "@echo off" in content
    assert "cd /d " in content
    assert "--foreground" in content
    assert 'del "%~f0"' in content


def test_schtask_cleans_old_batch_files(monkeypatch, tmp_path):
    (tmp_path / "_bg_pipeline_old1.bat").write_text("old", encoding="utf-8")
    (tmp_path / "_bg_pipeline_old2.bat").write_text("old", encoding="utf-8")
    (tmp_path / "keep_this.bat").write_text("keep", encoding="utf-8")

    monkeypatch.setattr("src.config.TEMP_BAT_DIR", tmp_path)
    monkeypatch.setattr("subprocess.run", _mock_subprocess_run_success)
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/uv")
    monkeypatch.setattr("cli.time.sleep", lambda x: None)
    monkeypatch.setattr("cli._find_pipeline_pid", lambda: None)

    from cli import _background_via_scheduled_task
    _background_via_scheduled_task(_make_args(), tmp_path / "logs")

    remaining = [f.name for f in tmp_path.glob("*.bat")]
    assert "keep_this.bat" in remaining
    old_bg = [f for f in remaining if f.startswith("_bg_pipeline_old")]
    assert len(old_bg) == 0


def test_schtask_locked_batch_file_skipped(monkeypatch, tmp_path):
    locked = tmp_path / "_bg_pipeline_locked.bat"
    locked.write_text("locked", encoding="utf-8")

    original_unlink = Path.unlink

    def mock_unlink(self, missing_ok=False):
        if self.name == "_bg_pipeline_locked.bat":
            raise OSError("file in use")
        return original_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", mock_unlink)
    monkeypatch.setattr("src.config.TEMP_BAT_DIR", tmp_path)
    monkeypatch.setattr("subprocess.run", _mock_subprocess_run_success)
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/uv")
    monkeypatch.setattr("cli.time.sleep", lambda x: None)
    monkeypatch.setattr("cli._find_pipeline_pid", lambda: None)

    from cli import _background_via_scheduled_task
    rc = _background_via_scheduled_task(_make_args(), tmp_path / "logs")
    assert rc == 0
    assert locked.exists()


def test_schtask_create_failure(monkeypatch, tmp_path):
    call_count = 0

    def mock_run(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        mock = MagicMock()
        if call_count == 1:
            mock.returncode = 1
            mock.stderr = "Access denied"
        else:
            mock.returncode = 0
            mock.stdout = ""
        return mock

    monkeypatch.setattr("src.config.TEMP_BAT_DIR", tmp_path)
    monkeypatch.setattr("subprocess.run", mock_run)
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/uv")

    from cli import _background_via_scheduled_task
    rc = _background_via_scheduled_task(_make_args(), tmp_path / "logs")
    assert rc == 1


def test_schtask_run_failure(monkeypatch, tmp_path):
    call_count = 0

    def mock_run(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        mock = MagicMock()
        if call_count == 2:
            mock.returncode = 1
            mock.stderr = "Task not found"
        else:
            mock.returncode = 0
            mock.stdout = ""
        return mock

    monkeypatch.setattr("src.config.TEMP_BAT_DIR", tmp_path)
    monkeypatch.setattr("subprocess.run", mock_run)
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/uv")

    from cli import _background_via_scheduled_task
    rc = _background_via_scheduled_task(_make_args(), tmp_path / "logs")
    assert rc == 1


# --- _find_pipeline_pid ---

def test_find_pipeline_pid_with_results(monkeypatch):
    mock = MagicMock()
    mock.stdout = "1234\n5678\n"
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: mock)

    from cli import _find_pipeline_pid
    assert _find_pipeline_pid() == 1234


def test_find_pipeline_pid_no_results(monkeypatch):
    mock = MagicMock()
    mock.stdout = ""
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: mock)

    from cli import _find_pipeline_pid
    assert _find_pipeline_pid() is None


def test_find_pipeline_pid_timeout(monkeypatch):
    def raise_timeout(*a, **kw):
        raise subprocess.TimeoutExpired("powershell", 5)

    monkeypatch.setattr("subprocess.run", raise_timeout)

    from cli import _find_pipeline_pid
    assert _find_pipeline_pid() is None


# --- status subcommand parser ---

def test_status_parser():
    from cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["status"])
    assert args.command == "status"


# --- _handle_status cross-platform ---

def test_handle_status_linux_no_schtasks(monkeypatch, capsys):
    monkeypatch.setattr("src.config.IS_WINDOWS", False)
    from cli import _handle_status
    rc = _handle_status()
    assert rc == 0
    out = capsys.readouterr().out
    assert "only available on Windows" in out


def test_handle_status_windows_uses_schtasks(monkeypatch, capsys):
    monkeypatch.setattr("src.config.IS_WINDOWS", True)
    monkeypatch.setattr("src.config.SCHTASK_NAME_PREFIX", "MediaTranscribe_")

    def mock_run(*args, **kwargs):
        mock = MagicMock()
        mock.returncode = 1
        mock.stdout = ""
        return mock

    monkeypatch.setattr("subprocess.run", mock_run)
    monkeypatch.setattr("src.config.LOGS_DIR", tmp_dir := Path("/tmp/fake_logs"))

    from cli import _handle_status
    rc = _handle_status()
    assert rc == 0


# --- batch file quoting ---

def test_schtask_batch_file_quotes_paths(monkeypatch, tmp_path):
    monkeypatch.setattr("src.config.TEMP_BAT_DIR", tmp_path)
    monkeypatch.setattr("src.config.SCHTASK_NAME_PREFIX", "MediaTranscribe_")
    monkeypatch.setattr("subprocess.run", _mock_subprocess_run_success)
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/uv")
    monkeypatch.setattr("cli.time.sleep", lambda x: None)
    monkeypatch.setattr("cli._find_pipeline_pid", lambda: None)
    monkeypatch.setattr("os.getcwd", lambda: r"C:\Users\Matt\My Project")

    from cli import _background_via_scheduled_task
    rc = _background_via_scheduled_task(_make_args(), tmp_path / "logs")
    assert rc == 0

    bat_files = list(tmp_path.glob("_bg_pipeline_*.bat"))
    content = bat_files[0].read_text(encoding="utf-8")
    assert 'cd /d "C:\\Users\\Matt\\My Project"' in content


def test_schtask_uses_name_prefix_constant(monkeypatch, tmp_path):
    calls = []

    def mock_run(cmd, **kwargs):
        calls.append(cmd)
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = ""
        mock.stderr = ""
        return mock

    monkeypatch.setattr("src.config.TEMP_BAT_DIR", tmp_path)
    monkeypatch.setattr("src.config.SCHTASK_NAME_PREFIX", "TestPrefix_")
    monkeypatch.setattr("subprocess.run", mock_run)
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/uv")
    monkeypatch.setattr("cli.time.sleep", lambda x: None)
    monkeypatch.setattr("cli._find_pipeline_pid", lambda: None)

    from cli import _background_via_scheduled_task
    _background_via_scheduled_task(_make_args(), tmp_path / "logs")

    create_call = calls[0]
    tn_idx = create_call.index("/tn") + 1
    assert create_call[tn_idx] == "TestPrefix_pipeline"
