"""Tests for background-by-default execution logic in cli.py."""
import argparse
import re
import sys
from unittest.mock import MagicMock, patch

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
        # Patch the actual transcribe handler so it doesn't run
        with patch("src.transcribe.whisper_runner.WhisperRunner") as mock_runner:
            mock_instance = MagicMock()
            mock_runner.return_value = mock_instance
            from cli import main
            main()
        mock_popen.assert_not_called()


class TestBackgroundBuildsCorrectCommand:
    @patch("cli.subprocess.Popen")
    def test_command_includes_foreground(self, mock_popen, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["cli.py", "transcribe", "/tmp/videos"])
        mock_popen.return_value = MagicMock(pid=12345)

        args = argparse.Namespace(command="transcribe")
        background_relaunch(args, tmp_path)

        call_args = mock_popen.call_args
        child_cmd = call_args[0][0]
        assert child_cmd[0] == sys.executable
        assert "--foreground" in child_cmd
        assert "transcribe" in child_cmd
        if sys.platform != "win32":
            assert call_args[1]["start_new_session"] is True


class TestLogFileNaming:
    @patch("cli.subprocess.Popen")
    def test_log_matches_pattern(self, mock_popen, tmp_path):
        mock_popen.return_value = MagicMock(pid=99)
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
             patch("src.transcribe.corrections.apply_rules"):
            from cli import main
            main()
        mock_popen.assert_not_called()
