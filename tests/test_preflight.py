"""Tests for Preflight — 7-gate startup validation."""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from src.capture.preflight import Preflight, GateResult


def _mock_preflight(**overrides):
    """Create a Preflight with overridden gate methods."""
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


def test_all_gates_pass():
    pf = _mock_preflight()
    ok, gates = pf.run_all()
    assert ok is True
    assert len(gates) == 7
    assert all(g.passed for g in gates)


def test_chrome_down_auto_launch_succeeds():
    pf = _mock_preflight(_ensure_chrome=True)
    ok, gates = pf.run_all()
    assert gates[0].passed is True


def test_chrome_down_auto_launch_fails():
    pf = _mock_preflight(_ensure_chrome=False)
    ok, gates = pf.run_all()
    assert ok is False
    assert gates[0].passed is False
    assert gates[0].name == "Chrome CDP"


def test_obs_down_auto_launch_succeeds():
    pf = _mock_preflight(_ensure_obs=True)
    ok, gates = pf.run_all()
    assert gates[1].passed is True


def test_obs_down_fails():
    pf = _mock_preflight(_ensure_obs=False)
    ok, gates = pf.run_all()
    assert ok is False
    assert gates[1].passed is False


def test_patreon_session_via_auto_login():
    pf = _mock_preflight(_check_patreon_session=True)
    ok, gates = pf.run_all()
    assert gates[2].passed is True


def test_patreon_session_fails():
    pf = _mock_preflight(_check_patreon_session=False)
    ok, gates = pf.run_all()
    assert ok is False
    assert gates[2].passed is False


def test_disk_space_insufficient():
    pf = _mock_preflight(_check_disk_space=(False, "2.1 GB free"))
    ok, gates = pf.run_all()
    assert ok is False
    disk_gate = [g for g in gates if g.name == "Disk space"][0]
    assert disk_gate.passed is False


def test_test_recording_black_video():
    pf = _mock_preflight(_run_test_recording=(False, True, (1920, 1080)))
    ok, gates = pf.run_all()
    assert ok is False
    video_gate = [g for g in gates if "video" in g.name][0]
    assert video_gate.passed is False


def test_test_recording_silent_audio():
    pf = _mock_preflight(_run_test_recording=(True, False, (1920, 1080)))
    ok, gates = pf.run_all()
    assert ok is False
    audio_gate = [g for g in gates if "audio" in g.name][0]
    assert audio_gate.passed is False


def test_gate_skip_when_chrome_failed():
    pf = _mock_preflight(_ensure_chrome=False)
    ok, gates = pf.run_all()
    patreon_gate = [g for g in gates if g.name == "Patreon session"][0]
    assert patreon_gate.passed is False
    assert "skipped" in patreon_gate.detail


def test_gate_skip_test_recording_when_obs_failed():
    pf = _mock_preflight(_ensure_obs=False)
    ok, gates = pf.run_all()
    test_gates = [g for g in gates if "Test recording" in g.name]
    assert all(not g.passed for g in test_gates)
    assert all("skipped" in g.detail for g in test_gates)


def test_gate_result_dataclass():
    g = GateResult(name="test", passed=True, detail="ok")
    assert g.name == "test"
    assert g.passed is True
    assert g.detail == "ok"


def test_ensure_chrome_real_implementation():
    pf = Preflight()
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.read.return_value = b'[{"type":"page"}]'
        result = pf._ensure_chrome()
    assert result is True


def test_ensure_chrome_not_running_no_autolaunch():
    pf = Preflight()
    with patch("urllib.request.urlopen", side_effect=Exception("refused")), \
         patch("src.capture.preflight.IS_WINDOWS", False):
        result = pf._ensure_chrome()
    assert result is False


def test_check_disk_space_sufficient():
    pf = Preflight()
    mock_usage = MagicMock()
    mock_usage.free = 20 * 1024 * 1024 * 1024
    with patch("shutil.disk_usage", return_value=mock_usage):
        ok, detail = pf._check_disk_space()
    assert ok is True
    assert "GB" in detail


def test_check_disk_space_insufficient():
    pf = Preflight()
    mock_usage = MagicMock()
    mock_usage.free = 2 * 1024 * 1024 * 1024
    with patch("shutil.disk_usage", return_value=mock_usage):
        ok, detail = pf._check_disk_space()
    assert ok is False


def test_check_patreon_session_delegates_to_source():
    pf = Preflight()
    mock_cdp = AsyncMock()
    mock_cdp.__aenter__ = AsyncMock(return_value=mock_cdp)
    mock_cdp.__aexit__ = AsyncMock(return_value=False)

    with patch("src.capture.preflight.asyncio.run") as mock_run:
        mock_run.return_value = True
        result = pf._check_patreon_session()

    assert result is True
    mock_run.assert_called_once()


def test_check_patreon_session_handles_failure():
    pf = Preflight()
    with patch("src.capture.preflight.asyncio.run", side_effect=Exception("CDP down")):
        result = pf._check_patreon_session()
    assert result is False


def test_run_test_recording_delegates_to_async():
    pf = Preflight()
    with patch("src.capture.preflight.asyncio.run") as mock_run:
        mock_run.return_value = (True, True, (1920, 1080))
        video_ok, audio_ok, resolution = pf._run_test_recording()

    assert video_ok is True
    assert audio_ok is True
    assert resolution == (1920, 1080)


def test_run_test_recording_failure_returns_false():
    pf = Preflight()
    with patch("src.capture.preflight.asyncio.run", side_effect=Exception("OBS error")):
        video_ok, audio_ok, resolution = pf._run_test_recording()

    assert video_ok is False
    assert audio_ok is False
    assert resolution is None
