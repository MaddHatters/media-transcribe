# Plan: Content Discovery and Cataloging System

## Task Description

Build a content discovery and cataloging system for the media-transcribe pipeline. The system intercepts Patreon's internal API responses via Chrome DevTools Protocol network monitoring to build a complete catalog of all content with timestamps, detect new content on a recurring basis, and integrate with the existing recording pipeline via queue file generation.

## Objective

When complete, `uv run cli.py discover` will load the Patreon creator's posts page in Chrome, passively intercept the structured JSON API responses the browser naturally fetches, extract post metadata (titles, timestamps, content types, post IDs), and save a deduplicated catalog to disk. The command will also diff against previous catalogs to identify new posts and optionally generate queue files for the recording pipeline.

## Problem Statement

The pipeline currently requires manually constructing queue files with video URLs. There is no automated way to:
1. Know what content exists or when it was published
2. Detect when new content appears
3. Determine which content has already been recorded vs. what's new

Existing catalog files in `data/` (e.g., `patreon_catalog_firedupwealth.json`, `firedupwealth_all_posts.json`) were created manually and lack proper timestamps — every post has `"date": ""`. The new system solves this by extracting structured metadata from Patreon's own API responses.

## Solution Approach

**Network interception via CDP**: When Chrome loads the Patreon posts page, it makes internal API calls that return structured JSON with exact timestamps, titles, content types, and post IDs. Rather than making additional HTTP requests (which would look bot-like), we intercept these responses via Chrome DevTools Protocol's `Network` domain — the browser does the work, we just read what it fetched.

**Minimal CDPClient changes**: The current `CDPClient._send()` discards CDP event messages while waiting for request-response pairs. Two small additions — an event buffer in `_send()` and a `drain_events()` method — enable network event capture without changing the client's architecture.

**Safety-first design**: Hard-coded rate limits (cooldown between runs, max pages per session, randomized delays between scrolls) ensure the tool behaves like a normal subscriber browsing posts.

## Relevant Files

Use these files to complete the task:

- **`src/cdp.py`** (97 lines) — Add event buffering to `_send()` and a `drain_events()` method. Currently discards CDP events; needs to buffer them for network interception.
- **`src/config.py`** (49 lines) — Add `LOCAL_DATA` constant reference (already exists at line 18: `Path("/home/tuna/repos/media-transcribe/data")`). No changes needed here — `LOCAL_DATA` is already defined.
- **`src/sources/patreon.py`** (118 lines) — Existing Patreon source with `authenticate()` and stealth behavior. Discovery will reuse authentication but is a separate class.
- **`src/sources/base.py`** (35 lines) — `Post` dataclass. Discovery uses its own `DiscoveredPost` dataclass since catalog metadata differs from recording metadata.
- **`src/capture/batch.py`** (216 lines) — `load_queue()` function for queue file format reference. Discovery generates compatible queue files.
- **`cli.py`** (472 lines) — Add `discover` subcommand to `build_parser()` and handler in `main()`.
- **`AGENTS.md`** (199 lines) — Add Content Discovery documentation section.
- **`tests/conftest.py`** — Test configuration (path setup).

### New Files

- **`src/sources/discovery.py`** — `PatreonDiscovery` class with network interception, catalog management, cooldown enforcement
- **`tests/test_discovery.py`** — Tests for all discovery functionality

## Implementation Phases

### Phase 1: Foundation
Add event buffering to `CDPClient` and define the `DiscoveredPost` dataclass and safety constants in the new discovery module. These changes are additive and don't affect existing functionality.

### Phase 2: Core Implementation
Build the `PatreonDiscovery` class with network interception, catalog diffing, and cooldown enforcement. Add the `discover` CLI command with all flags.

### Phase 3: Integration & Polish
Add queue file generation for pipeline integration, write comprehensive tests, and update AGENTS.md documentation.

## Step by Step Tasks

IMPORTANT: Execute every step in order, top to bottom.

