# Plan: Media-Transcribe Pipeline Dashboard (Web App)

## Task Description

Build a standalone web application for the `media-transcribe` project — a local, private pipeline dashboard that provides visibility into the video content lifecycle, from Patreon discovery through recording, transcription, and correction. The app replaces the current CLI-only workflow for monitoring and managing the pipeline, while keeping the CLI fully functional as the execution layer.

The system spans two machines connected via a gRPC control plane:

- **devbox-01** (Linux) — runs the FastAPI web server + Vue 3 frontend + SQLite database. This is the control plane and user-facing dashboard.
- **obs-machine** (Windows) — runs a gRPC agent server that wraps the existing Pipeline, ContentWatcher, OBSEngine, and Preflight classes. This is the execution plane where recording and GPU transcription happen.

The browser talks HTTP/WebSocket to FastAPI; FastAPI talks gRPC to the agent server. The browser never speaks gRPC directly.

**Task type:** Feature
**Complexity:** Complex

## Objective

When this plan is complete, a developer on devbox-01 can open a browser and:
1. Browse all 1,640+ Patreon catalog posts with rich filtering (type, step status, date, tags)
2. See exactly which pipeline step each post has completed (not just "complete" or "failed")
3. Queue videos for recording and manage the queue (add, remove, reorder, start/pause)
4. Monitor the autonomous content watcher (interval, last/next cycle, toggle on/off)
5. Trigger content discovery manually and see new posts
6. Watch pipeline progress in real-time via WebSocket updates streamed from the obs-machine's gRPC agent

The obs-machine auto-starts its gRPC agent server at boot via a Windows startup task. The web app on devbox-01 connects to it over Tailscale with bearer token authentication.

## Problem Statement

The pipeline currently tracks only two coarse states per post: `ingested_status: null` (untouched) or `"complete"` / `"failed"`. There is no per-step granularity — you cannot tell if a video was recorded but not yet transcribed, or if transcription succeeded but correction failed. All operations require CLI commands with no visual overview. Managing a 1,640-post catalog through JSON files and `grep` is unsustainable as the library grows.

Additionally, controlling the obs-machine currently requires manual SSH commands with careful quoting for PowerShell. There is no structured RPC contract, no streaming event feedback, and no way to monitor pipeline progress in real time from devbox-01.

## Solution Approach

### Architecture Decisions

#### 1. Inter-Machine Communication: gRPC Agent Server

**Decision:** The obs-machine runs a gRPC server (port 8421) that the devbox-01 web app connects to as a client. No SSH for pipeline/watcher/discovery operations.

**Rationale:**
- **Structured contract** — protobuf service definition enforces typed request/response, unlike ad-hoc SSH command strings
- **Server-streaming** — `StreamEvents` RPC delivers real-time pipeline events (step started/completed/failed, watcher cycles) to the web app, which relays them to the browser over WebSocket
- **No shell quoting** — SSH to PowerShell on Windows is fragile (quoting, escaping, encoding). gRPC eliminates this class of bugs entirely
- **Auto-reconnect** — gRPC channels handle reconnection natively; SSH connections don't
- **Backward compatible** — the agent server wraps existing classes (`Pipeline`, `ContentWatcher`, `PatreonDiscovery`, `Preflight`, `OBSEngine`) without duplication. The CLI continues to work independently.

**Data flow:**
```
┌─────────────┐    HTTP/WS     ┌──────────────┐    gRPC (8421)    ┌────────────────┐
│   Browser   │ ◄────────────▶ │   FastAPI     │ ◄──────────────▶ │  Agent Server  │
│  (Vue SPA)  │   :8420        │  (devbox-01)  │   Tailscale      │ (obs-machine)  │
└─────────────┘                └──────────────┘                   └────────────────┘
                                     │                                    │
                                     ▼                                    ▼
                                SQLite DB                          Pipeline, OBS,
                              (lifecycle,                          Watcher, Whisper
                               queue, stats)                       (JSON catalog)
```

#### 2. Security: Tailscale + Bearer Token

**Decision:** Two-layer security — Tailscale for network isolation, bearer token for application-level authentication. No mTLS.

**Rationale:**
- **Tailscale (Layer 1)** — WireGuard encrypted tunnel, network-level device isolation. Only tailnet devices can reach port 8421. This is the real security boundary.
- **Bearer token (Layer 2)** — a shared secret in `.env` on both machines, validated via a gRPC interceptor. Defense-in-depth against accidental exposure, not the primary security mechanism.
- **No cert management** — mTLS would add cert generation, rotation, and distribution complexity for negligible security gain on top of Tailscale. The bearer token is simpler and sufficient.

```python
# .env on both machines (same value)
AGENT_TOKEN=<random 64-char hex>

# gRPC client (devbox-01) — sends token in call metadata
metadata = [("authorization", f"bearer {AGENT_TOKEN}")]
response = stub.RunPipeline(request, metadata=metadata)

# gRPC server interceptor (obs-machine) — validates token
class AuthInterceptor(grpc.aio.ServerInterceptor):
    async def intercept_service(self, continuation, handler_call_details):
        metadata = dict(handler_call_details.invocation_metadata)
        token = metadata.get("authorization", "")
        if token != f"bearer {self._expected_token}":
            raise grpc.aio.AbortError(grpc.StatusCode.UNAUTHENTICATED, "Invalid token")
        return await continuation(handler_call_details)
```

#### 3. Database: SQLite (not JSON, not PostgreSQL)

**Decision:** SQLite as the web app's primary data store on devbox-01. JSON remains the canonical format on the obs-machine for backward-compatible CLI usage.

**Rationale:**
- The web app needs rich filtering, sorting, and pagination — SQL is native for this
- Per-step lifecycle tracking (7 steps × ~1,640 posts × timestamps) creates more complex data than flat JSON handles ergonomically
- Queue management benefits from ACID transactions
- Concurrent access (web server reads + gRPC event writes) needs proper locking — JSON with `threading.Lock` is insufficient for multi-process
- SQLite is zero-config, ships with Python, and is a single file — no Docker, no external service
- At 1,640 records, SQLite is massively overkill in terms of scale, but the query expressiveness and concurrency model justify it

**Migration strategy:**
- One-time migration script reads `data/patreon_full_catalog.json` → inserts into SQLite
- New `SQLiteCatalog` class implements the same interface as `CatalogManager`
- JSON export remains available via CLI (`uv run cli.py catalog-export`) for backward compatibility
- The obs-machine continues using JSON (it runs pipeline steps, not the web app)
- The web app on devbox-01 is the new source of truth; catalog updates arrive via gRPC `StreamEvents` and are written directly to SQLite — no file-watching needed

#### 4. Frontend: Vue 3 + Vite + TypeScript

**Decision:** Vue 3 SPA with Vite build tooling and TypeScript.

**Rationale:**
- Consistent with the orchestrator frontend the user already maintains
- Pinia for state management — lightweight and TypeScript-native
- TailwindCSS for utility-first styling (fast to build, consistent look)
- Vue Router for SPA navigation between dashboard views
- No SSR needed — fully client-side, served as static files by FastAPI

#### 5. Backend: FastAPI + SQLite + uvicorn

**Decision:** FastAPI REST API with WebSocket support, running on devbox-01.

**Rationale:**
- FastAPI is async-native, has built-in WebSocket support, and auto-generates OpenAPI docs
- Pydantic models shared between API and database layer for type safety
- uvicorn as the ASGI server (same stack as the orchestrator)
- The service layer uses the gRPC client (`ObsClient`) to communicate with the obs-machine for all pipeline, watcher, and remote discovery operations

#### 6. AI Extension Points (Phase 2 — stub only)

- `web/ai/provider.py` — abstract `AIProvider` protocol with `complete()`, `embed()`, `stream()` methods
- `web/ai/vectorstore.py` — abstract `VectorStore` protocol with `index()`, `search()`, `delete()` methods
- `/api/chat` route returns 501 with `{"detail": "AI chat available in Phase 2"}`
- Provider config in `web/config.py` with `AI_PROVIDER`, `AI_MODEL`, `VECTOR_STORE` settings (unused until Phase 2)

---

## gRPC Service Definition

### `proto/agent.proto`

