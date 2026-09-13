# Plan: Refactor Discovery to Use Patreon Public JSON API

## Task Description

Replace the CDP/browser-based content discovery system (`src/sources/discovery.py`) with a simple HTTP client that calls Patreon's public JSON API directly. The API requires zero authentication and returns structured post metadata including titles, timestamps, content types, and pagination cursors. This eliminates the need for Chrome, CDP, WebSockets, Patreon auth, and the obs-machine entirely — discovery becomes a lightweight HTTP operation that runs on devbox-01.

## Objective

When complete, `uv run cli.py discover` will fetch posts from `https://www.patreon.com/api/posts` via `urllib.request`, parse the JSON:API response, and save a catalog to disk. No browser, no CDP, no auth, no obs-machine. The command runs in under 5 seconds for a single page fetch and under 2 minutes for a full catalog of ~2000 posts.

## Problem Statement

The current discovery system requires:
- Chrome running with CDP on the obs-machine
- Patreon session authentication via Windows Credential Manager
- Network interception via CDP's `Network` domain
- Async code (`asyncio`, `CDPClient`, `PatreonSource`)
- The obs-machine to be online and reachable

All of this is unnecessary. Patreon's internal API at `/api/posts` is publicly accessible with no auth. A simple `curl` with the campaign ID returns full post metadata. This refactor replaces ~220 lines of async CDP interception with ~120 lines of synchronous HTTP calls.

## Solution Approach

**Direct HTTP via `urllib.request`**: Use Python's built-in HTTP library to call the Patreon JSON:API endpoint. No external dependencies needed. The API supports filtering by campaign ID, media type, and pagination via cursors.

**Synchronous, not async**: The new discovery module is entirely synchronous — no `asyncio.run()` wrapper needed in the CLI handler. This simplifies the code and makes testing trivial.

**Runs on devbox-01**: Since no browser is needed, discovery runs locally without SSH to the obs-machine. The watcher's `_discover()` method also simplifies — no CDP context manager, no auth.

**Campaign ID, not creator slug**: The API uses numeric campaign IDs (`5008493` for Mr. FIRED Up Wealth), not URL slugs.

## Relevant Files

Use these files to complete the task:

- **`src/sources/discovery.py`** (220 lines) — Complete rewrite. Replace CDP-based `PatreonDiscovery` with HTTP-based client using `urllib.request`.
- **`cli.py`** (608 lines) — Rewrite `discover` command handler (remove asyncio, CDP, auth). Add new flags: `--video-only`, `--all-types`, `--campaign-id`. Remove `asyncio.run()` wrapper.
- **`src/pipeline/watcher.py`** (209 lines) — Update `_discover()` method to use new `PatreonDiscovery.fetch_posts()` instead of CDP. Remove CDP/auth imports.
- **`tests/test_discovery.py`** (368 lines) — Complete rewrite. Replace CDP mock infrastructure with `urllib.request` mocking. Test HTTP fetching, pagination, and API response parsing.
- **`tests/test_watcher.py`** (372 lines) — Verify watcher tests still pass after `_discover()` changes.
- **`AGENTS.md`** (246 lines) — Replace CDP-based discovery docs with API-based docs. Note that discover now runs on devbox-01.

### New Files

- **`tests/fixtures/patreon_api_response.json`** — Minimal fixture of the actual Patreon API response format, used by discovery tests.

## Implementation Phases

### Phase 1: Foundation
Create the test fixture and rewrite `src/sources/discovery.py` from scratch with the new HTTP-based `PatreonDiscovery` class. This is a clean replacement — no incremental changes to the old code.

### Phase 2: Core Implementation
Rewrite the `discover` CLI handler to use the new synchronous API. Update the watcher's `_discover()` method to drop CDP dependency. Rewrite all discovery tests.

### Phase 3: Integration & Polish
Run the full test suite, verify CLI help output, and update AGENTS.md documentation.

## Step by Step Tasks

IMPORTANT: Execute every step in order, top to bottom.

### 1. Create Test Fixture

Create `tests/fixtures/patreon_api_response.json` with a minimal but realistic fixture of the Patreon API response. This is the shape returned by `https://www.patreon.com/api/posts?filter[campaign_id]=5008493&sort=-published_at&page[count]=50`:

```json
{
  "data": [
    {
      "id": "119811238",
      "attributes": {
        "title": "Masterclass 19 - Munger Mental Models",
        "created_at": "2025-01-15T18:30:00.000+00:00",
        "post_type": "video_external_file",
        "patreon_url": "/posts/masterclass-19-119811238",
        "published_at": "2025-01-15T18:30:00.000+00:00"
      },
      "type": "post"
    },
    {
      "id": "119500001",
      "attributes": {
        "title": "Weekly Market Recap - Jan 10",
        "created_at": "2025-01-10T12:00:00.000+00:00",
        "post_type": "video_embed",
        "patreon_url": "/posts/weekly-market-recap-119500001",
        "published_at": "2025-01-10T12:00:00.000+00:00"
      },
      "type": "post"
    },
    {
      "id": "119200002",
      "attributes": {
        "title": "Community Q&A Thread",
        "created_at": "2025-01-05T09:00:00.000+00:00",
        "post_type": "text_only",
        "patreon_url": "/posts/community-qa-119200002",
        "published_at": "2025-01-05T09:00:00.000+00:00"
      },
      "type": "post"
    },
    {
      "id": "118900003",
      "attributes": {
        "title": "Podcast Episode 42 - Dividend Growth",
        "created_at": "2024-12-28T15:00:00.000+00:00",
        "post_type": "podcast",
        "patreon_url": "/posts/podcast-ep-42-118900003",
        "published_at": "2024-12-28T15:00:00.000+00:00"
      },
      "type": "post"
    }
  ],
  "meta": {
    "pagination": {
      "total": 1994,
      "cursors": {
        "next": "eyJwIjoiMjAyNC0xMi0yOFQxNTowMDowMC4wMDBaIn0="
      }
    }
  }
}
```

- Include at least 4 posts with different `post_type` values: `video_external_file`, `video_embed`, `text_only`, `podcast`
- Include `meta.pagination.total` and `meta.pagination.cursors.next` for pagination testing
- Keep it minimal — only fields the code actually uses

### 2. Rewrite src/sources/discovery.py

Replace the entire file. The new module has ZERO dependency on `src/cdp`, Chrome, websockets, asyncio, or the obs-machine.

**Module-level constants:**
```python
PATREON_API = "https://www.patreon.com/api/posts"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
PAGE_DELAY_SECONDS = 1.0
MAX_PAGES = 50
COOLDOWN_HOURS = 12
```

**`DiscoveredPost` dataclass:**
```python
@dataclass
class DiscoveredPost:
    post_id: str
    url: str
    title: str
    created_at: str           # ISO format
    post_type: str            # video_external_file, video_embed, podcast, etc.
    has_video: bool
    recorded: bool = False
    recording_date: Optional[str] = None
```

Key differences from the old dataclass:
- `created_at` replaces `published_at` (matches API field name)
- Drops `collection` and `player_type` (not relevant without browser)
- Adds `recorded` and `recording_date` for tracking pipeline state

**`PatreonDiscovery` class methods:**

- `__init__(self, campaign_id: str = "5008493", cooldown_hours: float = COOLDOWN_HOURS)` — Campaign ID replaces creator slug.

- `fetch_posts(self, media_type=None, max_pages=1, page_size=50) -> list[DiscoveredPost]` — Core method. Builds URL with query params, makes HTTP request via `urllib.request.Request`/`urlopen`, parses JSON:API response. Handles pagination via `meta.pagination.cursors.next`. Sleeps `PAGE_DELAY_SECONDS` between pages. Returns list of `DiscoveredPost`.

- `check_cooldown(self, state_dir: Path) -> bool` — Same logic as before. Reads `last_discovery.txt` from `state_dir`, compares against `cooldown_hours`. Returns `True` if enough time passed or file missing.

- `update_cooldown(self, state_dir: Path)` — Writes current ISO timestamp to `state_dir / "last_discovery.txt"`.

