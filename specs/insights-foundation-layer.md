# Plan: Insights Foundation Layer (Steps 1–5)

## Task Description

Implement the foundation layer for the Insights pipeline dashboard web app. This covers the data layer, lifecycle state machine, protobuf contract, and Pydantic models — everything needed before building API routes or the frontend. The scope maps to Steps 1–5 from the full plan at `specs/media-transcribe-web-app.md`.

This is the first ADW for Insights. Nothing in `web/`, `proto/`, or `tests/web/` exists yet. The goal is to establish the schema, state machine, and data migration so that subsequent ADWs (API routes, agent server, frontend) can build on a tested foundation.

## Objective

When this plan is complete:
1. `pyproject.toml` has `web` and `agent` optional dependency groups + `grpcio-tools` in dev
2. `proto/agent.proto` contains the full gRPC service definition; generated Python stubs import cleanly
3. `web/lifecycle.py` implements the `StepStatus` enum and `derive_post_status()` with full test coverage
4. `web/database.py` creates all SQLite tables (including multi-source `sources` table) and migrates the 1,632-post JSON catalog
5. `web/models.py` defines all Pydantic request/response models
6. All tests pass: `uv run pytest tests/web/ -v`

## Problem Statement

The pipeline currently tracks only two coarse states per post: `ingested_status: null` (untouched) or `"complete"` / `"failed"`. There is no per-step granularity — you cannot tell if a video was recorded but not yet transcribed. All 1,632 posts live in a flat JSON file with no rich querying. The foundation layer introduces the SQLite schema, lifecycle state machine, and typed models that make granular pipeline tracking possible.

## Solution Approach

Build five discrete, testable layers bottom-up:
1. **Dependencies** — add FastAPI, gRPC, aiosqlite to `pyproject.toml`
2. **Protobuf** — define the gRPC contract that the agent server and web backend will share
3. **Lifecycle** — pure-Python state machine with no external deps; easy to test
4. **Database** — async SQLite layer with schema creation and JSON migration
5. **Models** — Pydantic models that wire the database to future API routes

Each layer is independently testable. No existing `src/` files are modified (except `pyproject.toml` for dependencies).

## Relevant Files

### Existing Files (read-only context)

- `pyproject.toml` — add new dependency groups here (the only existing file that gets modified)
- `src/config.py` — `CATALOG_PATH` (line 19) used by `web/config.py` for JSON migration source path
- `src/pipeline/runner.py` — `STEPS` list (line 20-28) defines the 7 pipeline steps that `web/lifecycle.py` must mirror
- `src/sources/discovery.py` — `DiscoveredPost` dataclass (lines 24-54) defines all catalog fields the migration must handle
- `src/catalog.py` — `CatalogManager` — the JSON format the migration reads from
- `data/patreon_full_catalog.json` — the 1,632-post catalog to migrate; posts have 7 fields: `post_id`, `url`, `title`, `created_at`, `post_type`, `has_video`, `has_audio`
- `specs/media-transcribe-web-app.md` — full 21-step plan with schema definitions, proto definition, and model specs

### New Files

- `proto/__init__.py` — empty package init
- `proto/agent.proto` — full gRPC service definition (copied exactly from the plan)
- `proto/generate.sh` — shell script to run protoc and fix imports
- `proto/agent_pb2.py` — generated (by protoc)
- `proto/agent_pb2_grpc.py` — generated (by protoc)
- `web/__init__.py` — empty package init
- `web/config.py` — configuration constants (DB_PATH, HOST, PORT, agent connection, CORS)
- `web/lifecycle.py` — `StepStatus` enum, `PIPELINE_STEPS`, `derive_post_status()`, `step_can_run()`
- `web/database.py` — `init_db()`, `migrate_from_json()`, `get_db()`
- `web/models.py` — all Pydantic request/response models
- `tests/web/__init__.py` — empty package init
- `tests/web/test_lifecycle.py` — state machine unit tests
- `tests/web/test_database.py` — schema creation + JSON migration tests

## Implementation Phases

### Phase 1: Foundation Setup
Add dependencies, create package structure (`web/`, `proto/`, `tests/web/`).

