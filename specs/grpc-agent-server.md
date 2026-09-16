# Plan: gRPC Agent Server (obs-machine)

## Task Description

Build the gRPC agent server that runs on the obs-machine (Windows). This covers Steps 6-8 from the full web app plan at `specs/media-transcribe-web-app.md`. The agent server wraps existing pipeline classes (`Pipeline`, `ContentWatcher`, `PatreonDiscovery`, `Preflight`) behind a gRPC service contract, enabling the devbox-01 web app to control the obs-machine without SSH.

**Task type:** Feature
**Complexity:** Complex

## Objective

When complete, the obs-machine runs a gRPC server on port 8421 that:
1. Authenticates callers via bearer token (except HealthCheck)
2. Implements all 7 RPCs defined in `proto/agent.proto`
3. Streams real-time pipeline events to connected clients
4. Starts via `uv run cli.py serve` subcommand
5. All tests pass with mocked OBS/Chrome/Patreon — no real network calls

## Problem Statement

Controlling the obs-machine currently requires SSH commands with fragile PowerShell quoting. There is no structured RPC contract, no streaming event feedback, and no way for the upcoming web dashboard to programmatically control pipeline operations. The agent server provides the typed, streaming, auto-reconnecting gRPC interface that the web app on devbox-01 will connect to.

## Solution Approach

Three layers built bottom-up:

1. **Auth interceptor** (`agent/interceptors.py`) — gRPC server interceptor validates bearer token from call metadata, exempts HealthCheck for monitoring
2. **Agent servicer** (`agent/server.py`) — `AgentServiceServicer` implementation wrapping Pipeline, ContentWatcher, PatreonDiscovery; manages subscriber queues for `StreamEvents`; background asyncio tasks for long-running operations
3. **CLI entry point** (`cli.py serve`) — wires everything together, starts gRPC server

The only modification to existing code is adding optional callback hooks to `Pipeline.__init__()` and `_process_one()` — backward compatible (None when not provided).

## Relevant Files

Use these files to complete the task:

### Existing Files (read/integrate)

- `proto/agent_pb2.py` — Generated protobuf message classes (already committed)
- `proto/agent_pb2_grpc.py` — Generated gRPC stubs and servicers; `AgentServiceServicer` is the base class to override, `add_AgentServiceServicer_to_server` registers it
- `src/pipeline/runner.py` — `Pipeline` class + `STEPS` list + `PipelineResult` — **modify** to add callback hooks
- `src/pipeline/watcher.py` — `ContentWatcher` — wrap for `StartWatcher`/`StopWatcher` RPCs; use `read_status()` for `GetStatus`
- `src/sources/discovery.py` — `PatreonDiscovery` + `DiscoveredPost` — wrap for `TriggerDiscovery` RPC
- `src/catalog.py` — `CatalogManager` — used by `TriggerDiscovery` to merge discovered posts
- `src/capture/preflight.py` — `Preflight` — used by `HealthCheck` RPC for OBS/Chrome/disk checks
- `src/config.py` — Paths, OBS config, `BACKUP_DIR`, `CATALOG_PATH`, `IS_WINDOWS`
- `cli.py` — CLI entry point — **modify** to add `serve` subcommand and add to `LONG_RUNNING_COMMANDS`
- `web/lifecycle.py` — `StepStatus` enum, `PIPELINE_STEPS` — reference for step names
- `web/config.py` — Already has `AGENT_HOST`, `AGENT_PORT`, `AGENT_TOKEN` for the client side
- `pyproject.toml` — Already has `agent = ["grpcio>=1.60"]` optional dependency

### Existing Test Files (reference for patterns)

- `tests/test_pipeline.py` — Uses `AsyncMock`, `MagicMock`, `patch.object`, `pytest.mark.asyncio`
- `tests/test_watcher.py` — Watcher test patterns
- `tests/web/test_lifecycle.py` — Clean class-based test organization

### New Files

