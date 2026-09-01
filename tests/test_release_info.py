"""Tests for the release-info subcommand and version tracking."""
import os
from pathlib import Path
from unittest.mock import patch, MagicMock


def test_version_importable():
    from src import __version__
    assert isinstance(__version__, str)
    assert __version__


def test_cli_release_info_args():
    from cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["release-info"])
    assert args.command == "release-info"


def test_release_info_output(capsys):
    mock_result = MagicMock()
    mock_result.stdout = "abc1234\n"
    mock_result.returncode = 0

    with patch("subprocess.run", return_value=mock_result):
        from cli import main
        import sys
        with patch.object(sys, "argv", ["cli.py", "release-info"]):
            main()

    captured = capsys.readouterr()
    assert "Version:" in captured.out
    assert "Commit:" in captured.out
    assert "Target:" in captured.out


def test_release_info_remote_unreachable(capsys):
    fail_result = MagicMock()
    fail_result.returncode = 1
    fail_result.stdout = ""

    git_result = MagicMock()
    git_result.stdout = "abc1234\n"
    git_result.returncode = 0

    def side_effect(cmd, **kwargs):
        if cmd[0] == "ssh":
            return fail_result
        return git_result

    with patch("subprocess.run", side_effect=side_effect):
        import sys
        from cli import main
        with patch.object(sys, "argv", ["cli.py", "release-info"]):
            main()

    captured = capsys.readouterr()
    assert "(unreachable)" in captured.out


def test_release_script_executable():
    script = Path(__file__).parent.parent / "scripts" / "release.sh"
    assert script.exists(), "scripts/release.sh must exist"
    assert os.access(script, os.X_OK), "scripts/release.sh must be executable"
