"""Tests for environment setup & teardown module."""
import os
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# is_ssh_session()
# ---------------------------------------------------------------------------

def test_is_ssh_session_with_ssh_client():
    with patch.dict(os.environ, {"SSH_CLIENT": "192.168.1.1 12345 22"}):
        from src.capture.environment import is_ssh_session
        assert is_ssh_session() is True


def test_is_ssh_session_with_ssh_connection():
    with patch.dict(os.environ, {"SSH_CONNECTION": "192.168.1.1 12345 10.0.0.1 22"}):
        from src.capture.environment import is_ssh_session
        assert is_ssh_session() is True


def test_is_ssh_session_local(monkeypatch):
    monkeypatch.delenv("SSH_CLIENT", raising=False)
    monkeypatch.delenv("SSH_CONNECTION", raising=False)
    with patch("src.capture.environment.IS_WINDOWS", False):
        from src.capture.environment import is_ssh_session
        assert is_ssh_session() is False


def test_is_ssh_session_windows_session_zero(monkeypatch):
    monkeypatch.delenv("SSH_CLIENT", raising=False)
    monkeypatch.delenv("SSH_CONNECTION", raising=False)
    with patch("src.capture.environment.IS_WINDOWS", True):
        mock_kernel32 = MagicMock()

        def fake_session_id(pid, ref):
            ref.value = 0

        mock_kernel32.ProcessIdToSessionId = fake_session_id
        mock_kernel32.GetCurrentProcessId.return_value = 1234
        with patch("src.capture.environment.ctypes") as mock_ctypes:
            mock_ctypes.windll.kernel32 = mock_kernel32
            mock_ref = MagicMock()
            mock_ref.value = 0
            mock_ctypes.c_ulong.return_value = mock_ref
            mock_ctypes.byref.return_value = mock_ref
            from src.capture.environment import is_ssh_session
            assert is_ssh_session() is True


def test_is_ssh_session_windows_session_nonzero(monkeypatch):
    monkeypatch.delenv("SSH_CLIENT", raising=False)
    monkeypatch.delenv("SSH_CONNECTION", raising=False)
    with patch("src.capture.environment.IS_WINDOWS", True):
        mock_kernel32 = MagicMock()

        def fake_session_id(pid, ref):
            ref.value = 1

        mock_kernel32.ProcessIdToSessionId = fake_session_id
        mock_kernel32.GetCurrentProcessId.return_value = 1234
        with patch("src.capture.environment.ctypes") as mock_ctypes:
            mock_ctypes.windll.kernel32 = mock_kernel32
            mock_ref = MagicMock()
            mock_ref.value = 1
            mock_ctypes.c_ulong.return_value = mock_ref
            mock_ctypes.byref.return_value = mock_ref
            from src.capture.environment import is_ssh_session
            assert is_ssh_session() is False


# ---------------------------------------------------------------------------
# Chrome flags
# ---------------------------------------------------------------------------

def test_chrome_launch_flags():
    from src.config import CHROME_FLAGS
    assert "--remote-debugging-port=9222" in CHROME_FLAGS
    assert "--start-maximized" in CHROME_FLAGS
    assert "--autoplay-policy=no-user-gesture-required" in CHROME_FLAGS
    assert any("--user-data-dir=" in f for f in CHROME_FLAGS)


# ---------------------------------------------------------------------------
# Scheduled task bat file
# ---------------------------------------------------------------------------

