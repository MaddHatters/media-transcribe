# Plan: Pipeline Test Mode (--test-mode)

## Task Description

Add a `--test-mode` flag to `cli.py pipeline` that runs the full end-to-end recording → analyze → transcribe → correct flow using a local test video instead of Patreon content. This eliminates the risk of Patreon ban during development/testing and removes the dependency on Patreon access for pipeline validation.

## Objective

When `uv run cli.py pipeline --queue test_assets/test_queue.json --test-mode` is run on the obs-machine, the pipeline executes every step identically to production — OBS records, Chrome plays fullscreen via CDP, Whisper transcribes — except the video source is a local HTML page with a generated test video instead of a Patreon post.

## Problem Statement

The pipeline's only content source is Patreon. Testing requires:
- Active Patreon session (credential management, risk of detection/ban)
- Network access to Patreon servers
- Real Patreon content (limited access, slow to load)

This makes iteration slow and risky. A test mode that exercises the identical code paths with a local video eliminates all three constraints.

## Solution Approach

1. **Local test video**: Generate a 60-second MP4 with SMPTE color bars + 440Hz sine tone via ffmpeg, serve it from a minimal HTML page. The player detector sees a `<video>` element and selects the existing `HTML5Player` handler — no new player code needed.
2. **TestSource**: A minimal `Source` protocol implementor where `authenticate()` returns True and `navigate_to()` just calls `cdp.navigate()` (no stealth behavior, no Patreon DOM interaction).
3. **Preflight skip_patreon**: A single boolean on `Preflight.__init__()` that auto-passes the Patreon session gate. All other gates (Chrome, OBS, disk, test recording) still run.
4. **CLI wiring**: `--test-mode` flag on the pipeline subcommand. When set, substitutes `TestSource` for `PatreonSource` and passes `skip_patreon=True` to `Preflight`.

## Relevant Files

Use these files to complete the task:

- **`cli.py`** (lines 127-139, 262-333) — Add `--test-mode` argument to pipeline parser; wire TestSource/Preflight changes in pipeline command handler
- **`src/sources/base.py`** — Source protocol definition (reference for TestSource interface)
- **`src/sources/youtube.py`** — Model for TestSource (simple source, no auth)
- **`src/capture/preflight.py`** (lines 38-89) — Add `skip_patreon` parameter to `__init__()` and conditional gate logic in `run_all()`
- **`src/pipeline/runner.py`** — Pipeline class (no changes needed — already accepts any Source)
- **`src/capture/recorder.py`** (line 53) — URL navigation (no changes needed — `cdp.navigate()` handles `file://` URLs)
- **`src/players/detector.py`** — Player detection (no changes needed — `<video>` element → `html5` handler)
- **`src/config.py`** — Path constants (add `TEST_ASSETS_DIR` constant)
- **`scripts/release.sh`** (line 80) — Add `test_assets/` to deploy SCP command
- **`tests/test_cli.py`** — Existing CLI argument parsing tests (add `--test-mode` test)
- **`tests/test_preflight.py`** — Existing preflight tests (add `skip_patreon` tests)

### New Files

- **`src/sources/test_source.py`** — TestSource class implementing Source protocol
- **`test_assets/test_video.html`** — Self-contained HTML page with `<video>` element pointing to test_video.mp4
- **`test_assets/generate_test_video.py`** — Script to generate test_video.mp4 via ffmpeg
- **`test_assets/test_queue.json`** — Queue file with a single entry pointing at the local test video page
- **`tests/test_test_mode.py`** — Tests for TestSource, test-mode queue rewriting, and generate script

## Implementation Phases

### Phase 1: Foundation
Create the test video infrastructure (HTML page, video generator script, queue file) and the TestSource class. These are standalone with no impact on existing code.

### Phase 2: Core Implementation
Modify Preflight to support `skip_patreon`, add `--test-mode` to CLI, and wire the flag through the pipeline command handler to substitute TestSource and configure preflight.