- `agent/__init__.py` — Package init
- `agent/config.py` — Port, token config, `.env` loading, startup validation
- `agent/interceptors.py` — `AuthInterceptor(grpc.aio.ServerInterceptor)` — bearer token validation
- `agent/server.py` — `AgentServiceServicer` implementation + `run_server()` entry point
- `tests/agent/__init__.py` — Test package init
- `tests/agent/test_interceptors.py` — Auth interceptor tests
- `tests/agent/test_server.py` — Agent server unit tests

## Implementation Phases

### Phase 1: Foundation

Config module, auth interceptor, and their tests. No gRPC server yet — validate interceptor logic in isolation.

### Phase 2: Core Implementation

`AgentServiceServicer` implementing all 7 RPCs. Add pipeline callback hooks. Background task management for `RunPipeline`, `StartWatcher`, `StreamEvents`.

### Phase 3: Integration & Polish

CLI `serve` subcommand wiring. `run_server()` function. Full test suite. Validation that existing tests don't regress.

## Step by Step Tasks

IMPORTANT: Execute every step in order, top to bottom.

### 1. Create `agent/__init__.py`

- Create empty `agent/__init__.py` to make `agent` a Python package
- Create empty `tests/agent/__init__.py` for the test package

### 2. Create `agent/config.py`

- Load configuration from environment variables with `.env` file support
- Implementation:

```python
import os
import sys
from pathlib import Path


def _load_dotenv() -> None:
    """Load .env file from project root if it exists."""
    for candidate in [Path(".env"), Path(__file__).resolve().parent.parent / ".env"]:
        if candidate.exists():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("\"'")
                if key and key not in os.environ:
                    os.environ[key] = value
            break


_load_dotenv()

PORT = int(os.getenv("AGENT_PORT", "8421"))
AGENT_TOKEN = os.getenv("AGENT_TOKEN", "")


def validate_config() -> None:
    """Fail-fast if AGENT_TOKEN is not set or too short."""
    if not AGENT_TOKEN:
        print("FATAL: AGENT_TOKEN environment variable is not set.", file=sys.stderr)
        print("Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\"", file=sys.stderr)
        sys.exit(1)
    if len(AGENT_TOKEN) < 32:
        print(f"FATAL: AGENT_TOKEN must be >= 32 chars (got {len(AGENT_TOKEN)}).", file=sys.stderr)
        sys.exit(1)
```

Key behaviors:
- `PORT` defaults to 8421
- `AGENT_TOKEN` loaded from env; `.env` file loaded on import if present
- `validate_config()` called at server startup — exits with clear message if token missing/short
- `.env` values don't override existing env vars (standard dotenv behavior)

### 3. Create `agent/interceptors.py`

- Implement `AuthInterceptor` as a `grpc.aio.ServerInterceptor`
- Implementation:

```python
import grpc
import grpc.aio

from agent.config import AGENT_TOKEN


class AuthInterceptor(grpc.aio.ServerInterceptor):

    def __init__(self, token: str | None = None):
        self._token = token or AGENT_TOKEN

    async def intercept_service(self, continuation, handler_call_details):
        method = handler_call_details.method
        if method.endswith("/HealthCheck"):
            return await continuation(handler_call_details)

        metadata = dict(handler_call_details.invocation_metadata)
        auth_value = metadata.get("authorization", "")

        if auth_value.lower() != f"bearer {self._token}".lower():
            return _unauthenticated_handler()

        return await continuation(handler_call_details)
```

Key behaviors:
- Reads `authorization` from gRPC call metadata
- Compares against `f"bearer {AGENT_TOKEN}"` (case-insensitive comparison on the "bearer" prefix)
- Aborts with `UNAUTHENTICATED` if missing or wrong
- **Exempts `/HealthCheck`** — allows monitoring probes without a token
- Accepts optional `token` parameter for testability (falls back to config)

The `_unauthenticated_handler()` returns a `grpc.unary_unary_rpc_method_handler` that always aborts with `StatusCode.UNAUTHENTICATED`. This is the standard pattern for gRPC aio interceptors because you can't directly abort from `intercept_service` — you must return a handler that does the aborting.