### Phase 2: Core Data Layer
Build the proto definition, lifecycle state machine, SQLite database layer, and Pydantic models — each with tests.

### Phase 3: Validation
Run all imports, verify proto stubs, run tests, confirm no regressions in existing test suite.

## Step by Step Tasks

IMPORTANT: Execute every step in order, top to bottom.

### 1. Add Dependencies to `pyproject.toml`

- Add `[project.optional-dependencies]` entries:
  ```toml
  web = [
      "fastapi>=0.115",
      "uvicorn[standard]>=0.30",
      "aiosqlite>=0.20",
      "websockets>=12",
      "grpcio>=1.60",
  ]
  agent = [
      "grpcio>=1.60",
  ]
  ```
- Merge `grpcio-tools>=1.60` into the existing `[dependency-groups]` dev group (which already has `pytest>=8` and `pytest-asyncio>=0.23`):
  ```toml
  dev = [
      "pytest>=8",
      "pytest-asyncio>=0.23",
      "grpcio-tools>=1.60",
  ]
  ```
- Run `uv sync --extra web` to install all web dependencies
- Verify: `uv run python -c "import fastapi, uvicorn, aiosqlite, grpc; print('deps OK')"`

### 2. Create Protobuf Definition + Generate Stubs

- Create directory `proto/`
- Create `proto/__init__.py` (empty file)
- Create `proto/agent.proto` with the **complete** gRPC service definition from the plan's "gRPC Service Definition" section. This includes:
  - `service AgentService` with 7 RPCs: `RunPipeline`, `StartWatcher`, `StopWatcher`, `GetStatus`, `HealthCheck`, `TriggerDiscovery`, `StreamEvents`
  - All message types: `Empty`, `PipelineRequest`, `PostEntry`, `PipelineResponse`, `WatcherConfig`, `WatcherResponse`, `WatcherState`, `AgentStatus`, `PipelineState`, `DiskInfo`, `HealthResponse`, `DiscoveryRequest`, `DiscoveryResponse`, `DiscoveredPostInfo`, `EventSubscription`, `PipelineEvent`
  - Copy the proto definition **exactly** from lines 143-298 of `specs/media-transcribe-web-app.md` — future ADWs depend on field numbers and types matching
- Create `proto/generate.sh`:
  ```bash
  #!/bin/bash
  set -euo pipefail
  cd "$(dirname "$0")/.."
  uv run python -m grpc_tools.protoc \
      -I proto \
      --python_out=proto \
      --grpc_python_out=proto \
      proto/agent.proto
  sed -i 's/import agent_pb2/from proto import agent_pb2/' proto/agent_pb2_grpc.py
  echo "Generated proto/agent_pb2.py and proto/agent_pb2_grpc.py"
  ```
- `chmod +x proto/generate.sh`
- Run `bash proto/generate.sh` to generate `proto/agent_pb2.py` and `proto/agent_pb2_grpc.py`
- Verify: `uv run python -c "from proto import agent_pb2, agent_pb2_grpc; print('Proto OK')"`
- The generated files are committed for convenience (avoids requiring grpcio-tools on obs-machine)

### 3. Create Lifecycle State Machine (`web/lifecycle.py`)