### Phase 3: Integration & Polish
Update the deploy script to include test_assets/, add a `generate-test-video` CLI subcommand, and write all tests.

## Step by Step Tasks

IMPORTANT: Execute every step in order, top to bottom.

### 1. Create test_assets directory and test video generator

- Create `test_assets/generate_test_video.py`:
  ```python
  """Generate a test video with SMPTE color bars, timestamp overlay, and sine tone."""
  import subprocess
  import sys
  from pathlib import Path

  def generate(output: Path, duration: int = 60):
      cmd = [
          "ffmpeg", "-y",
          "-f", "lavfi", "-i",
          f"smptebars=size=1920x1080:rate=30:duration={duration},"
          f"drawtext=text='%{{pts\\:hms}}':fontsize=72:fontcolor=white:"
          f"x=(w-tw)/2:y=h-th-50:box=1:boxcolor=black@0.7:boxborderw=10",
          "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
          "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
          "-c:a", "aac", "-b:a", "128k",
          "-pix_fmt", "yuv420p",
          str(output),
      ]
      subprocess.run(cmd, check=True)
      print(f"Generated: {output} ({output.stat().st_size / 1024 / 1024:.1f} MB)")

  if __name__ == "__main__":
      out = Path(__file__).parent / "test_video.mp4"
      generate(out, duration=int(sys.argv[1]) if len(sys.argv) > 1 else 60)
  ```
- The script uses SMPTE color bars (non-black background — passes preflight video check) and a 440Hz sine tone (passes audio check)
- The `drawtext` overlay renders a running timestamp — useful for verifying recording captured the right segment and for OCR testing in later pipeline steps

### 2. Create test video HTML page

- Create `test_assets/test_video.html`:
  ```html
  <!DOCTYPE html>
  <html>
  <head><title>Pipeline Test Video</title></head>
  <body style="margin:0;background:#1a1a2e">
  <video id="v" style="width:100%;height:100vh;object-fit:contain" controls>
    <source src="test_video.mp4" type="video/mp4">
  </video>
  <script>
  document.getElementById('v').play().catch(function(){});
  </script>
  </body>
  </html>
  ```
- The `<video>` element will be detected by `detector.py` DETECTION_JS as `player: "html5"` → `HTML5Player` handler
- Dark background (`#1a1a2e`) is non-black so the video element stands out but the page isn't jarring
- Auto-play on load so Chrome CDP doesn't need to click-to-play
- The video element supports all required properties: `duration`, `currentTime`, `play()`, `pause()`, `muted`, `requestFullscreen()`

### 3. Create test queue file

- Create `test_assets/test_queue.json`:
  ```json
  [
    {
      "url": "file:///C:/Users/Matt/transcribe/test_assets/test_video.html",
      "filename": "Pipeline Test - 60s Color Bars"
    }
  ]
  ```
- Uses `file://` URL with absolute Windows path to obs-machine deploy location
- Single entry — enough to validate the full pipeline; fast to run

### 4. Create TestSource

- Create `src/sources/test_source.py`:
  ```python
  """Test source — local video files, no authentication needed."""
  from __future__ import annotations

  from typing import TYPE_CHECKING

  from src.sources.base import Post

  if TYPE_CHECKING:
      from src.cdp import CDPClient


  class TestSource:
      name = "test"

      async def authenticate(self, cdp: CDPClient) -> bool:
          return True

      async def get_posts(self, cdp: CDPClient, query: str | None = None) -> list[Post]:
          return []

      async def navigate_to(self, cdp: CDPClient, url: str) -> None:
          await cdp.navigate(url, wait=10.0)
  ```
- Implements the full `Source` protocol (matches `src/sources/base.py:29`)
- Modeled after `YouTubeSource` — `authenticate()` returns True, `navigate_to()` does a plain CDP navigate
- No stealth behavior (no random mouse moves, no scroll delays) — this is a local file, no anti-bot detection
- `get_posts()` returns empty list (queue comes from the JSON file, not the source)

### 5. Add skip_patreon to Preflight

