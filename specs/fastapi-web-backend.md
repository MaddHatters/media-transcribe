# Plan: FastAPI Web Backend for Insights Dashboard

## Task Description

Build the complete FastAPI web backend for the Insights dashboard — Steps 9–14 and Step 21 from the master plan at `specs/media-transcribe-web-app.md`. This covers the gRPC client, all service layers, all REST/WebSocket routes, the app factory with lifespan management, the CLI `web` subcommand, and Phase 2 AI extension stubs.

The backend runs on devbox-01 and communicates with the obs-machine's gRPC agent server (already built in commit b91bd8a) for all pipeline, watcher, and discovery operations. The browser talks HTTP/WebSocket to FastAPI; FastAPI talks gRPC to the agent server.

## Objective

When this plan is complete:
1. `uv run cli.py web --help` shows the web subcommand
2. `uv run cli.py web` starts a FastAPI server on port 8420 with all API routes functional
3. All catalog, queue, watcher, discovery, pipeline, and agent health routes respond correctly
4. WebSocket at `/ws/events` relays real-time events from the gRPC stream
5. `POST /api/chat` returns 501 (Phase 2 stub)
6. All existing 594 tests continue to pass, plus new web backend tests

## Problem Statement

The foundation layer exists (models, database, lifecycle, config, proto stubs, agent server) but there is no service layer, no HTTP routes, no WebSocket endpoint, no app factory, and no CLI entry point for the web server. The gap between "data layer exists" and "working API server" is the entire service + route + glue layer.

## Solution Approach

Build bottom-up: gRPC client → service layers → route handlers → app factory → CLI integration. Each layer depends only on the one below it. Tests mock the layer below (ObsClient mocked in route tests, DB mocked in service tests where needed). The EventBus bridges gRPC stream events to WebSocket clients.

## Relevant Files

### Existing Files (read, integrate, do NOT rewrite)

- `web/config.py` — DB_PATH, HOST, PORT, CORS_ORIGINS, AGENT_HOST/PORT/TOKEN
- `web/database.py` — init_db(), migrate_from_json(), get_db(), full SQLite schema
- `web/models.py` — All Pydantic models (PostSummary, PostDetail, QueueEntry, AgentHealth, CatalogStats, etc.)
- `web/lifecycle.py` — StepStatus enum, PIPELINE_STEPS, derive_post_status(), step_can_run()
- `web/__init__.py` — Package init
- `proto/agent_pb2.py` + `proto/agent_pb2_grpc.py` — Generated gRPC stubs
- `agent/server.py` — AgentServiceServicer (all RPCs implemented)
- `agent/interceptors.py` — AuthInterceptor
- `agent/config.py` — Agent-side config + .env loader
- `cli.py` — CLI entry point (already has `serve` subcommand, needs `web` subcommand)
- `src/pipeline/runner.py` — Pipeline class with on_step_start/complete/fail callbacks
- `src/sources/base.py` — Post dataclass
- `src/catalog.py` — CatalogManager
- `tests/web/test_lifecycle.py` — Lifecycle unit tests (existing)
- `tests/web/test_database.py` — Database unit tests (existing)
- `tests/agent/test_interceptors.py` — Auth interceptor tests (existing)
- `tests/agent/test_server.py` — Agent server tests (existing)

### New Files

#### Services (`web/services/`)
- `web/services/__init__.py` — Package init
- `web/services/obs_client.py` — Async gRPC client wrapping all agent RPCs
- `web/services/catalog_service.py` — Catalog business logic (filtering, pagination, stats, upsert)
- `web/services/queue_service.py` — Queue CRUD + start/pause/clear/reorder
- `web/services/discovery_service.py` — Discovery trigger + merge into SQLite
- `web/services/pipeline_service.py` — Pipeline run orchestration + event handling
- `web/services/event_bus.py` — In-process pub/sub for WebSocket broadcast

#### Routes (`web/routes/`)
- `web/routes/__init__.py` — Router aggregation (creates and includes all sub-routers)
- `web/routes/catalog.py` — GET /api/catalog, GET /api/catalog/{post_id}, GET /api/catalog/stats, POST /api/catalog/import
- `web/routes/queue.py` — Queue CRUD + start/pause/clear/reorder endpoints
- `web/routes/watcher.py` — Watcher status/start/stop/config endpoints
- `web/routes/discovery.py` — Discovery trigger/history/new endpoints
- `web/routes/pipeline.py` — Pipeline status/run endpoints
- `web/routes/agent.py` — Agent health + status endpoints
- `web/routes/ws.py` — WebSocket /ws/events with heartbeat

#### App + AI Stubs
- `web/app.py` — FastAPI app factory with lifespan, CORS, error handlers, router inclusion
- `web/ai/__init__.py` — Package init
- `web/ai/provider.py` — AIProvider Protocol stub
- `web/ai/vectorstore.py` — VectorStore Protocol stub