```python
def _abort_with_unauthenticated(request, context):
    context.abort(grpc.StatusCode.UNAUTHENTICATED, "Invalid or missing authentication token")

def _unauthenticated_handler():
    return grpc.unary_unary_rpc_method_handler(_abort_with_unauthenticated)
```

**Important implementation note:** The `grpc.aio.ServerInterceptor.intercept_service` pattern requires returning either the result of `await continuation(handler_call_details)` (pass-through) or a replacement handler (rejection). The handler returned for rejection needs to match the RPC type (unary-unary for most RPCs). For the auth interceptor, returning a `unary_unary_rpc_method_handler` that aborts works for all method types because gRPC will invoke the handler and the abort terminates the call regardless.

### 4. Create `tests/agent/test_interceptors.py`

- Test the auth interceptor in isolation using a real in-process gRPC server
- Implementation approach:

```python
import pytest
import grpc
import grpc.aio
from proto import agent_pb2, agent_pb2_grpc
from agent.interceptors import AuthInterceptor

TEST_TOKEN = "a" * 64

@pytest.fixture
async def grpc_channel():
    """Start a minimal gRPC server with AuthInterceptor and return a channel to it."""
    # Create a minimal servicer that implements HealthCheck and GetStatus
    # Start server on localhost:0 (auto-assign port)
    # Yield channel
    # Shutdown server

async def test_valid_token_passes(grpc_channel):
    stub = agent_pb2_grpc.AgentServiceStub(grpc_channel)
    metadata = [("authorization", f"bearer {TEST_TOKEN}")]
    response = await stub.HealthCheck(agent_pb2.Empty(), metadata=metadata)
    assert response.healthy is not None  # Got a response, not rejected

async def test_invalid_token_rejected(grpc_channel):
    stub = agent_pb2_grpc.AgentServiceStub(grpc_channel)
    metadata = [("authorization", "bearer wrong_token")]
    with pytest.raises(grpc.aio.AioRpcError) as exc_info:
        await stub.GetStatus(agent_pb2.Empty(), metadata=metadata)
    assert exc_info.value.code() == grpc.StatusCode.UNAUTHENTICATED

async def test_missing_token_rejected(grpc_channel):
    stub = agent_pb2_grpc.AgentServiceStub(grpc_channel)
    with pytest.raises(grpc.aio.AioRpcError) as exc_info:
        await stub.GetStatus(agent_pb2.Empty())
    assert exc_info.value.code() == grpc.StatusCode.UNAUTHENTICATED

async def test_healthcheck_exempt_from_auth(grpc_channel):
    stub = agent_pb2_grpc.AgentServiceStub(grpc_channel)
    # No metadata — should still work for HealthCheck
    response = await stub.HealthCheck(agent_pb2.Empty())
    assert response.healthy is not None
```

Test structure:
- Fixture creates a real `grpc.aio.server()` with the `AuthInterceptor` and a minimal servicer that implements `HealthCheck` (returns a basic response) and `GetStatus` (returns a basic response)
- Server binds to `localhost:0` (auto-assign port) — no port conflicts
- Each test creates a stub and exercises the interceptor
- 4 test cases: valid token, invalid token, missing token, HealthCheck exempt

### 5. Modify `src/pipeline/runner.py` — Add Callback Hooks

- Add optional callback parameters to `Pipeline.__init__()`:

```python
class Pipeline:
    def __init__(self, source, engine, output_dir: Path | None = None,
                 enable_breaks: bool = False, preflight=None,
                 catalog: CatalogManager | None = None,
                 on_step_start=None, on_step_complete=None, on_step_fail=None):
        # ...existing init...
        self._on_step_start = on_step_start
        self._on_step_complete = on_step_complete
        self._on_step_fail = on_step_fail
```

- Modify `_process_one()` to call callbacks around each step:

```python
async def _process_one(self, post, steps: list[str]) -> PipelineResult:
    result = PipelineResult(
        post_url=post.url,
        post_title=post.title,
    )

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

    return result
```

**Backward compatibility:** All three callbacks default to `None`. When `None`, no callback is called. Existing CLI usage passes no callbacks — behavior unchanged. The agent server wires these callbacks to emit `PipelineEvent` messages to `StreamEvents` subscribers.

