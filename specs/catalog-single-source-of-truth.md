# Plan: Catalog as Single Source of Truth (Phase 1)

## Task Description
Make the catalog file (`data/patreon_catalog_firedupwealth.json`) the single source of truth for the media-transcribe pipeline. Currently the pipeline uses ad-hoc queue files (`conf_final_queue.json`) and a `seen_urls.txt` file for tracking. The catalog files in `data/` have `recorded: false` on everything and are never updated after ingestion. This plan unifies discovery, pipeline input, and ingestion tracking into one catalog-centric workflow.

## Objective
When this plan is complete:
1. The catalog schema tracks full post lifecycle (discovery through ingestion)
2. A daily refresh command (`catalog-refresh`) updates the catalog from the Patreon public API
3. The pipeline reads directly from the catalog (`--from-catalog`) instead of manual queue files
4. The pipeline writes ingestion results back to the catalog after each post
5. Existing recordings are reflected in the catalog via a one-time migration
6. Non-video post types are gracefully skipped (not treated as errors)

## Problem Statement
The pipeline has three disconnected tracking mechanisms that drift apart:
- **Queue files** — manually created JSON arrays of `{url, filename}` pairs
- **`seen_urls.txt`** — a flat file on the obs-machine tracking recorded URLs
- **Catalog files** — discovery output with `recorded: false` that's never updated

This creates operational friction: you have to manually build queue files, cross-reference `seen_urls.txt`, and the catalog gives no visibility into what's been ingested. The catalog should own the full lifecycle.

## Solution Approach
1. **Extend the `DiscoveredPost` dataclass** with ingestion lifecycle fields (`ingested_at`, `ingested_status`, etc.) and create a `CatalogManager` class that owns atomic read/write/merge of the catalog file.
2. **Add `catalog-refresh` CLI command** — a thin wrapper around the existing `PatreonDiscovery.fetch_posts()` that merges new posts into the catalog while preserving existing ingestion status.
3. **Add `--from-catalog` to the `pipeline` command** — reads the catalog, filters for unprocessed posts, and feeds them to the existing `Pipeline.run()` flow. After each post completes/fails, the `CatalogManager` updates the entry in-place and writes the file.
4. **One-time migration script** — reads `seen_urls.txt` and recording directories, backfills `ingested_status="complete"` for known recordings.

## Relevant Files

### Existing files to modify
- `src/sources/discovery.py` — `DiscoveredPost` dataclass gets new fields; `PatreonDiscovery.save_catalog()` updated for new schema
- `src/pipeline/runner.py` — `Pipeline.run()` and `_process_one()` gain catalog write-back hook
- `src/pipeline/watcher.py` — `ContentWatcher._discover()` and `_run_pipeline()` updated to use catalog-centric flow
- `cli.py` — add `catalog-refresh` subcommand, add `--from-catalog` flag to `pipeline`
- `src/sources/base.py` — `Post` dataclass may need a `post_type` field for routing
- `src/capture/batch.py` — catalog-based filtering replaces `filter_unseen()` when using `--from-catalog`

### New files to create
- `src/catalog.py` — `CatalogManager` class: atomic read/write/merge, filtering, and write-back logic
- `src/scripts/migrate_seen.py` — one-time migration script
- `tests/test_catalog.py` — tests for `CatalogManager`
- `tests/test_catalog_refresh.py` — tests for the refresh flow (or inline in `test_catalog.py`)

## Implementation Phases

### Phase 1: Foundation — Schema & CatalogManager
Extend the catalog schema and build the `CatalogManager` class that owns all catalog I/O. This is the foundation everything else builds on.

### Phase 2: Core Implementation — Refresh, Pipeline Integration, Write-back
Wire `catalog-refresh` into the CLI, add `--from-catalog` to the pipeline, and implement the write-back hook so the catalog is updated after each post.

### Phase 3: Integration & Polish — Migration, Watcher, Testing
Run the one-time migration to backfill existing recordings, update the watcher to use the catalog, and ensure all tests pass.

## Step by Step Tasks

### 1. Extend `DiscoveredPost` schema in `src/sources/discovery.py`

Add the new lifecycle fields to `DiscoveredPost`:

- Add fields to the dataclass:
  ```python
  @dataclass
  class DiscoveredPost:
      post_id: str
      url: str
      title: str
      created_at: str
      post_type: str
      has_video: bool
      recorded: bool = False
      recording_date: Optional[str] = None
      # --- New Phase 1 fields ---
      discovered_at: Optional[str] = None
      ingested_at: Optional[str] = None
      ingested_status: Optional[str] = None  # "complete" | "failed" | "skipped" | None
      recording_mb: Optional[float] = None
      transcript_words: Optional[int] = None
      output_path: Optional[str] = None
      error: Optional[str] = None
  ```
- Update `fetch_posts()` to set `discovered_at` to current UTC ISO timestamp for newly fetched posts
- Ensure `save_catalog()` serializes the new fields (already handled by `asdict()`)
- Run `uv run pytest tests/test_discovery.py` — fix any breakage from the new fields

### 2. Create `src/catalog.py` — CatalogManager

This is the core new module. It owns catalog I/O and provides the filtering/update API.

- Create `src/catalog.py` with class `CatalogManager`:
  ```python
  class CatalogManager:
      def __init__(self, catalog_path: Path):
          self._path = catalog_path
          self._lock = threading.Lock()

      def load(self) -> list[dict]:
          """Load catalog posts from disk. Returns empty list if missing."""

      def save(self, posts: list[dict], metadata: dict | None = None) -> None:
          """Atomic write: write to .tmp, then rename. Preserves metadata header."""

      def merge_discovered(self, discovered: list[DiscoveredPost]) -> tuple[list[dict], int]:
          """Merge discovered posts into existing catalog.
          New posts are added. Existing posts KEEP their ingestion status.
          Returns (merged_posts, new_count)."""

      def get_pending(self, post_types: list[str] | None = None) -> list[dict]:
          """Return posts where ingested_status is None, ordered by created_at desc."""

      def update_post(self, post_id: str, updates: dict) -> None:
          """Update a single post entry in-place and write immediately.
          Thread-safe via self._lock."""

      def find_by_url(self, url: str) -> dict | None:
          """Look up a post by URL."""
  ```

- **Atomic write** — `save()` writes to `catalog_path.with_suffix('.tmp')` then `os.replace()` to the final path. This prevents corruption if the process crashes mid-write.
- **Metadata preservation** — the catalog file has a header (`creator`, `campaign_id`, `last_discovery`, `total_posts`, `video_posts`). `save()` recomputes `total_posts` and `video_posts` from the post list.
- **`merge_discovered()`** logic:
  1. Load existing posts into a dict keyed by `post_id`
  2. For each discovered post: if `post_id` not in existing, add it (with `discovered_at` set to now). If it exists, update metadata fields (`title`, `post_type`, `has_video`, `created_at`) but NEVER overwrite ingestion fields (`ingested_at`, `ingested_status`, `recording_mb`, `transcript_words`, `output_path`, `error`).
  3. Return merged list and count of new posts
- **`get_pending()`** — filter where `ingested_status is None`, sorted by `created_at` descending

### 3. Create `tests/test_catalog.py`

- Test `CatalogManager.load()` with missing file, empty file, valid file
- Test `CatalogManager.save()` produces valid JSON, preserves metadata header
- Test `CatalogManager.save()` atomic write (`.tmp` then rename)
- Test `CatalogManager.merge_discovered()`:
  - New posts are added with `discovered_at`
  - Existing posts keep their `ingested_status` even when metadata changes
  - Duplicate posts are deduplicated by `post_id`
- Test `CatalogManager.get_pending()`:
  - Returns only posts with `ingested_status is None`
  - Ordered by `created_at` desc
  - Optionally filtered by `post_types`
- Test `CatalogManager.update_post()`:
  - Updates the correct post by `post_id`
  - Writes immediately to disk
  - Raises `KeyError` for unknown `post_id`
- Test `CatalogManager.find_by_url()` — found and not-found cases
- Test crash safety — catalog is valid JSON after `save()` even if the test kills the process after `.tmp` is written
- Run `uv run pytest tests/test_catalog.py`

### 4. Add `catalog-refresh` CLI command

Wire a new `catalog-refresh` subcommand into `cli.py`:

- In `build_parser()`, add:
  ```python
  cr = sub.add_parser("catalog-refresh", help="Refresh catalog from Patreon public API")
  cr.add_argument("--catalog", default="data/patreon_catalog_firedupwealth.json",
      help="Catalog file path")
  cr.add_argument("--campaign-id", default="5008493")
  cr.add_argument("--full", action="store_true",
      help="Paginate through all posts (slow, respects cooldown)")
  cr.add_argument("--force", action="store_true",
      help="Ignore cooldown timer")
  ```
- In `main()`, add the handler:
  ```python
  elif args.command == "catalog-refresh":
      from src.catalog import CatalogManager
      from src.sources.discovery import PatreonDiscovery, MAX_PAGES

      catalog = CatalogManager(Path(args.catalog))
      discovery = PatreonDiscovery(campaign_id=args.campaign_id)

      if args.full and not args.force:
          if not discovery.check_cooldown(Path("data")):
              print("Cooldown active. Use --force to override.")
              return 0

      max_pages = MAX_PAGES if args.full else 1
      posts = discovery.fetch_posts(media_type=None, max_pages=max_pages)
      merged, new_count = catalog.merge_discovered(posts)
      catalog.save(merged)

      if args.full:
          discovery.update_cooldown(Path("data"))

      print(f"Catalog refreshed: {new_count} new, {len(merged)} total")
  ```
- This command fetches ALL post types (not just video) so the catalog is comprehensive
- Add test in `tests/test_cli.py` or a new `tests/test_catalog_refresh.py` to verify the subcommand parses

### 5. Add `--from-catalog` to the `pipeline` command

Modify the pipeline CLI to optionally read from the catalog instead of a queue file:

- In `build_parser()`, update the `pipeline` subparser:
  - Change `--queue` from `required=True` to `required=False, default=None`
  - Add `--from-catalog` flag: `p.add_argument("--from-catalog", default=None, metavar="PATH", nargs="?", const="data/patreon_catalog_firedupwealth.json", help="Read unprocessed posts from catalog file")`
  - Add validation: exactly one of `--queue` or `--from-catalog` must be specified
- In `main()` pipeline handler, add the catalog branch:
  ```python
  if args.from_catalog:
      from src.catalog import CatalogManager
      catalog = CatalogManager(Path(args.from_catalog))
      pending = catalog.get_pending()
      # Route by post_type
      processable = []
      for entry in pending:
          pt = entry.get("post_type", "")
          if entry.get("has_video"):
              processable.append(entry)
          elif pt == "poll":
              catalog.update_post(entry["post_id"], {
                  "ingested_status": "skipped",
                  "error": "poll posts not ingested",
              })
          else:
              catalog.update_post(entry["post_id"], {
                  "ingested_status": "skipped",
                  "error": f"{pt} handler not yet implemented",
              })
              log.info("Skipping post_type=%s: handler not yet implemented", pt)
      queue_data = [{"url": e["url"], "filename": _title_to_filename(e["title"])} for e in processable]
  ```
- Add `_title_to_filename(title: str) -> str` helper (same logic as `Post.__post_init__`)
- Pass the `CatalogManager` instance through to the pipeline so write-back works (see step 6)

### 6. Implement pipeline write-back to catalog

After each post completes (success or failure), update the catalog entry:

- Add a `catalog` parameter to `Pipeline.__init__()`:
  ```python
  def __init__(self, source, engine, output_dir=None,
               enable_breaks=False, preflight=None, catalog=None):
      ...
      self._catalog = catalog  # CatalogManager | None
  ```
- In `Pipeline.run()`, after each `_process_one()` call, if `self._catalog` is set, call `_write_back_to_catalog(post, result)`:
  ```python
  async def _write_back_to_catalog(self, post, result: PipelineResult) -> None:
      if not self._catalog:
          return
      post_id = _extract_post_id(post.url)  # parse from URL path
      updates = {}
      if result.steps_failed:
          updates["ingested_status"] = "failed"
          updates["error"] = "; ".join(f"{k}: {v}" for k, v in result.steps_failed.items())
      else:
          updates["ingested_status"] = "complete"
          updates["ingested_at"] = datetime.now(timezone.utc).isoformat()
          recording = result.output_paths.get("recording", "")
          if recording:
              try:
                  updates["recording_mb"] = round(Path(recording).stat().st_size / (1024 * 1024), 1)
              except OSError:
                  pass
              updates["output_path"] = recording
          txt_path = result.output_paths.get("transcript_txt", "")
          if txt_path:
              try:
                  words = len(Path(txt_path).read_text(encoding="utf-8").split())
                  updates["transcript_words"] = words
              except OSError:
                  pass
      try:
          self._catalog.update_post(post_id, updates)
      except KeyError:
          log.warning("Post %s not found in catalog — skipping write-back", post_id)
  ```