#### Tests
- `tests/web/__init__.py` — Package init (if not existing)
- `tests/web/conftest.py` — Shared fixtures (async DB, mock ObsClient, FastAPI TestClient)
- `tests/web/test_obs_client.py` — ObsClient unit tests with mock gRPC server
- `tests/web/test_catalog_service.py` — CatalogService unit tests
- `tests/web/test_catalog_api.py` — Catalog route integration tests
- `tests/web/test_queue_api.py` — Queue route integration tests

## Implementation Phases

### Phase 1: Foundation — gRPC Client + Custom Errors
Build ObsClient with error mapping. This is the bridge between web backend and agent server — every route that touches the obs-machine goes through this client.

### Phase 2: Core Services
Build CatalogService, QueueService, DiscoveryService, PipelineService, EventBus. These encapsulate all business logic. Routes will be thin wrappers.

### Phase 3: Routes + App Factory
Build all route modules, the app factory with lifespan management, and the CLI `web` subcommand. Wire everything together.

### Phase 4: WebSocket + Event Relay
Build EventBus pub/sub and the WebSocket route. Wire gRPC StreamEvents → EventBus → WebSocket in the app lifespan.

### Phase 5: AI Stubs + Tests
Add Phase 2 AI extension points and complete test coverage.

## Step by Step Tasks

IMPORTANT: Execute every step in order, top to bottom.

### 1. Create Custom Error Types

Create error classes that ObsClient and routes both use.

- Add to `web/services/__init__.py`:
  ```python
  class AgentUnavailableError(Exception):
      """Raised when the obs-machine gRPC agent is unreachable."""

  class AgentAuthError(Exception):
      """Raised when gRPC auth fails (bad or missing AGENT_TOKEN)."""
  ```

### 2. Build ObsClient (Step 9)

Create `web/services/obs_client.py` — the async gRPC client that wraps all agent RPCs.

**Class: `ObsClient`**
- `__init__(host: str, port: int, token: str)`:
  - Store host, port as channel target string `f"{host}:{port}"`
  - Store auth metadata: `[("authorization", f"bearer {token}")]`
  - Initialize `_channel` and `_stub` as None
- `async connect()`:
  - Create `grpc.aio.insecure_channel(self._target)`
  - Create `agent_pb2_grpc.AgentServiceStub(self._channel)`
- `async close()`:
  - Close channel if open
- `async health_check() -> AgentHealth`:
  - Call `self._stub.HealthCheck(agent_pb2.Empty(), metadata=self._metadata, timeout=5)`
  - Map response to `web.models.AgentHealth` Pydantic model
  - Catch `grpc.aio.AioRpcError`: UNAVAILABLE → `AgentUnavailableError`, UNAUTHENTICATED → `AgentAuthError`
- `async get_status() -> dict`:
  - Call `self._stub.GetStatus(agent_pb2.Empty(), metadata=self._metadata, timeout=5)`
  - Return dict with health, watcher, pipeline, disk sub-dicts
- `async run_pipeline(posts: list[dict], steps: list[str] | None = None, shuffle: bool = False, breaks: bool = True) -> dict`:
  - Build `PipelineRequest` from args (convert post dicts to `PostEntry` messages)
  - Call `self._stub.RunPipeline(request, metadata=self._metadata)`
  - Return `{"started": bool, "run_id": str, "queue_size": int, "error": str}`
- `async start_watcher(config: dict) -> dict`:
  - Build `WatcherConfig` from config dict
  - Call `self._stub.StartWatcher(config_msg, metadata=self._metadata)`
  - Return response as dict
- `async stop_watcher() -> dict`:
  - Call `self._stub.StopWatcher(agent_pb2.Empty(), metadata=self._metadata)`
- `async trigger_discovery(full_catalog: bool = False, force: bool = False) -> dict`:
  - Call with timeout=30
  - Return `{"total_found": int, "new_posts": int, "video_posts": int, "new_post_list": list, "error": str}`
- `async stream_events(callback: Callable) -> None`:
  - Subscribe to `StreamEvents` server-stream
  - For each event, call `await callback(event_dict)` where event_dict maps PipelineEvent fields
  - On disconnect, log warning and retry with exponential backoff (1s, 2s, 4s, 8s, max 60s)
  - On `grpc.aio.AioRpcError` with UNAVAILABLE, retry; with UNAUTHENTICATED, raise

**Helper: `_grpc_error_handler()`** — a private method or context manager that catches `grpc.aio.AioRpcError` and maps to custom exceptions.

**Important patterns:**
- All methods attach `self._metadata` for auth
- Proto imports: `from proto import agent_pb2, agent_pb2_grpc`
- Routes never import proto directly — only through ObsClient

### 3. Build CatalogService (Step 10 — service layer)