```protobuf
syntax = "proto3";
package agent;

service AgentService {
  // Start a pipeline run for specific posts with optional step filtering
  rpc RunPipeline(PipelineRequest) returns (PipelineResponse);

  // Start the autonomous content watcher loop
  rpc StartWatcher(WatcherConfig) returns (WatcherResponse);

  // Gracefully stop the watcher (finishes current video, then stops)
  rpc StopWatcher(Empty) returns (WatcherResponse);

  // Get combined status: pipeline state, watcher state, disk usage, OBS/Chrome health
  rpc GetStatus(Empty) returns (AgentStatus);

  // Health check: is the machine up, OBS running, Chrome available, disk OK
  rpc HealthCheck(Empty) returns (HealthResponse);

  // Run Patreon content discovery (fetch new posts)
  rpc TriggerDiscovery(DiscoveryRequest) returns (DiscoveryResponse);

  // Server-streaming: real-time pipeline events pushed to client
  rpc StreamEvents(EventSubscription) returns (stream PipelineEvent);
}

message Empty {}

// --- Pipeline ---
message PipelineRequest {
  repeated PostEntry posts = 1;      // posts to process
  repeated string steps = 2;         // optional step filter (empty = all steps)
  bool shuffle = 3;                  // randomize order (anti-detection)
  bool enable_breaks = 4;            // human-like pauses between videos
}

message PostEntry {
  string post_id = 1;
  string url = 2;
  string title = 3;
  string filename = 4;
  string post_type = 5;
}

message PipelineResponse {
  bool started = 1;
  string run_id = 2;                 // unique ID for this pipeline run
  int32 queue_size = 3;
  string error = 4;                  // non-empty if failed to start
}

// --- Watcher ---
message WatcherConfig {
  float interval_hours = 1;          // minimum 12h enforced server-side
  repeated string steps = 2;         // pipeline steps to run per cycle
  int32 max_per_run = 3;             // max videos per cycle
  bool dry_run = 4;                  // discover but don't record
}

message WatcherResponse {
  bool success = 1;
  string message = 2;
  WatcherState state = 3;
}

message WatcherState {
  bool running = 1;
  int32 pid = 2;
  int32 cycle = 3;
  float interval_hours = 4;
  string last_run = 5;              // ISO timestamp
  string next_run = 6;              // ISO timestamp
  int32 new_found = 7;
  int32 recorded = 8;
  int32 failed = 9;
  int32 total_recorded = 10;
  string started_at = 11;
}

// --- Status ---
message AgentStatus {
  HealthResponse health = 1;
  WatcherState watcher = 2;
  PipelineState pipeline = 3;
  DiskInfo disk = 4;
}

message PipelineState {
  bool running = 1;
  string run_id = 2;
  int32 total = 3;
  int32 completed = 4;
  int32 failed = 5;
  string current_post = 6;
  string current_step = 7;
}

message DiskInfo {
  int64 total_bytes = 1;
  int64 free_bytes = 2;
  string drive = 3;                 // e.g. "D:"
}

message HealthResponse {
  bool healthy = 1;
  bool obs_connected = 2;
  bool chrome_available = 3;
  bool disk_ok = 4;                 // >= 5GB free
  string obs_version = 5;
  string error = 6;
}

// --- Discovery ---
message DiscoveryRequest {
  bool full_catalog = 1;            // paginate through all posts (slow)
  bool force = 2;                   // ignore cooldown timer
  string campaign_id = 3;           // default: "5008493"
}

message DiscoveryResponse {
  int32 total_found = 1;
  int32 new_posts = 2;
  int32 video_posts = 3;
  repeated DiscoveredPostInfo new_post_list = 4;
  string error = 5;
}

message DiscoveredPostInfo {
  string post_id = 1;
  string title = 2;
  string url = 3;
  string published_at = 4;
  string post_type = 5;
  bool has_video = 6;
}

// --- Streaming Events ---
message EventSubscription {
  repeated string event_types = 1;  // empty = all events
}

message PipelineEvent {
  string type = 1;                  // step_started, step_completed, step_failed,
                                    // watcher_cycle, discovery_complete, pipeline_complete
  string run_id = 2;
  string post_id = 3;
  string step = 4;
  string status = 5;
  string error = 6;
  string output_path = 7;
  float duration_seconds = 8;
  string timestamp = 9;            // ISO 8601
  map<string, string> metadata = 10;
}
```

---

## Granular Lifecycle State Machine

### Per-Step Status (replaces coarse `ingested_status`)

```
┌──────────┐     ┌────────┐     ┌─────────┐     ┌───────────┐     ┌────────┐
│ PENDING  │────▶│ QUEUED │────▶│ RUNNING │────▶│ COMPLETED │     │ FAILED │
└──────────┘     └────────┘     └─────────┘     └───────────┘     └────────┘
                                     │                                 ▲
                                     └─────────────────────────────────┘
                                                 (on error)

                 ┌─────────┐
                 │ SKIPPED │  (post type not applicable for this step)
                 └─────────┘
```

Each of the 7 pipeline steps has its own status:

```python
class StepStatus(str, Enum):
    PENDING   = "pending"     # Not yet started
    QUEUED    = "queued"      # Waiting in queue
    RUNNING   = "running"     # Currently executing
    COMPLETED = "completed"   # Successfully finished
    FAILED    = "failed"      # Failed with error message
    SKIPPED   = "skipped"     # Intentionally skipped (e.g., poll post → no record step)
```

### Steps (from `src/pipeline/runner.py`)

