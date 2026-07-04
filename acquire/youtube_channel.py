#!/usr/bin/env python3
"""Save transcripts for a YouTube channel's videos — recent uploads or a date range.

Two sources of candidate videos, both skipping anything already in a seen-file
and saving via youtube_transcript.save_transcript:

- Default: the channel's public RSS feed (no API key; the ~15 most recent
  uploads). Meant for a scheduled poll (systemd user timer) to catch new uploads.
- With --since / --until / --all: the full upload history via
  `uvx yt-dlp --flat-playlist` (with approximate upload dates), for backfilling
  a historical range. Throttled with --sleep between videos.

Usage:
    uv run acquire/youtube_channel.py https://www.youtube.com/@SomeChannel --dest transcripts
    uv run acquire/youtube_channel.py UC_x5XG1OV2P6uZZ5FSM9Ttw --dest transcripts
    uv run acquire/youtube_channel.py <channel> --since 2025-01-01 --sleep 2  # backfill
    uv run acquire/youtube_channel.py <channel> --since 2025-01-01 --dry-run
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
import urllib.request
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import NamedTuple

import youtube_transcript

_CHANNEL_ID_RE = re.compile(r"UC[A-Za-z0-9_-]{22}")
_ATOM = "{http://www.w3.org/2005/Atom}"
_YT = "{http://www.youtube.com/xml/schemas/2015}"
_USER_AGENT = "Mozilla/5.0 (media-transcribe youtube_channel)"


class ChannelVideo(NamedTuple):
    video_id: str
    title: str
    published: str


def channel_id_from_text(value: str) -> str | None:
    """Return a UC… channel id from a raw id or /channel//feed URL, else None.

    Handle and custom URLs (``@name``) carry no channel id and need a network
    lookup; those return None here so resolve_channel_id can fall back.
    """
    value = value.strip()
    match = _CHANNEL_ID_RE.search(value)
    if not match:
        return None
    if value == match.group(0) or "channel/" in value or "channel_id=" in value:
        return match.group(0)
    return None


def _http_get(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 (fixed https host)
        return response.read().decode("utf-8", errors="replace")


def _channel_page_url(value: str) -> str:
    value = value.strip()
    if value.startswith(("http://", "https://")):
        return value
    handle = value if value.startswith("@") else f"@{value}"
    return f"https://www.youtube.com/{handle}"


def resolve_channel_id(value: str) -> str:
    """Resolve any channel reference (id, URL, or @handle) to a UC… channel id."""
    direct = channel_id_from_text(value)
    if direct:
        return direct
    page = _http_get(_channel_page_url(value))
    for pattern in (
        r'"(?:channelId|externalId)":"(UC[A-Za-z0-9_-]{22})"',
        r'youtube\.com/channel/(UC[A-Za-z0-9_-]{22})',
    ):
        match = re.search(pattern, page)
        if match:
            return match.group(1)
    raise ValueError(f"Could not resolve a channel id from: {value!r}")


def parse_channel_feed(xml_text: str) -> list[ChannelVideo]:
    """Parse a YouTube channel Atom feed into videos, newest first (feed order)."""
    root = ElementTree.fromstring(xml_text)
    videos: list[ChannelVideo] = []
    for entry in root.findall(f"{_ATOM}entry"):
        video_id = entry.findtext(f"{_YT}videoId")
        if not video_id:
            continue
        title = entry.findtext(f"{_ATOM}title") or ""
        published = entry.findtext(f"{_ATOM}published") or ""
        videos.append(ChannelVideo(video_id, title, published))
    return videos


def fetch_channel_feed(channel_id: str) -> list[ChannelVideo]:
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    return parse_channel_feed(_http_get(url))


def parse_uploads_output(text: str) -> list[ChannelVideo]:
    """Parse yt-dlp `--print "date\\tid\\ttitle"` lines into videos (newest first)."""
    videos: list[ChannelVideo] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 2)
        if len(parts) < 2:
            continue
        upload_date, video_id = parts[0], parts[1]
        title = parts[2] if len(parts) > 2 else ""
        videos.append(ChannelVideo(video_id=video_id, title=title, published=upload_date))
    return videos


def fetch_channel_uploads(channel_id: str) -> list[ChannelVideo]:
    """Full upload history via yt-dlp flat-playlist, with approximate dates.

    Unlike the RSS feed (~15 recent), this lists every upload. Dates come from
    the channel page's "X ago" labels — good to the day for recent videos,
    coarser for old ones — which is enough for date-range filtering.
    """
    url = f"https://www.youtube.com/channel/{channel_id}/videos"
    result = subprocess.run(
        [
            "uvx", "yt-dlp", "--flat-playlist",
            "--extractor-args", "youtubetab:approximate_date",
            "--print", "%(upload_date)s\t%(id)s\t%(title)s",  # real tab: Python escapes it
            "--no-warnings",
            url,
        ],
        check=True, capture_output=True, text=True,
    )
    return parse_uploads_output(result.stdout)


def normalize_date(value: str) -> str:
    """'2025-01-01' or '20250101' -> '20250101' (8 digits, for YYYYMMDD compare)."""
    digits = re.sub(r"\D", "", value)
    if len(digits) != 8:
        raise ValueError(f"Expected a date like YYYY-MM-DD, got: {value!r}")
    return digits


def filter_by_date(videos: list[ChannelVideo], since: str | None,
                   until: str | None) -> list[ChannelVideo]:
    """Keep videos whose (normalized YYYYMMDD) upload date is within [since, until]."""
    kept: list[ChannelVideo] = []
    for video in videos:
        date = video.published
        if not (date and date.isdigit() and len(date) == 8):
            continue  # undated — can't place it in the range, so leave it out
        if since and date < since:
            continue
        if until and date > until:
            continue
        kept.append(video)
    return kept


def load_seen(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def append_seen(path: Path, video_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{video_id}\n")


def default_seen_path(dest: Path, channel_id: str) -> Path:
    return dest / f".seen-{channel_id}.txt"


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("channel", help="channel id (UC…), channel URL, or @handle")
    parser.add_argument("--dest", type=Path, default=Path("."),
                        help="output folder for transcripts (default: .)")
    parser.add_argument("--seen", type=Path, default=None,
                        help="file recording processed video ids "
                             "(default: <dest>/.seen-<channel_id>.txt)")
    parser.add_argument("--lang", default="en",
                        help="caption language code to fetch (default: en)")
    parser.add_argument("--limit", type=int, default=None,
                        help="max new videos to process this run (oldest first)")
    parser.add_argument("--since", default=None,
                        help="only videos on/after this date (YYYY-MM-DD); "
                             "uses the full upload history, not just the RSS feed")
    parser.add_argument("--until", default=None,
                        help="only videos on/before this date (YYYY-MM-DD)")
    parser.add_argument("--all", action="store_true",
                        help="consider the full upload history even without a date range")
    parser.add_argument("--sleep", type=float, default=2.0,
                        help="seconds to wait between videos, to throttle yt-dlp (default: 2.0)")
    parser.add_argument("--keep-vtt", action="store_true",
                        help="keep raw .vtt files alongside transcripts")
    parser.add_argument("--dry-run", action="store_true",
                        help="list new videos without fetching transcripts")
    return parser


def gather_candidate_videos(channel_id: str, since: str | None, until: str | None,
                            use_full_history: bool) -> list[ChannelVideo]:
    """Return channel videos to consider: RSS-recent, or full history + date filter."""
    if not (use_full_history or since or until):
        return fetch_channel_feed(channel_id)
    videos = fetch_channel_uploads(channel_id)
    if since or until:
        videos = filter_by_date(videos,
                                normalize_date(since) if since else None,
                                normalize_date(until) if until else None)
    return videos


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    channel_id = resolve_channel_id(args.channel)
    seen_path = args.seen or default_seen_path(args.dest, channel_id)
    seen = load_seen(seen_path)

    candidates = gather_candidate_videos(channel_id, args.since, args.until, args.all)
    # Sources list newest-first; process oldest-first so transcripts land chronologically.
    new_videos = [video for video in reversed(candidates) if video.video_id not in seen]
    if args.limit is not None:
        new_videos = new_videos[:args.limit]

    if not new_videos:
        print(f"{channel_id}: no new videos ({len(candidates)} considered, all seen)")
        return 0

    print(f"{channel_id}: {len(new_videos)} new video(s)")
    if args.dry_run:
        for video in new_videos:
            print(f"  would fetch {video.published} {video.video_id}  {video.title}")
        return 0

    failures = 0
    channel_dirs: set[Path] = set()
    for index, video in enumerate(new_videos):
        try:
            out_path, line_count = youtube_transcript.save_transcript(
                video.video_id, args.dest, args.lang, args.keep_vtt)
        except FileNotFoundError as error:
            # No captions yet (common for a just-uploaded video). Leave it unseen
            # so a later run retries once YouTube generates them. Logged, not hidden.
            print(f"  skip {video.video_id}: {error}", file=sys.stderr)
            continue
        except subprocess.CalledProcessError as error:
            print(f"  yt-dlp failed for {video.video_id}: exit {error.returncode}",
                  file=sys.stderr)
            failures += 1
            continue
        finally:
            # Throttle between videos regardless of outcome (skip after the last).
            if index < len(new_videos) - 1:
                time.sleep(args.sleep)
        append_seen(seen_path, video.video_id)
        channel_dirs.add(out_path.parent.parent)
        print(f"  [{index + 1}/{len(new_videos)}] {video.video_id}: "
              f"{line_count} lines -> {out_path.parent.relative_to(args.dest)}/")

    # Rebuild the per-channel index.jsonl (publish date -> video) from metadata.
    for channel_dir in sorted(channel_dirs):
        youtube_transcript.write_channel_index(channel_dir)

    if failures:
        raise SystemExit(f"{failures} video(s) failed; see messages above")
    return 0


if __name__ == "__main__":
    sys.exit(main())