**Callback signatures:**
- `on_step_start(post: Post, step: str) -> None`
- `on_step_complete(post: Post, step: str, result: PipelineResult) -> None`
- `on_step_fail(post: Post, step: str, error: str) -> None`

### 6. Create `agent/server.py` — `AgentServiceServicer`

- The main servicer implementation wrapping all existing classes
- Implementation structure:

```python
import asyncio
import logging
import shutil
import uuid
from datetime import datetime, timezone

import grpc
import grpc.aio

from proto import agent_pb2, agent_pb2_grpc
from agent.config import PORT, validate_config
from agent.interceptors import AuthInterceptor

log = logging.getLogger(__name__)


class AgentServiceServicer(agent_pb2_grpc.AgentServiceServicer):

    def __init__(self):
        self._watcher = None              # ContentWatcher instance (if running)
        self._watcher_task = None         # asyncio.Task for watcher
        self._pipeline_task = None        # asyncio.Task for current pipeline run
        self._pipeline_run_id = None      # current run_id
        self._pipeline_total = 0
        self._pipeline_completed = 0
        self._pipeline_failed = 0
        self._pipeline_current_post = ""
        self._pipeline_current_step = ""
        self._subscribers: list[asyncio.Queue] = []
        self._subscriber_lock = asyncio.Lock()
```

#### RPC Implementations

**HealthCheck** — Lightweight, no side effects:
```python
async def HealthCheck(self, request, context):
    healthy = True
    obs_connected = False
    chrome_available = False
    disk_ok = False
    obs_version = ""
    error = ""

    # Test OBS WebSocket
    try:
        import obsws_python as obs
        cl = obs.ReqClient(host="localhost", port=4455, password="...", timeout=3)
        version_info = cl.get_version()
        obs_version = version_info.obs_version
        obs_connected = True
        cl.disconnect()
    except Exception as exc:
        obs_connected = False
        error = f"OBS: {exc}"

    # Test Chrome CDP
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:9222/json/version", timeout=3) as resp:
            chrome_available = resp.status == 200
    except Exception:
        chrome_available = False

    # Check disk space (>= 5GB free on the drive with BACKUP_DIR)
    try:
        from src.config import BACKUP_DIR
        usage = shutil.disk_usage(str(BACKUP_DIR))
        disk_ok = usage.free >= 5 * 1024**3
    except Exception:
        disk_ok = False

    healthy = obs_connected and chrome_available and disk_ok

    return agent_pb2.HealthResponse(
        healthy=healthy,
        obs_connected=obs_connected,
        chrome_available=chrome_available,
        disk_ok=disk_ok,
        obs_version=obs_version,
        error=error,
    )
```

**GetStatus** — Reads watcher state, pipeline state, disk info:
```python
async def GetStatus(self, request, context):
    # Health
    health = await self.HealthCheck(request, context)

    # Watcher state
    from src.pipeline.watcher import ContentWatcher
    watcher_data = ContentWatcher.read_status()
    watcher_state = agent_pb2.WatcherState()
    if watcher_data:
        watcher_state = agent_pb2.WatcherState(
            running=watcher_data.get("running", False),
            pid=watcher_data.get("pid", 0),
            cycle=watcher_data.get("cycle", 0),
            interval_hours=self._watcher.interval_hours if self._watcher else 0,
            last_run=watcher_data.get("last_run", ""),
            next_run=watcher_data.get("next_run", ""),
            new_found=watcher_data.get("last_result", {}).get("new_found", 0),
            recorded=watcher_data.get("last_result", {}).get("recorded", 0),
            failed=watcher_data.get("last_result", {}).get("failed", 0),
            total_recorded=watcher_data.get("total_recorded", 0),
            started_at=watcher_data.get("started_at", ""),
        )

    # Pipeline state
    pipeline_state = agent_pb2.PipelineState(
        running=self._pipeline_task is not None and not self._pipeline_task.done(),
        run_id=self._pipeline_run_id or "",
        total=self._pipeline_total,
        completed=self._pipeline_completed,
        failed=self._pipeline_failed,
        current_post=self._pipeline_current_post,
        current_step=self._pipeline_current_step,
    )

    # Disk info
    from src.config import BACKUP_DIR
    try:
        usage = shutil.disk_usage(str(BACKUP_DIR))
        disk_info = agent_pb2.DiskInfo(
            total_bytes=usage.total, free_bytes=usage.free, drive=str(BACKUP_DIR)[:2],
        )
    except Exception:
        disk_info = agent_pb2.DiskInfo()

    return agent_pb2.AgentStatus(
        health=health, watcher=watcher_state,
        pipeline=pipeline_state, disk=disk_info,
    )
```