Create `web/services/catalog_service.py`:

**Class: `CatalogService`**

- `__init__(db: aiosqlite.Connection)` — stores db reference

- `async list_posts(type: str | None, status: str | None, step_filter: str | None, search: str | None, tag: str | None, source_id: str | None, sort: str = "published_at", order: str = "desc", page: int = 1, per_page: int = 50) -> tuple[list[PostSummary], int]`:
  - Build dynamic SQL with WHERE clauses based on filters
  - `type` filter: `WHERE post_type = ?`
  - `status` filter: `WHERE overall_status = ?`
  - `step_filter`: format `"step_name:status"` → JOIN step_statuses WHERE step_name=? AND status=?
  - `search`: `WHERE title LIKE ?` (case-insensitive via COLLATE NOCASE)
  - `tag`: `WHERE tags LIKE ?` (JSON contains check)
  - `source_id`: `WHERE source_id = ?`
  - Sort whitelist: `published_at`, `created_at`, `title`, `overall_status`, `post_type`
  - Pagination: LIMIT/OFFSET
  - Return `(posts_list, total_count)` — total_count is COUNT(*) before LIMIT
  - For each post, fetch step_statuses with a second query (or LEFT JOIN)
  - Parse `tags` JSON string back to list

- `async get_post(post_id: str) -> PostDetail | None`:
  - Fetch post row + all step_statuses for that post_id
  - Return PostDetail with full step records

- `async get_stats() -> CatalogStats`:
  - `SELECT COUNT(*) FROM posts` → total_posts
  - `SELECT COUNT(*) FROM posts WHERE has_video = 1` → video_posts
  - `SELECT COUNT(*) FROM posts WHERE has_audio = 1` → audio_posts
  - `SELECT overall_status, COUNT(*) FROM posts GROUP BY overall_status` → by_status
  - `SELECT post_type, COUNT(*) FROM posts GROUP BY post_type` → by_type
  - `SELECT step_name, status, COUNT(*) FROM step_statuses GROUP BY step_name, status` → by_step

- `async update_step_status(post_id: str, step: str, status: StepStatus, started_at: str | None = None, completed_at: str | None = None, error: str | None = None, output_path: str | None = None, duration_seconds: float | None = None)`:
  - UPDATE step_statuses SET status=?, started_at=?, ... WHERE post_id=? AND step_name=?
  - Re-derive overall_status: fetch all step statuses for this post, call `derive_post_status()`, UPDATE posts SET overall_status=?

- `async import_from_json(json_path: Path) -> int`:
  - Delegate to `database.migrate_from_json(self._db, json_path)`

- `async upsert_discovered(posts: list[dict]) -> int`:
  - For each post dict (from gRPC discovery response):
    - INSERT OR IGNORE into posts table
    - If inserted, create step_statuses rows (all PENDING)
  - Return count of newly inserted posts

### 4. Build Catalog Routes (Step 10 — routes)

Create `web/routes/__init__.py`:
```python
from fastapi import APIRouter
from web.routes import catalog, queue, watcher, discovery, pipeline, agent, ws

api_router = APIRouter()
api_router.include_router(catalog.router, prefix="/api/catalog", tags=["catalog"])
api_router.include_router(queue.router, prefix="/api/queue", tags=["queue"])
api_router.include_router(watcher.router, prefix="/api/watcher", tags=["watcher"])
api_router.include_router(discovery.router, prefix="/api/discovery", tags=["discovery"])
api_router.include_router(pipeline.router, prefix="/api/pipeline", tags=["pipeline"])
api_router.include_router(agent.router, prefix="/api/agent", tags=["agent"])
```

Create `web/routes/catalog.py`:

- `router = APIRouter()`

- `GET /` (mounted at `/api/catalog`):
  - Query params: `type`, `status`, `step`, `search`, `tag`, `source_id`, `sort` (default "published_at"), `order` (default "desc"), `page` (default 1), `per_page` (default 50)
  - Get db from `get_db()` dependency
  - Create `CatalogService(db)`, call `list_posts(...)`
  - Return `{"posts": [...], "total": int, "page": int, "per_page": int}`

- `GET /stats` (IMPORTANT: define BEFORE `/{post_id}` to avoid route shadowing):
  - Return `CatalogStats` from `catalog_service.get_stats()`

- `GET /{post_id}`:
  - Return `PostDetail` or 404

- `POST /import`:
  - Body: `{"json_path": str | None}` (default: CATALOG_JSON_PATH from config)
  - Call `catalog_service.import_from_json(path)`
  - Return `{"imported": int}`

**Route ordering matters:** `/stats` must be declared before `/{post_id}`, otherwise FastAPI matches "stats" as a post_id.

### 5. Build Queue Service + Routes (Step 11)

Create `web/services/queue_service.py`:

**Class: `QueueService`**