- `diff_catalog(self, discovered: list[DiscoveredPost], catalog_path: Path) -> list[DiscoveredPost]` — Simplified. Loads existing catalog, builds set of known `post_id`s, returns only posts not in the set. Does NOT return merged list — caller handles merge if needed.

- `save_catalog(self, posts: list[DiscoveredPost], path: Path)` — Saves catalog JSON with structure: `creator`, `campaign_id`, `last_discovery`, `total_posts`, `video_posts`, `posts` (sorted by `created_at` desc).

**Critical implementation details:**
- Use `urllib.request` only — no `requests` library, no external dependency
- URL-encode query params manually (no `urllib.parse.urlencode` needed since params have no special chars except brackets which are passed as-is)
- Set `Accept: application/vnd.api+json` header
- Set `User-Agent` header
- `timeout=30` on `urlopen`
- `has_video` is True when `post_type in ("video_external_file", "video_embed")`
- `cooldown_hours` parameter moves from `__init__` to being used by `check_cooldown` — the `state_dir` is passed by the caller (CLI or watcher), not stored on the instance

### 3. Rewrite the discover CLI Command

**Update `build_parser()` — replace existing discover parser:**
```python
d = sub.add_parser("discover", help="Discover content from Patreon")
d.add_argument("--full-catalog", action="store_true",
    help="Fetch all posts (paginate through entire history)")
d.add_argument("--video-only", action="store_true", default=True,
    help="Only discover video posts (default: True)")
d.add_argument("--all-types", action="store_true",
    help="Discover all post types, not just video")
d.add_argument("--output", default="data/patreon_catalog.json",
    help="Catalog output path")
d.add_argument("--queue-new", default=None,
    help="Write new (unrecorded) video posts to a queue file")
d.add_argument("--force", action="store_true",
    help="Ignore cooldown timer")
d.add_argument("--campaign-id", default="5008493",
    help="Patreon campaign ID (default: Mr. FIRED Up Wealth)")
```

**Rewrite `elif args.command == "discover":` handler:**
- Remove the `async def _run_discovery()` wrapper and `asyncio.run()` call
- Remove imports of `CDPClient`, `PatreonSource`, `src.config.LOCAL_DATA`
- Make it fully synchronous:

```python
elif args.command == "discover":
    import json as json_mod
    from src.sources.discovery import PatreonDiscovery

    discovery = PatreonDiscovery(campaign_id=args.campaign_id)

    if args.full_catalog and not args.force:
        state_dir = Path("data")
        if not discovery.check_cooldown(state_dir):
            print("Cooldown active. Use --force to override.")
            return 0

    media_type = None if args.all_types else "video"
    max_pages = MAX_PAGES if args.full_catalog else 1

    label = "all" if args.full_catalog else "latest"
    type_label = media_type or "all"
    print(f"Discovering {label} {type_label} posts...")
    posts = discovery.fetch_posts(media_type=media_type, max_pages=max_pages)

    catalog_path = Path(args.output)
    new_posts = discovery.diff_catalog(posts, catalog_path)

    # Merge with existing catalog if present
    if catalog_path.exists():
        existing = json_mod.loads(catalog_path.read_text(encoding="utf-8"))
        existing_by_id = {p["post_id"]: p for p in existing.get("posts", [])}
        for p in posts:
            existing_by_id[p.post_id] = None  # mark as discovered
        # Build merged list: discovered posts take precedence
        from dataclasses import asdict
        discovered_by_id = {p.post_id: p for p in posts}
        all_posts = list(discovered_by_id.values())
        for pid, pdata in existing_by_id.items():
            if pid not in discovered_by_id and pdata is not None:
                all_posts.append(DiscoveredPost(**pdata))
    else:
        all_posts = posts

    discovery.save_catalog(all_posts, catalog_path)

    if args.full_catalog:
        discovery.update_cooldown(Path("data"))

    video_count = sum(1 for p in posts if p.has_video)
    print(f"\nDiscovery complete:")
    print(f"  Total found: {len(posts)}")
    print(f"  Video posts: {video_count}")
    print(f"  New: {len(new_posts)}")
    if new_posts:
        print(f"\n  New posts:")
        for p in new_posts[:10]:
            print(f"    {p.created_at[:10]}  {p.title[:70]}")

    if args.queue_new and new_posts:
        video_posts = [p for p in new_posts if p.has_video]
        bad = '<>:"/\\|?*'
        queue = []
        for p in video_posts:
            cleaned = "".join("_" if c in bad else c for c in p.title).strip()
            filename = cleaned if cleaned.strip("_ ") else "episode"
            queue.append({"url": p.url, "filename": filename})
        Path(args.queue_new).parent.mkdir(parents=True, exist_ok=True)
        Path(args.queue_new).write_text(
            json_mod.dumps(queue, indent=2), encoding="utf-8")
        print(f"\n  Queue written: {len(queue)} videos to {args.queue_new}")
```