**RunPipeline** — Starts pipeline in background task, returns immediately:
```python
async def RunPipeline(self, request, context):
    if self._pipeline_task and not self._pipeline_task.done():
        return agent_pb2.PipelineResponse(
            started=False, error="Pipeline already running",
            run_id=self._pipeline_run_id or "",
        )

    run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    self._pipeline_run_id = run_id
    self._pipeline_total = len(request.posts)
    self._pipeline_completed = 0
    self._pipeline_failed = 0

    self._pipeline_task = asyncio.create_task(
        self._run_pipeline_task(request, run_id)
    )

    return agent_pb2.PipelineResponse(
        started=True, run_id=run_id,
        queue_size=len(request.posts),
    )
```

The `_run_pipeline_task` method:
- Imports and instantiates `Pipeline` with callback hooks wired to `_broadcast()`
- Converts `request.posts` to `Post` objects
- Runs `pipeline.run()` with optional step filtering from `request.steps`
- On completion, broadcasts a `pipeline_complete` event
- On failure, broadcasts a `pipeline_failed` event
- Callbacks (`on_step_start`, `on_step_complete`, `on_step_fail`) create `PipelineEvent` messages and call `_broadcast()`:

```python
def _make_step_callback(self, event_type, run_id):
    def callback(post, step, *args):
        event = agent_pb2.PipelineEvent(
            type=event_type,
            run_id=run_id,
            post_id=getattr(post, "url", ""),  # extract_post_id later
            step=step,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        if event_type == "step_failed" and args:
            event.error = str(args[0])
        if event_type == "step_completed":
            event.status = "completed"
        asyncio.get_event_loop().call_soon_threadsafe(
            lambda: asyncio.create_task(self._broadcast(event))
        )
    return callback
```

**Note on thread safety:** The pipeline callbacks run on the asyncio event loop (Pipeline.run is async), so `_broadcast()` can be called directly as a coroutine. However, if any callback is invoked from a synchronous context (e.g., `asyncio.to_thread`), use `call_soon_threadsafe`. The safest approach is to always schedule via `call_soon_threadsafe`.

**StartWatcher** — Creates and starts ContentWatcher:
```python
async def StartWatcher(self, request, context):
    if self._watcher_task and not self._watcher_task.done():
        return agent_pb2.WatcherResponse(
            success=False, message="Watcher already running",
        )

    interval = max(request.interval_hours, 12.0)
    steps = list(request.steps) or ["record", "analyze", "transcribe", "correct"]

    from src.pipeline.watcher import ContentWatcher
    self._watcher = ContentWatcher(
        source="patreon",
        interval_hours=interval,
        steps=steps,
        max_per_run=request.max_per_run or 3,
        dry_run=request.dry_run,
    )

    self._watcher_task = asyncio.create_task(self._watcher.run_forever())

    return agent_pb2.WatcherResponse(
        success=True,
        message=f"Watcher started (interval={interval}h, max_per_run={request.max_per_run})",
    )
```

**StopWatcher** — Graceful shutdown:
```python
async def StopWatcher(self, request, context):
    if not self._watcher:
        return agent_pb2.WatcherResponse(success=False, message="No watcher running")

    self._watcher._shutdown = True
    return agent_pb2.WatcherResponse(
        success=True, message="Watcher shutdown initiated",
    )
```

