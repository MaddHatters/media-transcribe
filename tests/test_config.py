"""Tests for src/config.py constants and platform detection."""
import sys
from pathlib import Path

from src.config import (
    SCRIPTS_DIR, STATE_DIR, LOGS_DIR, BACKUP_DIR,
    CHROME_PATH, CHROME_PROFILE, OBS_PATH,
    LOCAL_TRANSCRIPTS, LOCAL_DATA,
    CDP_URL, OBS_HOST, OBS_PORT, OBS_PASSWORD,
    SSH_HOST, SSH_OPTS,
    BREAK_MIN_SECONDS, BREAK_MAX_SECONDS,
    CRED_TARGET, IS_WINDOWS,
)


def test_all_paths_are_path_objects():
    for p in (SCRIPTS_DIR, STATE_DIR, LOGS_DIR, BACKUP_DIR,
              CHROME_PATH, CHROME_PROFILE, OBS_PATH,
              LOCAL_TRANSCRIPTS, LOCAL_DATA):
        assert isinstance(p, Path), f"{p!r} is not a Path"


def test_cdp_url_format():
    assert CDP_URL.startswith("http://")
    assert ":9222" in CDP_URL


def test_obs_port_is_int():
    assert isinstance(OBS_PORT, int)
    assert OBS_PORT == 4455


def test_break_range_valid():
    assert BREAK_MIN_SECONDS < BREAK_MAX_SECONDS
    assert BREAK_MIN_SECONDS == 300
    assert BREAK_MAX_SECONDS == 1500


def test_ssh_opts_is_list():
    assert isinstance(SSH_OPTS, list)
    assert all(isinstance(o, str) for o in SSH_OPTS)


def test_is_windows_matches_platform():
    assert IS_WINDOWS == (sys.platform == "win32")


def test_base_imports():
    from src.players.base import DetectionResult, PlayerHandler
    d = DetectionResult(player="mux", element="video", meta={"duration": 120})
    assert d.player == "mux"