| Step | Input | Output | Runs On |
|------|-------|--------|---------|
| `record` | URL + filename | video.mp4 | obs-machine |
| `analyze` | video.mp4 | quality_report | obs-machine |
| `transcribe` | video.mp4 | .txt + .srt | obs-machine (GPU) |
| `correct` | .txt + .srt | corrected .txt + .srt | either |
| `find_gaps` | .srt | visual_gaps.yaml | either |
| `extract_frames` | gaps + video | screenshots/*.jpg | either |
| `ocr` | screenshots | slides/*.md | either |

### Derived Post Status

The overall post status is computed from step statuses:

```python
def derive_post_status(step_statuses: dict[str, StepStatus]) -> str:
    statuses = set(step_statuses.values())
    if StepStatus.RUNNING in statuses:
        return "in_progress"
    if all(s in (StepStatus.COMPLETED, StepStatus.SKIPPED) for s in statuses):
        return "completed"
    if StepStatus.FAILED in statuses and StepStatus.RUNNING not in statuses:
        return "failed"
    if StepStatus.QUEUED in statuses:
        return "queued"
    if any(s == StepStatus.COMPLETED for s in statuses):
        return "partial"    # some done, some pending
    return "discovered"     # all pending, nothing started
```

### Step Status Record (per post, per step)

```python
@dataclass
class StepRecord:
    status: StepStatus = StepStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    output_path: str | None = None
    duration_seconds: float | None = None
    attempt: int = 0          # retry count
```

---

## Data Model

### SQLite Schema (devbox-01)

```sql
-- Posts table (migrated from JSON catalog)
CREATE TABLE posts (
    post_id       TEXT PRIMARY KEY,
    url           TEXT NOT NULL,
    title         TEXT NOT NULL,
    created_at    TEXT,              -- Patreon created_at ISO
    published_at  TEXT,              -- Patreon published_at ISO
    edited_at     TEXT,
    post_type     TEXT,              -- video_external_file, video_embed, podcast, etc.
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
    tags          TEXT,              -- JSON array
    discovered_at TEXT,
    recording_mb  REAL,
    transcript_words INTEGER,
    output_path   TEXT,
    -- Derived overall status (computed, cached for fast queries)
    overall_status TEXT DEFAULT 'discovered'
);

-- Per-step lifecycle tracking
CREATE TABLE step_statuses (
    post_id       TEXT NOT NULL REFERENCES posts(post_id),
    step_name     TEXT NOT NULL,     -- record, analyze, transcribe, correct, find_gaps, extract_frames, ocr
    status        TEXT NOT NULL DEFAULT 'pending',
    started_at    TEXT,
    completed_at  TEXT,
    error         TEXT,
    output_path   TEXT,
    duration_seconds REAL,
    attempt       INTEGER DEFAULT 0,
    PRIMARY KEY (post_id, step_name)
);

-- Recording queue
CREATE TABLE queue (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id       TEXT NOT NULL REFERENCES posts(post_id),
    priority      INTEGER DEFAULT 0,   -- higher = sooner
    added_at      TEXT NOT NULL,
    status        TEXT DEFAULT 'waiting', -- waiting, processing, done, cancelled
    started_at    TEXT,
    completed_at  TEXT,
    UNIQUE(post_id)
);

-- Watcher configuration + state (local mirror of obs-machine watcher state)
CREATE TABLE watcher_config (
    key           TEXT PRIMARY KEY,
    value         TEXT NOT NULL
);

-- Discovery log
CREATE TABLE discovery_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    completed_at  TEXT,
    posts_found   INTEGER DEFAULT 0,
    new_posts     INTEGER DEFAULT 0,
    source        TEXT DEFAULT 'patreon',
    status        TEXT DEFAULT 'running'  -- running, completed, failed
);

-- Indexes for common queries
CREATE INDEX idx_posts_type ON posts(post_type);
CREATE INDEX idx_posts_status ON posts(overall_status);
CREATE INDEX idx_posts_published ON posts(published_at);
CREATE INDEX idx_step_status ON step_statuses(status);
CREATE INDEX idx_queue_status ON queue(status);
```

### Pydantic Models (shared between API and DB)

```python
class PostSummary(BaseModel):
    post_id: str
    url: str
    title: str
    published_at: str | None
    post_type: str
    has_video: bool
    has_audio: bool
    duration_seconds: float | None
    thumbnail_url: str | None
    tags: list[str]
    overall_status: str
    steps: dict[str, StepStatusResponse]

class StepStatusResponse(BaseModel):
    status: str
    started_at: str | None
    completed_at: str | None
    error: str | None

class QueueEntry(BaseModel):
    post_id: str
    title: str
    priority: int
    added_at: str
    status: str

class WatcherStatus(BaseModel):
    running: bool
    pid: int | None
    cycle: int
    interval_hours: float
    last_run: str | None
    next_run: str | None
    last_result: dict
    total_recorded: int

class AgentHealth(BaseModel):
    healthy: bool
    obs_connected: bool
    chrome_available: bool
    disk_ok: bool
    obs_version: str | None
    error: str | None

class CatalogStats(BaseModel):
    total_posts: int
    video_posts: int
    audio_posts: int
    by_status: dict[str, int]
    by_type: dict[str, int]
    by_step: dict[str, dict[str, int]]  # step → status → count
```

---

## Backend API Routes

### Catalog

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/catalog` | List posts with filtering, sorting, pagination |
| `GET` | `/api/catalog/:post_id` | Single post with full step detail |
| `GET` | `/api/catalog/stats` | Aggregate statistics |
| `POST` | `/api/catalog/import` | Re-import from JSON catalog file |

**Query parameters for `GET /api/catalog`:**
- `type` — filter by post_type (video, audio, podcast, all)
- `status` — filter by overall_status (discovered, queued, in_progress, partial, completed, failed)
- `step` — filter by specific step status (e.g., `step=transcribe:pending`)
- `search` — text search on title
- `tag` — filter by tag
- `sort` — field to sort by (default: `published_at`)
- `order` — asc/desc (default: desc)
- `page` / `per_page` — pagination (default: 1 / 50)

### Queue

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/queue` | Current queue with post details |
| `POST` | `/api/queue` | Add post(s) to queue (`{post_ids: [...], priority?: number}`) |
| `DELETE` | `/api/queue/:post_id` | Remove from queue |
| `PATCH` | `/api/queue/:post_id` | Update priority |
| `POST` | `/api/queue/reorder` | Bulk reorder (`{post_ids: [...]}`) |
| `POST` | `/api/queue/start` | Start processing queue (sends `RunPipeline` gRPC to obs-machine) |
| `POST` | `/api/queue/pause` | Pause queue processing |
| `POST` | `/api/queue/clear` | Clear completed/cancelled entries |

### Watcher

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/watcher/status` | Watcher state (via `GetStatus` gRPC to obs-machine) |
| `POST` | `/api/watcher/start` | Start watcher (sends `StartWatcher` gRPC to obs-machine) |
| `POST` | `/api/watcher/stop` | Stop watcher (sends `StopWatcher` gRPC to obs-machine) |
| `PATCH` | `/api/watcher/config` | Update config (`{interval_hours, max_per_run, steps}`) |

### Discovery

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/discovery/trigger` | Run discovery (sends `TriggerDiscovery` gRPC, merges results into SQLite) |
| `GET` | `/api/discovery/history` | Recent discovery runs |
| `GET` | `/api/discovery/new` | Posts discovered since last check (not yet queued) |

### Pipeline

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/pipeline/status` | Current pipeline run state (from `GetStatus` gRPC) |
| `POST` | `/api/pipeline/run` | Start pipeline for specific posts (sends `RunPipeline` gRPC) |

### Agent Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/agent/health` | obs-machine health (via `HealthCheck` gRPC): OBS, Chrome, disk |
| `GET` | `/api/agent/status` | Full agent status (via `GetStatus` gRPC): pipeline + watcher + disk |

### WebSocket

| Path | Description |
|------|-------------|
| `WS /ws/events` | Real-time events relayed from gRPC `StreamEvents`: step status changes, queue updates, watcher cycle events, discovery results |

**Event format (same for gRPC `PipelineEvent` and WebSocket JSON):**
```json
{
  "type": "step_completed",
  "run_id": "run_20260913_103000",
  "post_id": "12345",
  "step": "transcribe",
  "status": "completed",
  "output_path": "D:/MasterClass Video Backup/transcripts/Masterclass 19.txt",
  "duration_seconds": 142.5,
  "timestamp": "2026-09-13T10:32:22Z"
}
```

### AI Chat (Phase 2 — stub)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/chat` | Returns 501: "AI chat available in Phase 2" |
| `GET` | `/api/chat/providers` | Lists configured AI providers (empty in Phase 1) |

---

## Frontend Component Tree

```
App.vue
├── AppLayout.vue                    # Sidebar nav + main content area
│   ├── SidebarNav.vue              # Dashboard, Catalog, Queue, Watcher links
│   └── <router-view />
│
├── views/
│   ├── DashboardView.vue           # Overview: stats cards + recent activity + quick actions
│   │   ├── StatsCards.vue          # Total posts, videos, transcribed, pending counts
│   │   ├── AgentHealthBadge.vue   # obs-machine connection status (green/red dot)
│   │   ├── PipelineOverview.vue   # Step-by-step funnel chart (how many at each stage)
│   │   ├── RecentActivity.vue     # Last 10 step completions/failures
│   │   └── QuickActions.vue       # Discover Now, View Queue, Start Pipeline buttons
│   │
│   ├── CatalogView.vue            # Full catalog browser
│   │   ├── FilterBar.vue          # Type, status, step, date range, search, tag filters
│   │   ├── CatalogTable.vue       # Sortable table of posts
│   │   │   └── CatalogRow.vue     # One post row with inline step badges
│   │   │       └── StepBadge.vue  # Colored badge per step (pending/running/done/failed)
│   │   ├── PaginationBar.vue      # Page navigation
│   │   └── PostDetailModal.vue    # Expanded view: all step details, timeline, retry actions
│   │       └── StepTimeline.vue   # Vertical timeline of step executions with timestamps
│   │
│   ├── QueueView.vue              # Recording queue management
│   │   ├── QueueControls.vue      # Start/Pause/Clear buttons + status indicator
│   │   ├── QueueList.vue          # Draggable queue items with priority
│   │   │   └── QueueItem.vue      # Single queue entry with remove/priority controls
│   │   └── AddToQueuePanel.vue    # Search catalog + add selected posts to queue
│   │
│   └── WatcherView.vue            # Watcher dashboard
│       ├── WatcherStatus.vue      # Running/stopped, PID, interval, cycle count
│       ├── WatcherControls.vue    # Start/Stop toggle, interval/max-per-run config
│       ├── WatcherTimeline.vue    # History of watcher cycles with results
│       └── DiscoveryFeed.vue      # New posts since last check, quick-add to queue
│           └── DiscoveryCard.vue  # Post card with thumbnail, title, date, "Add to Queue" button
│
├── components/shared/
│   ├── StatusBadge.vue            # Reusable status badge (color-coded)
│   ├── PostTypeIcon.vue           # Icon for video/audio/podcast/text
│   ├── DurationDisplay.vue        # Formats seconds → "1h 23m"
│   ├── DateDisplay.vue            # Relative/absolute date display
│   ├── LoadingSpinner.vue
│   └── EmptyState.vue             # "No posts found" / "Queue empty" illustrations
│
├── stores/ (Pinia)
│   ├── catalog.ts                 # Posts, filters, pagination state
│   ├── queue.ts                   # Queue entries + processing state
│   ├── watcher.ts                 # Watcher status + config
│   ├── agent.ts                   # obs-machine health + connection state
│   └── websocket.ts               # WebSocket connection + event distribution
│
├── api/
│   ├── client.ts                  # Base fetch wrapper with error handling
│   ├── catalog.ts                 # Catalog API calls
│   ├── queue.ts                   # Queue API calls
│   ├── watcher.ts                 # Watcher API calls
│   ├── discovery.ts               # Discovery API calls
│   └── agent.ts                   # Agent health/status API calls
│
├── types/
│   └── index.ts                   # TypeScript interfaces matching Pydantic models
│
└── router.ts                      # Vue Router config
```

---

## Relevant Files

### Existing Files (read/integrate, don't rewrite)

- `src/catalog.py` — `CatalogManager` — the service layer wraps this; SQLite adapter implements same interface
- `src/pipeline/runner.py` — `Pipeline` class + `STEPS` list + `PipelineResult` — add optional step-level callback hooks for the agent server to emit gRPC events
- `src/pipeline/watcher.py` — `ContentWatcher` — the agent server wraps this for `StartWatcher`/`StopWatcher` RPCs
- `src/sources/discovery.py` — `PatreonDiscovery` + `DiscoveredPost` — the agent server wraps this for `TriggerDiscovery` RPC
- `src/sources/base.py` — `Post` dataclass + `Source` protocol — used by pipeline
- `src/config.py` — paths, network config, OBS config — extend with agent server settings (port, token env var)
- `cli.py` — CLI entry point — add `web` subcommand (devbox-01) and `serve` subcommand (obs-machine)
- `pyproject.toml` — add FastAPI, uvicorn, aiosqlite, grpcio dependencies

### New Files

#### Protobuf (`proto/`)

- `proto/agent.proto` — gRPC service definition (see full listing in gRPC Service Definition section above)
- `proto/agent_pb2.py` — generated protobuf message classes (committed for convenience, regenerated via `grpcio-tools`)
- `proto/agent_pb2_grpc.py` — generated gRPC stubs and servicers

#### Agent Server — obs-machine (`agent/`)

- `agent/__init__.py` — Package init
- `agent/server.py` — gRPC `AgentServiceServicer` implementation; wraps Pipeline, ContentWatcher, PatreonDiscovery, Preflight, OBSEngine; manages `StreamEvents` subscriber list and broadcasts `PipelineEvent` messages
- `agent/config.py` — Agent-specific config: port (default 8421), token from `AGENT_TOKEN` env var
- `agent/interceptors.py` — `AuthInterceptor` — validates bearer token from gRPC call metadata against `AGENT_TOKEN`

#### Web Backend — devbox-01 (`web/`)

- `web/__init__.py` — Package init
- `web/app.py` — FastAPI app factory, middleware, lifespan events (init DB, connect gRPC client on startup, disconnect on shutdown)
- `web/config.py` — Web-specific configuration: port (8420), host, CORS origins, DB path, agent server address (`100.66.194.100:8421`), `AGENT_TOKEN` from env
- `web/database.py` — SQLite connection management, schema creation, migration from JSON
- `web/models.py` — Pydantic models for API request/response
- `web/lifecycle.py` — `StepStatus` enum, `derive_post_status()`, state machine logic
- `web/routes/__init__.py` — Router aggregation
- `web/routes/catalog.py` — Catalog CRUD + filtering endpoints
- `web/routes/queue.py` — Queue management endpoints
- `web/routes/watcher.py` — Watcher status/control endpoints (delegates to gRPC client)
- `web/routes/discovery.py` — Discovery trigger endpoints (delegates to gRPC client, merges results into SQLite)
- `web/routes/pipeline.py` — Pipeline status/run endpoints (delegates to gRPC client)
- `web/routes/agent.py` — Agent health + status endpoints (delegates to gRPC client)
- `web/routes/ws.py` — WebSocket event stream (relays from gRPC `StreamEvents`)
- `web/services/__init__.py` — Service layer init
- `web/services/catalog_service.py` — Business logic wrapping `CatalogManager` with SQLite
- `web/services/queue_service.py` — Queue management logic
- `web/services/obs_client.py` — Async gRPC client: connects to obs-machine agent server, sends RPCs, manages `StreamEvents` subscription; all watcher/pipeline/discovery operations go through this
- `web/services/discovery_service.py` — Discovery orchestration: calls gRPC `TriggerDiscovery`, merges new posts into SQLite, logs to `discovery_runs`
- `web/services/pipeline_service.py` — Pipeline orchestration: calls gRPC `RunPipeline`, processes `StreamEvents` to update SQLite step statuses
- `web/services/event_bus.py` — In-process event bus for WebSocket broadcast; receives events from gRPC stream relay, fans out to connected browser WebSocket clients
- `web/ai/__init__.py` — Phase 2 extension point
- `web/ai/provider.py` — Abstract `AIProvider` protocol (stub)
- `web/ai/vectorstore.py` — Abstract `VectorStore` protocol (stub)

#### Frontend (`frontend/`)

- `frontend/package.json` — Dependencies (vue, vite, pinia, vue-router, tailwindcss, typescript)
- `frontend/vite.config.ts` — Vite config with API proxy to FastAPI
- `frontend/tsconfig.json` — TypeScript config
- `frontend/tailwind.config.js` — Tailwind config
- `frontend/index.html` — SPA entry point
- `frontend/src/main.ts` — Vue app bootstrap
- `frontend/src/App.vue` — Root component
- `frontend/src/router.ts` — Route definitions
- All component/store/api/type files listed in the component tree above

#### Tests

- `tests/web/test_catalog_api.py` — Catalog endpoint tests
- `tests/web/test_queue_api.py` — Queue endpoint tests
- `tests/web/test_lifecycle.py` — State machine logic tests
- `tests/web/test_database.py` — SQLite migration + CRUD tests
- `tests/web/test_catalog_service.py` — Service layer tests
- `tests/web/test_discovery_service.py` — Discovery service tests
- `tests/web/test_obs_client.py` — gRPC client tests (mock server)
- `tests/agent/test_server.py` — Agent server unit tests (in-process, no OBS/Chrome)
- `tests/agent/test_interceptors.py` — Auth interceptor tests (valid token, invalid token, missing token)

---

## Implementation Phases

### Phase 1: Foundation (Steps 1–5)

Establish the data layer, lifecycle state machine, skeleton backend, and protobuf contract. No frontend yet — validate with `curl` and pytest.

- Dependencies (grpcio, FastAPI, aiosqlite)
- Protobuf definition + code generation
- `StepStatus` enum and `derive_post_status()` logic
- SQLite schema + migration from JSON catalog
- Pydantic models
- FastAPI app skeleton with catalog endpoints
- Tests for data layer and state machine

### Phase 2: Agent Server (Steps 6–8)

Build the gRPC agent server on the obs-machine side. This is the execution-plane counterpart to the web app.

- Bearer token auth interceptor
- `AgentServiceServicer` implementation wrapping Pipeline, ContentWatcher, Preflight
- Pipeline callback hooks for step-level event emission
- `cli.py serve` subcommand
- Agent server tests

### Phase 3: Core Web Backend (Steps 9–12)

Build out all web API routes using the gRPC client to communicate with the agent server.

- gRPC client (`ObsClient`) connecting to agent server
- Queue management service + routes
- Watcher/discovery/pipeline routes (all via gRPC)
- Event bus + WebSocket relay from gRPC `StreamEvents`
- Full API test coverage

### Phase 4: Frontend (Steps 13–16)

Build the Vue 3 SPA with all views and real-time updates.

- Project scaffolding (Vite + Vue 3 + TypeScript + Tailwind + Pinia)
- Dashboard view with stats, agent health badge, and activity feed
- Catalog browser with filtering, sorting, pagination, step badges
- Queue management view with drag-to-reorder
- Watcher dashboard with controls and discovery feed
- WebSocket integration for live updates

### Phase 5: Integration & Polish (Steps 17–19)

Wire everything together, deploy, and test end-to-end.

- Production frontend build, FastAPI static file serving
- obs-machine deployment: Windows startup task for agent server
- `.env` setup on both machines
- End-to-end testing with real catalog data
- Phase 2 AI extension stubs

---

## Step by Step Tasks

IMPORTANT: Execute every step in order, top to bottom.

### 1. Add Dependencies

- Add to `pyproject.toml` under `[project.optional-dependencies]`:
  ```toml
  # Web dashboard (devbox-01)
  web = [
      "fastapi>=0.115",
      "uvicorn[standard]>=0.30",
      "aiosqlite>=0.20",
      "websockets>=12",
      "grpcio>=1.60",
  ]
  # gRPC agent server (obs-machine)
  agent = [
      "grpcio>=1.60",
  ]
  ```
- Add to `[dependency-groups]`:
  ```toml
  dev = [
      "pytest>=8",
      "pytest-asyncio>=0.23",
      "grpcio-tools>=1.60",
  ]
  ```
- Run `uv sync --extra web` on devbox-01
- Run `uv sync --extra agent` on obs-machine

### 2. Create Protobuf Definition + Generate Stubs

- Create `proto/agent.proto` with the full service definition (see gRPC Service Definition section)
- Add code generation script `proto/generate.sh`:
  ```bash
  #!/bin/bash
  # Generate Python gRPC stubs from proto definition
  set -euo pipefail
  cd "$(dirname "$0")/.."
  uv run python -m grpc_tools.protoc \
      -I proto \
      --python_out=proto \
      --grpc_python_out=proto \
      proto/agent.proto
  # Fix relative import in generated grpc file
  sed -i 's/import agent_pb2/from proto import agent_pb2/' proto/agent_pb2_grpc.py
  echo "Generated proto/agent_pb2.py and proto/agent_pb2_grpc.py"
  ```
- Run `bash proto/generate.sh` to generate `proto/agent_pb2.py` and `proto/agent_pb2_grpc.py`
- Create `proto/__init__.py` (empty, makes proto a package for imports)
- Commit the generated files for convenience (avoid requiring `grpcio-tools` on the obs-machine)

### 3. Create Lifecycle State Machine

- Create `web/lifecycle.py`:
  - `StepStatus` enum: `PENDING`, `QUEUED`, `RUNNING`, `COMPLETED`, `FAILED`, `SKIPPED`
  - `PIPELINE_STEPS` list: mirrors `src/pipeline/runner.STEPS`
  - `derive_post_status(step_statuses: dict[str, StepStatus]) -> str` — computes overall status
  - `step_can_run(step: str, step_statuses: dict) -> bool` — checks if dependencies are met (e.g., `transcribe` needs `record` completed)
- Create `tests/web/test_lifecycle.py`:
  - Test all status derivation cases: all pending → `discovered`, mixed → `partial`, all done → `completed`, any running → `in_progress`, failed with none running → `failed`
  - Test step dependency validation

### 4. Create SQLite Database Layer

- Create `web/database.py`:
  - `async def init_db(db_path: Path) -> aiosqlite.Connection` — creates tables from schema above
  - `async def migrate_from_json(db: Connection, json_path: Path) -> int` — reads JSON catalog, inserts into `posts` table, initializes `step_statuses` rows (all `PENDING`, except populate from existing `ingested_status` field: if `"complete"` → set all steps to `COMPLETED`, if `"failed"` → set last applicable step to `FAILED`, if `"skipped"` → set all to `SKIPPED`)
  - `async def get_db() -> AsyncGenerator[Connection]` — FastAPI dependency for request-scoped connections
- Create `web/config.py`:
  - `DB_PATH = Path("data/media_transcribe.db")`
  - `HOST = "0.0.0.0"`
  - `PORT = 8420`
  - `CORS_ORIGINS = ["http://localhost:5173", "http://localhost:8420"]`
  - `CATALOG_JSON_PATH` — imported from `src.config.CATALOG_PATH`
  - `AGENT_HOST = os.getenv("AGENT_HOST", "100.66.194.100")` — obs-machine Tailscale IP
  - `AGENT_PORT = int(os.getenv("AGENT_PORT", "8421"))`
  - `AGENT_TOKEN = os.getenv("AGENT_TOKEN", "")` — bearer token for gRPC auth
- Create `tests/web/test_database.py`:
  - Test schema creation on fresh DB
  - Test migration from a sample JSON catalog (use a fixture with 5 posts)
  - Test migration preserves existing `ingested_status` correctly

### 5. Create Pydantic Models

- Create `web/models.py`:
  - `PostSummary` — compact post representation for list views
  - `PostDetail` — full post with all step records
  - `StepStatusResponse` — per-step status detail
  - `QueueEntry` — queue item
  - `QueueAddRequest` — `{post_ids: list[str], priority: int = 0}`
  - `WatcherStatus` — watcher state
  - `WatcherConfigUpdate` — `{interval_hours: float | None, max_per_run: int | None, steps: list[str] | None}`
  - `AgentHealth` — obs-machine health (OBS, Chrome, disk)
  - `CatalogStats` — aggregate statistics
  - `DiscoveryTriggerRequest` — `{full_catalog: bool = False}`
  - `DiscoveryRunResponse` — discovery run result
  - `PipelineRunRequest` — `{post_ids: list[str], steps: list[str] | None}`
  - `WebSocketEvent` — `{type: str, data: dict, timestamp: str}`

### 6. Build Agent Server: Auth Interceptor

- Create `agent/__init__.py`
- Create `agent/config.py`:
  - `PORT = int(os.getenv("AGENT_PORT", "8421"))`
  - `AGENT_TOKEN = os.getenv("AGENT_TOKEN", "")` — loaded from `.env` file
  - Validate that `AGENT_TOKEN` is set and >= 32 chars on startup (fail-fast)
- Create `agent/interceptors.py`:
  - `AuthInterceptor(grpc.aio.ServerInterceptor)`:
    - Reads `AGENT_TOKEN` from config
    - On each RPC, extracts `authorization` from call metadata
    - Compares against `f"bearer {AGENT_TOKEN}"`
    - Aborts with `UNAUTHENTICATED` if missing or wrong
    - Passes through to handler if valid
  - Exempt `HealthCheck` from auth (allows external monitoring without a token)
- Create `tests/agent/test_interceptors.py`:
  - Test valid token → passes through
  - Test invalid token → `UNAUTHENTICATED`
  - Test missing token → `UNAUTHENTICATED`
  - Test `HealthCheck` exempt from auth

### 7. Build Agent Server: Core Implementation

- Create `agent/server.py` — `AgentServiceServicer`:
  - **`RunPipeline`**: Instantiates `Pipeline` with callback hooks, runs in a background `asyncio.Task`, returns immediately with `run_id`. Callbacks emit `PipelineEvent` to all `StreamEvents` subscribers.
  - **`StartWatcher`**: Creates and starts a `ContentWatcher` in a background task. Validates `interval_hours >= 12`. Emits `watcher_cycle` events via `StreamEvents`.
  - **`StopWatcher`**: Sets `ContentWatcher._shutdown = True` for graceful stop. Returns current state.
  - **`GetStatus`**: Reads `ContentWatcher.read_status()` for watcher state, checks `Pipeline` run state, queries disk space via `shutil.disk_usage()`, returns combined `AgentStatus`.
  - **`HealthCheck`**: Tests OBS WebSocket connection, Chrome CDP availability, disk space. Lightweight — no side effects.
  - **`TriggerDiscovery`**: Wraps `PatreonDiscovery.fetch_posts()` + `CatalogManager.merge_discovered()`. Returns counts + new post details.
  - **`StreamEvents`**: Registers the call as a subscriber. Yields `PipelineEvent` messages as they're produced by pipeline callbacks, watcher cycles, and discovery runs. Handles client disconnect gracefully.
  - Internal: `_event_queue: asyncio.Queue` per subscriber, `_broadcast(event: PipelineEvent)` sends to all queues.
- Modify `src/pipeline/runner.py`:
  - Add `on_step_start: Callable | None = None`, `on_step_complete: Callable | None = None`, `on_step_fail: Callable | None = None` parameters to `Pipeline.__init__()`:
    ```python
    def __init__(self, source, engine, output_dir=None, enable_breaks=False,
                 preflight=None, catalog=None,
                 on_step_start=None, on_step_complete=None, on_step_fail=None):
        # ...existing init...
        self._on_step_start = on_step_start
        self._on_step_complete = on_step_complete
        self._on_step_fail = on_step_fail
    ```
  - In `_process_one()`, call callbacks around each step:
    ```python
    for step in steps:
        if self._on_step_start:
            self._on_step_start(post, step)
        try:
            method = getattr(self, f"_step_{step}")
            await method(post, result)
            result.steps_completed.append(step)
            if self._on_step_complete:
                self._on_step_complete(post, step, result)
        except Exception as exc:
            log.error("Step '%s' failed for %s: %s", step, post.title, exc)
            result.steps_failed[step] = str(exc)
            if self._on_step_fail:
                self._on_step_fail(post, step, str(exc))
    ```
  - These callbacks are `None` when running via CLI (backward compatible), wired up by the agent server
- Create `tests/agent/test_server.py`:
  - Test `HealthCheck` returns valid response (mock OBS/Chrome checks)
  - Test `GetStatus` returns combined status
  - Test `TriggerDiscovery` with mocked Patreon API
  - Test `RunPipeline` starts a background task and returns `run_id`
  - Test `StreamEvents` receives events after `RunPipeline` triggers step callbacks

### 8. Add `serve` Subcommand to CLI

- Add to `cli.py`'s `build_parser()`:
  ```python
  # --- serve (agent gRPC server) ---
  s = sub.add_parser("serve", help="Start the gRPC agent server")
  s.add_argument("--port", type=int, default=8421)
  s.add_argument("--foreground", action="store_true",
                 help="Run in foreground instead of backgrounding")
  ```
- Add `"serve"` to `LONG_RUNNING_COMMANDS` set
- Handler in `main()`:
  ```python
  elif args.command == "serve":
      import asyncio
      from agent.server import run_server
      asyncio.run(run_server(port=args.port))
  ```
- Create `agent/server.run_server(port: int)` — creates gRPC server with `AuthInterceptor`, adds `AgentServiceServicer`, starts on `0.0.0.0:{port}`, waits for termination
- Test: `uv run cli.py serve --foreground` on obs-machine starts the server

### 9. Build gRPC Client (`ObsClient`)

- Create `web/services/obs_client.py`:
  - `ObsClient`:
    - `__init__(host: str, port: int, token: str)` — creates `grpc.aio.insecure_channel` (Tailscale handles encryption), stores auth metadata `[("authorization", f"bearer {token}")]`
    - `async def connect()` — opens channel, creates stub from `agent_pb2_grpc.AgentServiceStub`
    - `async def close()` — closes channel
    - `async def health_check() -> AgentHealth` — calls `HealthCheck` RPC, maps to Pydantic model
    - `async def get_status() -> dict` — calls `GetStatus` RPC
    - `async def run_pipeline(posts, steps=None, shuffle=False, breaks=True) -> dict` — calls `RunPipeline` RPC
    - `async def start_watcher(config) -> dict` — calls `StartWatcher` RPC
    - `async def stop_watcher() -> dict` — calls `StopWatcher` RPC
    - `async def trigger_discovery(full_catalog=False, force=False) -> dict` — calls `TriggerDiscovery` RPC
    - `async def stream_events(callback: Callable) -> None` — subscribes to `StreamEvents` server-stream, calls `callback(event)` for each received `PipelineEvent`. Runs in a background task. Auto-reconnects on disconnect with exponential backoff.
  - All methods attach auth metadata to calls
  - Timeout handling: 5s for health/status, 30s for discovery, no timeout for pipeline/watcher/stream
  - Error mapping: `grpc.StatusCode.UNAVAILABLE` → raise `AgentUnavailableError`; `UNAUTHENTICATED` → raise `AgentAuthError`
- Create `tests/web/test_obs_client.py`:
  - Test with mock gRPC server in-process
  - Test auth metadata is sent
  - Test error mapping (unavailable, auth failure)
  - Test `stream_events` receives and forwards events

### 10. Build Catalog Service + Routes

- Create `web/services/catalog_service.py`:
  - `CatalogService(db: Connection)`:
    - `async def list_posts(filters, sort, page, per_page) -> tuple[list[PostSummary], int]` — filtered query with pagination
    - `async def get_post(post_id: str) -> PostDetail | None` — single post with all step records
    - `async def get_stats() -> CatalogStats` — aggregate counts by status, type, step
    - `async def update_step_status(post_id: str, step: str, status: StepStatus, **kwargs)` — update step, recompute overall status
    - `async def import_from_json(json_path: Path) -> int` — re-import from JSON
    - `async def upsert_discovered(posts: list[dict]) -> int` — insert/update posts from gRPC discovery response
- Create `web/routes/catalog.py`:
  - `GET /api/catalog` — query params for filtering/sorting/pagination, returns `{posts: [...], total: int, page: int}`
  - `GET /api/catalog/{post_id}` — returns `PostDetail`
  - `GET /api/catalog/stats` — returns `CatalogStats`
  - `POST /api/catalog/import` — triggers re-import from JSON
- Create `tests/web/test_catalog_service.py` and `tests/web/test_catalog_api.py`

### 11. Build Queue Service + Routes

- Create `web/services/queue_service.py`:
  - `QueueService(db: Connection, obs_client: ObsClient)`:
    - `async def get_queue() -> list[QueueEntry]` — ordered by priority desc, added_at asc
    - `async def add_to_queue(post_ids: list[str], priority: int = 0) -> int` — adds entries, returns count
    - `async def remove_from_queue(post_id: str) -> bool`
    - `async def update_priority(post_id: str, priority: int)`
    - `async def reorder(post_ids: list[str])` — sets priority based on position
    - `async def start_queue() -> dict` — reads waiting queue entries, builds `PipelineRequest` with post details, calls `obs_client.run_pipeline()`, marks entries as `processing`
    - `async def pause_queue()` — sets flag; next gRPC event check stops sending new items
    - `async def clear_completed()`
- Create `web/routes/queue.py` — REST endpoints matching the API table above
- Create `tests/web/test_queue_api.py`

### 12. Build Watcher, Discovery, Pipeline, and Agent Routes

- Create `web/routes/watcher.py`:
  - `GET /api/watcher/status` — calls `obs_client.get_status()`, extracts watcher state
  - `POST /api/watcher/start` — calls `obs_client.start_watcher(config)`
  - `POST /api/watcher/stop` — calls `obs_client.stop_watcher()`
  - `PATCH /api/watcher/config` — validates config, calls `obs_client.start_watcher()` with updated params (restart)
- Create `web/services/discovery_service.py`:
  - `DiscoveryService(db: Connection, obs_client: ObsClient)`:
    - `async def trigger(full_catalog: bool = False, force: bool = False) -> DiscoveryRunResponse` — calls `obs_client.trigger_discovery()`, merges new posts into SQLite via `CatalogService.upsert_discovered()`, logs to `discovery_runs`
    - `async def get_new_posts() -> list[PostSummary]` — posts with `overall_status = 'discovered'` and no queue entry
    - `async def get_history() -> list[DiscoveryRunResponse]` — recent discovery runs from SQLite
- Create `web/routes/discovery.py`
- Create `web/services/pipeline_service.py`:
  - `PipelineService(db: Connection, obs_client: ObsClient, event_bus: EventBus)`:
    - `async def run(post_ids: list[str], steps: list[str] | None) -> dict` — calls `obs_client.run_pipeline()`, returns `run_id`
    - `async def get_status() -> dict` — calls `obs_client.get_status()`, extracts pipeline state
    - `async def handle_event(event: PipelineEvent)` — called when gRPC stream delivers an event; updates SQLite step status, publishes to EventBus for WebSocket relay
- Create `web/routes/pipeline.py`
- Create `web/routes/agent.py`:
  - `GET /api/agent/health` — calls `obs_client.health_check()`, returns `AgentHealth`
  - `GET /api/agent/status` — calls `obs_client.get_status()`, returns full `AgentStatus`

### 13. Build Event Bus + WebSocket Route

- Create `web/services/event_bus.py`:
  - `EventBus` singleton:
    - `subscribers: set[WebSocket]`
    - `async def subscribe(ws: WebSocket)`
    - `async def unsubscribe(ws: WebSocket)`
    - `async def publish(event: WebSocketEvent)` — broadcasts JSON to all subscribers
  - Event types: `step_started`, `step_completed`, `step_failed`, `queue_update`, `watcher_cycle`, `discovery_complete`, `pipeline_complete`
- Create `web/routes/ws.py`:
  - `WS /ws/events` — accepts WebSocket, registers with EventBus, sends events until disconnect
  - Heartbeat ping every 30s to detect stale connections
- Wire gRPC event stream → EventBus in `web/app.py` lifespan:
  - On startup, launch a background task that calls `obs_client.stream_events(callback)` where `callback` processes each `PipelineEvent`:
    1. Updates SQLite step status via `PipelineService.handle_event()`
    2. Converts to `WebSocketEvent` and publishes to `EventBus`
  - On shutdown, cancel the background task

### 14. Create FastAPI App Factory + CLI Subcommands

- Create `web/app.py`:
  - `create_app() -> FastAPI`:
    - Lifespan:
      - Startup: init DB + migrate from JSON if DB doesn't exist; create `ObsClient` and connect; start gRPC `StreamEvents` relay task
      - Shutdown: cancel relay task; close `ObsClient`; close DB
    - CORS middleware (configurable origins)
    - Include all route modules (catalog, queue, watcher, discovery, pipeline, agent, ws)
    - Mount `frontend/dist/` as static files (production mode)
    - Error handlers: `AgentUnavailableError` → 503, `AgentAuthError` → 502
    - OpenAPI docs at `/docs`
- Add `web` subcommand to `cli.py`:
  ```python
  w = sub.add_parser("web", help="Start the pipeline dashboard web server")
  w.add_argument("--host", default="0.0.0.0")
  w.add_argument("--port", type=int, default=8420)
  w.add_argument("--dev", action="store_true", help="Enable auto-reload for development")
  ```
  - Handler: `uvicorn.run("web.app:create_app", factory=True, host=..., port=..., reload=args.dev)`

### 15. Scaffold Frontend Project

- Initialize Vue 3 project in `frontend/`:
  ```bash
  npm create vite@latest frontend -- --template vue-ts
  cd frontend
  npm install vue-router@4 pinia @vueuse/core
  npm install -D tailwindcss @tailwindcss/vite
  ```
- Configure `vite.config.ts` with API proxy:
  ```typescript
  server: {
    proxy: {
      '/api': 'http://localhost:8420',
      '/ws': { target: 'ws://localhost:8420', ws: true }
    }
  }
  ```
- Set up TailwindCSS, Vue Router, Pinia
- Create TypeScript interfaces in `frontend/src/types/index.ts` matching Pydantic models (including `AgentHealth`)
- Create API client in `frontend/src/api/client.ts` with base URL and error handling

### 16. Build Dashboard View

- Create `frontend/src/views/DashboardView.vue`:
  - Stats cards: total posts, videos, fully transcribed, pending, failed
  - `AgentHealthBadge.vue` — polls `GET /api/agent/health` every 30s, shows green/yellow/red dot for obs-machine connectivity + OBS/Chrome status
  - Pipeline funnel: horizontal bar showing count at each step status
  - Recent activity feed: last 10 step completions (from WebSocket events)
  - Quick action buttons: Discover Now, View Queue, Open Catalog
- Create `frontend/src/stores/catalog.ts` (Pinia):
  - State: posts, filters, pagination, stats, loading
  - Actions: `fetchPosts()`, `fetchStats()`, `fetchPost(id)`
- Create `frontend/src/stores/agent.ts` (Pinia):
  - State: health, status, lastChecked
  - Actions: `fetchHealth()`, `fetchStatus()`
- Wire up API calls to backend

### 17. Build Catalog Browser View

- Create `frontend/src/views/CatalogView.vue`:
  - `FilterBar.vue` — dropdowns for type, status, step; date range picker; text search; tag filter
  - `CatalogTable.vue` — sortable columns: title, date, type, status, step progress
  - `CatalogRow.vue` — single row with `StepBadge.vue` instances showing 7 colored dots
  - `StepBadge.vue` — colored circle: gray (pending), blue (queued), yellow spinning (running), green (completed), red (failed), gray-strikethrough (skipped)
  - `PostDetailModal.vue` — click row to expand: full step timeline, output paths, error messages, "Retry Step" and "Add to Queue" buttons
  - `PaginationBar.vue` — page numbers, per-page selector
- Default sort: `published_at` descending

### 18. Build Queue + Watcher Views

- Create `frontend/src/views/QueueView.vue`:
  - Queue list with drag-to-reorder (use `@vueuse/core` drag utilities or `vue-draggable-plus`)
  - Controls: Start Pipeline, Pause, Clear Completed
  - Add panel: search catalog posts, click to add to queue
  - Status indicator: idle / processing / paused
- Create `frontend/src/views/WatcherView.vue`:
  - Status display: running/stopped, current cycle, interval, next run countdown
  - Controls: Start/Stop toggle, interval selector, max-per-run input
  - Discovery feed: cards for recently discovered posts, "Add to Queue" button on each
  - Cycle history: table of past watcher runs with results (found/recorded/failed)
- Create corresponding Pinia stores (`queue.ts`, `watcher.ts`)

### 19. WebSocket Integration

- Create `frontend/src/stores/websocket.ts`:
  - Auto-connect on app mount, reconnect on disconnect (exponential backoff)
  - Parse incoming events and dispatch to relevant stores:
    - `step_started` / `step_completed` / `step_failed` → update post in catalog store
    - `queue_update` → refresh queue store
    - `watcher_cycle` → update watcher store
    - `discovery_complete` → show notification + refresh discovery feed
    - `pipeline_complete` → show notification + refresh catalog stats
  - Toast notifications for important events (step failed, pipeline complete)

### 20. Production Build + Deployment

- Add build script to `frontend/package.json`: `"build": "vite build"`
- Configure `web/app.py` to serve `frontend/dist/` as static files when the directory exists
- Add `.gitignore` entries: `frontend/node_modules/`, `frontend/dist/`, `data/media_transcribe.db`, `.env`
- **obs-machine deployment:**
  - Create `.env` on obs-machine (`C:\Users\Matt\transcribe\.env`):
    ```
    AGENT_TOKEN=<generate with: python -c "import secrets; print(secrets.token_hex(32))">
    ```
  - Create Windows startup task for agent server auto-start:
    ```powershell
    schtasks /create /tn "MediaTranscribe_Agent" `
      /tr "powershell -Command \"cd C:\Users\Matt\transcribe; uv run cli.py serve --foreground\"" `
      /sc onstart /rl highest /it /f
    ```
  - Verify: `schtasks /run /tn "MediaTranscribe_Agent"` then test with `grpcurl` or the health endpoint
- **devbox-01 deployment:**
  - Create `.env` in repo root (gitignored):
    ```
    AGENT_TOKEN=<same value as obs-machine>
    AGENT_HOST=100.66.194.100
    AGENT_PORT=8421
    ```
  - Build frontend: `cd frontend && npm run build`
  - Start: `uv run cli.py web`
- Test full flow:
  1. Agent server running on obs-machine (port 8421)
  2. `uv run cli.py web` starts server on devbox-01 (port 8420)
  3. Open `http://localhost:8420` — dashboard loads, agent health badge shows green
  4. Click "Discover Now" — gRPC `TriggerDiscovery` fetches from Patreon, new posts appear
  5. Select posts → Add to Queue → Start Pipeline → gRPC `RunPipeline` fires
  6. WebSocket shows live step progress (relayed from gRPC `StreamEvents`)
  7. Watcher dashboard shows obs-machine watcher status

### 21. Add Phase 2 Extension Stubs

- Create `web/ai/__init__.py`
- Create `web/ai/provider.py`:
  ```python
  class AIProvider(Protocol):
      async def complete(self, messages: list[dict], **kwargs) -> str: ...
      async def embed(self, texts: list[str]) -> list[list[float]]: ...
      async def stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]: ...
  ```
- Create `web/ai/vectorstore.py`:
  ```python
  class VectorStore(Protocol):
      async def index(self, documents: list[Document]) -> int: ...
      async def search(self, query: str, top_k: int = 10) -> list[SearchResult]: ...
      async def delete(self, doc_ids: list[str]) -> int: ...
  ```
- Add stub route `POST /api/chat` → 501 response
- Add placeholder config: `AI_PROVIDER = None`, `VECTOR_STORE = None`

---

## Testing Strategy

### Unit Tests (pytest, no network/OBS/Chrome)

- **Lifecycle logic**: All status derivation paths, step dependency checks, edge cases (empty steps, all skipped)
- **Database layer**: Schema creation, JSON migration, CRUD operations, filter queries
- **Service layer**: Catalog filtering, queue ordering, status computation — mock DB with in-memory SQLite
- **API routes**: FastAPI `TestClient` with fixture DB and mock `ObsClient` — test all endpoints, query params, error cases
- **Auth interceptor**: Valid token passes, invalid/missing token rejects, `HealthCheck` exempt
- **Agent server**: In-process servicer tests with mocked Pipeline/Watcher/Discovery classes
- **gRPC client**: Tests with mock in-process gRPC server

### Integration Tests

- **Migration test**: Load the real `patreon_full_catalog.json`, migrate to SQLite, verify counts match
- **gRPC roundtrip**: Start agent server in-process, connect client, run `HealthCheck` → verify response
- **Event stream test**: Start agent server, connect client, subscribe to `StreamEvents`, trigger `RunPipeline` with mock pipeline, verify events arrive
- **Discovery → SQLite test**: Mock Patreon API, trigger discovery via gRPC, verify new posts in SQLite

### Frontend Tests (optional, Phase 1 can skip)

- Component tests with Vitest + Vue Test Utils for critical components (StepBadge, FilterBar, AgentHealthBadge)
- E2E tests with Playwright for full flow (discovery → queue → verify status)

### Test Commands
```bash
# All backend tests
uv run pytest tests/ -v

# Web-specific tests
uv run pytest tests/web/ -v

# Agent server tests
uv run pytest tests/agent/ -v

# Frontend dev server
cd frontend && npm run dev

# Frontend build
cd frontend && npm run build

# Full stack (production mode)
uv run cli.py web
```

---

## Acceptance Criteria

1. **Agent server**: `uv run cli.py serve --foreground` starts gRPC server on port 8421; `HealthCheck` RPC responds with OBS/Chrome/disk status
2. **Bearer token auth**: gRPC calls without valid `AGENT_TOKEN` are rejected with `UNAUTHENTICATED`; `HealthCheck` is exempt
3. **Catalog browsing**: All 1,640+ posts load in the catalog view, filterable by type (video/audio/all), overall status, per-step status, and text search
4. **Per-step visibility**: Each post shows 7 step badges; clicking reveals timestamps, errors, output paths
5. **Default sort**: Posts sorted by `published_at` descending by default
6. **Queue management**: Can add/remove posts from queue, reorder by drag; "Start Pipeline" sends `RunPipeline` gRPC to obs-machine
7. **Watcher dashboard**: Shows watcher status from obs-machine via gRPC (running/stopped, interval, next run), start/stop controls work
8. **Discovery**: "Discover Now" button sends `TriggerDiscovery` gRPC, merges results into SQLite, new posts appear in feed
9. **Real-time updates**: gRPC `StreamEvents` delivers step status changes to FastAPI, which relays via WebSocket to browser within 1 second
10. **Agent health**: Dashboard shows obs-machine health badge (green/yellow/red) based on `HealthCheck` gRPC
11. **Migration**: Running `uv run cli.py web` on a fresh install auto-migrates from JSON catalog to SQLite
12. **Backward compatibility**: All existing CLI commands (`pipeline`, `discover`, `watch`, etc.) continue to work unchanged on the obs-machine
13. **Tests pass**: `uv run pytest tests/web/ tests/agent/ -v` passes with ≥90% coverage of backend code
14. **Phase 2 stubs**: `POST /api/chat` returns 501; `AIProvider` and `VectorStore` protocols exist in `web/ai/`
15. **Standalone**: No dependency on the orchestrator — runs independently on devbox-01
16. **Auto-start**: obs-machine agent server starts automatically at boot via Windows startup task

---

## Validation Commands

Execute these commands to validate the task is complete:

```bash
# --- Dependencies ---
uv sync --extra web                  # devbox-01: verify web deps install
uv sync --extra agent                # obs-machine: verify agent deps install

# --- Protobuf ---
uv run python -c "from proto import agent_pb2, agent_pb2_grpc; print('OK')"

# --- Lifecycle ---
uv run python -c "from web.lifecycle import StepStatus, derive_post_status; print('OK')"

# --- Agent server ---
uv run cli.py serve --help           # verify CLI subcommand exists
# On obs-machine:
uv run cli.py serve --foreground &   # start agent server
uv run python -c "
import grpc
from proto import agent_pb2, agent_pb2_grpc
channel = grpc.insecure_channel('localhost:8421')
stub = agent_pb2_grpc.AgentServiceStub(channel)
resp = stub.HealthCheck(agent_pb2.Empty())
print(f'healthy={resp.healthy}, obs={resp.obs_connected}, chrome={resp.chrome_available}')
"

# --- Web server ---
uv run cli.py web --help             # verify CLI subcommand exists
uv run cli.py web &; sleep 3; curl -s http://localhost:8420/api/catalog/stats | python -m json.tool
curl -s http://localhost:8420/api/agent/health | python -m json.tool

# --- Tests ---
uv run pytest tests/web/ -v          # web backend tests
uv run pytest tests/agent/ -v        # agent server tests
uv run pytest tests/ -v              # all tests (verify no regressions)

# --- Frontend ---
cd frontend && npm run build         # verify frontend builds

# --- Auth ---
# Should fail with UNAUTHENTICATED:
uv run python -c "
import grpc
from proto import agent_pb2, agent_pb2_grpc
channel = grpc.insecure_channel('100.66.194.100:8421')
stub = agent_pb2_grpc.AgentServiceStub(channel)
try:
    stub.GetStatus(agent_pb2.Empty())
except grpc.RpcError as e:
    print(f'Expected: {e.code()} = {e.details()}')
"
```

---

## Notes

### Dependencies to Add

```bash
# Backend — devbox-01 (web dashboard + gRPC client)
uv add --optional web fastapi "uvicorn[standard]" aiosqlite websockets grpcio

# Backend — obs-machine (gRPC agent server)
uv add --optional agent grpcio

# Dev (both machines, for protoc code generation)
uv add --group dev grpcio-tools

# Frontend (in frontend/ directory)
npm create vite@latest . -- --template vue-ts
npm install vue-router@4 pinia @vueuse/core
npm install -D tailwindcss @tailwindcss/vite
```

### Port Assignment

| Service | Port | Machine | Protocol |
|---------|------|---------|----------|
| FastAPI web server | 8420 | devbox-01 | HTTP + WebSocket |
| Vite dev server | 5173 | devbox-01 | HTTP (proxies to 8420) |
| gRPC agent server | 8421 | obs-machine | gRPC (HTTP/2) |
| OBS WebSocket | 4455 | obs-machine | WebSocket (internal only) |
| Chrome CDP | 9222 | obs-machine | HTTP (internal only) |

Production: frontend served from FastAPI on 8420 (static files from `frontend/dist/`).

### gRPC Channel Security

The gRPC channel uses `grpc.insecure_channel()` — this is safe because:
1. **Tailscale provides the encryption.** All traffic between devbox-01 and obs-machine traverses a WireGuard tunnel. The gRPC bytes are already encrypted at the network layer.
2. **Bearer token provides authentication.** Even if someone were on the tailnet, they'd need the `AGENT_TOKEN` to make RPC calls.
3. Using `grpc.secure_channel()` with TLS would double-encrypt without meaningful security gain, while adding cert management overhead.

### `.env` File Management

Both machines need a `.env` file with the same `AGENT_TOKEN` value:

```bash
# Generate token (run once, copy to both machines):
python -c "import secrets; print(f'AGENT_TOKEN={secrets.token_hex(32)}')"

# devbox-01: /home/tuna/repos/media-transcribe/.env
AGENT_TOKEN=<the token>
AGENT_HOST=100.66.194.100
AGENT_PORT=8421

# obs-machine: C:\Users\Matt\transcribe\.env
AGENT_TOKEN=<same token>
AGENT_PORT=8421
```

Load with `python-dotenv` or manual `os.getenv()` with `.env` parsing in config modules. The `.env` file is gitignored.

### Catalog Sync Strategy

With gRPC, catalog sync is event-driven rather than file-watching:

1. **Pipeline events** → gRPC `StreamEvents` delivers `step_completed` / `step_failed` events → web app updates SQLite directly
2. **Discovery** → gRPC `TriggerDiscovery` response includes new post data → web app inserts into SQLite
3. **No file-watching needed** — the gRPC stream is the sync mechanism
4. **Fallback**: `POST /api/catalog/import` manually re-imports from JSON if data drifts
5. **obs-machine still writes JSON** via `CatalogManager` for backward compatibility with CLI. The web app's SQLite is the primary data store for the dashboard.

### Windows Startup Task for Agent Server

```powershell
# Create the startup task (run once, elevated PowerShell):
schtasks /create /tn "MediaTranscribe_Agent" `
    /tr "powershell -WindowStyle Hidden -Command \"cd C:\Users\Matt\transcribe; uv run cli.py serve --foreground 2>&1 | Tee-Object -FilePath C:\Users\Matt\agent-control\logs\agent_server.log\"" `
    /sc onstart /rl highest /it /f

# Test it:
schtasks /run /tn "MediaTranscribe_Agent"

# Check status:
schtasks /query /tn "MediaTranscribe_Agent" /fo LIST

# The agent server logs to C:\Users\Matt\agent-control\logs\agent_server.log
```

### Security Model Summary

```
┌─────────────────────────────────────────────────────────────────┐
│                        Tailscale Mesh                          │
│  (WireGuard encrypted, device-authenticated, NAT traversal)    │
│                                                                │
│  ┌──────────────┐                    ┌───────────────────┐     │
│  │  devbox-01   │ ── gRPC :8421 ──▶ │   obs-machine     │     │
│  │              │    + bearer token  │                   │     │
│  │  FastAPI     │                    │  Agent Server     │     │
│  │  :8420       │                    │  (Pipeline, OBS,  │     │
│  │  (browser ◄──│── HTTP/WS)        │   Watcher, etc.)  │     │
│  └──────────────┘                    └───────────────────┘     │
│                                                                │
│  Layer 1: Tailscale — only tailnet devices can reach :8421     │
│  Layer 2: Bearer token — AGENT_TOKEN in .env on both machines  │
│  Layer 3: HealthCheck exempt (monitoring probe, no side effects)│
└─────────────────────────────────────────────────────────────────┘
```

### Phase 2 Extension Architecture

When AI chat is implemented:
1. Implement `AIProvider` for the chosen provider (e.g., `AnthropicProvider`, `OpenAIProvider`, `OllamaProvider`)
2. Implement `VectorStore` for the chosen store (e.g., `ChromaVectorStore`, `LanceDBStore`)
3. Add transcript indexing pipeline: on gRPC `step_completed` event for `transcribe` step, chunk transcript → embed → store
4. `POST /api/chat` accepts `{message: str, context_filter?: {post_ids, date_range}}` → RAG retrieval → LLM completion → streamed response
5. Frontend: chat panel component, transcript search, insights dashboard
