# Insights App — Architecture Reference

> Pipeline dashboard for the media-transcribe project.
> **URL:** `https://insights.tunalab.dev`
> **Spec:** `specs/media-transcribe-web-app.md`

## System Overview

**Insights** is a standalone web application that provides visibility into the Patreon video content lifecycle — from discovery through recording, transcription, correction, and OCR. It replaces the CLI-only workflow for monitoring and managing the media-transcribe pipeline while the CLI remains fully functional as the execution layer on the obs-machine.

The system spans two machines connected via a gRPC control plane over Tailscale:

- **devbox-01** (Linux) — control plane. Runs the FastAPI web server, Vue 3 frontend, and SQLite database. Accessible at `https://insights.tunalab.dev` via Caddy reverse proxy.
- **obs-machine** (Windows) — execution plane. Runs a gRPC agent server that wraps the existing Pipeline, ContentWatcher, OBSEngine, and Preflight classes. Recording and GPU transcription happen here.

The browser never speaks gRPC directly. FastAPI acts as the bridge: HTTP/WebSocket for the browser, gRPC for the obs-machine.

### What It Does

1. **Catalog browser** — filterable by post type (video/audio/podcast), per-step pipeline status, tags, date, and text search. Default sort: Patreon `published_at` descending.
2. **Per-step pipeline tracking** — each post shows granular status across 7 pipeline steps, replacing the old binary `complete`/`failed` tracking.
3. **Recording queue** — select posts to queue, reorder by priority, start/pause pipeline processing on the obs-machine.
4. **Watcher dashboard** — monitor and control the autonomous content watcher (interval, last/next cycle, start/stop).
5. **Discovery feed** — trigger Patreon content discovery, view new posts, quick-add to recording queue.
6. **Real-time updates** — pipeline step events stream from obs-machine → web server → browser in real time.
7. **(Future) AI chat** — RAG-powered chat over transcript data with swappable model providers. Stubbed in Phase 1.

### What It Is NOT

- Not part of the orchestrator (`multi-agent-orchestration`) — fully standalone
- Not a replacement for the CLI — `cli.py` remains the execution layer on the obs-machine; Insights is the control plane
- Not a media player or transcript viewer (future phase)

---

## Topology

```
                          ┌──────────────────────────────────────────────────────┐
                          │                   Tailscale Mesh                     │
                          │          (WireGuard encrypted, device-auth)          │
                          │                                                      │
  Browser                 │  devbox-01 (100.126.202.43)         obs-machine      │
  (any tailnet device)    │  ┌─────────────────────────┐       (100.66.194.100)  │
        │                 │  │                         │       ┌──────────────┐  │
        │ HTTPS           │  │  Caddy (:443)           │ gRPC  │ Agent Server │  │
        └────────────────────▶  │ reverse_proxy        │──────▶│   (:8421)    │  │
                          │  │  ▼                      │       │              │  │
                          │  │ FastAPI (:8420)          │       │ ├─Pipeline   │  │
                          │  │  │ REST API             │       │ ├─Watcher    │  │
                          │  │  │ WebSocket (/ws)      │       │ ├─OBSEngine  │  │
                          │  │  │                      │       │ ├─Preflight  │  │
                          │  │  │ ObsClient (gRPC)─────│───────│ ├─Discovery  │  │
                          │  │  │                      │       │ └─Whisper    │  │
                          │  │ Vue 3 SPA               │       │              │  │
                          │  │  (frontend/dist/)       │       │ JSON catalog │  │
                          │  │                         │       │ (CLI compat) │  │
                          │  │ SQLite                   │       └──────────────┘  │
                          │  │  data/media_transcribe.db│                         │
                          │  └─────────────────────────┘                         │
                          └──────────────────────────────────────────────────────┘
```

### Request Path

```
Browser → Caddy (HTTPS :443) → FastAPI (:8420) → gRPC client → Agent Server (:8421 obs-machine)
                                     │                                  │
                                     ▼                                  ▼
                               SQLite (reads/writes)             Pipeline execution
                                     │                                  │
                                     ▼                                  ▼
                              WebSocket (:8420/ws)           StreamEvents (gRPC stream)
                                     │                                  │
                                     ▼                                  │
                                  Browser  ◄────── events relayed ◄─────┘
```

---

## Component Breakdown

### devbox-01 Components