- `__init__(db: aiosqlite.Connection, obs_client: ObsClient)` — stores both

- `async get_queue() -> list[QueueEntry]`:
  - `SELECT q.*, p.title FROM queue q JOIN posts p ON q.post_id = p.post_id WHERE q.status IN ('waiting', 'processing') ORDER BY q.priority DESC, q.added_at ASC`
  - Return list of QueueEntry models

- `async add_to_queue(post_ids: list[str], priority: int = 0) -> int`:
  - For each post_id: INSERT OR IGNORE INTO queue (post_id, priority, added_at, status) VALUES (?, ?, datetime('now'), 'waiting')
  - Also update the post's step_statuses: set `record` to QUEUED
  - Re-derive overall_status
  - Return count of added entries

- `async remove_from_queue(post_id: str) -> bool`:
  - DELETE FROM queue WHERE post_id = ? AND status = 'waiting'
  - If removed, revert step_statuses `record` back to PENDING
  - Return whether a row was deleted

- `async update_priority(post_id: str, priority: int)`:
  - UPDATE queue SET priority = ? WHERE post_id = ?

- `async reorder(post_ids: list[str])`:
  - For i, post_id in enumerate: UPDATE queue SET priority = (len - i) WHERE post_id = ?
  - Higher priority = processed first

- `async start_queue() -> dict`:
  - Fetch all 'waiting' queue entries with post details
  - Build post dicts for ObsClient.run_pipeline()
  - Call `self._obs_client.run_pipeline(posts)`
  - Mark entries as 'processing'
  - Return run_pipeline response

- `async pause_queue()`:
  - UPDATE queue SET status = 'waiting' WHERE status = 'processing'

- `async clear_completed()`:
  - DELETE FROM queue WHERE status IN ('done', 'cancelled')

Create `web/routes/queue.py`:

- `GET /` → get_queue()
- `POST /` → add_to_queue (body: QueueAddRequest)
- `DELETE /{post_id}` → remove_from_queue
- `PATCH /{post_id}` → update_priority (body: `{"priority": int}`)
- `POST /reorder` → reorder (body: `{"post_ids": list[str]}`)
- `POST /start` → start_queue
- `POST /pause` → pause_queue
- `POST /clear` → clear_completed

### 6. Build Watcher Routes (Step 12a)

Create `web/routes/watcher.py`:

- `GET /status`:
  - Call `obs_client.get_status()`, extract watcher state
  - Return `WatcherStatus` model

- `POST /start`:
  - Body: `WatcherConfigUpdate`
  - Call `obs_client.start_watcher(config_dict)`
  - Return response dict

- `POST /stop`:
  - Call `obs_client.stop_watcher()`
  - Return response dict

- `PATCH /config`:
  - Body: `WatcherConfigUpdate`
  - Validate (interval_hours >= 12 if provided)
  - Call `obs_client.start_watcher(updated_config)` (restart with new config)
  - Return response dict

### 7. Build Discovery Service + Routes (Step 12b)

Create `web/services/discovery_service.py`:

**Class: `DiscoveryService`**

- `__init__(db: aiosqlite.Connection, obs_client: ObsClient)`

- `async trigger(full_catalog: bool = False, force: bool = False) -> DiscoveryRunResponse`:
  - INSERT into discovery_runs (started_at, status='running')
  - Call `obs_client.trigger_discovery(full_catalog, force)`
  - If error, UPDATE discovery_runs status='failed', return error
  - Merge new posts into SQLite via CatalogService.upsert_discovered()
  - UPDATE discovery_runs (completed_at, posts_found, new_posts, status='completed')
  - Return DiscoveryRunResponse

- `async get_new_posts() -> list[PostSummary]`:
  - Query posts with overall_status='discovered' that have no queue entry
  - `SELECT p.* FROM posts p LEFT JOIN queue q ON p.post_id = q.post_id WHERE p.overall_status = 'discovered' AND q.id IS NULL ORDER BY p.published_at DESC`

- `async get_history() -> list[DiscoveryRunResponse]`:
  - `SELECT * FROM discovery_runs ORDER BY started_at DESC LIMIT 20`

Create `web/routes/discovery.py`:

- `POST /trigger` → trigger discovery (body: DiscoveryTriggerRequest)
- `GET /history` → get_history()
- `GET /new` → get_new_posts()

### 8. Build Pipeline Service + Routes (Step 12c)

Create `web/services/pipeline_service.py`:

**Class: `PipelineService`**

- `__init__(db: aiosqlite.Connection, obs_client: ObsClient, event_bus: EventBus)`

- `async run(post_ids: list[str], steps: list[str] | None = None) -> dict`:
  - Fetch post details from SQLite for each post_id
  - Build post dicts with url, title, filename, post_type
  - Call `obs_client.run_pipeline(posts, steps)`
  - Return `{"started": bool, "run_id": str, "queue_size": int}`