def test_scheduled_task_bat_content(tmp_path):
    with patch("src.capture.environment.TEMP_BAT_DIR", tmp_path), \
         patch("src.capture.environment.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        from src.capture.environment import _launch_via_scheduled_task
        result = _launch_via_scheduled_task(
            r"C:\Program Files\app.exe",
            ["--flag1", "--flag2"],
            "TestTask",
        )
    assert result is True
    bat_file = tmp_path / "TestTask.bat"
    assert bat_file.exists()
    content = bat_file.read_text()
    assert "@echo off" in content
    assert "app.exe" in content
    assert "--flag1" in content


def test_scheduled_task_create_fails(tmp_path):
    with patch("src.capture.environment.TEMP_BAT_DIR", tmp_path), \
         patch("src.capture.environment.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="error")
        from src.capture.environment import _launch_via_scheduled_task
        result = _launch_via_scheduled_task("app.exe", [], "TestTask")
    assert result is False


# ---------------------------------------------------------------------------
# _launch_app
# ---------------------------------------------------------------------------

def test_launch_app_ssh_delegates_to_scheduled_task():
    from src.capture.environment import _launch_app
    with patch("src.capture.environment.is_ssh_session", return_value=True), \
         patch("src.capture.environment._launch_via_scheduled_task", return_value=True) as mock_sched:
        from pathlib import Path
        result = _launch_app(Path("/app.exe"), ["--flag"], "Task")
    assert result is True
    mock_sched.assert_called_once()


def test_launch_app_local_uses_popen():
    from src.capture.environment import _launch_app
    with patch("src.capture.environment.is_ssh_session", return_value=False), \
         patch("src.capture.environment.subprocess.Popen") as mock_popen:
        from pathlib import Path
        result = _launch_app(Path("/app.exe"), ["--flag"], "Task")
    assert result is True
    mock_popen.assert_called_once()


def test_launch_app_exception_returns_false():
    from src.capture.environment import _launch_app
    with patch("src.capture.environment.is_ssh_session", return_value=False), \
         patch("src.capture.environment.subprocess.Popen", side_effect=OSError("fail")):
        from pathlib import Path
        result = _launch_app(Path("/app.exe"), [], "Task")
    assert result is False


# ---------------------------------------------------------------------------
# EnvironmentManager._setup_chrome
# ---------------------------------------------------------------------------

def test_setup_chrome_already_running():
    from src.capture.environment import EnvironmentManager
    env = EnvironmentManager()
    with patch("src.capture.environment.urllib.request.urlopen") as mock_url:
        mock_url.return_value.read.return_value = b'[{"type":"page"}]'
        result = env._setup_chrome()
    assert result is True


def test_setup_chrome_not_running_linux():
    from src.capture.environment import EnvironmentManager
    env = EnvironmentManager()
    with patch("src.capture.environment.urllib.request.urlopen", side_effect=Exception("refused")), \
         patch("src.capture.environment.IS_WINDOWS", False):
        result = env._setup_chrome()
    assert result is False


def test_setup_chrome_launches_and_polls():
    from src.capture.environment import EnvironmentManager
    env = EnvironmentManager()
    call_count = 0

    def urlopen_side_effect(url, timeout=None):
        nonlocal call_count
        call_count += 1
        if call_count <= 1:
            raise Exception("refused")
        return MagicMock(read=MagicMock(return_value=b'[]'))

    with patch("src.capture.environment.urllib.request.urlopen", side_effect=urlopen_side_effect), \
         patch("src.capture.environment.IS_WINDOWS", True), \
         patch("src.capture.environment._launch_app", return_value=True), \
         patch("src.capture.environment.time.sleep"):
        result = env._setup_chrome()
    assert result is True


# ---------------------------------------------------------------------------
# EnvironmentManager._setup_obs
# ---------------------------------------------------------------------------

def test_setup_obs_already_running():
    from src.capture.environment import EnvironmentManager
    env = EnvironmentManager()
    mock_client = MagicMock()
    with patch("src.capture.environment._obs_connect", return_value=mock_client):
        result = env._setup_obs()
    assert result is True


def test_setup_obs_not_running_linux():
    from src.capture.environment import EnvironmentManager
    env = EnvironmentManager()
    with patch("src.capture.environment._obs_connect", side_effect=Exception("refused")), \
         patch("src.capture.environment.IS_WINDOWS", False):
        result = env._setup_obs()
    assert result is False


def test_setup_obs_launches_and_polls():
    from src.capture.environment import EnvironmentManager
    env = EnvironmentManager()
    call_count = 0

    def connect_side_effect():
        nonlocal call_count
        call_count += 1
        if call_count <= 1:
            raise Exception("refused")
        return MagicMock()

    with patch("src.capture.environment._obs_connect", side_effect=connect_side_effect), \
         patch("src.capture.environment.IS_WINDOWS", True), \
         patch("src.capture.environment._launch_app", return_value=True), \
         patch("src.capture.environment.time.sleep"):
        result = env._setup_obs()
    assert result is True


# ---------------------------------------------------------------------------
# EnvironmentManager._configure_obs
# ---------------------------------------------------------------------------

def test_configure_obs_sets_window_capture():
    from src.capture.environment import EnvironmentManager
    env = EnvironmentManager()
    mock_client = MagicMock()
    mock_settings = MagicMock()
    mock_settings.input_settings = {"window": "SomeOtherWindow"}
    mock_client.get_input_settings.return_value = mock_settings
    with patch("src.capture.environment._obs_connect", return_value=mock_client):
        result = env._configure_obs()
    mock_client.set_input_settings.assert_any_call(
        "Window Capture", {"window": "Chrome_WidgetWin_1"}, True,
    )
    mock_client.set_input_settings.assert_any_call(
        "Desktop Audio", {"device_id": "default"}, True,
    )
    assert result is True


def test_configure_obs_skips_window_if_already_set():
    from src.capture.environment import EnvironmentManager
    env = EnvironmentManager()
    mock_client = MagicMock()
    mock_settings = MagicMock()
    mock_settings.input_settings = {"window": "Chrome_WidgetWin_1:some:details"}
    mock_client.get_input_settings.return_value = mock_settings
    with patch("src.capture.environment._obs_connect", return_value=mock_client):
        result = env._configure_obs()
    calls = [c for c in mock_client.set_input_settings.call_args_list
             if c[0][0] == "Window Capture"]
    assert len(calls) == 0
    assert result is True


def test_configure_obs_handles_failure():
    from src.capture.environment import EnvironmentManager
    env = EnvironmentManager()
    with patch("src.capture.environment._obs_connect", side_effect=Exception("conn refused")):
        result = env._configure_obs()
    assert result is False


# ---------------------------------------------------------------------------
# EnvironmentManager.setup / teardown
# ---------------------------------------------------------------------------

def test_setup_all_succeed():
    from src.capture.environment import EnvironmentManager
    env = EnvironmentManager()
    env._setup_chrome = MagicMock(return_value=True)
    env._setup_obs = MagicMock(return_value=True)
    env._configure_obs = MagicMock(return_value=True)
    ok, messages = env.setup()
    assert ok is True
    assert len(messages) == 3


def test_setup_chrome_fails():
    from src.capture.environment import EnvironmentManager
    env = EnvironmentManager()
    env._setup_chrome = MagicMock(return_value=False)
    ok, messages = env.setup()
    assert ok is False
    assert "FAILED" in messages[0]


def test_setup_obs_fails():
    from src.capture.environment import EnvironmentManager
    env = EnvironmentManager()
    env._setup_chrome = MagicMock(return_value=True)
    env._setup_obs = MagicMock(return_value=False)
    ok, messages = env.setup()
    assert ok is False


def test_setup_configure_fails():
    from src.capture.environment import EnvironmentManager
    env = EnvironmentManager()
    env._setup_chrome = MagicMock(return_value=True)
    env._setup_obs = MagicMock(return_value=True)
    env._configure_obs = MagicMock(return_value=False)
    ok, messages = env.setup()
    assert ok is False


# ---------------------------------------------------------------------------
# Teardown
# ---------------------------------------------------------------------------

def test_teardown_stops_recording():
    from src.capture.environment import EnvironmentManager
    env = EnvironmentManager()
    mock_client = MagicMock()
    mock_client.get_record_status.return_value.output_active = True
    with patch("src.capture.environment._obs_connect", return_value=mock_client), \
         patch("src.capture.environment.IS_WINDOWS", False), \
         patch("src.capture.environment.urllib.request.urlopen", side_effect=Exception("down")), \
         patch("src.capture.environment._cleanup_scheduled_task"):
        ok, messages = env.teardown()
    mock_client.stop_record.assert_called_once()
    assert ok is True


def test_teardown_skips_stop_if_not_recording():
    from src.capture.environment import EnvironmentManager
    env = EnvironmentManager()
    mock_client = MagicMock()
    mock_client.get_record_status.return_value.output_active = False
    with patch("src.capture.environment._obs_connect", return_value=mock_client), \
         patch("src.capture.environment.IS_WINDOWS", False), \
         patch("src.capture.environment.urllib.request.urlopen", side_effect=Exception("down")), \
         patch("src.capture.environment._cleanup_scheduled_task"):
        ok, messages = env.teardown()
    mock_client.stop_record.assert_not_called()
    assert ok is True


def test_teardown_chrome_via_cdp():
    from src.capture.environment import EnvironmentManager
    env = EnvironmentManager()

    version_data = b'{"webSocketDebuggerUrl": "ws://localhost:9222/devtools/browser/abc"}'
    mock_conn = MagicMock()

    with patch("src.capture.environment._obs_connect", side_effect=Exception("down")), \
         patch("src.capture.environment.IS_WINDOWS", False), \
         patch("src.capture.environment.urllib.request.urlopen") as mock_url, \
         patch("src.capture.environment._cleanup_scheduled_task"), \
         patch.dict("sys.modules", {"websockets.sync.client": MagicMock(connect=MagicMock(return_value=mock_conn))}):
        mock_url.return_value.read.return_value = version_data
        ok, messages = env.teardown()
    assert ok is True


def test_teardown_chrome_fallback_taskkill():
    from src.capture.environment import EnvironmentManager
    env = EnvironmentManager()
    with patch("src.capture.environment._obs_connect", side_effect=Exception("down")), \
         patch("src.capture.environment.IS_WINDOWS", True), \
         patch("src.capture.environment.urllib.request.urlopen", side_effect=Exception("down")), \
         patch("src.capture.environment.subprocess.run") as mock_run, \
         patch("src.capture.environment._cleanup_scheduled_task"):
        mock_run.return_value = MagicMock(returncode=0)
        ok, messages = env.teardown()
    taskkill_calls = [c for c in mock_run.call_args_list
                      if "taskkill" in str(c)]
    assert len(taskkill_calls) >= 1
    assert ok is True


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def test_cleanup_scheduled_task(tmp_path):
    bat_file = tmp_path / "TestTask.bat"
    bat_file.write_text("@echo off")
    with patch("src.capture.environment.TEMP_BAT_DIR", tmp_path), \
         patch("src.capture.environment.subprocess.run"):
        from src.capture.environment import _cleanup_scheduled_task
        _cleanup_scheduled_task("TestTask")
    assert not bat_file.exists()


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

def test_cli_setup_args():
    from cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["setup"])
    assert args.command == "setup"


def test_cli_teardown_args():
    from cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["teardown"])
    assert args.command == "teardown"