- In `src/capture/preflight.py`, modify `__init__` (line 39):
  ```python
  def __init__(self, cdp_url: str = CDP_URL, skip_patreon: bool = False):
      self._cdp_url = cdp_url
      self._skip_patreon = skip_patreon
  ```
- In `run_all()` (lines 56-63), replace the Patreon session gate block:
  ```python
  if self._skip_patreon:
      gates.append(GateResult("Patreon session", True, "skipped (test mode)"))
  elif chrome_ok:
      patreon_ok = self._check_patreon_session()
      gates.append(GateResult("Patreon session", patreon_ok))
      if not patreon_ok:
          all_ok = False
  else:
      gates.append(GateResult("Patreon session", False, "skipped (no Chrome)"))
      all_ok = False
  ```
- This is the minimal change: one new parameter, one conditional branch. All other gates still run.
- The gate reports `True` with detail `"skipped (test mode)"` so the gate count stays at 7 and the log output clearly shows what happened.

### 6. Add --test-mode flag to CLI pipeline parser

- In `cli.py`, add after line 139 (after `--foreground`):
  ```python
  p.add_argument("--test-mode", action="store_true",
      help="Use local test video instead of Patreon (no network access needed)")
  ```

### 7. Wire --test-mode in the pipeline command handler

- In `cli.py`, modify the pipeline command block (lines 262-333). The key changes are in the recording setup section (lines 288-315):

  **Replace the source creation block** (lines 290-294):
  ```python
  if has_record:
      from src.engines.obs_engine import OBSEngine
      engine = OBSEngine()
      if args.test_mode:
          from src.sources.test_source import TestSource
          source = TestSource()
      else:
          from src.sources.patreon import PatreonSource
          source = PatreonSource()
  ```

  **Print test mode banner** — add right after the queue loading section (after line 283, before `posts = ...`):
  ```python
  if args.test_mode:
      print("*** TEST MODE — using local test video ***")
  ```

  **Pass skip_patreon to Preflight** — modify lines 310-311:
  ```python
  pf = Preflight(skip_patreon=args.test_mode)
  ```

- The rest of the pipeline (OBS, Chrome CDP, fullscreen, recording, analyze, transcribe, correct) runs identically — that's the point. We're only swapping the source and skipping the Patreon session check.

### 8. Add generate-test-video CLI subcommand

- In `cli.py`, add a new subcommand in `build_parser()` (after the pipeline parser, around line 140):
  ```python
  # --- generate-test-video ---
  gtv = sub.add_parser("generate-test-video", help="Generate test video for --test-mode")
  gtv.add_argument("--duration", type=int, default=60, help="Duration in seconds")
  ```

- In `main()`, add the command handler (before the `transfer-transcripts` block):
  ```python
  elif args.command == "generate-test-video":
      from test_assets.generate_test_video import generate
      out = Path("test_assets/test_video.mp4")
      out.parent.mkdir(exist_ok=True)
      generate(out, duration=args.duration)
      return 0
  ```

- Also add `"generate-test-video"` to the `LONG_RUNNING_COMMANDS` set if generating takes a while, but 60s of ultrafast libx264 should complete in <5 seconds, so likely not needed. Skip it.

### 9. Update deploy script to include test_assets

- In `scripts/release.sh`, modify the SCP line (line 80-82) to include `test_assets/`:
  ```bash
  scp -r src/ cli.py pyproject.toml launch_chrome.bat \
      transcribe/corrections.txt transcribe/finance_vocab.txt \
      test_assets/ \
      "$REMOTE:$REMOTE_DIR/"
  ```
- The `test_video.mp4` file (generated on obs-machine, not committed to repo) won't exist in the deploy source. That's fine — SCP copies whatever is in `test_assets/` (the HTML, generator script, and queue file). The user runs `generate-test-video` on the obs-machine to create the MP4.
- Add a note to the release summary about generating the test video:
  ```bash
  echo "To set up test mode (first time):"
  echo "  ssh $REMOTE \"cd $REMOTE_DIR; uv run cli.py generate-test-video\""
  ```

