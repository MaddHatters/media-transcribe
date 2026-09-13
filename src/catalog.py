"""Catalog manager — single source of truth for post lifecycle tracking."""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.sources.discovery import DiscoveredPost

log = logging.getLogger(__name__)


def extract_post_id(url: str) -> str:
    m = re.search(r"(\d+)(?:\?|$)", url)
    if m:
        return m.group(1)
    parts = url.rstrip("/").split("/")
    for part in reversed(parts):
        m2 = re.search(r"(\d+)$", part)
        if m2:
            return m2.group(1)
    return ""

INGESTION_FIELDS = frozenset({
    "ingested_at", "ingested_status", "recording_mb",
    "transcript_words", "output_path", "error",
    "recorded", "recording_date",
})


class CatalogManager:
    def __init__(self, catalog_path: Path):
        self._path = catalog_path
        self._lock = threading.Lock()

    def load(self) -> list[dict]:
        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return data.get("posts", data.get("sessions", []))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Could not load catalog %s: %s", self._path, exc)
            return []

    def _load_metadata(self) -> dict:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return {k: v for k, v in data.items() if k not in ("posts", "sessions")}
        except (json.JSONDecodeError, OSError):
            return {}

    def save(self, posts: list[dict], metadata: dict | None = None) -> None:
        meta = metadata or self._load_metadata()
        meta["total_posts"] = len(posts)
        meta["video_posts"] = sum(1 for p in posts if p.get("has_video"))
        meta["audio_posts"] = sum(1 for p in posts if p.get("has_audio"))
        meta["last_discovery"] = datetime.now(timezone.utc).isoformat()
        meta.setdefault("creator", "Mr. FIRED Up Wealth")

        catalog = {**meta, "posts": posts}
        tmp_path = self._path.with_suffix(".tmp")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(
            json.dumps(catalog, indent=2, ensure_ascii=False), encoding="utf-8",
        )
        os.replace(tmp_path, self._path)

    def merge_discovered(self, discovered: list[DiscoveredPost]) -> tuple[list[dict], int]:
        existing = self.load()
        existing_by_id = {p["post_id"]: p for p in existing if "post_id" in p}

        new_count = 0
        for post in discovered:
            post_dict = asdict(post)
            pid = post_dict["post_id"]
            if pid in existing_by_id:
                entry = existing_by_id[pid]
                for key, value in post_dict.items():
                    if key not in INGESTION_FIELDS:
                        entry[key] = value
            else:
                if not post_dict.get("discovered_at"):
                    post_dict["discovered_at"] = datetime.now(timezone.utc).isoformat()
                existing_by_id[pid] = post_dict
                new_count += 1

        merged = sorted(
            existing_by_id.values(),
            key=lambda p: p.get("created_at", ""),
            reverse=True,
        )
        return list(merged), new_count

    def get_pending(self, post_types: list[str] | None = None) -> list[dict]:
        posts = self.load()
        pending = [p for p in posts if p.get("ingested_status") is None]
        if post_types:
            pending = [p for p in pending if p.get("post_type", "") in post_types]
        return sorted(pending, key=lambda p: p.get("created_at", ""), reverse=True)

    def update_post(self, post_id: str, updates: dict) -> None:
        with self._lock:
            posts = self.load()
            for post in posts:
                if post.get("post_id") == post_id:
                    post.update(updates)
                    self.save(posts)
                    return
            raise KeyError(f"Post {post_id} not found in catalog")

    def update_posts_batch(self, updates_by_id: dict[str, dict]) -> None:
        if not updates_by_id:
            return
        with self._lock:
            posts = self.load()
            for post in posts:
                pid = post.get("post_id")
                if pid in updates_by_id:
                    post.update(updates_by_id[pid])
            self.save(posts)

    def find_by_url(self, url: str) -> dict | None:
        for post in self.load():
            if post.get("url") == url:
                return post
        return None