### 1. Add CDP Event Buffering

Modify `src/cdp.py` to buffer CDP event messages instead of discarding them:

- Add `self._events: list[dict] = []` to `CDPClient.__init__()` (after `self._msg_id = 0`)
- In `_send()`, when a received message has no matching `id` but has a `"method"` key, append it to `self._events` instead of discarding
- Add `drain_events(method: str | None = None) -> list[dict]` method:
  - If `method` is None, return all buffered events and clear the buffer
  - If `method` is specified, return only events matching that method name and remove them from the buffer
- Add `async def collect_events(self, duration: float) -> int` method:
  - Read from the websocket for `duration` seconds using `asyncio.wait_for` on `self._ws.recv()` in a loop
  - Buffer any event messages (those with `"method"` key) into `self._events`
  - Return count of events collected
  - Catch `asyncio.TimeoutError` to exit cleanly when duration expires

The changes look like this in context:

```python
async def _send(self, method: str, params: dict | None = None) -> dict:
    self._msg_id += 1
    mid = self._msg_id
    await self._ws.send(json.dumps({
        "id": mid, "method": method, "params": params or {},
    }))
    while True:
        resp = json.loads(await self._ws.recv())
        if resp.get("id") == mid:
            return resp
        if "method" in resp:          # <-- new: buffer CDP events
            self._events.append(resp)  # <-- instead of discarding

def drain_events(self, method: str | None = None) -> list[dict]:
    if method is None:
        events = self._events[:]
        self._events.clear()
        return events
    matched = [e for e in self._events if e.get("method") == method]
    self._events = [e for e in self._events if e.get("method") != method]
    return matched

async def collect_events(self, duration: float) -> int:
    deadline = asyncio.get_event_loop().time() + duration
    count = 0
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            break
        try:
            raw = await asyncio.wait_for(self._ws.recv(), timeout=remaining)
            resp = json.loads(raw)
            if "method" in resp:
                self._events.append(resp)
                count += 1
        except asyncio.TimeoutError:
            break
    return count
```

### 2. Create Discovery Module — Constants and Dataclass

Create `src/sources/discovery.py` with the rate-limiting constants and `DiscoveredPost` dataclass:

- Define constants at module level:
  ```python
  DISCOVERY_COOLDOWN_HOURS = 12
  MIN_PAGE_DELAY_SECONDS = 2.0
  MAX_PAGE_DELAY_SECONDS = 5.0
  MAX_PAGES_PER_SESSION = 5
  MAX_SCROLLS_PER_PAGE = 10
  COOLDOWN_FILE = "last_discovery.txt"
  ```
- Define `DiscoveredPost` dataclass:
  ```python
  @dataclass
  class DiscoveredPost:
      post_id: str
      url: str
      title: str
      published_at: str
      post_type: str
      has_video: bool
      collection: str = ""
      player_type: str = "unknown"
  ```
- Imports: `asyncio`, `json`, `logging`, `random`, `dataclasses`, `datetime`, `pathlib`, `typing.TYPE_CHECKING`
- Use `from src.config import LOCAL_DATA` for the default catalog output path

### 3. Implement PatreonDiscovery — Cooldown and Catalog Management

Add the `PatreonDiscovery` class with cooldown checking, catalog diffing, and catalog saving:

```python
class PatreonDiscovery:
    def __init__(self, creator_slug: str = "firedupwealth", cooldown_hours: float = DISCOVERY_COOLDOWN_HOURS):
        self.creator_slug = creator_slug
        self.cooldown_hours = cooldown_hours
        self.posts_url = f"https://www.patreon.com/cw/{creator_slug}/posts"
        self._state_dir = LOCAL_DATA  # catalog/state files live in data/
```

**`check_cooldown(self) -> bool`**:
- Read timestamp from `self._state_dir / COOLDOWN_FILE`
- Parse as ISO format datetime
- Compare against `datetime.now(timezone.utc)` (use UTC consistently)
- Return `True` if enough hours have passed or file doesn't exist
- Log the hours since last run if within cooldown