- `async get_status() -> dict`:
  - Call `obs_client.get_status()`
  - Extract pipeline state
  - Return dict

- `async handle_event(event: dict) -> None`:
  - Parse event type: step_started, step_completed, step_failed, pipeline_complete
  - For step events: update step_statuses in SQLite via CatalogService.update_step_status()
  - For pipeline_complete: update queue entries to 'done'
  - Publish to EventBus for WebSocket relay

Create `web/routes/pipeline.py`:

- `GET /status` → get_status()
- `POST /run` → run (body: PipelineRunRequest)

### 9. Build Agent Routes (Step 12d)

Create `web/routes/agent.py`:

- `GET /health` → obs_client.health_check(), return AgentHealth
- `GET /status` → obs_client.get_status(), return full agent status dict

Both routes should catch `AgentUnavailableError` and return a degraded response (healthy=False) with 200 status (not 503) so the frontend always gets valid JSON. The `AgentUnavailableError` → 503 mapping in the app-level error handler is for routes that *require* the agent (pipeline/run, watcher/start, etc.).

### 10. Build EventBus (Step 13a)

Create `web/services/event_bus.py`:

**Class: `EventBus`** (singleton-style, instantiated once in app lifespan)

- `__init__()`:
  - `self._subscribers: set[asyncio.Queue] = set()` — one queue per WebSocket client
  - `self._lock = asyncio.Lock()`

- `async subscribe() -> asyncio.Queue`:
  - Create queue, add to subscribers set, return it

- `async unsubscribe(queue: asyncio.Queue)`:
  - Remove from subscribers set

- `async publish(event: dict)`:
  - For each subscriber queue, put_nowait(event)
  - If queue full, log warning and drop event (no blocking)

Event types flowing through the bus:
- `step_started`, `step_completed`, `step_failed` — from gRPC stream
- `queue_update` — emitted by QueueService on add/remove/start
- `watcher_cycle` — from gRPC stream
- `discovery_complete` — from DiscoveryService after trigger
- `pipeline_complete` — from gRPC stream

### 11. Build WebSocket Route (Step 13b)

Create `web/routes/ws.py`:

- `WS /ws/events`:
  ```python
  @router.websocket("/ws/events")
  async def websocket_events(websocket: WebSocket):
      await websocket.accept()
      event_bus = websocket.app.state.event_bus
      queue = await event_bus.subscribe()
      try:
          while True:
              try:
                  event = await asyncio.wait_for(queue.get(), timeout=30)
                  await websocket.send_json(event)
              except asyncio.TimeoutError:
                  # Heartbeat ping
                  await websocket.send_json({"type": "ping", "timestamp": datetime.now(timezone.utc).isoformat()})
      except WebSocketDisconnect:
          pass
      finally:
          await event_bus.unsubscribe(queue)
  ```

### 12. Build FastAPI App Factory (Step 14)

Create `web/app.py`:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    # 1. Init database
    from web.database import init_db
    from web.config import DB_PATH, CATALOG_JSON_PATH, AGENT_HOST, AGENT_PORT, AGENT_TOKEN
    db = await init_db(DB_PATH)
    app.state.db = db
    
    # 2. Auto-migrate from JSON if DB is empty
    cursor = await db.execute("SELECT COUNT(*) FROM posts")
    count = (await cursor.fetchone())[0]
    if count == 0 and CATALOG_JSON_PATH.exists():
        from web.database import migrate_from_json
        imported = await migrate_from_json(db, CATALOG_JSON_PATH)
        # log imported count
    
    # 3. Create ObsClient and connect
    from web.services.obs_client import ObsClient
    obs_client = ObsClient(AGENT_HOST, AGENT_PORT, AGENT_TOKEN)
    await obs_client.connect()
    app.state.obs_client = obs_client
    
    # 4. Create EventBus
    from web.services.event_bus import EventBus
    event_bus = EventBus()
    app.state.event_bus = event_bus
    
    # 5. Start gRPC stream relay background task
    relay_task = asyncio.create_task(_relay_grpc_events(obs_client, db, event_bus))
    
    yield
    
    # --- Shutdown ---
    relay_task.cancel()
    await obs_client.close()
    await db.close()


async def _relay_grpc_events(obs_client, db, event_bus):
    """Bridge gRPC StreamEvents to EventBus for WebSocket relay."""
    from web.services.pipeline_service import PipelineService
    pipeline_svc = PipelineService(db, obs_client, event_bus)
    
    async def on_event(event_dict):
        await pipeline_svc.handle_event(event_dict)
        await event_bus.publish(event_dict)
    
    await obs_client.stream_events(on_event)