| Component | What | Where | Depends On |
|-----------|------|-------|------------|
| **Caddy** | TLS termination, serves frontend static files from `frontend/dist/`, proxies `/api/*` and `/ws/*` to FastAPI | `/etc/caddy/Caddyfile` | Cloudflare DNS A record, systemd |
| **FastAPI** | REST API + WebSocket on `:8420`. API-only in production (Caddy serves static files) | `web/app.py` | SQLite, ObsClient, uvicorn |
| **Vue 3 SPA** | Dashboard UI — catalog browser, queue manager, watcher dashboard, discovery feed | `frontend/` | FastAPI (API + WebSocket) |
| **SQLite** | Primary data store: posts, per-step lifecycle, queue, discovery logs | `data/media_transcribe.db` | Migrated from JSON on first run |
| **ObsClient** | Async gRPC client connecting to obs-machine agent server | `web/services/obs_client.py` | gRPC channel to `100.66.194.100:8421`, `AGENT_TOKEN` |
| **EventBus** | In-process pub/sub. Receives gRPC events, fans out to browser WebSocket clients | `web/services/event_bus.py` | ObsClient stream relay |

### obs-machine Components

| Component | What | Where | Depends On |
|-----------|------|-------|------------|
| **Agent Server** | gRPC server on `:8421`. Wraps Pipeline, Watcher, Discovery, Preflight | `agent/server.py` | `AGENT_TOKEN`, OBS, Chrome, GPU |
| **AuthInterceptor** | gRPC interceptor validating bearer token. `HealthCheck` exempt | `agent/interceptors.py` | `AGENT_TOKEN` from `.env` |
| **Pipeline** | Chains record → analyze → transcribe → correct → find_gaps → extract_frames → ocr | `src/pipeline/runner.py` | OBSEngine, Source, CatalogManager |
| **ContentWatcher** | Autonomous discovery + recording loop on configurable interval | `src/pipeline/watcher.py` | PatreonDiscovery, Pipeline |
| **OBSEngine** | Controls OBS Studio via WebSocket (`:4455`) | `src/engines/obs_engine.py` | OBS Studio |
| **Whisper** | GPU-accelerated transcription via faster-whisper | `src/transcribe/whisper_runner.py` | NVIDIA GTX 1060, CUDA 12.6 |
| **JSON Catalog** | Legacy catalog format, still written by `CatalogManager` for CLI compat | `data/patreon_full_catalog.json` | Filesystem |

---

## Data Flow

### Pipeline Execution

```
 Browser                    FastAPI (devbox-01)              Agent Server (obs-machine)
    │                            │                                │
    │ POST /api/queue/start      │                                │
    ├───────────────────────────▶│                                │
    │                            │ RunPipeline(PipelineRequest)   │
    │                            ├───────────────────────────────▶│
    │                            │ PipelineResponse {run_id}      │
    │                            │◀───────────────────────────────┤
    │                            │                                │
    │                            │ StreamEvents subscription      │
    │                            │◀─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┤
    │                            │                                │ Pipeline runs steps...
    │                            │ PipelineEvent{step_started}    │
    │                            │◀───────────────────────────────┤
    │                            │  ├─ update SQLite              │
    │ WebSocket event            │  └─ publish to EventBus       │
    │◀───────────────────────────┤                                │
    │                            │ PipelineEvent{step_completed}  │
    │                            │◀───────────────────────────────┤
    │ WebSocket event            │  ├─ update SQLite              │
    │◀───────────────────────────┤  └─ publish to EventBus       │
    │                            │                                │
```

### Catalog Sync

Catalog sync is **event-driven** via gRPC — no file-watching:

| Trigger | Mechanism | Target |
|---------|-----------|--------|
| Pipeline step completes | gRPC `StreamEvents` → FastAPI updates SQLite | `step_statuses` table |
| Discovery trigger | gRPC `TriggerDiscovery` response → FastAPI inserts into SQLite | `posts` table |
| JSON re-import (fallback) | `POST /api/catalog/import` → reads JSON, upserts SQLite | `posts` + `step_statuses` |
| CLI pipeline run on obs-machine | `CatalogManager` writes to JSON (backward compat) | `patreon_full_catalog.json` |

SQLite on devbox-01 is the primary data store for the dashboard. JSON on obs-machine is kept for CLI backward compatibility only.

### Watcher Control

```
Start:  Browser → POST /api/watcher/start → FastAPI → ObsClient → gRPC StartWatcher → Agent Server
Status: Browser → GET /api/watcher/status  → FastAPI → ObsClient → gRPC GetStatus   → Agent Server
Stop:   Browser → POST /api/watcher/stop   → FastAPI → ObsClient → gRPC StopWatcher  → Agent Server
```

Watcher cycle events flow back via `StreamEvents` → EventBus → WebSocket → browser.

### Discovery

