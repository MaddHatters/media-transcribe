from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from pathlib import Path

import aiosqlite

from web.config import DB_PATH
from web.lifecycle import PIPELINE_STEPS

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    source_type TEXT NOT NULL,
    config      TEXT,
    created_at  TEXT NOT NULL
);

INSERT OR IGNORE INTO sources (id, name, description, source_type, created_at)
VALUES ('fuw', 'Fired Up Wealth', 'FIRE Investing Masterclass video library from Patreon', 'patreon', datetime('now'));

CREATE TABLE IF NOT EXISTS posts (
    post_id       TEXT PRIMARY KEY,
    source_id     TEXT NOT NULL DEFAULT 'fuw' REFERENCES sources(id),
    url           TEXT NOT NULL,
    title         TEXT NOT NULL,
    created_at    TEXT,
    published_at  TEXT,
    edited_at     TEXT,
    post_type     TEXT,
    has_video     BOOLEAN DEFAULT 0,
    has_audio     BOOLEAN DEFAULT 0,
    duration_seconds REAL,
    embed_url     TEXT,
    embed_provider TEXT,
    thumbnail_url TEXT,
    like_count    INTEGER,
    comment_count INTEGER,
    is_paid       BOOLEAN,
    min_cents_pledged_to_view INTEGER,
    tags          TEXT,
    discovered_at TEXT,
    recording_mb  REAL,
    transcript_words INTEGER,
    output_path   TEXT,
    overall_status TEXT DEFAULT 'discovered'
);

CREATE TABLE IF NOT EXISTS step_statuses (
    post_id       TEXT NOT NULL REFERENCES posts(post_id),
    step_name     TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',
    started_at    TEXT,
    completed_at  TEXT,
    error         TEXT,
    output_path   TEXT,
    duration_seconds REAL,
    attempt       INTEGER DEFAULT 0,
    PRIMARY KEY (post_id, step_name)
);

CREATE TABLE IF NOT EXISTS queue (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id       TEXT NOT NULL REFERENCES posts(post_id),
    priority      INTEGER DEFAULT 0,
    added_at      TEXT NOT NULL,
    status        TEXT DEFAULT 'waiting',
    started_at    TEXT,
    completed_at  TEXT,
    UNIQUE(post_id)
);

CREATE TABLE IF NOT EXISTS watcher_config (
    key           TEXT PRIMARY KEY,
    value         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS discovery_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id     TEXT NOT NULL DEFAULT 'fuw' REFERENCES sources(id),
    started_at    TEXT NOT NULL,
    completed_at  TEXT,
    posts_found   INTEGER DEFAULT 0,
    new_posts     INTEGER DEFAULT 0,
    source        TEXT DEFAULT 'patreon',
    status        TEXT DEFAULT 'running'
);

CREATE INDEX IF NOT EXISTS idx_posts_type ON posts(post_type);
CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(overall_status);
CREATE INDEX IF NOT EXISTS idx_posts_published ON posts(published_at);
CREATE INDEX IF NOT EXISTS idx_posts_source ON posts(source_id);
CREATE INDEX IF NOT EXISTS idx_step_status ON step_statuses(status);
CREATE INDEX IF NOT EXISTS idx_queue_status ON queue(status);
"""


async def init_db(db_path: Path | None = None) -> aiosqlite.Connection:
    path = db_path or DB_PATH
    db = await aiosqlite.connect(path)
    await db.execute("PRAGMA journal_mode=WAL")
    await db.executescript(_SCHEMA)
    await db.commit()
    return db


async def migrate_from_json(db: aiosqlite.Connection, json_path: Path) -> int:
    raw = json.loads(json_path.read_text(encoding="utf-8"))
    posts = raw.get("posts", raw.get("sessions", []))
    count = 0

    for post in posts:
        post_id = post["post_id"]
        tags_raw = post.get("tags")
        if isinstance(tags_raw, list):
            tags_str = json.dumps(tags_raw)
        else:
            tags_str = tags_raw

        ingested = post.get("ingested_status")
        if ingested == "complete":
            overall = "completed"
        elif ingested == "failed":
            overall = "failed"
        elif ingested == "skipped":
            overall = "completed"
        else:
            overall = "discovered"

        created_at = post.get("created_at")
        published_at = post.get("published_at", created_at)

        result = await db.execute(
            """INSERT OR IGNORE INTO posts
               (post_id, source_id, url, title, created_at, published_at, edited_at,
                post_type, has_video, has_audio, duration_seconds, embed_url,
                embed_provider, thumbnail_url, like_count, comment_count,
                is_paid, min_cents_pledged_to_view, tags, discovered_at,
                recording_mb, transcript_words, output_path, overall_status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                post_id,
                "fuw",
                post["url"],
                post["title"],
                created_at,
                published_at,
                post.get("edited_at"),
                post.get("post_type"),
                post.get("has_video", False),
                post.get("has_audio", False),
                post.get("duration_seconds"),
                post.get("embed_url"),
                post.get("embed_provider"),
                post.get("thumbnail_url"),
                post.get("like_count"),
                post.get("comment_count"),
                post.get("is_paid"),
                post.get("min_cents_pledged_to_view"),
                tags_str,
                post.get("discovered_at"),
                post.get("recording_mb"),
                post.get("transcript_words"),
                post.get("output_path"),
                overall,
            ),
        )
        if result.rowcount and result.rowcount > 0:
            count += 1

            if ingested == "complete":
                step_status = "completed"
            elif ingested == "skipped":
                step_status = "skipped"
            else:
                step_status = "pending"

            for step in PIPELINE_STEPS:
                s = step_status
                if ingested == "failed" and step == "record":
                    s = "failed"
                elif ingested == "failed" and step != "record":
                    s = "pending"
                await db.execute(
                    "INSERT OR IGNORE INTO step_statuses (post_id, step_name, status) VALUES (?, ?, ?)",
                    (post_id, step, s),
                )

    await db.commit()
    return count


async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()