def create_app() -> FastAPI:
    app = FastAPI(title="Media Transcribe Dashboard", lifespan=lifespan)
    
    # CORS
    from web.config import CORS_ORIGINS
    app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, ...)
    
    # Routes
    from web.routes import api_router
    app.include_router(api_router)
    
    # WebSocket route (not prefixed)
    from web.routes.ws import router as ws_router
    app.include_router(ws_router)
    
    # Phase 2 AI stub
    @app.post("/api/chat")
    async def chat_stub():
        from fastapi import HTTPException
        raise HTTPException(status_code=501, detail="AI chat available in Phase 2")
    
    # Error handlers
    from web.services import AgentUnavailableError, AgentAuthError
    @app.exception_handler(AgentUnavailableError)
    async def agent_unavailable_handler(request, exc):
        return JSONResponse(status_code=503, content={"detail": "Agent server unavailable"})
    
    @app.exception_handler(AgentAuthError)
    async def agent_auth_handler(request, exc):
        return JSONResponse(status_code=502, content={"detail": "Agent authentication failed"})
    
    return app
```

**Dependency injection pattern for services:**

Routes need access to the DB connection and ObsClient. Use FastAPI dependencies:

```python
# In web/dependencies.py or inline in routes:
async def get_catalog_service(db=Depends(get_db)):
    return CatalogService(db)

async def get_obs_client(request: Request):
    return request.app.state.obs_client

async def get_event_bus(request: Request):
    return request.app.state.event_bus
```

Alternatively, since ObsClient and EventBus are singletons on `app.state`, routes can access them via `request.app.state.obs_client`. The DB connection is per-request via `get_db()`.

### 13. Add `web` Subcommand to CLI (Step 14b)

Modify `cli.py`:

- Add to `build_parser()` (after the `serve` subcommand):
  ```python
  # --- web (dashboard server) ---
  w = sub.add_parser("web", help="Start the pipeline dashboard web server")
  w.add_argument("--host", default="0.0.0.0")
  w.add_argument("--port", type=int, default=8420)
  w.add_argument("--dev", action="store_true", help="Enable auto-reload for development")
  ```

- Add `"web"` to `LONG_RUNNING_COMMANDS` set

- Add handler in `main()` (before `elif args.command == "release-info":`):
  ```python
  elif args.command == "web":
      import uvicorn
      uvicorn.run(
          "web.app:create_app",
          factory=True,
          host=args.host,
          port=args.port,
          reload=getattr(args, 'dev', False),
      )
  ```

**IMPORTANT:** Only modify `cli.py` — add the `web` subcommand and handler. Do not modify any other existing files.

### 14. Build Phase 2 AI Stubs (Step 21)

Create `web/ai/__init__.py`:
```python
# Phase 2 AI extension point — not yet implemented
```

Create `web/ai/provider.py`:
```python
from __future__ import annotations
from typing import AsyncIterator, Protocol

class AIProvider(Protocol):
    async def complete(self, messages: list[dict], **kwargs) -> str: ...
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
    async def stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]: ...
```

Create `web/ai/vectorstore.py`:
```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol

@dataclass
class Document:
    id: str
    text: str
    metadata: dict

@dataclass
class SearchResult:
    document: Document
    score: float

class VectorStore(Protocol):
    async def index(self, documents: list[Document]) -> int: ...
    async def search(self, query: str, top_k: int = 10) -> list[SearchResult]: ...
    async def delete(self, doc_ids: list[str]) -> int: ...
```

### 15. Create Test Fixtures + Shared Helpers

Create `tests/web/conftest.py`:

```python
import pytest
import aiosqlite
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from web.database import init_db
from web.models import AgentHealth

@pytest.fixture
async def db(tmp_path):
    """In-memory SQLite DB with schema initialized."""
    db = await init_db(tmp_path / "test.db")
    db.row_factory = aiosqlite.Row
    yield db
    await db.close()

@pytest.fixture
def mock_obs_client():
    """Mock ObsClient that returns canned responses."""
    client = AsyncMock()
    client.health_check.return_value = AgentHealth(
        healthy=True, obs_connected=True, chrome_available=True,
        disk_ok=True, obs_version="30.2", error=None,
    )
    client.get_status.return_value = {
        "health": {...},
        "watcher": {"running": False},
        "pipeline": {"running": False},
        "disk": {"total_bytes": 1000000000000, "free_bytes": 500000000000},
    }
    client.run_pipeline.return_value = {"started": True, "run_id": "run_test_001", "queue_size": 2, "error": ""}
    client.trigger_discovery.return_value = {"total_found": 100, "new_posts": 3, "video_posts": 80, "new_post_list": [], "error": ""}
    client.start_watcher.return_value = {"success": True, "message": "Watcher started"}
    client.stop_watcher.return_value = {"success": True, "message": "Watcher stopped"}
    return client