**`_update_cooldown(self)`**:
- Write current UTC ISO timestamp to `self._state_dir / COOLDOWN_FILE`

**`diff_catalog(self, discovered: list[DiscoveredPost], catalog_path: Path) -> tuple[list[DiscoveredPost], list[DiscoveredPost]]`**:
- Load existing catalog JSON from `catalog_path` if it exists
- Build a set of existing `post_id` values
- New posts = discovered posts whose `post_id` is not in the existing set
- All posts = merge: new posts + existing posts (discovered data takes precedence for posts that appear in both — update titles/timestamps if they changed)
- Return `(new_posts, all_posts)`

**`save_catalog(self, posts: list[DiscoveredPost], path: Path)`**:
- Build catalog dict with structure:
  ```python
  {
      "creator": "Mr. FIRED Up Wealth",
      "creator_slug": self.creator_slug,
      "last_discovery": datetime.now(timezone.utc).isoformat(),
      "total_posts": len(posts),
      "posts": [asdict(p) for p in posts]
  }
  ```
- Write as formatted JSON with `indent=2` and `ensure_ascii=False`
- Ensure parent directory exists with `path.parent.mkdir(parents=True, exist_ok=True)`

### 4. Implement PatreonDiscovery — Network Interception

Add the core `discover()` and `_intercept_posts()` methods:

**`async def discover(self, cdp, full_catalog: bool = False) -> list[DiscoveredPost]`**:
1. Enable network monitoring: `await cdp._send("Network.enable")`
2. Navigate to posts page: `await cdp.navigate(self.posts_url, wait=8.0)`
3. Collect initial events: `await cdp.collect_events(3.0)`
4. If `full_catalog`, scroll to trigger additional API calls:
   - Loop up to `MAX_SCROLLS_PER_PAGE` times per "page" (set of scroll actions), up to `MAX_PAGES_PER_SESSION` pages
   - Each scroll: `await cdp.js("window.scrollBy(0, window.innerHeight)")` with randomized delay (`random.uniform(MIN_PAGE_DELAY_SECONDS, MAX_PAGE_DELAY_SECONDS)`)
   - After each scroll batch, `await cdp.collect_events(2.0)` to capture new API responses
   - Stop scrolling when no new events arrive (page fully loaded)
   - Log each page load with timestamp for audit trail
5. Extract post data from buffered network responses: call `_extract_posts_from_events(cdp)`
6. Disable network monitoring: `await cdp._send("Network.disable")`
7. Update cooldown timestamp
8. Return deduplicated posts sorted by `published_at` descending

**`async def _extract_posts_from_events(self, cdp) -> list[DiscoveredPost]`**:
1. Drain all `Network.responseReceived` events from CDP
2. For each event, check if the response URL contains `/api/posts` or matches Patreon's API patterns (URL contains `patreon.com` and response `mimeType` is `application/json` or similar)
3. For matching responses, call `await cdp._send("Network.getResponseBody", {"requestId": event["params"]["requestId"]})`
4. Parse the response body as JSON
5. Look for the `"data"` array in the response — this contains post objects
6. For each post object in `data`, extract:
   - `post_id` from `data[i]["id"]`
   - `title` from `data[i]["attributes"]["title"]`
   - `published_at` from `data[i]["attributes"]["published_at"]`
   - `post_type` from `data[i]["attributes"]["post_type"]`
   - `url` constructed as `https://www.patreon.com/posts/{post_id}`
   - `has_video` inferred from `post_type` containing `"video"`
   - `player_type` — attempt to detect from response metadata if available, default `"unknown"`