**Important**: `discover` must NOT be added to `LONG_RUNNING_COMMANDS`. It runs inline — a single page fetch takes <2 seconds, full catalog <2 minutes.

### 4. Update the Watcher's _discover() Method

Rewrite `ContentWatcher._discover()` in `src/pipeline/watcher.py` to use the new HTTP-based discovery instead of CDP:

**Before (remove):**
```python
async def _discover(self) -> list[DiscoveredPost]:
    from src.sources.discovery import PatreonDiscovery
    from src.cdp import CDPClient
    from src.sources.patreon import PatreonSource
    from src.config import LOCAL_DATA

    discovery = PatreonDiscovery(cooldown_hours=0)
    catalog_path = LOCAL_DATA / "patreon_catalog.json"

    async with CDPClient() as cdp:
        source = PatreonSource()
        if not await source.authenticate(cdp):
            log.error("[watch] Patreon authentication failed")
            return []

        all_posts = await discovery.discover(cdp, full_catalog=False)
        new_posts, merged = discovery.diff_catalog(all_posts, catalog_path)
        discovery.save_catalog(merged, catalog_path)

    video_posts = [p for p in new_posts if p.has_video]
    if video_posts:
        log.info("[watch] Found %d new video(s)", len(video_posts))
    return video_posts
```

**After (replace with):**
```python
async def _discover(self) -> list[DiscoveredPost]:
    from src.sources.discovery import PatreonDiscovery
    from src.config import LOCAL_DATA

    discovery = PatreonDiscovery(cooldown_hours=0)
    catalog_path = LOCAL_DATA / "patreon_catalog.json"

    all_posts = discovery.fetch_posts(media_type="video", max_pages=1)
    new_posts = discovery.diff_catalog(all_posts, catalog_path)
    discovery.save_catalog(all_posts, catalog_path)

    if new_posts:
        log.info("[watch] Found %d new video(s)", len(new_posts))
    return new_posts
```

Key changes:
- Remove imports: `CDPClient`, `PatreonSource`
- Remove `async with CDPClient() as cdp:` context manager
- Remove authentication step
- Call `fetch_posts()` (sync) instead of `discover()` (async)
- Use simplified `diff_catalog()` that returns just new posts
- The method stays `async` because the watcher's `run_forever()` loop is async, but the discovery call itself is synchronous (blocking call inside async context is fine here — it takes <2 seconds)

### 5. Rewrite tests/test_discovery.py

Complete rewrite. Remove all CDP mock infrastructure. Test the HTTP-based discovery with `urllib.request` mocking.

**Fixtures:**
```python
@pytest.fixture
def disc():
    return PatreonDiscovery(campaign_id="5008493")

@pytest.fixture
def fixture_response():
    fixture_path = Path(__file__).parent / "fixtures" / "patreon_api_response.json"
    return json.loads(fixture_path.read_text())
```

**Tests to write (each as a separate test function):**

