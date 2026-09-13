from __future__ import annotations

from pydantic import BaseModel


class StepStatusResponse(BaseModel):
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    output_path: str | None = None
    duration_seconds: float | None = None
    attempt: int = 0


class PostSummary(BaseModel):
    post_id: str
    source_id: str
    url: str
    title: str
    published_at: str | None = None
    post_type: str
    has_video: bool
    has_audio: bool
    duration_seconds: float | None = None
    thumbnail_url: str | None = None
    tags: list[str] = []
    overall_status: str
    steps: dict[str, StepStatusResponse] = {}


class PostDetail(PostSummary):
    created_at: str | None = None
    edited_at: str | None = None
    embed_url: str | None = None
    embed_provider: str | None = None
    like_count: int | None = None
    comment_count: int | None = None
    is_paid: bool | None = None
    min_cents_pledged_to_view: int | None = None
    discovered_at: str | None = None
    recording_mb: float | None = None
    transcript_words: int | None = None
    output_path: str | None = None


class QueueEntry(BaseModel):
    post_id: str
    title: str
    priority: int
    added_at: str
    status: str


class QueueAddRequest(BaseModel):
    post_ids: list[str]
    priority: int = 0


class WatcherStatus(BaseModel):
    running: bool
    pid: int | None = None
    cycle: int = 0
    interval_hours: float = 24.0
    last_run: str | None = None
    next_run: str | None = None
    last_result: dict = {}
    total_recorded: int = 0


class WatcherConfigUpdate(BaseModel):
    interval_hours: float | None = None
    max_per_run: int | None = None
    steps: list[str] | None = None


class AgentHealth(BaseModel):
    healthy: bool
    obs_connected: bool
    chrome_available: bool
    disk_ok: bool
    obs_version: str | None = None
    error: str | None = None


class CatalogStats(BaseModel):
    total_posts: int
    video_posts: int
    audio_posts: int
    by_status: dict[str, int] = {}
    by_type: dict[str, int] = {}
    by_step: dict[str, dict[str, int]] = {}


class DiscoveryTriggerRequest(BaseModel):
    full_catalog: bool = False
    force: bool = False


class DiscoveryRunResponse(BaseModel):
    id: int | None = None
    started_at: str
    completed_at: str | None = None
    posts_found: int = 0
    new_posts: int = 0
    source: str = "patreon"
    status: str = "running"


class PipelineRunRequest(BaseModel):
    post_ids: list[str]
    steps: list[str] | None = None


class WebSocketEvent(BaseModel):
    type: str
    data: dict = {}
    timestamp: str