- Create `web/__init__.py` (empty)
- Create `web/lifecycle.py` with:

  **`StepStatus` enum** (must be `str, Enum` for JSON serialization):
  ```python
  class StepStatus(str, Enum):
      PENDING   = "pending"
      QUEUED    = "queued"
      RUNNING   = "running"
      COMPLETED = "completed"
      FAILED    = "failed"
      SKIPPED   = "skipped"
  ```

  **`PIPELINE_STEPS`** — must mirror `src/pipeline/runner.STEPS` exactly:
  ```python
  PIPELINE_STEPS = ["record", "analyze", "transcribe", "correct", "find_gaps", "extract_frames", "ocr"]
  ```

  **`derive_post_status(step_statuses: dict[str, StepStatus]) -> str`** — computes overall status from per-step statuses. Priority order:
  1. If any step is `RUNNING` → `"in_progress"`
  2. If all steps are `COMPLETED` or `SKIPPED` → `"completed"`
  3. If any step is `FAILED` (and none `RUNNING`) → `"failed"`
  4. If any step is `QUEUED` → `"queued"`
  5. If any step is `COMPLETED` (but some still `PENDING`) → `"partial"`
  6. Otherwise (all `PENDING`) → `"discovered"`

  **`step_can_run(step: str, step_statuses: dict[str, StepStatus]) -> bool`** — validates step dependencies:
  - `record` → always can run (no dependencies)
  - `analyze` → requires `record` COMPLETED
  - `transcribe` → requires `record` COMPLETED
  - `correct` → requires `transcribe` COMPLETED
  - `find_gaps` → requires `transcribe` COMPLETED
  - `extract_frames` → requires `find_gaps` COMPLETED and `record` COMPLETED
  - `ocr` → requires `extract_frames` COMPLETED

  Implementation approach for dependencies: define a `STEP_DEPENDENCIES` dict mapping each step to its prerequisite steps (all must be COMPLETED):
  ```python
  STEP_DEPENDENCIES: dict[str, list[str]] = {
      "record": [],
      "analyze": ["record"],
      "transcribe": ["record"],
      "correct": ["transcribe"],
      "find_gaps": ["transcribe"],
      "extract_frames": ["find_gaps", "record"],
      "ocr": ["extract_frames"],
  }
  ```

- Create `tests/web/__init__.py` (empty)
- Create `tests/web/test_lifecycle.py` with tests covering:
  - **derive_post_status paths:**
    - All PENDING → `"discovered"`
    - Any RUNNING → `"in_progress"` (even if others are FAILED)
    - All COMPLETED → `"completed"`
    - All SKIPPED → `"completed"`
    - Mix of COMPLETED and SKIPPED → `"completed"`
    - Any FAILED, none RUNNING → `"failed"`
    - Any QUEUED, none RUNNING → `"queued"`
    - Some COMPLETED, some PENDING → `"partial"`
    - FAILED + RUNNING → `"in_progress"` (RUNNING takes priority)
    - QUEUED + COMPLETED → `"queued"` (not partial)
  - **step_can_run:**
    - `record` can always run
    - `transcribe` cannot run when `record` is PENDING
    - `transcribe` can run when `record` is COMPLETED
    - `extract_frames` needs both `find_gaps` and `record` COMPLETED
    - `ocr` needs `extract_frames` COMPLETED
    - Unknown step raises `ValueError`
  - **PIPELINE_STEPS matches runner.STEPS:**
    - Import both and assert equality

### 4. Create SQLite Database Layer

**`web/config.py`:**
- `DB_PATH = Path("data/media_transcribe.db")`
- `HOST = "0.0.0.0"`
- `PORT = 8420`
- `CORS_ORIGINS = ["http://localhost:5173", "http://localhost:8420"]`
- `AGENT_HOST = os.getenv("AGENT_HOST", "100.66.194.100")`
- `AGENT_PORT = int(os.getenv("AGENT_PORT", "8421"))`
- `AGENT_TOKEN = os.getenv("AGENT_TOKEN", "")`
- Import `CATALOG_PATH` from `src.config` and expose as `CATALOG_JSON_PATH`

**`web/database.py`:**

`async def init_db(db_path: Path) -> aiosqlite.Connection`:
- Opens an aiosqlite connection
- Enables WAL mode for concurrent read/write: `PRAGMA journal_mode=WAL`
- Creates all tables via `executescript()`:

  ```sql
  -- Multi-source support
  CREATE TABLE IF NOT EXISTS sources (
      id          TEXT PRIMARY KEY,
      name        TEXT NOT NULL,
      description TEXT,
      source_type TEXT NOT NULL,
      config      TEXT,
      created_at  TEXT NOT NULL
  );

  -- Seed FUW source if not exists
  INSERT OR IGNORE INTO sources (id, name, description, source_type, created_at)
  VALUES ('fuw', 'Fired Up Wealth', 'FIRE Investing Masterclass video library from Patreon', 'patreon', datetime('now'));

  -- Posts (migrated from JSON catalog)
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

  -- Per-step lifecycle tracking
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

  -- Recording queue
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

  -- Watcher configuration + state
  CREATE TABLE IF NOT EXISTS watcher_config (
      key           TEXT PRIMARY KEY,
      value         TEXT NOT NULL
  );

  -- Discovery log
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

  -- Indexes
  CREATE INDEX IF NOT EXISTS idx_posts_type ON posts(post_type);
  CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(overall_status);
  CREATE INDEX IF NOT EXISTS idx_posts_published ON posts(published_at);
  CREATE INDEX IF NOT EXISTS idx_posts_source ON posts(source_id);
  CREATE INDEX IF NOT EXISTS idx_step_status ON step_statuses(status);
  CREATE INDEX IF NOT EXISTS idx_queue_status ON queue(status);
  ```

