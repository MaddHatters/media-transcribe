# Plan: Chunk 24 — New-video ingest runner

## Task Description
Implement `transcribe/ingest_new.py` — a standalone runner that scans the Patreon Masterclass
source directory for `.mkv` files, diffs against existing transcripts, and transcribes only
the missing videos via the existing `transcribe.py` pipeline. The runner must be idempotent:
re-running it when all videos are already transcribed is a no-op.

Scope is defined by ADW backlog chunk 24 (`[det]`, no deps). One new module, one new test file,
two named test cases, one commit.

## Objective
A single `uv run transcribe/ingest_new.py` command identifies and transcribes any Patreon
Masterclass videos that lack transcripts, producing the same `.txt` + `.srt` output the existing
pipeline creates. Running it again immediately afterward does nothing.

## Problem Statement
The Masterclass library grows over time as new `.mkv` files appear in the source directory.
Currently, invoking the full `transcribe.py` pipeline requires the user to manually check what's
new. A purpose-built ingest runner automates the scan→diff→transcribe cycle and serves as the
entry point for future scheduled ingestion (roadmap Phase 7).

## Solution Approach
Factor the scan-and-diff logic into `ingest_new.py` as pure functions (`find_new`) that are
trivially testable without Whisper. Wire the actual transcription call through a pluggable
`transcribe_fn` parameter so tests can inject a stub, while production defaults to shelling out
to `transcribe.py --only <stem>`. This matches the project's "standalone scripts, no packages"
architecture and reuses the existing pipeline without modification.

## Relevant Files

**Existing (read-only context):**
- `transcribe/transcribe.py` — the existing Whisper pipeline; `ingest_new.py` delegates to it
  via subprocess using `--only` and `--out` flags (lines 106-107, 126-129)
- `transcribe/corrections.py` — inherited by `transcribe.py`; not directly imported
- `transcribe/corrections.txt`, `transcribe/finance_vocab.txt` — inherited by `transcribe.py`
- `tests/conftest.py` — adds `transcribe/` and `acquire/` to `sys.path`; already covers
  `ingest_new.py` via the `transcribe/` entry
- `AGENTS.md` — project guidelines (TDD, standalone scripts, argparse, CPU-only, never upload)
- `pyproject.toml` — pytest config, deps (no new deps needed)

### New Files
- `transcribe/ingest_new.py` — the new-video ingest runner
- `tests/test_ingest_new.py` — two named tests + supporting fixtures

## Implementation Phases

### Phase 1: Foundation — pure scan logic
Implement `find_new()` as a pure function that takes two `Path` arguments and returns a list of
`.mkv` `Path` objects that lack corresponding `.txt` + `.srt` transcripts. No imports from
`transcribe.py` — just `pathlib` operations.

### Phase 2: Core — ingest orchestrator + CLI
Implement `ingest()` which calls `find_new()`, reports the diff, and feeds each new video to a
`transcribe_fn` callable. Implement `main()` with argparse. Default `transcribe_fn` shells out
to `transcribe.py --only <stem> --out <transcripts_dir>`.

### Phase 3: Tests + validation
Write `test_ingest_new.py` with the two required tests using `tmp_path` fixtures and a stub
transcribe function. Run the full suite, run `ruff check`, ensure no regressions.

## Step by Step Tasks

### 1. Write test file `tests/test_ingest_new.py` (TDD — tests first)

Create the test file with both named tests and a helper stub:

- **Stub `_fake_transcribe(video, out_dir)`**: creates `<stem>.txt` and `<stem>.srt` in
  `out_dir`, simulating what the real pipeline produces.