**TriggerDiscovery** — Wraps PatreonDiscovery + CatalogManager:
```python
async def TriggerDiscovery(self, request, context):
    from src.sources.discovery import PatreonDiscovery, MAX_PAGES
    from src.catalog import CatalogManager
    from src.config import CATALOG_PATH

    campaign_id = request.campaign_id or "5008493"
    max_pages = MAX_PAGES if request.full_catalog else 1
    discovery = PatreonDiscovery(campaign_id=campaign_id)

    if request.full_catalog and not request.force:
        if not discovery.check_cooldown(CATALOG_PATH.parent):
            return agent_pb2.DiscoveryResponse(error="Cooldown active")

    fetched = discovery.fetch_posts(media_type="video", max_pages=max_pages)
    new_posts = discovery.diff_catalog(fetched, CATALOG_PATH)

    catalog = CatalogManager(CATALOG_PATH)
    merged, new_count = catalog.merge_discovered(fetched)
    catalog.save(merged)

    if request.full_catalog:
        discovery.update_cooldown(CATALOG_PATH.parent)

    new_post_list = [
        agent_pb2.DiscoveredPostInfo(
            post_id=p.post_id, title=p.title, url=p.url,
            published_at=p.published_at or "", post_type=p.post_type,
            has_video=p.has_video,
        )
        for p in new_posts
    ]

    return agent_pb2.DiscoveryResponse(
        total_found=len(fetched), new_posts=len(new_posts),
        video_posts=sum(1 for p in fetched if p.has_video),
        new_post_list=new_post_list,
    )
```

**StreamEvents** — Server-streaming RPC with per-subscriber queue:
```python
async def StreamEvents(self, request, context):
    queue = asyncio.Queue(maxsize=100)
    async with self._subscriber_lock:
        self._subscribers.append(queue)

    event_types = set(request.event_types) if request.event_types else None

    try:
        while not context.cancelled():
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30)
            except asyncio.TimeoutError:
                continue  # heartbeat loop — check if context is still alive
            if event_types and event.type not in event_types:
                continue
            yield event
    except asyncio.CancelledError:
        pass
    finally:
        async with self._subscriber_lock:
            self._subscribers.remove(queue)
```

**_broadcast** — Sends event to all subscriber queues:
```python
async def _broadcast(self, event: agent_pb2.PipelineEvent) -> None:
    async with self._subscriber_lock:
        for queue in self._subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                log.warning("Subscriber queue full — dropping event")
```

#### `run_server()` Entry Point

```python
async def run_server(port: int | None = None) -> None:
    validate_config()

    server_port = port or PORT
    interceptor = AuthInterceptor()
    server = grpc.aio.server(interceptors=[interceptor])
    servicer = AgentServiceServicer()
    agent_pb2_grpc.add_AgentServiceServicer_to_server(servicer, server)
    server.add_insecure_port(f"0.0.0.0:{server_port}")

    log.info("Agent server starting on 0.0.0.0:%d", server_port)
    await server.start()
    log.info("Agent server ready")

    try:
        await server.wait_for_termination()
    except KeyboardInterrupt:
        log.info("Shutting down agent server")
        await server.stop(grace=5)
```

### 7. Create `tests/agent/test_server.py`

- Test the servicer in-process with mocked external dependencies
- Use a `grpc.aio.server()` fixture with the servicer registered

```python
# Fixture: starts an in-process gRPC server with AgentServiceServicer
# Uses a free port (server.add_insecure_port("[::]:0"))
# Patches external deps: OBS, Chrome CDP, disk_usage, Pipeline, Discovery

@pytest.fixture
async def server_and_channel():
    """Start agent server with mocked deps, return (servicer, channel, stub)."""
    # Patch obsws_python, urllib.request.urlopen, shutil.disk_usage
    # Create server on free port
    # Return channel and stub
    ...
```

Test cases:

1. **test_health_check_returns_valid_response** — Mock OBS as connected, Chrome as available, disk as OK. Assert `healthy=True`, `obs_connected=True`, etc.

2. **test_health_check_reports_obs_down** — Mock OBS connection to raise. Assert `healthy=False`, `obs_connected=False`.