### 10. Write tests

- Create `tests/test_test_mode.py` with the following tests:

  **TestSource tests:**
  ```python
  async def test_test_source_authenticate():
      from src.sources.test_source import TestSource
      source = TestSource()
      cdp = AsyncMock()
      assert await source.authenticate(cdp) is True

  async def test_test_source_get_posts():
      from src.sources.test_source import TestSource
      source = TestSource()
      cdp = AsyncMock()
      assert await source.get_posts(cdp) == []

  async def test_test_source_navigate_to():
      from src.sources.test_source import TestSource
      source = TestSource()
      cdp = AsyncMock()
      await source.navigate_to(cdp, "file:///test.html")
      cdp.navigate.assert_called_once_with("file:///test.html", wait=10.0)

  def test_test_source_satisfies_protocol():
      from src.sources.base import Source
      from src.sources.test_source import TestSource
      assert isinstance(TestSource(), Source)
  ```

  **Preflight skip_patreon tests:**
  ```python
  def test_preflight_skip_patreon_passes_gate():
      pf = _mock_preflight()  # reuse helper from test_preflight.py pattern
      pf._skip_patreon = True
      ok, gates = pf.run_all()
      patreon_gate = [g for g in gates if g.name == "Patreon session"][0]
      assert patreon_gate.passed is True
      assert "test mode" in patreon_gate.detail

  def test_preflight_skip_patreon_does_not_call_check():
      pf = Preflight(skip_patreon=True)
      pf._ensure_chrome = MagicMock(return_value=True)
      pf._ensure_obs = MagicMock(return_value=True)
      pf._check_patreon_session = MagicMock(return_value=False)
      pf._check_disk_space = MagicMock(return_value=(True, "50 GB free"))
      pf._run_test_recording = MagicMock(return_value=(True, True, (1920, 1080)))
      ok, gates = pf.run_all()
      pf._check_patreon_session.assert_not_called()
      assert ok is True
  ```

  **CLI argument parsing test:**
  ```python
  def test_cli_pipeline_test_mode_flag():
      from cli import build_parser
      parser = build_parser()
      args = parser.parse_args(["pipeline", "--queue", "q.json", "--test-mode"])
      assert args.test_mode is True

  def test_cli_pipeline_test_mode_default_false():
      from cli import build_parser
      parser = build_parser()
      args = parser.parse_args(["pipeline", "--queue", "q.json"])
      assert args.test_mode is False

  def test_cli_generate_test_video_args():
      from cli import build_parser
      parser = build_parser()
      args = parser.parse_args(["generate-test-video", "--duration", "30"])
      assert args.command == "generate-test-video"
      assert args.duration == 30
  ```

  **Generate script test:**
  ```python
  def test_generate_test_video_builds_correct_ffmpeg_cmd():
      from test_assets.generate_test_video import generate
      with patch("test_assets.generate_test_video.subprocess.run") as mock_run:
          mock_run.return_value = MagicMock(returncode=0)
          # mock stat for the print statement
          with patch("pathlib.Path.stat") as mock_stat:
              mock_stat.return_value = MagicMock(st_size=5 * 1024 * 1024)
              generate(Path("/tmp/test.mp4"), duration=30)
          cmd = mock_run.call_args[0][0]
          assert cmd[0] == "ffmpeg"
          assert "-y" in cmd
          assert "sine=frequency=440:duration=30" in " ".join(cmd)
          assert "smptebars" in " ".join(cmd)
  ```

### 11. Validate all tests pass

- Run `uv run pytest` to ensure no regressions
- Run `uv run python -m py_compile cli.py` and `uv run python -m py_compile src/sources/test_source.py` to verify syntax
- Run `uv run pytest tests/test_test_mode.py -v` to verify new tests specifically

## Testing Strategy

