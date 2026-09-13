"""Content discovery via Patreon public JSON API."""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

PATREON_API = "https://www.patreon.com/api/posts"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
PAGE_DELAY_SECONDS = 1.0
MAX_PAGES = 50
COOLDOWN_HOURS = 12


@dataclass
class DiscoveredPost:
    post_id: str
    url: str
    title: str
    created_at: str
    post_type: str
    has_video: bool
    # --- Enriched fields (from Patreon API) ---
    published_at: Optional[str] = None
    edited_at: Optional[str] = None
    has_audio: bool = False
    duration_seconds: Optional[float] = None
    embed_url: Optional[str] = None
    embed_provider: Optional[str] = None
    thumbnail_url: Optional[str] = None
    like_count: Optional[int] = None
    comment_count: Optional[int] = None
    is_paid: Optional[bool] = None
    min_cents_pledged_to_view: Optional[int] = None
    tags: Optional[list] = None
    # --- Lifecycle fields ---
    recorded: bool = False
    recording_date: Optional[str] = None
    discovered_at: Optional[str] = None
    ingested_at: Optional[str] = None
    ingested_status: Optional[str] = None  # "complete" | "failed" | "skipped" | None
    recording_mb: Optional[float] = None
    transcript_words: Optional[int] = None
    output_path: Optional[str] = None
    error: Optional[str] = None


class PatreonDiscovery:
    def __init__(self, campaign_id: str = "5008493", cooldown_hours: float = COOLDOWN_HOURS):
        self.campaign_id = campaign_id
        self.cooldown_hours = cooldown_hours

    def fetch_posts(self, media_type: str | None = None, max_pages: int = 1, page_size: int = 50) -> list[DiscoveredPost]:
        posts: list[DiscoveredPost] = []
        cursor: str | None = None

        for page in range(max_pages):
            url = f"{PATREON_API}?filter[campaign_id]={self.campaign_id}&sort=-published_at&page[count]={page_size}"
            if media_type:
                url += f"&filter[media_types]={media_type}"
            if cursor:
                url += f"&page[cursor]={urllib.parse.quote(cursor, safe='')}"

            req = urllib.request.Request(url, headers={
                "Accept": "application/vnd.api+json",
                "User-Agent": USER_AGENT,
            })
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read())
            except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
                log.error("Patreon API request failed (page %d): %s", page + 1, exc)
                break

            for item in data.get("data", []):
                attrs = item.get("attributes", {})
                post_id = str(item.get("id", ""))
                title = attrs.get("title", "")
                if not post_id or not title:
                    continue
                post_type = attrs.get("post_type", "")

                # Duration: try video_preview first, then post_file
                duration = None
                vp = attrs.get("video_preview")
                if vp and vp.get("full_content_duration"):
                    duration = vp["full_content_duration"]
                pf = attrs.get("post_file")
                if not duration and pf and pf.get("duration"):
                    duration = pf["duration"]

                # Embed (YouTube URL for video_embed posts)
                embed = attrs.get("embed")
                embed_url = embed.get("url") if embed else None
                embed_provider = embed.get("provider") if embed else None

                # Tags from relationships
                tag_data = (
                    item.get("relationships", {})
                        .get("user_defined_tags", {})
                        .get("data", [])
                )
                tags = [t["id"].replace("user_defined;", "") for t in tag_data if "id" in t]

                # Thumbnail
                image = attrs.get("image")
                thumb = image.get("thumb_url") if image else None

                posts.append(DiscoveredPost(
                    post_id=post_id,
                    url=attrs.get("url") or f"https://www.patreon.com/posts/{post_id}",
                    title=title,
                    created_at=attrs.get("created_at", ""),
                    post_type=post_type,
                    has_video=post_type in ("video_external_file", "video_embed", "livestream_youtube"),
                    published_at=attrs.get("published_at"),
                    edited_at=attrs.get("edited_at"),
                    has_audio=post_type in ("podcast", "audio_file"),
                    duration_seconds=duration,
                    embed_url=embed_url,
                    embed_provider=embed_provider,
                    thumbnail_url=thumb,
                    like_count=attrs.get("like_count"),
                    comment_count=attrs.get("comment_count"),
                    is_paid=attrs.get("is_paid"),
                    min_cents_pledged_to_view=attrs.get("min_cents_pledged_to_view"),
                    tags=tags or None,
                    discovered_at=datetime.now(timezone.utc).isoformat(),
                ))

            pagination = data.get("meta", {}).get("pagination", {})
            cursor = pagination.get("cursors", {}).get("next")
            if not cursor:
                break

            if page < max_pages - 1:
                time.sleep(PAGE_DELAY_SECONDS)

        return posts

    def check_cooldown(self, state_dir: Path) -> bool:
        cooldown_path = state_dir / "last_discovery.txt"
        if not cooldown_path.exists():
            return True
        try:
            ts = cooldown_path.read_text(encoding="utf-8").strip()
            last_run = datetime.fromisoformat(ts)
            now = datetime.now(timezone.utc)
            hours_since = (now - last_run).total_seconds() / 3600
            if hours_since < self.cooldown_hours:
                log.info("Discovery cooldown active — %.1f hours since last run", hours_since)
                return False
            return True
        except (ValueError, OSError) as exc:
            log.warning("Could not read cooldown file: %s", exc)
            return True

    def update_cooldown(self, state_dir: Path) -> None:
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "last_discovery.txt").write_text(
            datetime.now(timezone.utc).isoformat(), encoding="utf-8",
        )

    def diff_catalog(self, discovered: list[DiscoveredPost], catalog_path: Path) -> list[DiscoveredPost]:
        existing_ids: set[str] = set()
        if catalog_path.exists():
            try:
                data = json.loads(catalog_path.read_text(encoding="utf-8"))
                for p in data.get("posts", []):
                    existing_ids.add(p["post_id"])
            except (json.JSONDecodeError, KeyError, OSError) as exc:
                log.warning("Could not load existing catalog: %s", exc)
        return [p for p in discovered if p.post_id not in existing_ids]

    def save_catalog(self, posts: list[DiscoveredPost], path: Path) -> None:
        sorted_posts = sorted(posts, key=lambda p: p.created_at, reverse=True)
        video_count = sum(1 for p in sorted_posts if p.has_video)
        audio_count = sum(1 for p in sorted_posts if p.has_audio)
        catalog = {
            "creator": "Mr. FIRED Up Wealth",
            "campaign_id": self.campaign_id,
            "last_discovery": datetime.now(timezone.utc).isoformat(),
            "total_posts": len(sorted_posts),
            "video_posts": video_count,
            "audio_posts": audio_count,
            "posts": [asdict(p) for p in sorted_posts],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False), encoding="utf-8")
