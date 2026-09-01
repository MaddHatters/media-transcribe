"""Tests for --test-mode pipeline feature: TestSource, preflight skip, CLI args, generator."""
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# -- TestSource tests --

@pytest.mark.asyncio
async def test_test_source_authenticate():
    from src.sources.test_source import TestSource
    source = TestSource()
    cdp = AsyncMock()
    assert await source.authenticate(cdp) is True


@pytest.mark.asyncio
async def test_test_source_get_posts():
    from src.sources.test_source import TestSource
    source = TestSource()
    cdp = AsyncMock()
    assert await source.get_posts(cdp) == []


@pytest.mark.asyncio
async def test_test_source_navigate_to():
    from src.sources.test_source import TestSource
    source = TestSource()
    cdp = AsyncMock()
    await source.navigate_to(cdp, "file:///test.html")
    cdp.navigate.assert_called_once_with("file:///test.html", wait=10.0)


def test_test_source_satisfies_protocol():
    from src.sources.base import Source
    from src.sources.test_source import TestSource
    assert isinstance(TestSource(), Source)


# -- Preflight skip_patreon tests --

def _mock_preflight(**overrides):
    from src.capture.preflight import Preflight
    pf = Preflight()
    defaults = {
        "_ensure_chrome": True,
        "_ensure_obs": True,
        "_check_patreon_session": True,
        "_check_disk_space": (True, "50.2 GB free"),
        "_run_test_recording": (True, True, (1920, 1080)),
    }
    defaults.update(overrides)
    for method, return_val in defaults.items():
        setattr(pf, method, MagicMock(return_value=return_val))
    return pf


def test_preflight_skip_patreon_passes_gate():
    pf = _mock_preflight()
    pf._skip_patreon = True
    ok, gates = pf.run_all()
    patreon_gate = [g for g in gates if g.name == "Patreon session"][0]
    assert patreon_gate.passed is True
    assert "test mode" in patreon_gate.detail


def test_preflight_skip_patreon_does_not_call_check():
    from src.capture.preflight import Preflight
    pf = Preflight(skip_patreon=True)
    pf._ensure_chrome = MagicMock(return_value=True)
    pf._ensure_obs = MagicMock(return_value=True)
    pf._check_patreon_session = MagicMock(return_value=False)
    pf._check_disk_space = MagicMock(return_value=(True, "50 GB free"))
    pf._run_test_recording = MagicMock(return_value=(True, True, (1920, 1080)))
    ok, gates = pf.run_all()
    pf._check_patreon_session.assert_not_called()
    assert ok is True


def test_preflight_default_does_not_skip_patreon():
    from src.capture.preflight import Preflight
    pf = Preflight()
    assert pf._skip_patreon is False


# -- CLI argument parsing tests --

def test_cli_pipeline_test_mode_flag():
    from cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["pipeline", "--queue", "q.json", "--test-mode"])
    assert args.test_mode is True


def test_cli_pipeline_test_mode_default_false():
    from cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["pipeline", "--queue", "q.json"])
    assert args.test_mode is False


def test_cli_generate_test_video_args():
    from cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["generate-test-video", "--duration", "30"])
    assert args.command == "generate-test-video"
    assert args.duration == 30


def test_cli_generate_test_video_default_duration():
    from cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["generate-test-video"])
    assert args.command == "generate-test-video"
    assert args.duration == 60


# -- Generate script test --

def test_generate_test_video_builds_correct_ffmpeg_cmd():
    from test_assets.generate_test_video import generate
    with patch("test_assets.generate_test_video.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        with patch("pathlib.Path.stat") as mock_stat:
            mock_stat.return_value = MagicMock(st_size=5 * 1024 * 1024)
            generate(Path("/tmp/test.mp4"), duration=30)
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "ffmpeg"
        assert "-y" in cmd
        assert "sine=frequency=440:duration=30" in " ".join(cmd)
        assert "smptebars" in " ".join(cmd)
