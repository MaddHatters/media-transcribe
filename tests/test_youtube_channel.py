"""Tests for youtube_channel.py pure helpers (no network)."""
from pathlib import Path

import pytest

import youtube_channel as ytc

SAMPLE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns="http://www.w3.org/2005/Atom">
  <yt:channelId>UC_x5XG1OV2P6uZZ5FSM9Ttw</yt:channelId>
  <title>Some Channel</title>
  <entry>
    <yt:videoId>AAAAAAAAAAA</yt:videoId>
    <title>Newest Video</title>
    <published>2026-07-02T12:00:00+00:00</published>
  </entry>
  <entry>
    <yt:videoId>BBBBBBBBBBB</yt:videoId>
    <title>Older Video</title>
    <published>2026-07-01T12:00:00+00:00</published>
  </entry>
</feed>
"""

CHANNEL_ID = "UC_x5XG1OV2P6uZZ5FSM9Ttw"


def test_parse_channel_feed_reads_entries_newest_first():
    videos = ytc.parse_channel_feed(SAMPLE_FEED)
    assert [v.video_id for v in videos] == ["AAAAAAAAAAA", "BBBBBBBBBBB"]
    assert videos[0].title == "Newest Video"
    assert videos[1].published == "2026-07-01T12:00:00+00:00"


def test_parse_channel_feed_empty():
    empty = ('<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" '
             'xmlns="http://www.w3.org/2005/Atom"></feed>')
    assert ytc.parse_channel_feed(empty) == []


@pytest.mark.parametrize("value, expected", [
    (CHANNEL_ID, CHANNEL_ID),
    (f"https://www.youtube.com/channel/{CHANNEL_ID}", CHANNEL_ID),
    (f"https://www.youtube.com/channel/{CHANNEL_ID}/videos", CHANNEL_ID),
    (f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}", CHANNEL_ID),
    ("https://www.youtube.com/@SomeHandle", None),
    ("@SomeHandle", None),
    ("SomeHandle", None),
])
def test_channel_id_from_text(value, expected):
    assert ytc.channel_id_from_text(value) == expected


@pytest.mark.parametrize("value, expected", [
    ("@handle", "https://www.youtube.com/@handle"),
    ("handle", "https://www.youtube.com/@handle"),
    ("https://www.youtube.com/@handle", "https://www.youtube.com/@handle"),
])
def test_channel_page_url(value, expected):
    assert ytc._channel_page_url(value) == expected


def test_default_seen_path():
    assert ytc.default_seen_path(Path("out"), CHANNEL_ID) == Path(f"out/.seen-{CHANNEL_ID}.txt")


def test_load_seen_missing_file_is_empty(tmp_path):
    assert ytc.load_seen(tmp_path / "nope.txt") == set()


def test_append_and_load_seen_roundtrip(tmp_path):
    path = tmp_path / "sub" / "seen.txt"
    ytc.append_seen(path, "AAAAAAAAAAA")
    ytc.append_seen(path, "BBBBBBBBBBB")
    assert ytc.load_seen(path) == {"AAAAAAAAAAA", "BBBBBBBBBBB"}