3. **test_get_status_returns_combined** — Mock all subsystems. Assert response has health, watcher, pipeline, and disk fields.

4. **test_trigger_discovery_with_mocked_api** — Patch `PatreonDiscovery.fetch_posts()` to return fake `DiscoveredPost` list. Patch `CatalogManager`. Assert response has correct counts.

5. **test_run_pipeline_starts_background_task** — Call `RunPipeline` with mock posts. Assert `started=True` and `run_id` is non-empty. Verify the pipeline task was created.

6. **test_run_pipeline_rejects_when_already_running** — Start one pipeline, then try to start another. Assert second call returns `started=False` with error message.

7. **test_stream_events_receives_pipeline_events** — Subscribe via `StreamEvents`, trigger a pipeline run with mocked fast-completing steps, assert events arrive with correct types and fields.

8. **test_start_watcher_validates_interval** — Call `StartWatcher` with `interval_hours=6`. Assert it gets clamped to 12h minimum.

9. **test_stop_watcher_graceful** — Start watcher, then stop. Assert `_shutdown` flag is set.

All tests use `unittest.mock.patch` for OBS, Chrome, Patreon API, disk — no real network calls.

### 8. Add `serve` Subcommand to `cli.py`

- Add to `build_parser()`:

```python
# --- serve (agent gRPC server) ---
s = sub.add_parser("serve", help="Start the gRPC agent server")
s.add_argument("--port", type=int, default=8421,
               help="gRPC server port (default: 8421)")
s.add_argument("--foreground", action="store_true",
               help="Run in foreground instead of backgrounding")
```

- Add `"serve"` to `LONG_RUNNING_COMMANDS` set (line 34):

```python
LONG_RUNNING_COMMANDS = {"record", "transcribe", "analyze", "pipeline", "watch", "serve"}
```

- Add handler in `main()` (after the `watch` handler, before `release-info`):

```python
elif args.command == "serve":
    import asyncio
    from agent.server import run_server
    asyncio.run(run_server(port=args.port))
```

### 9. Validate Everything

Run all validation commands to confirm correctness.

## Testing Strategy

### Unit Tests (no network, no OBS, no Chrome)

**Interceptor tests (`tests/agent/test_interceptors.py`):**
- In-process gRPC server with `AuthInterceptor`
- Valid token → RPC succeeds
- Invalid token → `UNAUTHENTICATED` status
- Missing token → `UNAUTHENTICATED` status
- HealthCheck → passes without any token (exempt)

**Server tests (`tests/agent/test_server.py`):**
- In-process gRPC server with `AgentServiceServicer`
- All external dependencies mocked (`obsws_python`, `urllib.request`, `shutil.disk_usage`, `Pipeline`, `PatreonDiscovery`, `CatalogManager`)
- HealthCheck returns valid response with mocked OBS/Chrome/disk
- GetStatus returns combined status from all subsystems
- TriggerDiscovery returns correct counts with mocked Patreon API
- RunPipeline starts background task and returns run_id
- RunPipeline rejects second concurrent run
- StreamEvents receives events from pipeline callbacks
- StartWatcher clamps interval to 12h minimum
- StopWatcher sets shutdown flag

**Pipeline callback tests (in existing `tests/test_pipeline.py`):**
- Verify callbacks are called in correct order (start → complete or start → fail)
- Verify callbacks are not called when set to None (backward compatibility)
- Verify callback arguments are correct

### Regression Tests

- All existing tests pass unchanged: `uv run pytest tests/ -v`
- Pipeline tests specifically unchanged: `uv run pytest tests/test_pipeline.py -v`

## Acceptance Criteria