1. **`test_discovered_post_defaults`** — DiscoveredPost has `recorded=False` and `recording_date=None` by default
2. **`test_discovered_post_has_video_for_video_types`** — `video_external_file` and `video_embed` both set `has_video=True`
3. **`test_discovered_post_has_video_false_for_non_video`** — `text_only`, `podcast` set `has_video=False`
4. **`test_fetch_posts_parses_response`** — Mock `urllib.request.urlopen` to return fixture JSON. Verify correct number of posts, correct fields extracted.
5. **`test_fetch_posts_pagination`** — Mock two pages: first returns cursor, second returns no cursor. Verify both pages' posts are returned.
6. **`test_fetch_posts_media_type_filter`** — Verify the `filter[media_types]` query param is included when `media_type` is set.
7. **`test_fetch_posts_no_media_type_filter`** — Verify no `filter[media_types]` param when `media_type=None`.
8. **`test_fetch_posts_respects_max_pages`** — With `max_pages=1`, only one HTTP request is made even if cursor is returned.
9. **`test_fetch_posts_page_delay`** — Verify `time.sleep(PAGE_DELAY_SECONDS)` is called between paginated requests (mock `time.sleep`).
10. **`test_check_cooldown_no_file`** — Returns True when no cooldown file exists.
11. **`test_check_cooldown_expired`** — Returns True when timestamp is older than cooldown hours.
12. **`test_check_cooldown_active`** — Returns False when timestamp is recent.
13. **`test_update_cooldown_writes_file`** — Creates the file with ISO timestamp.
14. **`test_diff_catalog_no_existing`** — All posts are new when catalog doesn't exist.
15. **`test_diff_catalog_some_new`** — Correctly identifies new posts vs known.
16. **`test_diff_catalog_none_new`** — Returns empty list when all posts are known.
17. **`test_save_catalog_structure`** — Saved JSON has `creator`, `campaign_id`, `last_discovery`, `total_posts`, `video_posts`, `posts`.
18. **`test_save_catalog_sorted_by_date`** — Posts in catalog are sorted by `created_at` descending.
19. **`test_save_catalog_roundtrip`** — Save and reload produces valid DiscoveredPost objects.
20. **`test_save_catalog_video_count`** — `video_posts` field matches actual count.
21. **`test_constants_reasonable`** — `COOLDOWN_HOURS >= 1`, `PAGE_DELAY_SECONDS > 0`, `MAX_PAGES <= 100`.

**Mocking strategy for HTTP tests:**
Use `unittest.mock.patch` on `urllib.request.urlopen`. Create a mock response object with a context manager (`__enter__`/`__exit__`) that has a `.read()` method returning the fixture JSON bytes. Example:

```python
def _mock_urlopen(response_data):
    mock_resp = MagicMock()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = json.dumps(response_data).encode()
    return mock_resp
```

### 6. Verify Watcher Tests

Run `tests/test_watcher.py` and verify all tests pass. The watcher tests mock `_discover()` at the method level, so the internal change from CDP to HTTP should not affect them. However, check:
- The `DiscoveredPost` import still works (field names changed from `published_at` to `created_at`)
- The test fixtures create `DiscoveredPost` objects with the new field names

Update `DiscoveredPost` construction in `test_watcher.py` — change `published_at` to `created_at` in all test factories.

### 7. Update AGENTS.md

Replace the "Content Discovery" section (lines 177-205) with:

```markdown
### Content Discovery

Discover uses Patreon's public JSON API (no auth needed). Runs on devbox-01.

```bash
# Check for new video posts (1 API request, no cooldown):
uv run cli.py discover

# Full catalog of all ~2000 posts (paginated, cooldown enforced):
uv run cli.py discover --full-catalog

# Discover and create a recording queue:
uv run cli.py discover --queue-new data/new_queue.json

# Then record on obs-machine:
scp data/new_queue.json Matt@100.66.194.100:C:/Users/Matt/transcribe/
ssh Matt@100.66.194.100 "cd C:\Users\Matt\transcribe; uv run cli.py pipeline --queue new_queue.json"
```

**Catalog location:** `data/patreon_catalog.json` (default)
```

Also update the "Project Structure" section if `src/sources/discovery.py` is mentioned in the tree. And update the "Tooling" section — remove "websockets — CDP communication" note if it's now only used by other modules (check if `src/cdp.py` is still used by `record`, `pipeline`, etc. before removing).

### 8. Validate