**Unit tests** (in `tests/test_test_mode.py`):
- TestSource protocol compliance (runtime_checkable `isinstance` check)
- TestSource method behavior (authenticate returns True, navigate calls cdp.navigate, get_posts returns [])
- Preflight `skip_patreon=True` passes the Patreon gate without calling `_check_patreon_session`
- Preflight `skip_patreon=False` (default) preserves existing behavior
- CLI `--test-mode` flag parsing (present → True, absent → False)
- CLI `generate-test-video` subcommand parsing
- generate_test_video.py produces correct ffmpeg command

**Integration test** (manual, on obs-machine after deploy):
1. `uv run cli.py generate-test-video` → produces `test_assets/test_video.mp4`
2. `uv run cli.py pipeline --queue test_assets/test_queue.json --test-mode --steps record` → OBS records the local test video
3. Full pipeline: `uv run cli.py pipeline --queue test_assets/test_queue.json --test-mode` → recording + analysis + transcription + correction all complete

**Edge cases to verify:**
- `--test-mode` without `--queue` still requires `--queue` (argparse handles this)
- `--test-mode` with `--skip-preflight` works (both flags active — TestSource used, no preflight at all)
- `--test-mode` with `--steps transcribe,correct` (no recording) — TestSource is not instantiated, behaves like normal non-record pipeline
- `--test-mode` does NOT affect the `record` standalone command (only `pipeline`)

## Acceptance Criteria

- [ ] `uv run cli.py pipeline --queue test_assets/test_queue.json --test-mode` accepted by CLI parser
- [ ] Pipeline prints `*** TEST MODE — using local test video ***` when `--test-mode` is set
- [ ] Preflight skips Patreon session check and reports `"skipped (test mode)"` when `--test-mode` is set
- [ ] TestSource implements the full Source protocol (passes `isinstance(TestSource(), Source)`)
- [ ] `uv run cli.py generate-test-video` runs without error (given ffmpeg is installed)
- [ ] test_assets/test_video.html serves a `<video>` element that the player detector identifies as `"html5"`
- [ ] All existing tests continue to pass (`uv run pytest`)
- [ ] New tests in `tests/test_test_mode.py` pass
- [ ] `scripts/release.sh` deploys `test_assets/` to obs-machine
- [ ] No changes to existing pipeline behavior when `--test-mode` is NOT set

## Validation Commands

Execute these commands to validate the task is complete:

- `uv run python -m py_compile cli.py` — Verify CLI compiles
- `uv run python -m py_compile src/sources/test_source.py` — Verify TestSource compiles
- `uv run python -m py_compile test_assets/generate_test_video.py` — Verify generator compiles
- `uv run pytest tests/test_test_mode.py -v` — Run new test-mode tests
- `uv run pytest tests/test_cli.py -v` — Verify CLI tests still pass (including new --test-mode tests)
- `uv run pytest tests/test_preflight.py -v` — Verify preflight tests still pass
- `uv run pytest tests/test_pipeline.py -v` — Verify pipeline tests still pass
- `uv run pytest` — Full test suite, no regressions

## Notes

- **test_video.mp4 is not committed to git** — it's ~5-10 MB and is generated on the obs-machine via `cli.py generate-test-video`. Add `test_assets/test_video.mp4` to `.gitignore`.
- **ffmpeg is required** on the obs-machine (already installed per AGENTS.md).
- **file:// URLs in Chrome CDP**: Chrome supports `file://` navigation out of the box when launched with `--allow-file-access-from-files` or when the page is already a local file. The existing `--remote-debugging-port=9222` launch flags in `src/config.py:35` don't restrict this. If Chrome blocks file:// access, add `--allow-file-access-from-files` to `CHROME_FLAGS` in `src/config.py`.
- **No new dependencies** — this feature uses only stdlib + existing project deps (ffmpeg via subprocess).
- **The queue file hardcodes a Windows path** (`file:///C:/Users/Matt/transcribe/...`). This is intentional — the pipeline only runs on the obs-machine (Windows). For cross-platform dev testing, the queue URL would need to be adjusted manually.