@pytest.fixture
async def seed_db(db):
    """Seed DB with sample posts for testing."""
    for i in range(5):
        await db.execute(
            "INSERT INTO posts (post_id, source_id, url, title, post_type, has_video, published_at, overall_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (f"post_{i}", "fuw", f"https://patreon.com/posts/{i}", f"Test Post {i}", "video_external_file", True, f"2026-01-0{i+1}T00:00:00Z", "discovered"),
        )
        for step in ["record", "analyze", "transcribe", "correct", "find_gaps", "extract_frames", "ocr"]:
            await db.execute(
                "INSERT INTO step_statuses (post_id, step_name, status) VALUES (?, ?, ?)",
                (f"post_{i}", step, "pending"),
            )
    await db.commit()
    return db
```

### 16. Write ObsClient Tests

Create `tests/web/test_obs_client.py`:

- Test `health_check()` returns AgentHealth model with correct fields
- Test `get_status()` returns dict with expected keys
- Test `run_pipeline()` sends correct PipelineRequest message
- Test auth metadata is attached to all calls
- Test error mapping: mock gRPC UNAVAILABLE → raises AgentUnavailableError
- Test error mapping: mock gRPC UNAUTHENTICATED → raises AgentAuthError
- Test `stream_events()` receives events via callback

**Approach:** Use `unittest.mock.AsyncMock` to mock the gRPC stub. Don't spin up a real gRPC server — that's an integration test. For unit tests, mock `agent_pb2_grpc.AgentServiceStub` and verify the correct proto messages are constructed.

### 17. Write Catalog Service + API Tests

Create `tests/web/test_catalog_service.py`:
- Test `list_posts()` with no filters returns all posts
- Test `list_posts()` with type filter returns only matching type
- Test `list_posts()` with status filter
- Test `list_posts()` with source_id filter
- Test `list_posts()` with search filter (partial title match)
- Test `list_posts()` pagination (page=1 per_page=2, verify total and results)
- Test `list_posts()` sort by published_at desc (default)
- Test `get_post()` returns PostDetail with step records
- Test `get_post()` returns None for nonexistent post_id
- Test `get_stats()` returns correct aggregates
- Test `update_step_status()` updates step and recomputes overall_status
- Test `upsert_discovered()` inserts new posts and creates step_statuses

Create `tests/web/test_catalog_api.py`:
- Use `httpx.AsyncClient` with FastAPI `TestClient` pattern
- Override `get_db` dependency to use test DB
- Override `request.app.state.obs_client` to use mock
- Test `GET /api/catalog` returns paginated list
- Test `GET /api/catalog?type=video_external_file` filters correctly
- Test `GET /api/catalog?source_id=fuw` filters by source
- Test `GET /api/catalog/stats` returns CatalogStats
- Test `GET /api/catalog/{post_id}` returns PostDetail
- Test `GET /api/catalog/nonexistent` returns 404
- Test `POST /api/catalog/import` triggers migration

### 18. Write Queue API Tests

Create `tests/web/test_queue_api.py`:
- Test `GET /api/queue` returns empty list initially
- Test `POST /api/queue` adds posts to queue, returns count
- Test `POST /api/queue` with duplicate post_id is idempotent
- Test `DELETE /api/queue/{post_id}` removes entry
- Test `PATCH /api/queue/{post_id}` updates priority
- Test `POST /api/queue/reorder` reorders correctly
- Test `POST /api/queue/start` calls ObsClient.run_pipeline (mock obs_client)
- Test `POST /api/queue/clear` removes completed entries

### 19. Validate Everything

Run all validation commands to ensure correctness.

- `uv run cli.py web --help` — verify subcommand exists and shows options
- `uv run python -c "from web.app import create_app; print('OK')"` — verify app factory imports cleanly
- `uv run python -c "from web.services.obs_client import ObsClient; print('OK')"` — verify ObsClient imports
- `uv run python -c "from web.ai.provider import AIProvider; from web.ai.vectorstore import VectorStore; print('OK')"` — verify AI stubs
- `uv run pytest tests/web/ -v` — all web tests pass
- `uv run pytest tests/ -v` — all tests pass (no regressions)

## Testing Strategy

### Unit Tests
- **ObsClient**: Mock gRPC stub, verify proto message construction and error mapping
- **CatalogService**: In-memory SQLite, test all query paths including filters, pagination, upsert
- **QueueService**: In-memory SQLite + mock ObsClient, test all CRUD operations
- **EventBus**: Test subscribe/unsubscribe/publish with asyncio.Queue consumers
- **PipelineService.handle_event()**: Mock DB + EventBus, verify step_status updates

### API Integration Tests
- **All route modules**: Use `httpx.AsyncClient` with `app = create_app()`, override dependencies with test DB and mock ObsClient
- **WebSocket**: Test `/ws/events` with `websockets` test client — connect, receive heartbeat, receive published event
- **Error handling**: Verify AgentUnavailableError → 503 and AgentAuthError → 502 responses

### No-Mock Tests (ObsClient only, optional)
- With a real gRPC agent server running locally, test the full ObsClient flow (health_check, get_status)
- Skip automatically if no server available (`@pytest.mark.skipif`)

## Acceptance Criteria

1. `uv run cli.py web --help` prints usage with --host, --port, --dev options
2. `uv run python -c "from web.app import create_app; print('OK')"` succeeds
3. `GET /api/catalog` returns paginated posts with step badges
4. `GET /api/catalog?source_id=fuw` filters by source
5. `GET /api/catalog/stats` returns aggregate CatalogStats
6. `GET /api/catalog/{post_id}` returns PostDetail with all 7 step records
7. Queue CRUD works: POST to add, DELETE to remove, PATCH priority, POST reorder
8. `POST /api/queue/start` calls ObsClient.run_pipeline() and returns run_id
9. `GET /api/agent/health` returns AgentHealth (or gracefully degraded if agent unreachable)
10. `GET /api/watcher/status` returns watcher state from agent
11. `POST /api/discovery/trigger` calls gRPC TriggerDiscovery and merges results into SQLite
12. `WS /ws/events` accepts connection and sends heartbeat pings every 30s
13. `POST /api/chat` returns 501 with "AI chat available in Phase 2"
14. All existing tests still pass (594+ tests)
15. New web tests pass: `uv run pytest tests/web/ -v`
16. No proto imports in route files — all gRPC access goes through ObsClient

## Validation Commands

Execute these commands to validate the task is complete:

```bash
# Verify CLI subcommand
uv run cli.py web --help