1. **`uv run cli.py serve --help`** prints help text with `--port` and `--foreground` options
2. **`uv run python -c "from agent.server import AgentServiceServicer; print('OK')"`** succeeds
3. **`uv run python -c "from agent.interceptors import AuthInterceptor; print('OK')"`** succeeds
4. **`uv run python -c "from agent.config import PORT, AGENT_TOKEN, validate_config; print('OK')"`** succeeds
5. **Bearer token auth works**: gRPC calls without valid `AGENT_TOKEN` are rejected with `UNAUTHENTICATED`; HealthCheck is exempt
6. **Pipeline callbacks backward compatible**: Existing `Pipeline()` instantiation (no callbacks) continues to work; `_process_one()` calls callbacks when provided and skips when None
7. **All 7 RPCs implemented**: HealthCheck, GetStatus, RunPipeline, StartWatcher, StopWatcher, TriggerDiscovery, StreamEvents all have functional implementations
8. **StreamEvents delivers real-time events**: Pipeline callbacks → `_broadcast()` → subscriber queues → `StreamEvents` yield
9. **`uv run pytest tests/agent/ -v`** passes — all interceptor and server tests green
10. **`uv run pytest tests/ -v`** passes — no regressions in existing 300+ tests
11. **`serve` in `LONG_RUNNING_COMMANDS`** — auto-backgrounds over SSH, runs foreground with `--foreground`

## Validation Commands

Execute these commands to validate the task is complete:

```bash
# --- Import checks ---
uv run python -c "from agent.server import AgentServiceServicer; print('OK')"
uv run python -c "from agent.interceptors import AuthInterceptor; print('OK')"
uv run python -c "from agent.config import PORT, AGENT_TOKEN; print('OK')"

# --- CLI subcommand ---
uv run cli.py serve --help

# --- Agent server tests ---
uv run pytest tests/agent/test_interceptors.py -v
uv run pytest tests/agent/test_server.py -v

# --- Pipeline callback tests (in existing test file) ---
uv run pytest tests/test_pipeline.py -v

# --- Full regression check ---
uv run pytest tests/ -v

# --- Verify proto imports still work ---
uv run python -c "from proto import agent_pb2, agent_pb2_grpc; print('OK')"

# --- Verify serve is in LONG_RUNNING_COMMANDS ---
uv run python -c "
import cli
assert 'serve' in cli.LONG_RUNNING_COMMANDS, 'serve not in LONG_RUNNING_COMMANDS'
print('OK')
"
```

## Notes

### gRPC Async vs Sync

The generated `AgentServiceServicer` in `proto/agent_pb2_grpc.py` defines synchronous methods. When using `grpc.aio.server()`, the servicer methods **can be coroutines** — gRPC will `await` them. Our implementation defines all methods as `async def`, which works with `grpc.aio.server()`.

### Thread Safety in Callbacks

Pipeline's `_process_one` runs on the asyncio event loop (it's `async def`). The callbacks are called directly from the coroutine, so they execute on the event loop thread. The `_broadcast()` method is also a coroutine. Since both run on the same event loop, no `call_soon_threadsafe` is needed — just `await self._broadcast(event)` or schedule with `asyncio.create_task`. However, since callbacks are synchronous functions (not coroutines), they should use `asyncio.get_event_loop().create_task(self._broadcast(event))` to schedule the broadcast without blocking.

### OBS WebSocket Access

The HealthCheck probes OBS via `obsws_python` (the same library used by `OBSEngine`). Import is conditional — if `obsws_python` is not installed (e.g., on devbox-01), the check returns `obs_connected=False`. This is fine because the agent server only runs on the obs-machine where `obsws_python` is available via `--extra capture`.

### No New Dependencies Required

- `grpcio` already in `pyproject.toml` under `[project.optional-dependencies] agent`
- `grpcio-tools` already in `[dependency-groups] dev`
- No additional packages needed

### File Diff Summary

| File | Action |
|------|--------|
| `agent/__init__.py` | Create (empty) |
| `agent/config.py` | Create |
| `agent/interceptors.py` | Create |
| `agent/server.py` | Create |
| `tests/agent/__init__.py` | Create (empty) |
| `tests/agent/test_interceptors.py` | Create |
| `tests/agent/test_server.py` | Create |
| `src/pipeline/runner.py` | Modify (add 3 callback params to `__init__`, 6 lines in `_process_one`) |
| `cli.py` | Modify (add `serve` to `LONG_RUNNING_COMMANDS`, add parser + handler) |