`async def migrate_from_json(db: aiosqlite.Connection, json_path: Path) -> int`:
- Reads the JSON catalog file: `json_path` → parse → extract `posts` list
- For each post in the JSON:
  - Insert into `posts` table with `source_id='fuw'`
  - Map JSON fields to columns: `post_id`, `url`, `title`, `created_at` (used as both `created_at` and `published_at` since the catalog only has `created_at`), `post_type`, `has_video`, `has_audio`
  - Handle enriched fields if present: `published_at`, `edited_at`, `duration_seconds`, `embed_url`, `embed_provider`, `thumbnail_url`, `like_count`, `comment_count`, `is_paid`, `min_cents_pledged_to_view`, `tags` (serialize list as JSON string), `discovered_at`, `recording_mb`, `transcript_words`, `output_path`
  - Initialize 7 `step_statuses` rows for each post, all with status `"pending"` by default
  - If the post has `ingested_status == "complete"`: set all 7 step statuses to `"completed"` and set `overall_status = "completed"`
  - If `ingested_status == "failed"`: set overall_status to `"failed"`, set the last applicable step (based on available output — or just the `record` step if no info) to `"failed"`, and preceding completed steps to `"completed"`
  - If `ingested_status == "skipped"`: set all steps to `"skipped"` and `overall_status = "completed"`
  - If no `ingested_status`: all steps stay `"pending"`, overall_status stays `"discovered"`