- **`test_transcribes_only_missing`**:
  - Create `tmp_path / "source"` with three `.mkv` stub files: `A.mkv`, `B.mkv`, `C.mkv`
    (contents don't matter — just `touch` them)
  - Create `tmp_path / "transcripts"` with `A.txt` + `A.srt` (video A already transcribed)
  - Call `ingest(source, transcripts, transcribe_fn=_fake_transcribe)`
  - Assert return value is `["B", "C"]` (sorted stems of what was transcribed)
  - Assert `B.txt`, `B.srt`, `C.txt`, `C.srt` now exist in `transcripts/`
  - Assert `_fake_transcribe` was NOT called for `A`

- **`test_rerun_is_noop`**:
  - Same setup as above (all three already have `.txt` + `.srt` in `transcripts/`)
  - Call `ingest(source, transcripts, transcribe_fn=_fake_transcribe)`
  - Assert return value is `[]`
  - Assert `_fake_transcribe` was never called (use a counter or mock)

### 2. Create `transcribe/ingest_new.py`

Module-level docstring following the project convention (see `transcribe.py` lines 1-18).

**`find_new(source_dir: Path, transcripts_dir: Path) -> list[Path]`**
```python
def find_new(source_dir: Path, transcripts_dir: Path) -> list[Path]:
    all_mkv = sorted(
        p for p in source_dir.iterdir()
        if p.suffix.lower() == ".mkv"
    )
    done = {
        p.stem
        for p in transcripts_dir.glob("*.txt")
        if (transcripts_dir / f"{p.stem}.srt").exists()
    }
    return [v for v in all_mkv if v.stem not in done]
```

Key details:
- Only `.mkv` (case-insensitive suffix check), directly in the dir (no recursion) — per spec
- A video is "done" only when BOTH `.txt` and `.srt` exist (matches `transcribe.py` line 74)
- `transcripts_dir` may not exist yet — handle with `if not transcripts_dir.is_dir(): return all_mkv`
- Sorted for deterministic ordering

**`ingest(source_dir: Path, transcripts_dir: Path, *, transcribe_fn=None) -> list[str]`**
```python
def ingest(source_dir, transcripts_dir, *, transcribe_fn=None):
    new = find_new(source_dir, transcripts_dir)
    if not new:
        print("Nothing new to transcribe.")
        return []
    transcribe_fn = transcribe_fn or _default_transcribe
    print(f"{len(new)} new video(s) to transcribe:")
    for v in new:
        print(f"  {v.name}")
    for v in new:
        transcribe_fn(v, transcripts_dir)
    return [v.stem for v in new]
```

**`_default_transcribe(video: Path, transcripts_dir: Path) -> None`**
```python
def _default_transcribe(video, transcripts_dir):
    subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent / "transcribe.py"),
         str(video.parent), "--only", video.stem, "--out", str(transcripts_dir)],
        check=True,
    )
```

**`main() -> int`**
- argparse with positional `source` (default: the Patreon Masterclass path) and optional `--out`
  (default: `<source>/transcripts`)
- Validate source exists
- Call `ingest()` and return 0 on success

### 3. Run tests

- `uv run pytest tests/test_ingest_new.py -v` — the two new tests must pass
- `uv run pytest` — full suite must be green, no regressions

### 4. Run ruff check

- `uv run ruff check transcribe/ingest_new.py tests/test_ingest_new.py`
- Fix any lint issues

### 5. Validate the complete suite

- `uv run pytest` — full green
- `uv run ruff check` — clean across the whole project

## Testing Strategy

Both tests use `tmp_path` fixtures with stub `.mkv` files (empty files with the right extension).
The real Whisper pipeline is never loaded — a `_fake_transcribe` stub creates the `.txt` + `.srt`
output files, simulating the pipeline's effect. This satisfies the `[det]` gate and the "no
network in the unit gate" DoD requirement.

**`test_transcribes_only_missing`** proves the scan→diff→transcribe logic by:
1. Pre-populating one video's transcripts
2. Running ingest
3. Asserting only the un-transcribed videos were passed to the stub

**`test_rerun_is_noop`** proves idempotency by:
1. Pre-populating ALL videos' transcripts
2. Running ingest
3. Asserting zero transcription calls and an empty return value

Edge case coverage in the two tests:
- Empty transcripts directory (implied by `test_transcribes_only_missing` if transcripts_dir
  doesn't pre-exist for B and C)
- Mixed state (some done, some not)
- Fully caught-up state (rerun is noop)

## Acceptance Criteria
1. `tests/test_ingest_new.py::test_transcribes_only_missing` passes
2. `tests/test_ingest_new.py::test_rerun_is_noop` passes
3. `uv run pytest` — full suite green, no regressions
4. `uv run ruff check` — clean
5. `ingest_new.py` is standalone-runnable: `uv run transcribe/ingest_new.py --help` works
6. No new dependencies added to `pyproject.toml`
7. One reviewable commit

## Validation Commands
- `uv run pytest tests/test_ingest_new.py -v` — both named tests pass
- `uv run pytest` — full suite green
- `uv run ruff check` — clean lint
- `uv run python -m py_compile transcribe/ingest_new.py` — compiles without error
- `uv run transcribe/ingest_new.py --help` — prints usage without error

## Notes
- No new dependencies. `subprocess`, `pathlib`, `argparse`, `sys` are all stdlib.
- The default source path (`/mnt/secondary/media/patreon/FIRE Investing Masterclass/`) is
  hardcoded as the argparse default, matching the project's convention of baking in the known
  media paths (see `transcribe.py` usage docstring line 15, `bin/youtube-finance-transcripts.sh`).
- The `transcribe_fn` parameter is the seam for testing — not a generic extension point. Keep it
  keyword-only and undocumented in `--help`.
- `find_new` only looks at files DIRECTLY in `source_dir` (no `rglob`) — per the spec "no
  per-video subdirs".
- The "done" check requires BOTH `.txt` AND `.srt` — a partial transcript (only one file) is
  treated as incomplete and will be re-transcribed, consistent with `transcribe.py` line 74.