- Add `_extract_post_id(url: str) -> str` helper — extracts the numeric ID from the URL path (e.g., `https://www.patreon.com/posts/154133781` -> `"154133781"`, and for slug URLs like `https://www.patreon.com/firedupwealth/posts/degen-gambling-165364356` -> `"165364356"`)
- Write-back happens **immediately** after each post (not at the end of the run) — this is critical for crash recovery
- In `cli.py` pipeline handler, pass the `CatalogManager` to `Pipeline()` when using `--from-catalog`

### 7. Add `post_type` to `Post` dataclass for routing

- In `src/sources/base.py`, add `post_type: str = ""` to the `Post` dataclass
- When building `Post` objects from catalog entries (step 5), populate `post_type` from the catalog
- This allows future phases to route on `post_type` within the pipeline itself

### 8. Implement graceful post-type handling

When the pipeline encounters a post type it can't handle:

- The routing in step 5 handles this at the CLI level (before posts enter the pipeline)
- For `poll` posts: set `ingested_status="skipped"`, `error="poll posts not ingested"` — permanently skipped
- For `text`, `audio`, `image` posts: set `ingested_status="skipped"`, `error="<type> handler not yet implemented"` — will be unblocked in Phase 2
- Log at INFO level (not ERROR): `"Skipping post_type=text: handler not yet implemented"`
- Continue to the next post — never abort the run

### 9. Create one-time migration script `src/scripts/migrate_seen.py`

- Create `src/scripts/` directory and `migrate_seen.py`:
  ```python
  """One-time migration: backfill catalog from seen_urls.txt and recording files."""
  ```