```
1. Browser → POST /api/discovery/trigger → FastAPI
2. FastAPI → ObsClient → gRPC TriggerDiscovery → Agent Server
3. Agent Server: PatreonDiscovery.fetch_posts() + CatalogManager.merge_discovered()
4. Agent Server returns DiscoveryResponse {total_found, new_posts, new_post_list}
5. FastAPI: merge new posts into SQLite, log to discovery_runs table
6. FastAPI: publish "discovery_complete" via EventBus → WebSocket → browser
```

---

## Lifecycle State Machine

### Per-Step Status

Each of the 7 pipeline steps has an independent status:

```
PENDING ──▶ QUEUED ──▶ RUNNING ──▶ COMPLETED
                          │
                          └──▶ FAILED

SKIPPED  (post type not applicable for this step)
```

```python
class StepStatus(str, Enum):
    PENDING   = "pending"
    QUEUED    = "queued"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    SKIPPED   = "skipped"
```

### Pipeline Steps

| # | Step | Input | Output | Runs On |
|---|------|-------|--------|---------|
| 1 | `record` | URL + filename | video.mp4 | obs-machine |
| 2 | `analyze` | video.mp4 | quality_report | obs-machine |
| 3 | `transcribe` | video.mp4 | .txt + .srt | obs-machine (GPU) |
| 4 | `correct` | .txt + .srt | corrected .txt + .srt | either |
| 5 | `find_gaps` | .srt | visual_gaps.yaml | either |
| 6 | `extract_frames` | gaps + video | screenshots/*.jpg | either |
| 7 | `ocr` | screenshots | slides/*.md | either |

Steps have dependencies: `transcribe` requires `record` output, `correct` requires `transcribe` output, etc. The lifecycle module (`web/lifecycle.py`) validates these via `step_can_run()`.

### Derived Post Status

The overall post status is computed from its 7 step statuses — never set directly:

| Overall Status | Condition |
|----------------|-----------|
| `in_progress` | Any step is `RUNNING` |
| `completed` | All steps are `COMPLETED` or `SKIPPED` |
| `failed` | Any step `FAILED`, none `RUNNING` |
| `queued` | Any step `QUEUED`, none `RUNNING` |
| `partial` | Some steps `COMPLETED`, some still `PENDING` |
| `discovered` | All steps `PENDING` (nothing started) |

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
        return "partial"
    return "discovered"
```

### Step Status Record

Each `(post_id, step_name)` pair in the `step_statuses` table tracks:

| Field | Type | Description |
|-------|------|-------------|
| `status` | StepStatus | Current step state |
| `started_at` | ISO datetime | When the step began executing |
| `completed_at` | ISO datetime | When the step finished (success or failure) |
| `error` | string | Error message if failed |
| `output_path` | string | Path to step output (recording, transcript, etc.) |
| `duration_seconds` | float | Execution time |
| `attempt` | int | Retry count |

---

## Security Model

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

**Layer 1 — Tailscale:** WireGuard encrypted tunnel. Only tailnet devices can reach port 8421. This is the primary security boundary.

**Layer 2 — Bearer token:** Shared `AGENT_TOKEN` (64-char hex) in `.env` on both machines. Validated by gRPC `AuthInterceptor`. Defense-in-depth against accidental exposure.

**No mTLS.** gRPC uses `insecure_channel()` — Tailscale already encrypts at the network layer. Adding TLS would double-encrypt without meaningful security gain while adding cert management overhead.

**HealthCheck exempt** from auth — read-only probe, no side effects.

**No web UI authentication** in Phase 1. Access is restricted by Tailscale — only tailnet devices can reach `insights.tunalab.dev` (resolves to a Tailscale IP). Add auth at the Caddy or FastAPI layer if remote access beyond the tailnet is needed.

**`.env` on both machines (gitignored):**

```bash
# Generate once, copy to both:
python -c "import secrets; print(f'AGENT_TOKEN={secrets.token_hex(32)}')"

# devbox-01: /home/tuna/repos/media-transcribe/.env
AGENT_TOKEN=<the token>
AGENT_HOST=100.66.194.100
AGENT_PORT=8421

# obs-machine: C:\Users\Matt\transcribe\.env
AGENT_TOKEN=<same token>
AGENT_PORT=8421
```

- CORS restricted to `localhost` origins (Vite dev server + production)
- No sensitive data in API responses (OBS password, tokens stay in server-side config)

---

## Service Configuration

### devbox-01: systemd

**Service:** `insights-backend.service` (user service)
**Unit file:** `deploy/insights-backend.service`
**Installed at:** `~/.config/systemd/user/insights-backend.service`

```ini
[Unit]
Description=Insights - Media Transcribe Pipeline Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/tuna/repos/media-transcribe
Environment=PATH=/home/tuna/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=HOME=/home/tuna
EnvironmentFile=%h/repos/media-transcribe/.env
ExecStart=/home/tuna/.local/bin/uv run cli.py web --host 127.0.0.1 --port 8420 --foreground
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

`--host 127.0.0.1` binds to localhost only — Caddy handles external access. `--foreground` prevents the CLI auto-backgrounding logic from re-spawning. `EnvironmentFile` loads `.env` since `web/config.py` uses raw `os.getenv()` without `load_dotenv()`.

```bash
systemctl --user enable --now insights-backend.service   # enable + start
systemctl --user status insights-backend.service         # check
systemctl --user restart insights-backend.service        # restart
journalctl --user -u insights-backend.service -f         # tail logs
```

### devbox-01: Caddy

**Vhost:** `deploy/caddy-insights.conf`

Caddy serves the Vue SPA directly from `frontend/dist/` and only proxies `/api/*` and `/ws/*` to FastAPI. This avoids modifying `web/app.py` and matches the devbox-01 convention (life-tracker, orchestrator).

```
insights.tunalab.dev {
    bind 100.126.202.43

    handle /api/* {
        reverse_proxy localhost:8420
    }

    handle /ws/* {
        reverse_proxy localhost:8420
    }

    handle {
        root * /home/tuna/repos/media-transcribe/frontend/dist
        try_files {path} /index.html
        file_server

        @assets path /assets/*
        header @assets Cache-Control "public, max-age=31536000, immutable"

        @html path / /index.html
        header @html Cache-Control "no-cache"
    }

    tls {
        dns cloudflare {file./etc/caddy/cloudflare-api-token}
    }
}
```

Applied via `sudo caddy-vhost /home/tuna/repos/media-transcribe/deploy/caddy-insights.conf`. TLS via Cloudflare DNS-01 challenge. SPA fallback via `try_files`. Hashed assets cached immutably; `index.html` served as no-cache for instant deploys.

### devbox-01: Cloudflare DNS

```bash
sudo cf-dns create insights 100.126.202.43    # DNS-only (gray cloud), not Cloudflare-proxied
```

`insights.tunalab.dev` A record → `100.126.202.43` (devbox-01 Tailscale IP). Cloudflare provides DNS management only — it does not proxy traffic. Only tailnet devices can resolve and reach this IP.

### obs-machine: Windows Task Scheduler

**Task:** `MediaTranscribe_AgentServer`
**Trigger:** At system startup (before user login)
**Action:** `uv run cli.py serve --port 8421`

```powershell
$action = New-ScheduledTaskAction `
    -Execute "uv" `
    -Argument "run cli.py serve --port 8421" `
    -WorkingDirectory "C:\Users\Matt\transcribe"
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName "MediaTranscribe_AgentServer" `
    -Action $action -Trigger $trigger -Settings $settings `
    -User "Matt" -RunLevel Highest
```

Logs to `C:\Users\Matt\agent-control\logs\agent_server.log`.

---

## Ports

| Service | Port | Machine | Protocol | Notes |
|---------|------|---------|----------|-------|
| Caddy (HTTPS) | 443 | devbox-01 | HTTPS | TLS for `insights.tunalab.dev` |
| FastAPI | 8420 | devbox-01 | HTTP + WS | Bound to `127.0.0.1`; Caddy fronts it |
| Vite dev server | 5173 | devbox-01 | HTTP | Dev only; proxies to `:8420` |
| gRPC agent server | 8421 | obs-machine | gRPC (HTTP/2) | Tailscale only; bearer token |
| OBS WebSocket | 4455 | obs-machine | WebSocket | Internal — agent server uses it |
| Chrome CDP | 9222 | obs-machine | HTTP | Internal — recorder uses it |

---

## Key Paths

### devbox-01

| Path | Description |
|------|-------------|
| `/home/tuna/repos/media-transcribe/` | Source repo root |
| `data/media_transcribe.db` | SQLite database (lifecycle, queue, stats) |
| `data/patreon_full_catalog.json` | JSON catalog (1,640+ posts, legacy) |
| `frontend/dist/` | Built Vue SPA (served by Caddy in production) |
| `web/` | FastAPI backend package |
| `agent/` | gRPC agent server package (runs on obs-machine, developed here) |
| `proto/agent.proto` | gRPC service definition |
| `proto/agent_pb2.py`, `proto/agent_pb2_grpc.py` | Generated protobuf stubs |
| `deploy/caddy-insights.conf` | Caddy vhost snippet |
| `deploy/insights-backend.service` | systemd user service unit file |
| `.env` | `AGENT_TOKEN`, `AGENT_HOST`, `AGENT_PORT` (gitignored) |
| `/mnt/secondary/media/patreon/FIRE Investing Masterclass/` | Recordings + transcripts storage |

### obs-machine

| Path | Description |
|------|-------------|
| `C:\Users\Matt\transcribe\` | Deployed project (cli.py + src/ + agent/) |
| `C:\Users\Matt\transcribe\.env` | `AGENT_TOKEN`, `AGENT_PORT` (gitignored) |
| `C:\Users\Matt\agent-control\logs\` | Pipeline + agent server logs |
| `C:\Users\Matt\agent-control\state\` | Watcher status, seen URLs, queue files |
| `C:\Users\Matt\agent-control\chrome-profile\` | Chrome user data for Patreon sessions |
| `D:\MasterClass Video Backup\` | Recordings output |
| `D:\MasterClass Video Backup\transcripts\` | Transcript output (.txt + .srt) |

---

## gRPC Service Contract

**File:** `proto/agent.proto`

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
  // EXEMPT from bearer token auth (allows monitoring probes)
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

### RPC Summary

| RPC | Type | Auth | Description |
|-----|------|------|-------------|
| `RunPipeline` | Unary | Required | Start pipeline for posts/steps. Returns `run_id` immediately; runs async |
| `StartWatcher` | Unary | Required | Start autonomous loop. Enforces 12h min interval |
| `StopWatcher` | Unary | Required | Graceful shutdown — finishes current video |
| `GetStatus` | Unary | Required | Combined: pipeline + watcher + disk + health |
| `HealthCheck` | Unary | **Exempt** | Lightweight probe: OBS, Chrome, disk. No side effects |
| `TriggerDiscovery` | Unary | Required | Fetch new posts from Patreon API |
| `StreamEvents` | Server-stream | Required | Real-time events: step start/complete/fail, watcher cycles, discovery |

### Event Types (via `StreamEvents`)

| Type | Emitted When | Key Fields |
|------|-------------|------------|
| `step_started` | Pipeline begins a step for a post | `run_id`, `post_id`, `step`, `timestamp` |
| `step_completed` | Step finishes successfully | `run_id`, `post_id`, `step`, `output_path`, `duration_seconds` |
| `step_failed` | Step fails with error | `run_id`, `post_id`, `step`, `error` |
| `watcher_cycle` | Watcher completes a discovery + pipeline cycle | metadata: `{cycle, new_found, recorded, failed}` |
| `discovery_complete` | Discovery finishes | metadata: `{total_found, new_posts, video_posts}` |
| `pipeline_complete` | All posts in a run are done | `run_id`, metadata: `{total, succeeded, failed}` |

---

## Extension Points (Phase 2)

Phase 2 adds AI-powered chat over transcript data. Stubbed in Phase 1:

### Provider Abstraction (`web/ai/provider.py`)

```python
class AIProvider(Protocol):
    async def complete(self, messages: list[dict], **kwargs) -> str: ...
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
    async def stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]: ...
```

Planned implementations: `AnthropicProvider`, `OpenAIProvider`, `OllamaProvider`.

### Vector Store Abstraction (`web/ai/vectorstore.py`)

```python
class VectorStore(Protocol):
    async def index(self, documents: list[Document]) -> int: ...
    async def search(self, query: str, top_k: int = 10) -> list[SearchResult]: ...
    async def delete(self, doc_ids: list[str]) -> int: ...
```

Planned implementations: `ChromaVectorStore`, `LanceDBStore`.

### Phase 2 Data Flow

```
Transcript step completes → gRPC event → chunk transcript → embed via AIProvider → store in VectorStore
User question → POST /api/chat → RAG retrieval from VectorStore → LLM completion → streamed response
```

`POST /api/chat` returns `501 Not Implemented` until Phase 2.

---

## Related Docs

| Document | Path | Description |
|----------|------|-------------|
| Implementation Plan | `specs/media-transcribe-web-app.md` | Full step-by-step build plan (21 tasks) |
| Project Conventions | `AGENTS.md` | Architecture, test commands, deployment, infrastructure |
| Deployment Guide | `DEPLOY.md` | Git-based deploy flow (devbox-01 → obs-machine) |
| Project Roadmap | `roadmap.yaml` | 8-phase roadmap: transcription → expert agents |
| Windows Traps | `docs/windows-recording-traps.md` | OBS/Chrome/RDP pitfalls on obs-machine |
| Auth Reference | `app_docs/auth.md` | Credential and account details |
| CLI Tools | `tools/README.md` | `cf-dns`, `caddy-vhost`, mount tools |