7. Deduplicate by `post_id`
8. Handle errors gracefully: log and skip responses that fail to parse (some network responses won't be API calls)

**Important safety constraints in `discover()`**:
- Track total pages loaded; hard-stop at `MAX_PAGES_PER_SESSION` (5)
- Log every navigation and scroll action with timestamp
- Never make direct HTTP requests — all data comes from CDP event interception

### 5. Implement Queue File Generation

Add a method to generate pipeline-compatible queue files from new video posts:

**`def generate_queue(self, posts: list[DiscoveredPost], output_path: Path) -> int`**:
- Filter to only posts where `has_video is True`
- Convert each to queue format: `{"url": post.url, "filename": post.title}`
- Sanitize filenames using the same logic as `Post.__post_init__()` in `src/sources/base.py`
- Write as JSON array to `output_path`
- Return count of queue entries written

### 6. Add `discover` CLI Command

Modify `cli.py` to add the discover subcommand:

**In `build_parser()`** — add after the `release-info` parser (before `return ap`):
```python
d = sub.add_parser("discover", help="Discover and catalog Patreon content")
d.add_argument("--full-catalog", action="store_true",
    help="Scroll to load all posts (use for initial catalog build)")
d.add_argument("--output", default=None,
    help="Catalog output path (default: data/patreon_catalog.json)")
d.add_argument("--force", action="store_true",
    help="Ignore cooldown timer")
d.add_argument("--queue-new", default=None,
    help="Generate queue file for new video posts at this path")
```

**In `main()`** — add `elif args.command == "discover":` handler:
1. Lazy import: `from src.sources.discovery import PatreonDiscovery`
2. Create `PatreonDiscovery()` instance
3. Check cooldown (unless `--force`):
   ```python
   if not args.force:
       can_run = await disc.check_cooldown()  # needs asyncio.run wrapper
       if not can_run:
           print("Discovery skipped (cooldown active). Use --force to override.")
           return 0
   ```
4. Since discover uses CDP but is NOT a long-running command, run it inline (no backgrounding):
   ```python
   from src.cdp import CDPClient
   from src.sources.patreon import PatreonSource
   
   async def _run_discovery():
       async with CDPClient() as cdp:
           # Authenticate first
           source = PatreonSource()
           if not await source.authenticate(cdp):
               print("Patreon authentication failed")
               return 1
           
           # Discover
           disc = PatreonDiscovery()
           posts = await disc.discover(cdp, full_catalog=args.full_catalog)
           
           # Diff and save catalog
           catalog_path = Path(args.output) if args.output else LOCAL_DATA / "patreon_catalog.json"
           new_posts, all_posts = disc.diff_catalog(posts, catalog_path)
           disc.save_catalog(all_posts, catalog_path)
           
           # Print summary
           video_count = sum(1 for p in all_posts if p.has_video)
           print(f"Discovery complete:")
           print(f"  Total posts found: {len(all_posts)}")
           print(f"  With video: {video_count}")
           print(f"  New since last check: {len(new_posts)}")
           if new_posts:
               print(f"  New posts:")
               for p in new_posts:
                   vflag = "(video)" if p.has_video else "(text)"
                   print(f"    - {p.published_at[:10]}: {p.title} {vflag}")
           print(f"  Catalog saved to: {catalog_path}")
           
           # Generate queue if requested
           if args.queue_new and new_posts:
               queue_path = Path(args.queue_new)
               count = disc.generate_queue(new_posts, queue_path)
               print(f"  Queue file: {queue_path} ({count} video(s))")
           
           return 0
   
   import asyncio
   return asyncio.run(_run_discovery())
   ```

**Note**: `discover` is NOT added to `LONG_RUNNING_COMMANDS` — it runs inline in the foreground. A full catalog scan with 5 pages takes ~30 seconds max.

### 7. Write Tests

Create `tests/test_discovery.py` with comprehensive tests:

**Fixtures:**
```python
@pytest.fixture
def state_dir(tmp_path):
    return tmp_path

@pytest.fixture
def disc(state_dir):
    d = PatreonDiscovery(creator_slug="firedupwealth")
    d._state_dir = state_dir
    return d
```

**Cooldown tests:**
- `test_cooldown_no_file` — returns True when no cooldown file exists
- `test_cooldown_expired` — returns True when file timestamp is older than `cooldown_hours`
- `test_cooldown_active` — returns False when file timestamp is recent
- `test_cooldown_force_irrelevant` — verify that `check_cooldown()` is pure (force is handled by CLI, not the class)

**Catalog diff tests:**
- `test_diff_empty_catalog` — all discovered posts are new when catalog doesn't exist
- `test_diff_no_new_posts` — no new posts when all discovered posts are in catalog
- `test_diff_some_new` — correctly identifies subset of new posts
- `test_diff_updates_existing` — posts appearing in both get updated metadata from discovery

**Catalog save/load roundtrip:**
- `test_save_catalog` — saves valid JSON with expected structure
- `test_save_load_roundtrip` — save then load produces same data

**DiscoveredPost dataclass:**
- `test_discovered_post_defaults` — verify default field values
- `test_discovered_post_has_video` — verify has_video inference

**Queue generation:**
- `test_generate_queue_video_only` — only video posts get queued
- `test_generate_queue_empty` — no video posts produces empty queue
- `test_generate_queue_format` — output matches pipeline queue format (`url` + `filename` keys)

**Rate limiting constants:**
- `test_constants_reasonable` — cooldown >= 1h, delays > 0, max_pages <= 10

**Network interception (mock CDP):**
- `test_extract_posts_from_api_response` — mock `Network.responseReceived` events and `Network.getResponseBody` response; verify correct post extraction
- `test_extract_skips_non_api_responses` — non-API network events are ignored
- `test_extract_handles_malformed_json` — bad JSON in response body is skipped gracefully
- `test_discover_enables_and_disables_network` — verify `Network.enable` called before navigation and `Network.disable` after
- `test_discover_updates_cooldown` — cooldown file is written after successful discovery
- `test_discover_respects_max_pages` — scrolling stops at `MAX_PAGES_PER_SESSION`

**CDP event buffering tests** (add to `tests/test_cdp.py`):
- `test_send_buffers_events` — events received during `_send()` are stored in `_events`
- `test_drain_events_all` — `drain_events()` with no filter returns all and clears
- `test_drain_events_filtered` — `drain_events("Network.responseReceived")` returns only matching events
- `test_collect_events_duration` — `collect_events()` reads for specified duration

**Mock CDP helper for discovery tests:**
```python
def _make_cdp_with_network(api_responses: list[dict]) -> AsyncMock:
    """Create a mock CDPClient that simulates network interception."""
    cdp = AsyncMock()
    cdp._events = []
    cdp._msg_id = 0
    
    # Simulate buffered Network.responseReceived events
    for i, resp_data in enumerate(api_responses):
        cdp._events.append({
            "method": "Network.responseReceived",
            "params": {
                "requestId": f"req-{i}",
                "response": {
                    "url": "https://www.patreon.com/api/posts?...",
                    "mimeType": "application/json",
                },
            },
        })
    
    # Mock _send for Network.getResponseBody
    async def mock_send(method, params=None):
        if method == "Network.getResponseBody":
            req_id = params["requestId"]
            idx = int(req_id.split("-")[1])
            return {"result": {"body": json.dumps(api_responses[idx])}}
        return {"result": {}}
    
    cdp._send = AsyncMock(side_effect=mock_send)
    cdp.drain_events = CDPClient.drain_events.__get__(cdp)
    return cdp
```

### 8. Update AGENTS.md

Add a "Content Discovery" section after the "Queue file format" section:

```markdown
### Content Discovery

Discover and catalog Patreon content via CDP network interception:

```bash
# Check for new posts (default — first page only):
uv run cli.py discover

# Build initial full catalog (scrolls to load all posts):
uv run cli.py discover --full-catalog --output data/patreon_catalog.json

# Force discovery (ignore 12-hour cooldown):
uv run cli.py discover --force

# Discover and generate queue for new videos:
uv run cli.py discover --queue-new data/new_queue.json
# Then record:
uv run cli.py pipeline --queue data/new_queue.json
```

**Safety guarantees:**
- 12-hour cooldown between discovery runs (override with `--force`)
- Max 5 page loads per session
- Random 2–5 second delays between scrolls
- No direct HTTP requests — all data from browser's own API calls via CDP
- Every page load logged with timestamp for audit

**Catalog location:** `data/patreon_catalog.json` (default)
```

### 9. Validate

- Run `uv run pytest tests/test_discovery.py -v` — all discovery tests pass
- Run `uv run pytest tests/test_cdp.py -v` — CDP event buffering tests pass
- Run `uv run pytest` — full suite passes (no regressions)
- Run `uv run python -m py_compile src/sources/discovery.py` — compiles
- Run `uv run python -m py_compile cli.py` — compiles
- Verify `uv run cli.py discover --help` prints usage with all flags

## Testing Strategy

**Unit tests** cover all pure logic (cooldown checking, catalog diffing, queue generation, post extraction from API JSON) without requiring a browser or network.

**CDP interaction tests** use mocked CDPClient instances that simulate buffered network events and `Network.getResponseBody` responses. This validates the interception pipeline end-to-end in isolation.

**Integration boundary**: The actual CDP WebSocket connection and Patreon page loads are NOT tested automatically — these are manual, on-machine validation only. The test boundary stops at the CDPClient mock layer.

**Test patterns**: Follow existing conventions — `pytest-asyncio` with `asyncio_mode = "auto"`, `tmp_path` for file system tests, `AsyncMock` for CDP, helper factories for complex mock objects.

## Acceptance Criteria

- `uv run cli.py discover --help` shows all flags (--full-catalog, --output, --force, --queue-new)
- Cooldown is enforced: running twice within 12 hours without `--force` prints skip message
- `--force` overrides cooldown
- `--full-catalog` scrolls to load additional pages (up to MAX_PAGES_PER_SESSION)
- Catalog JSON has correct structure: creator, creator_slug, last_discovery, total_posts, posts array
- Each post in catalog has: post_id, url, title, published_at, post_type, has_video, player_type
- `--queue-new` generates a pipeline-compatible queue file with only new video posts
- All rate-limiting constants are enforced (delays, max pages, max scrolls)
- Every page load is logged with a timestamp
- No direct HTTP requests to Patreon (all through CDP)
- `uv run pytest` — full test suite passes with no regressions
- AGENTS.md updated with Content Discovery section

## Validation Commands

Execute these commands to validate the task is complete:

- `uv run python -m py_compile src/sources/discovery.py` — Discovery module compiles
- `uv run python -m py_compile src/cdp.py` — CDP changes compile
- `uv run python -m py_compile cli.py` — CLI changes compile
- `uv run pytest tests/test_discovery.py -v` — All discovery tests pass
- `uv run pytest tests/test_cdp.py -v` — CDP event buffering tests pass
- `uv run pytest` — Full test suite passes (no regressions)
- `uv run cli.py discover --help` — Shows usage with all flags

## Notes

- The `PatreonSource.authenticate()` method in `src/sources/patreon.py` already handles login. Discovery reuses it before starting network interception.
- The CDPClient event buffering change is backward-compatible — existing code never reads `_events`, so buffering events that were previously discarded has no side effects.
- Patreon's internal API response format may change. The `_extract_posts_from_events` method should handle missing fields gracefully and log warnings for unexpected structures rather than crashing.
- The `LOCAL_DATA` constant in `src/config.py` (line 18) already points to the repo's `data/` directory — no new config constants needed.
- Discovery runs on the obs-machine (where Chrome + CDP are available), not devbox-01. But tests run on devbox-01 with mocked CDP.
- Existing catalog files in `data/` use a different schema (no `post_id`, different field names). The new catalog format is intentionally different and does not attempt backward compatibility with the old files — they were manually created one-offs.