- The script:
  1. SSH to obs-machine, read `C:\Users\Matt\agent-control\state\seen_urls.txt`
  2. SSH to obs-machine, list files in `D:\MasterClass Video Backup\` to get sizes
  3. Load the catalog from `data/patreon_catalog_firedupwealth.json` (or `data/patreon_full_catalog.json` — whichever is the canonical one)
  4. For each URL in `seen_urls.txt`, find the matching catalog entry (by URL) and set:
     - `ingested_status = "complete"`
     - `ingested_at` = file modification time (or "unknown")
     - `recording_mb` = file size
     - `output_path` = recording directory name
  5. Write the updated catalog
- Also merge the conference catalog (`data/fuw_2026_conference_catalog.json`) into the main catalog — the conference sessions have a different schema (`volume`, `sessions` vs `posts`) so the migration normalizes them
- Make it runnable as: `uv run python src/scripts/migrate_seen.py`
- Make it idempotent — running it twice produces the same result

### 10. Update the watcher to use CatalogManager

- In `src/pipeline/watcher.py`, update `_discover()`:
  - Use `CatalogManager.merge_discovered()` instead of the inline merge logic
  - This deduplicates the merge code that's currently in both `watcher.py` and `cli.py discover`
- Update `_run_pipeline()`:
  - Pass the `CatalogManager` instance to `Pipeline()` so write-back works during autonomous runs
- This ensures the watcher also writes ingestion results back to the catalog

### 11. Handle the two catalog formats

There are currently two catalog files with different schemas:
- `data/patreon_catalog_firedupwealth.json` — CDP-scraped format with `{title, url, date, type, has_video, is_locked, preview, recorded}` and no `post_id`
- `data/patreon_full_catalog.json` — public API format with `{post_id, url, title, created_at, post_type, has_video}`

The public API format is the canonical one going forward. The migration script (step 9) should:
- Read both files
- Normalize the CDP-scraped entries to match the public API schema (extract `post_id` from URL, map `type` to `post_type`)
- Merge everything into the unified catalog
- After migration, the CDP-scraped catalog is no longer needed for pipeline operations

### 12. Update tests and validate

- Run `uv run pytest` — ensure all 303+ existing tests pass
- New tests cover:
  - `CatalogManager` CRUD operations (step 3)
  - `catalog-refresh` CLI command parsing
  - `--from-catalog` CLI command parsing and mutual exclusivity with `--queue`
  - Pipeline write-back (mock `CatalogManager.update_post()`)
  - Post-type routing (video -> process, text -> skip, poll -> skip)
  - Atomic write (no corruption on crash)
  - Migration script (with fixture data)

## Testing Strategy

### Unit tests (`tests/test_catalog.py`)
- `CatalogManager.load()` — missing file, corrupt JSON, valid file
- `CatalogManager.save()` — valid JSON output, atomic rename, metadata header
- `CatalogManager.merge_discovered()` — new posts added, existing kept, ingestion fields preserved
- `CatalogManager.get_pending()` — correct filtering and ordering
- `CatalogManager.update_post()` — correct update, immediate write, KeyError on unknown
- `CatalogManager.find_by_url()` — found and not-found

### Integration tests (`tests/test_pipeline.py` additions)
- Pipeline with `catalog=CatalogManager(...)` calls `update_post()` on success
- Pipeline with `catalog=CatalogManager(...)` calls `update_post()` on failure with error
- Pipeline without catalog (`catalog=None`) works exactly as before (no regression)

### CLI tests (`tests/test_cli.py` additions)
- `catalog-refresh` subcommand parses correctly
- `--from-catalog` and `--queue` are mutually exclusive
- `--from-catalog` with no argument defaults to `data/patreon_catalog_firedupwealth.json`

### Post-type routing tests
- Video posts are processed
- Text/audio/image posts are skipped with appropriate error message
- Poll posts are permanently skipped
- Skipped posts have `ingested_status="skipped"` in catalog

## Acceptance Criteria

1. `uv run cli.py catalog-refresh` updates the catalog with new posts from the public API
2. `uv run cli.py catalog-refresh --full` paginates through all posts (respects cooldown)
3. `uv run cli.py pipeline --from-catalog` reads unprocessed posts and ingests them
4. After ingestion, catalog entries have `ingested_at`, `ingested_status`, `recording_mb`, `transcript_words`, and `output_path`
5. `--from-catalog` and `--queue` are mutually exclusive — providing both is an error
6. Existing recordings are reflected in the catalog via the migration script
7. Non-video post types are gracefully skipped with `ingested_status="skipped"` and descriptive `error` field
8. Poll posts are permanently skipped
9. Catalog file is valid JSON after every write (atomic write via tmp+rename)
10. All existing tests pass, new tests cover catalog read/write/merge/routing logic
11. The watcher (`watch` command) also writes back to the catalog
12. `catalog-refresh` merges preserve ingestion fields — a refresh never clears a post's `ingested_status`

## Validation Commands

- `uv run python -m py_compile src/catalog.py` — verify catalog module compiles
- `uv run python -m py_compile cli.py` — verify CLI compiles with new commands
- `uv run pytest tests/test_catalog.py -v` — run catalog tests
- `uv run pytest tests/test_pipeline.py -v` — run pipeline tests (including write-back)
- `uv run pytest tests/test_discovery.py -v` — ensure discovery tests pass with new fields
- `uv run pytest tests/test_cli.py -v` — ensure CLI tests pass
- `uv run pytest` — full test suite (all 303+ tests)
- `uv run cli.py catalog-refresh --help` — verify command is registered
- `uv run cli.py pipeline --help` — verify `--from-catalog` flag shows up

## Notes

- No new dependencies needed — the catalog refresh uses the existing `PatreonDiscovery` class which uses `urllib.request` (stdlib)
- The `patreon_full_catalog.json` (1632 posts from the public API) should become the canonical starting point. The CDP-scraped `patreon_catalog_firedupwealth.json` (22 posts) can be absorbed into it during migration.
- The conference catalog (`fuw_2026_conference_catalog.json`) uses a `sessions` key instead of `posts` — the migration normalizes this to `posts`
- Atomic writes use `os.replace()` which is atomic on both Linux and Windows (POSIX and NTFS)
- The `CatalogManager` uses a threading lock, not asyncio, because writes happen in sync context (after each pipeline step completes). The pipeline itself is async but the write-back is a quick sync operation.
- Phase 2 (future) will add handlers for `text`, `audio`, and `image` post types. The `ingested_status="skipped"` with `error="<type> handler not yet implemented"` makes it easy to find and re-process these posts when handlers are added (filter where `ingested_status="skipped"` AND `error LIKE "%not yet implemented%"`).
