"""Tests for youtube_channel.py pure helpers (no network)."""
import urllib.error
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


def test_gather_uses_feed_by_default(monkeypatch):
    """The cheap default path reads the RSS feed and does not touch yt-dlp."""
    feed = ytc.parse_channel_feed(SAMPLE_FEED)
    monkeypatch.setattr(ytc, "fetch_channel_feed", lambda cid: feed)
    monkeypatch.setattr(ytc, "fetch_channel_uploads",
                        lambda cid: pytest.fail("uploads should not run when feed works"))
    got = ytc.gather_candidate_videos(CHANNEL_ID, None, None, use_full_history=False)
    assert [v.video_id for v in got] == ["AAAAAAAAAAA", "BBBBBBBBBBB"]


def test_gather_falls_back_to_ytdlp_when_feed_404s(monkeypatch):
    """A dead RSS feed (404) must fall back to the yt-dlp uploads listing."""
    import urllib.error

    def boom(cid):
        raise urllib.error.HTTPError(
            "https://www.youtube.com/feeds/videos.xml", 404, "Not Found", {}, None)

    uploads = ytc.parse_channel_feed(SAMPLE_FEED)
    monkeypatch.setattr(ytc, "fetch_channel_feed", boom)
    monkeypatch.setattr(ytc, "fetch_channel_uploads", lambda cid: uploads)
    got = ytc.gather_candidate_videos(CHANNEL_ID, None, None, use_full_history=False)
    assert [v.video_id for v in got] == ["AAAAAAAAAAA", "BBBBBBBBBBB"]


def test_fallback_caps_at_recent_limit_not_full_history(monkeypatch):
    """A feed outage must not turn the daily poll into a full-history backfill."""
    def boom(cid):
        raise urllib.error.HTTPError("u", 404, "Not Found", {}, None)

    # Simulate a channel with a long tail: far more uploads than the feed size.
    long_tail = [ytc.ChannelVideo(f"vid{i:04d}", f"t{i}", "") for i in range(200)]
    monkeypatch.setattr(ytc, "fetch_channel_feed", boom)
    monkeypatch.setattr(ytc, "fetch_channel_uploads", lambda cid: long_tail)
    got = ytc.gather_candidate_videos(CHANNEL_ID, None, None, use_full_history=False)
    assert len(got) == ytc.RSS_RECENT_LIMIT
    assert got[0].video_id == "vid0000"  # newest-first slice preserved


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


def test_parse_uploads_output():
    text = ("20260702\tAAAAAAAAAAA\tNewest Video\n"
            "20250115\tBBBBBBBBBBB\tOlder Video\n"
            "\n"  # blank line ignored
            "NA\tCCCCCCCCCCC\tUndated Video\n")
    videos = ytc.parse_uploads_output(text)
    assert [v.video_id for v in videos] == ["AAAAAAAAAAA", "BBBBBBBBBBB", "CCCCCCCCCCC"]
    assert videos[0].published == "20260702"
    assert videos[0].title == "Newest Video"


def test_parse_uploads_output_keeps_tabs_in_title():
    # Title with an embedded tab stays intact (split has maxsplit=2).
    videos = ytc.parse_uploads_output("20260101\tAAAAAAAAAAA\tA\tB")
    assert videos[0].title == "A\tB"


@pytest.mark.parametrize("value, expected", [
    ("2025-01-01", "20250101"),
    ("20250101", "20250101"),
    ("2026/07/03", "20260703"),
])
def test_normalize_date(value, expected):
    assert ytc.normalize_date(value) == expected


@pytest.mark.parametrize("bad", ["2025-1-1", "not-a-date", "20250101999", ""])
def test_normalize_date_rejects_bad(bad):
    with pytest.raises(ValueError):
        ytc.normalize_date(bad)


def _vid(video_id, date):
    return ytc.ChannelVideo(video_id=video_id, title=video_id, published=date)


def test_filter_by_date_since_and_until():
    videos = [_vid("a", "20241231"), _vid("b", "20250101"),
              _vid("c", "20260702"), _vid("d", "20270101")]
    kept = ytc.filter_by_date(videos, since="20250101", until="20261231")
    assert [v.video_id for v in kept] == ["b", "c"]


def test_filter_by_date_drops_undated():
    videos = [_vid("a", "20250601"), _vid("b", "NA"), _vid("c", "")]
    kept = ytc.filter_by_date(videos, since="20250101", until=None)
    assert [v.video_id for v in kept] == ["a"]


def test_default_seen_path():
    assert ytc.default_seen_path(Path("out"), CHANNEL_ID) == Path(f"out/.seen-{CHANNEL_ID}.txt")


def test_load_seen_missing_file_is_empty(tmp_path):
    assert ytc.load_seen(tmp_path / "nope.txt") == set()


def test_append_and_load_seen_roundtrip(tmp_path):
    path = tmp_path / "sub" / "seen.txt"
    ytc.append_seen(path, "AAAAAAAAAAA")
    ytc.append_seen(path, "BBBBBBBBBBB")
    assert ytc.load_seen(path) == {"AAAAAAAAAAA", "BBBBBBBBBBB"}