- Use `INSERT OR IGNORE` to be idempotent (re-running migration doesn't duplicate)
- Return count of posts inserted
- **Important**: The current catalog has **0 posts** with `ingested_status` set — all 1,632 are unprocessed. But the migration must handle the enriched case for when processed posts appear in the catalog.

`async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]`:
- FastAPI dependency that yields a connection from a shared pool/path
- Uses `web.config.DB_PATH`
- Ensures `row_factory = aiosqlite.Row` for dict-like access

**`tests/web/test_database.py`:**
- Use `tmp_path` fixture for isolated test databases
- **test_init_db_creates_tables**: Call `init_db()`, query `sqlite_master` to verify all 5 tables exist (`sources`, `posts`, `step_statuses`, `queue`, `watcher_config`, `discovery_runs`)
- **test_init_db_seeds_fuw_source**: Verify the `fuw` source is inserted with correct name, description, source_type
- **test_init_db_idempotent**: Call `init_db()` twice — no errors, same schema
- **test_migrate_from_json**: Create a fixture JSON file with 5 sample posts (mimicking `patreon_full_catalog.json` format). Migrate. Verify:
  - 5 rows in `posts` table
  - 35 rows in `step_statuses` table (5 posts × 7 steps)
  - All step statuses are `"pending"`
  - All overall_status values are `"discovered"`
  - `source_id` is `"fuw"` for all posts
- **test_migrate_preserves_ingested_status**: Create fixture with posts having `ingested_status`:
  - One post with `"complete"` → all steps `"completed"`, overall_status `"completed"`
  - One post with `"failed"` → check at least one step is `"failed"`
  - One post with `"skipped"` → all steps `"skipped"`, overall_status `"completed"`
  - One post with `null` → all steps `"pending"`, overall_status `"discovered"`
- **test_migrate_idempotent**: Run migration twice with same data — count stays the same (INSERT OR IGNORE)
- **test_migrate_serializes_tags**: Post with `tags: ["finance", "stocks"]` → stored as JSON string in `tags` column

### 5. Create Pydantic Models (`web/models.py`)

- All models use `from pydantic import BaseModel`
- Models to create:

  **`StepStatusResponse`**:
  ```python
  class StepStatusResponse(BaseModel):
      status: str
      started_at: str | None = None
      completed_at: str | None = None
      error: str | None = None
      output_path: str | None = None
      duration_seconds: float | None = None
      attempt: int = 0
  ```

  **`PostSummary`** (compact for list views):
  ```python
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
  ```

  **`PostDetail`** (full post with all fields):
  ```python
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
  ```

  **`QueueEntry`**:
  ```python
  class QueueEntry(BaseModel):
      post_id: str
      title: str
      priority: int
      added_at: str
      status: str
  ```

  **`QueueAddRequest`**:
  ```python
  class QueueAddRequest(BaseModel):
      post_ids: list[str]
      priority: int = 0
  ```

  **`WatcherStatus`**:
  ```python
  class WatcherStatus(BaseModel):
      running: bool
      pid: int | None = None
      cycle: int = 0
      interval_hours: float = 24.0
      last_run: str | None = None
      next_run: str | None = None
      last_result: dict = {}
      total_recorded: int = 0
  ```

  **`WatcherConfigUpdate`**:
  ```python
  class WatcherConfigUpdate(BaseModel):
      interval_hours: float | None = None
      max_per_run: int | None = None
      steps: list[str] | None = None
  ```

  **`AgentHealth`**:
  ```python
  class AgentHealth(BaseModel):
      healthy: bool
      obs_connected: bool
      chrome_available: bool
      disk_ok: bool
      obs_version: str | None = None
      error: str | None = None
  ```

  **`CatalogStats`**:
  ```python
  class CatalogStats(BaseModel):
      total_posts: int
      video_posts: int
      audio_posts: int
      by_status: dict[str, int] = {}
      by_type: dict[str, int] = {}
      by_step: dict[str, dict[str, int]] = {}
  ```

  **`DiscoveryTriggerRequest`**:
  ```python
  class DiscoveryTriggerRequest(BaseModel):
      full_catalog: bool = False
      force: bool = False
  ```

  **`DiscoveryRunResponse`**:
  ```python
  class DiscoveryRunResponse(BaseModel):
      id: int | None = None
      started_at: str
      completed_at: str | None = None
      posts_found: int = 0
      new_posts: int = 0
      source: str = "patreon"
      status: str = "running"
  ```

  **`PipelineRunRequest`**:
  ```python
  class PipelineRunRequest(BaseModel):
      post_ids: list[str]
      steps: list[str] | None = None
  ```

  **`WebSocketEvent`**:
  ```python
  class WebSocketEvent(BaseModel):
      type: str
      data: dict = {}
      timestamp: str
  ```

### 6. Run Validation

Execute all validation commands to confirm the foundation layer is working:

```bash
# Install dependencies
uv sync --extra web

# Verify proto stubs
uv run python -c "from proto import agent_pb2, agent_pb2_grpc; print('Proto OK')"

# Verify lifecycle module
uv run python -c "from web.lifecycle import StepStatus, derive_post_status, PIPELINE_STEPS; print('Lifecycle OK')"

# Verify database module
uv run python -c "from web.database import init_db; print('Database OK')"

# Verify models
uv run python -c "from web.models import PostSummary, PostDetail, CatalogStats, WebSocketEvent; print('Models OK')"

# Run new tests
uv run pytest tests/web/ -v

# Run ALL tests (verify no regressions)
uv run pytest tests/ -v
```

## Testing Strategy

### Unit Tests

- **`tests/web/test_lifecycle.py`** — Pure logic tests, no I/O. Tests every `derive_post_status` path and every `step_can_run` dependency rule. Also verifies `PIPELINE_STEPS` stays in sync with `src/pipeline/runner.STEPS`.
- **`tests/web/test_database.py`** — Uses `tmp_path` for isolated SQLite files. Tests schema creation, JSON migration (including ingested_status mapping), idempotency, source_id correctness, and tags serialization.

### Edge Cases to Cover

- `derive_post_status` with empty dict → `"discovered"` (no steps = all pending by convention)
- `derive_post_status` with subset of steps → still works (function operates on whatever dict is passed)
- Migration of post with `tags: null` vs `tags: []` vs `tags: ["a", "b"]`
- Migration with missing optional fields (e.g., post without `published_at`)
- `step_can_run` with unknown step name → `ValueError`

## Acceptance Criteria

1. `uv sync --extra web` installs without errors
2. `uv run python -c "from proto import agent_pb2, agent_pb2_grpc; print('OK')"` succeeds
3. `uv run python -c "from web.lifecycle import StepStatus, derive_post_status; print('OK')"` succeeds
4. `uv run python -c "from web.database import init_db; print('OK')"` succeeds
5. `uv run python -c "from web.models import PostSummary, CatalogStats; print('OK')"` succeeds
6. `uv run pytest tests/web/ -v` — all tests pass
7. `uv run pytest tests/ -v` — no regressions in existing 303+ tests
8. `proto/agent.proto` matches the full service definition from `specs/media-transcribe-web-app.md` exactly (all 7 RPCs, all message types, all field numbers)
9. `web/database.py` `init_db()` creates 6 tables: `sources`, `posts`, `step_statuses`, `queue`, `watcher_config`, `discovery_runs`
10. `web/database.py` `migrate_from_json()` inserts all 1,632 posts from `data/patreon_full_catalog.json` with `source_id='fuw'` and initializes 11,424 step_status rows (1,632 × 7)
11. `sources` table is seeded with the `fuw` source on init
12. `posts` table has `source_id` column with FK to `sources`
13. `web/models.py` `PostSummary` and `PostDetail` include `source_id: str` field
14. No existing files in `src/` are modified (only `pyproject.toml` changes)

## Validation Commands

Execute these commands to validate the task is complete:

```bash
# Dependencies install
uv sync --extra web

# Proto stubs import
uv run python -c "from proto import agent_pb2, agent_pb2_grpc; print('Proto OK')"

# Lifecycle imports
uv run python -c "from web.lifecycle import StepStatus, derive_post_status, PIPELINE_STEPS, step_can_run; print('Lifecycle OK')"

# Database imports
uv run python -c "from web.database import init_db; print('Database OK')"

# Models import
uv run python -c "from web.models import PostSummary, PostDetail, CatalogStats, WebSocketEvent, AgentHealth; print('Models OK')"

# Config imports
uv run python -c "from web.config import DB_PATH, HOST, PORT, AGENT_HOST; print('Config OK')"

# New tests pass
uv run pytest tests/web/ -v

# No regressions
uv run pytest tests/ -v

# Verify PIPELINE_STEPS matches runner.STEPS
uv run python -c "from web.lifecycle import PIPELINE_STEPS; from src.pipeline.runner import STEPS; assert PIPELINE_STEPS == STEPS, f'{PIPELINE_STEPS} != {STEPS}'; print('Steps match')"

# Verify migration against real catalog (smoke test)
uv run python -c "
import asyncio, tempfile
from pathlib import Path
from web.database import init_db, migrate_from_json
async def test():
    with tempfile.TemporaryDirectory() as d:
        db = await init_db(Path(d) / 'test.db')
        count = await migrate_from_json(db, Path('data/patreon_full_catalog.json'))
        print(f'Migrated {count} posts')
        row = await db.execute('SELECT COUNT(*) FROM step_statuses')
        steps = (await row.fetchone())[0]
        print(f'Step status rows: {steps}')
        await db.close()
asyncio.run(test())
"
```

## Notes

- The `data/patreon_full_catalog.json` currently has 1,632 posts with only 7 basic fields each (no enriched fields, no `ingested_status`). The migration code must still handle enriched fields for when they appear in future catalog updates.
- The `sources` table and `source_id` FK on `posts` is a forward-looking addition for multi-source support (TAC, YouTube, etc.). Only `fuw` is seeded initially.
- Generated proto files (`agent_pb2.py`, `agent_pb2_grpc.py`) should be committed to git so the obs-machine doesn't need `grpcio-tools` installed.
- `web/config.py` imports `CATALOG_PATH` from `src.config` — this cross-package import is intentional since it's the canonical catalog path.
- The `discovery_runs` table includes `source_id` with default `'fuw'` for multi-source future-proofing.
