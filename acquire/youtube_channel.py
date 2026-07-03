#!/usr/bin/env python3
"""Watch a YouTube channel and save transcripts for its new videos.

Polls a channel's public RSS feed (no API key; the ~15 most recent uploads),
skips any video already recorded in a seen-file, and saves a timestamped
transcript for each new one via youtube_transcript.save_transcript.

Run it on a schedule (e.g. a systemd user timer) to catch uploads as they land.
For a full back-catalogue rather than just recent uploads, enumerate the channel
with `uvx yt-dlp --flat-playlist` instead — the RSS feed only carries ~15.

Usage:
    uv run acquire/youtube_channel.py https://www.youtube.com/@SomeChannel --dest transcripts
    uv run acquire/youtube_channel.py UC_x5XG1OV2P6uZZ5FSM9Ttw --dest transcripts
    uv run acquire/youtube_channel.py <channel> --seen state/seen.txt --limit 5 --dry-run
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
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
    parser.add_argument("--keep-vtt", action="store_true",
                        help="keep raw .vtt files alongside transcripts")
    parser.add_argument("--dry-run", action="store_true",
                        help="list new videos without fetching transcripts")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    channel_id = resolve_channel_id(args.channel)
    seen_path = args.seen or default_seen_path(args.dest, channel_id)
    seen = load_seen(seen_path)

    feed = fetch_channel_feed(channel_id)
    # RSS is newest-first; process oldest-first so transcripts land chronologically.
    new_videos = [video for video in reversed(feed) if video.video_id not in seen]
    if args.limit is not None:
        new_videos = new_videos[:args.limit]

    if not new_videos:
        print(f"{channel_id}: no new videos ({len(feed)} in feed, all seen)")
        return 0

    print(f"{channel_id}: {len(new_videos)} new video(s)")
    if args.dry_run:
        for video in new_videos:
            print(f"  would fetch {video.video_id}  {video.title}")
        return 0

    failures = 0
    for video in new_videos:
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
        append_seen(seen_path, video.video_id)
        print(f"  {video.video_id}: {line_count} lines -> {out_path.parent.relative_to(args.dest)}/")

    if failures:
        raise SystemExit(f"{failures} video(s) failed; see messages above")
    return 0


if __name__ == "__main__":
    sys.exit(main())
