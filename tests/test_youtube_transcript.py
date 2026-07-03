"""Tests for youtube_transcript.py pure helpers (no network / no yt-dlp)."""
import pytest

import youtube_transcript as yt


@pytest.mark.parametrize("value, expected", [
    ("N8fzEctLPbE", "N8fzEctLPbE"),
    ("https://www.youtube.com/watch?v=N8fzEctLPbE", "N8fzEctLPbE"),
    ("https://www.youtube.com/watch?v=N8fzEctLPbE&t=42s", "N8fzEctLPbE"),
    ("https://youtu.be/N8fzEctLPbE", "N8fzEctLPbE"),
    ("https://www.youtube.com/shorts/N8fzEctLPbE", "N8fzEctLPbE"),
    ("https://www.youtube.com/embed/N8fzEctLPbE", "N8fzEctLPbE"),
])
def test_extract_video_id(value, expected):
    assert yt.extract_video_id(value) == expected


def test_extract_video_id_rejects_garbage():
    with pytest.raises(ValueError):
        yt.extract_video_id("not a youtube link")


@pytest.mark.parametrize("timestamp, expected", [
    ("00:00:00.000", 0.0),
    ("00:00:01.500", 1.5),
    ("00:01:02.500", 62.5),
    ("01:02:03.000", 3723.0),
    ("01:02.500", 62.5),
    ("00:00:00,250", 0.25),
])
def test_vtt_timestamp_to_seconds(timestamp, expected):
    assert yt.vtt_timestamp_to_seconds(timestamp) == expected


@pytest.mark.parametrize("seconds, expected", [
    (0, "0:00"),
    (5, "0:05"),
    (65, "1:05"),
    (3661, "1:01:01"),
    (3600 * 2 + 7, "2:00:07"),
])
def test_format_timestamp(seconds, expected):
    assert yt.format_timestamp(seconds) == expected


def test_strip_vtt_tags_removes_markup_and_entities():
    raw = 'hello<00:00:01.500><c> brave</c>&amp; new  world'
    assert yt.strip_vtt_tags(raw) == "hello brave& new world"


def test_parse_vtt_clean_manual_captions():
    vtt = (
        "WEBVTT\n\n"
        "00:00:00.000 --> 00:00:02.000\n"
        "Welcome to the show.\n\n"
        "00:00:02.000 --> 00:00:04.000\n"
        "Today we discuss dividends.\n"
    )
    assert yt.parse_vtt(vtt) == [
        (0.0, "Welcome to the show."),
        (2.0, "Today we discuss dividends."),
    ]


def test_parse_vtt_collapses_rolling_auto_captions():
    # YouTube auto-caption style: a rolling window with a line that grows
    # word-by-word and repeats across cues. Output should read once cleanly.
    vtt = (
        "WEBVTT\nKind: captions\nLanguage: en\n\n"
        "00:00:00.000 --> 00:00:01.000 align:start position:0%\n"
        "the market\n\n"
        "00:00:01.000 --> 00:00:02.000 align:start position:0%\n"
        "the market\n"
        "the market<00:00:01.400><c> is</c><00:00:01.700><c> up</c>\n\n"
        "00:00:02.000 --> 00:00:03.000 align:start position:0%\n"
        "the market is up\n"
        "today<00:00:02.400><c> we</c><00:00:02.700><c> buy</c>\n"
    )
    assert yt.parse_vtt(vtt) == [
        (0.0, "the market is up"),
        (2.0, "today we buy"),
    ]


def test_render_transcript():
    cues = [(0.0, "first line"), (65.0, "second line")]
    assert yt.render_transcript(cues) == "[0:00] first line\n[1:05] second line"


@pytest.mark.parametrize("name, expected", [
    ("Normal Title", "Normal Title"),
    ('bad/name:with*chars?', "bad_name_with_chars"),
    ("   ", "transcript"),
    ("", "transcript"),
])
def test_sanitize_filename(name, expected):
    assert yt.sanitize_filename(name) == expected