# Verify app factory imports
uv run python -c "from web.app import create_app; print('OK')"

# Verify ObsClient imports
uv run python -c "from web.services.obs_client import ObsClient; print('OK')"

# Verify all route modules import
uv run python -c "from web.routes import api_router; print(f'Routes: {len(api_router.routes)}')"

# Verify AI stubs import
uv run python -c "from web.ai.provider import AIProvider; from web.ai.vectorstore import VectorStore, Document, SearchResult; print('OK')"

# Verify event bus imports
uv run python -c "from web.services.event_bus import EventBus; print('OK')"

# Run web tests
uv run pytest tests/web/ -v

# Run ALL tests (no regressions)
uv run pytest tests/ -v

# Verify the app compiles (catch any runtime import errors)
uv run python -c "
from web.app import create_app
app = create_app()
routes = [r.path for r in app.routes if hasattr(r, 'path')]
print(f'App created with {len(routes)} routes')
for r in sorted(routes):
    print(f'  {r}')
"
```

## Notes

### Dependency Injection Strategy

The app uses two patterns for dependency injection:

1. **Per-request DB**: Via `get_db()` async generator dependency (already exists in `web/database.py`). Creates a new connection per request, closes on response.

2. **Singleton services**: ObsClient and EventBus are created once in lifespan and stored on `app.state`. Routes access them via `request.app.state.obs_client`.

For services that need both DB and ObsClient (QueueService, DiscoveryService, PipelineService), construct them in the route handler:

```python
@router.post("/start")
async def start_queue(request: Request, db=Depends(get_db)):
    service = QueueService(db, request.app.state.obs_client)
    return await service.start_queue()
```

### Route Architecture Constraint

**Routes never import from `proto/` directly.** All gRPC communication goes through `ObsClient`. This keeps the proto dependency contained and makes routes testable with a simple mock.

### File the Plan Skips

The plan at `specs/media-transcribe-web-app.md` defines Steps 15-20 (frontend) which are explicitly out of scope here. Step 14 includes mounting `frontend/dist/` as static files, but only if the directory exists — no frontend build is required.

### Queue Start Flow

When `POST /api/queue/start` is called:
1. QueueService reads waiting queue entries with post details from SQLite
2. Builds `posts` list with url, title, filename, post_type from the posts table
3. Calls `obs_client.run_pipeline(posts)` which sends `RunPipeline` RPC
4. Marks queue entries as 'processing' in SQLite
5. Pipeline events flow back via gRPC `StreamEvents` → EventBus → WebSocket
6. PipelineService.handle_event() updates step_statuses in SQLite as events arrive
7. On pipeline_complete event, queue entries are marked 'done'

### Agent Health Graceful Degradation

The `GET /api/agent/health` route should NOT raise 503 when the agent is unreachable. Instead, return a degraded `AgentHealth` response:
```python
AgentHealth(healthy=False, obs_connected=False, chrome_available=False,
            disk_ok=False, error="Agent server unreachable")
```

The frontend polls this endpoint regularly — a 503 would be noisy. Only mutation routes (pipeline/run, watcher/start, discovery/trigger) should propagate `AgentUnavailableError` to the 503 handler.
