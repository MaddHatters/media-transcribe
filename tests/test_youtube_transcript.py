"""Tests for youtube_transcript.py pure helpers (no network / no yt-dlp)."""
from pathlib import Path

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


@pytest.mark.parametrize("raw, expected", [
    ("20260702", "2026-07-02"),
    ("20250101", "2025-01-01"),
    (None, ""),
    ("", ""),
    ("NA", ""),
    ("2026-07-02", ""),  # already formatted / not 8 digits -> treated as unknown
])
def test_format_upload_date(raw, expected):
    assert yt.format_upload_date(raw) == expected


def test_metadata_from_info_extracts_publish_date():
    info = {"title": "Best Stocks", "channel": "Mr. FIRED Up Wealth",
            "upload_date": "20260702", "timestamp": 1783033200}
    meta = yt.metadata_from_info("N8fzEctLPbE", info)
    assert meta.upload_date == "2026-07-02"
    assert meta.timestamp == 1783033200
    assert meta.channel == "Mr. FIRED Up Wealth"
    assert meta.url == "https://www.youtube.com/watch?v=N8fzEctLPbE"


def test_metadata_from_info_falls_back_when_empty():
    meta = yt.metadata_from_info("abc12345678", {})
    assert meta.title == "abc12345678"
    assert meta.channel == "unknown channel"
    assert meta.upload_date == ""
    assert meta.timestamp is None


def test_write_metadata_and_channel_index_roundtrip(tmp_path):
    import json
    channel_dir = tmp_path / "Chan"
    # Two videos, written out of date order; index must sort by publish date.
    for vid, date in [("bbbbbbbbbbb", "20260201"), ("aaaaaaaaaaa", "20250101")]:
        out_dir = channel_dir / f"vid [{vid}]"
        out_dir.mkdir(parents=True)
        meta = yt.VideoMetadata(vid, "T", "Chan", yt.format_upload_date(date), 1, "u")
        yt.write_metadata(out_dir, meta, transcript_lines=5)
    index_path = yt.write_channel_index(channel_dir)
    rows = [json.loads(line) for line in index_path.read_text().splitlines()]
    assert [r["video_id"] for r in rows] == ["aaaaaaaaaaa", "bbbbbbbbbbb"]  # date-sorted
    assert rows[0]["upload_date"] == "2025-01-01"
    assert rows[0]["transcript_lines"] == 5


def test_video_output_dir_layout():
    out = yt.video_output_dir(Path("/media/youtube"), "Mr. FIRED Up Wealth",
                              "5 BEST Stocks to BUY Now", "abc12345678")
    assert out == Path("/media/youtube/Mr. FIRED Up Wealth/5 BEST Stocks to BUY Now [abc12345678]")


def test_video_output_dir_disambiguates_duplicate_titles():
    # Same channel + title, different ids must not collide.
    dest, channel, title = Path("/m"), "Chan", "Same Title"
    first = yt.video_output_dir(dest, channel, title, "aaaaaaaaaaa")
    second = yt.video_output_dir(dest, channel, title, "bbbbbbbbbbb")
    assert first != second


def test_video_output_dir_sanitizes_channel_and_title():
    out = yt.video_output_dir(Path("/m"), "Bad/Chan", "Ti:tle?", "id123456789")
    assert out == Path("/m/Bad_Chan/Ti_tle [id123456789]")


@pytest.mark.parametrize("name, expected", [
    ("Normal Title", "Normal Title"),
    ('bad/name:with*chars?', "bad_name_with_chars"),
    ("   ", "transcript"),
    ("", "transcript"),
])
def test_sanitize_filename(name, expected):
    assert yt.sanitize_filename(name) == expected
