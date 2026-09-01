"""Tests for background-by-default execution logic in cli.py."""
import argparse
import re
import subprocess
import sys
from unittest.mock import MagicMock, call, mock_open, patch

import pytest

from cli import LONG_RUNNING_COMMANDS, background_relaunch, build_parser


def test_long_running_commands_identified():
    assert LONG_RUNNING_COMMANDS == {"record", "transcribe", "analyze", "pipeline"}


class TestForegroundFlagParsed:
    @pytest.mark.parametrize("cmd,extra_args", [
        ("transcribe", ["/tmp/videos"]),
        ("analyze", ["/tmp/videos"]),
        ("record", ["--queue", "/tmp/q.json"]),
        ("pipeline", ["--queue", "/tmp/q.json"]),
    ])
    def test_foreground_present(self, cmd, extra_args):
        parser = build_parser()
        args = parser.parse_args([cmd] + extra_args + ["--foreground"])
        assert args.foreground is True

    @pytest.mark.parametrize("cmd,extra_args", [
        ("transcribe", ["/tmp/videos"]),
        ("analyze", ["/tmp/videos"]),
        ("record", ["--queue", "/tmp/q.json"]),
        ("pipeline", ["--queue", "/tmp/q.json"]),
    ])
    def test_foreground_absent(self, cmd, extra_args):
        parser = build_parser()
        args = parser.parse_args([cmd] + extra_args)
        assert args.foreground is False


class TestShortCommandsNoForeground:
    @pytest.mark.parametrize("cmd,extra_args", [
        ("correct", ["/tmp/transcripts"]),
        ("find-gaps", ["/tmp/transcripts"]),
        ("preflight", []),
        ("screenshot", []),
        ("transfer-transcripts", []),
    ])
    def test_no_foreground_attr(self, cmd, extra_args):
        parser = build_parser()
        args = parser.parse_args([cmd] + extra_args)
        assert not hasattr(args, "foreground")


class TestForegroundSkipsRelaunch:
    @patch("cli.subprocess.Popen")
    def test_foreground_flag_skips_relaunch(self, mock_popen, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["cli.py", "transcribe", "/tmp/x", "--foreground"])
        with patch("src.transcribe.whisper_runner.WhisperRunner") as mock_runner, \
             patch("src.logging_config.setup_logging", return_value="/tmp/test.log"):
            mock_instance = MagicMock()
            mock_runner.return_value = mock_instance
            from cli import main
            main()
        mock_popen.assert_not_called()


class TestBackgroundBuildsCorrectCommand:
    @patch("cli.time.sleep")
    @patch("cli.subprocess.Popen")
    def test_command_includes_foreground(self, mock_popen, mock_sleep, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["cli.py", "transcribe", "/tmp/videos"])
        mock_proc = MagicMock(pid=12345)
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        args = argparse.Namespace(command="transcribe")
        background_relaunch(args, tmp_path)

        call_args = mock_popen.call_args
        child_cmd = call_args[0][0]
        assert "--foreground" in child_cmd
        assert "transcribe" in child_cmd
        if sys.platform != "win32":
            assert call_args[1]["start_new_session"] is True


class TestLogFileNaming:
    @patch("cli.time.sleep")
    @patch("cli.subprocess.Popen")
    def test_log_matches_pattern(self, mock_popen, mock_sleep, tmp_path):
        mock_proc = MagicMock(pid=99)
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc
        args = argparse.Namespace(command="transcribe")
        background_relaunch(args, tmp_path)

        log_files = list(tmp_path.glob("transcribe_*.log"))
        assert len(log_files) == 1
        assert re.match(r"transcribe_\d{8}_\d{6}\.log", log_files[0].name)


class TestShortCommandsStayForeground:
    @patch("cli.subprocess.Popen")
    def test_correct_no_popen(self, mock_popen, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["cli.py", "correct", "/tmp/transcripts"])
        with patch("src.transcribe.corrections.load_rules", return_value=[]), \
             patch("src.transcribe.corrections.apply_rules"), \
             patch("src.logging_config.setup_logging", return_value="/tmp/test.log"):
            from cli import main
            main()
        mock_popen.assert_not_called()


class TestChildCommandUsesUvRun:
    @patch("cli.time.sleep")
    @patch("cli.subprocess.Popen")
    @patch("cli.shutil.which", return_value="/usr/bin/uv")
    def test_child_command_uses_uv_run(self, mock_which, mock_popen, mock_sleep, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["cli.py", "transcribe", "/tmp/videos"])
        mock_proc = MagicMock(pid=123)
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        args = argparse.Namespace(command="transcribe")
        background_relaunch(args, tmp_path)

        child_cmd = mock_popen.call_args[0][0]
        assert child_cmd[0] == "/usr/bin/uv"
        assert child_cmd[1] == "run"
        assert "--foreground" in child_cmd

    @patch("cli.time.sleep")
    @patch("cli.subprocess.Popen")
    @patch("cli.shutil.which", return_value=None)
    def test_child_command_falls_back_to_sys_executable(self, mock_which, mock_popen, mock_sleep, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["cli.py", "transcribe", "/tmp/videos"])
        mock_proc = MagicMock(pid=123)
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        args = argparse.Namespace(command="transcribe")
        background_relaunch(args, tmp_path)

        child_cmd = mock_popen.call_args[0][0]
        assert child_cmd[0] == sys.executable


class TestWindowsNoDetachedProcess:
    @patch("cli.time.sleep")
    @patch("cli.subprocess.Popen")
    @patch("cli.shutil.which", return_value=None)
    def test_windows_no_detached_process(self, mock_which, mock_popen, mock_sleep, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(sys, "argv", ["cli.py", "transcribe", "/tmp/videos"])

        CREATE_NO_WINDOW = 0x08000000
        DETACHED_PROCESS = 0x00000008
        monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", CREATE_NO_WINDOW, raising=False)
        monkeypatch.setattr(subprocess, "DETACHED_PROCESS", DETACHED_PROCESS, raising=False)

        mock_proc = MagicMock(pid=123)
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        args = argparse.Namespace(command="transcribe")
        background_relaunch(args, tmp_path)

        kwargs = mock_popen.call_args[1]
        flags = kwargs.get("creationflags", 0)
        assert flags & CREATE_NO_WINDOW
        assert not (flags & DETACHED_PROCESS)


class TestEnvAndCwdPassedToPopen:
    @patch("cli.time.sleep")
    @patch("cli.subprocess.Popen")
    def test_env_and_cwd_passed(self, mock_popen, mock_sleep, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["cli.py", "transcribe", "/tmp/videos"])
        mock_proc = MagicMock(pid=123)
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        args = argparse.Namespace(command="transcribe")
        background_relaunch(args, tmp_path)

        kwargs = mock_popen.call_args[1]
        assert "env" in kwargs
        assert "cwd" in kwargs


class TestLogFileLineBuffered:
    @patch("cli.time.sleep")
    @patch("cli.subprocess.Popen")
    def test_log_file_line_buffered(self, mock_popen, mock_sleep, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["cli.py", "transcribe", "/tmp/videos"])
        mock_proc = MagicMock(pid=123)
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        args = argparse.Namespace(command="transcribe")

        with patch("builtins.open", wraps=open) as mock_file_open:
            background_relaunch(args, tmp_path)

            log_open_call = None
            for c in mock_file_open.call_args_list:
                path_arg = str(c[0][0]) if c[0] else ""
                if ".log" in path_arg:
                    log_open_call = c
                    break

            assert log_open_call is not None
            assert log_open_call[1].get("buffering") == 1 or (len(log_open_call[0]) >= 3 and log_open_call[0][2] == 1)