- Run `uv run python -m py_compile src/sources/discovery.py` — compiles
- Run `uv run python -m py_compile cli.py` — compiles
- Run `uv run python -m py_compile src/pipeline/watcher.py` — compiles
- Run `uv run pytest tests/test_discovery.py -v` — all new tests pass
- Run `uv run pytest tests/test_watcher.py -v` — watcher tests pass
- Run `uv run pytest` — full suite passes with no regressions
- Run `uv run cli.py discover --help` — shows new flags (--video-only, --all-types, --campaign-id, --full-catalog, --output, --queue-new, --force)

## Testing Strategy

**Unit tests** cover all pure logic: HTTP response parsing, pagination, cooldown, catalog diffing, catalog saving, and DiscoveredPost dataclass behavior. All HTTP calls are mocked via `unittest.mock.patch("urllib.request.urlopen")`.

**Test fixture**: A real-shaped API response in `tests/fixtures/patreon_api_response.json` ensures the parser handles the actual Patreon response format, not a simplified mock.

**Watcher tests**: Existing watcher tests mock at the `_discover()` method level and should pass without changes (except updating `DiscoveredPost` field names). This validates that the watcher integration is not broken.

**No integration tests**: No tests make real HTTP calls to Patreon. Manual validation can be done with `uv run cli.py discover` on devbox-01.

## Acceptance Criteria

- `uv run cli.py discover --help` shows all flags: `--full-catalog`, `--video-only`, `--all-types`, `--output`, `--queue-new`, `--force`, `--campaign-id`
- `uv run cli.py discover` makes exactly 1 HTTP request (no browser, no auth)
- `uv run cli.py discover --full-catalog` paginates through all posts with 1-second delays between pages
- Cooldown enforced only for `--full-catalog`, overridable with `--force`
- Catalog JSON has correct structure: `creator`, `campaign_id`, `last_discovery`, `total_posts`, `video_posts`, `posts`
- Each post has: `post_id`, `url`, `title`, `created_at`, `post_type`, `has_video`, `recorded`, `recording_date`
- `--queue-new` generates a pipeline-compatible queue file with only new video posts
- `discover` is NOT in `LONG_RUNNING_COMMANDS` — runs inline, no backgrounding
- `src/sources/discovery.py` has ZERO imports from `src.cdp`, `asyncio`, `websockets`
- Watcher's `_discover()` no longer uses CDP or auth
- `uv run pytest` — full test suite passes with no regressions
- AGENTS.md updated with API-based discovery docs

## Validation Commands

Execute these commands to validate the task is complete:

- `uv run python -m py_compile src/sources/discovery.py` — Discovery module compiles
- `uv run python -m py_compile cli.py` — CLI changes compile
- `uv run python -m py_compile src/pipeline/watcher.py` — Watcher changes compile
- `uv run pytest tests/test_discovery.py -v` — All discovery tests pass
- `uv run pytest tests/test_watcher.py -v` — Watcher tests pass (no regressions)
- `uv run pytest` — Full test suite passes
- `uv run cli.py discover --help` — Shows usage with all new flags
- `grep -c "cdp\|CDPClient\|asyncio" src/sources/discovery.py` — Should output 0 (no CDP/async references)

## Notes

- **No migration of existing catalogs**: The `DiscoveredPost` dataclass field names change (`published_at` → `created_at`, drop `collection`/`player_type`, add `recorded`/`recording_date`). Existing `data/patreon_catalog.json` will be overwritten on next discovery run — this is fine since the API returns the full dataset.
- **`src/cdp.py` is NOT removed**: Other commands (record, pipeline, preflight) still use CDP for browser control. Only discovery drops the CDP dependency.
- **Watcher still runs on obs-machine**: Even though discovery no longer needs CDP, the watcher's `_run_pipeline()` still needs OBS/Chrome for recording. The discovery step inside the watcher is now a simple HTTP call, but the overall watcher still runs on obs-machine for the pipeline steps.
- **Rate limiting**: 1-second delay between paginated requests, max 50 pages (2500 posts). Full catalog is cooldown-gated at 12 hours. Single-page fetch (default) has no cooldown.
- **Campaign ID `5008493`**: This is Mr. FIRED Up Wealth's campaign. The `--campaign-id` flag makes it configurable for future use with other creators.
- **`urllib.request` not `requests`**: No external HTTP dependency. `urllib.request` is in the Python standard library.
