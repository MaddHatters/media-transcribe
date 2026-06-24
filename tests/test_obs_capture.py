"""Tests for obs_capture.py pure helpers (no browser/OBS needed)."""
import obs_capture


def test_safe_name_replaces_illegal_chars():
    assert obs_capture.safe_name('Masterclass 13: A/B?') == "Masterclass 13_ A_B_"


def test_safe_name_falls_back_when_empty():
    assert obs_capture.safe_name("   ") == "episode"
    assert obs_capture.safe_name("///") == "episode"


def test_safe_name_keeps_normal_titles():
    assert obs_capture.safe_name("Masterclass 7 - Balance Sheet Deep Dive") == \
        "Masterclass 7 - Balance Sheet Deep Dive"
