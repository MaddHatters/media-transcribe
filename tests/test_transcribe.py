"""Tests for transcribe.py helpers that don't require the Whisper model."""
import pytest

import transcribe


@pytest.mark.parametrize("seconds, expected", [
    (0, "00:00:00,000"),
    (1.5, "00:00:01,500"),
    (61, "00:01:01,000"),
    (3661.5, "01:01:01,500"),
    (3600 * 2 + 7, "02:00:07,000"),
])
def test_fmt_ts(seconds, expected):
    assert transcribe.fmt_ts(seconds) == expected


def test_fmt_ts_rounds_to_milliseconds():
    assert transcribe.fmt_ts(0.0006) == "00:00:00,001"
