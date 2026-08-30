# Plan: Phase 3 — Transcription, Analysis, Pipeline Orchestration & CLI

## Task Description
Complete the media-transcribe pipeline refactor by extracting transcription, correction, visual gap detection, video quality analysis, frame extraction, OCR, and cross-machine transfer logic from standalone scripts into composable `src/` modules. Wire everything together with a `Pipeline` orchestrator and a unified `cli.py` entry point. This is the final phase — Phase 1 created config, CDP, and players; Phase 2 created engines, recorder, batch, preflight, sources, and window management.

## Objective
When complete, the project has:
1. A `WhisperRunner` class wrapping faster-whisper with lazy model loading, resumability, and automatic corrections.
2. A `corrections` module (already exists at `transcribe/corrections.py`) re-exported from `src/transcribe/` for import consistency.
3. A `visual_gaps` module for SRT pattern scanning with structured `Gap` output.
4. A `QualityAnalyzer` with ffmpeg-based detection of black frames, freezes, silence, and bitrate drops.
5. A `frames` module for ffmpeg-based frame extraction at specific timestamps.
6. An `ocr` module wrapping RapidOCR with lazy imports.
7. A `TransferClient` for SCP-based cross-machine file sync.
8. A `Pipeline` orchestrator composing all steps with selective execution.
9. A `cli.py` argparse entry point with subcommands for every operation.
10. Full test coverage for all new modules.
11. Zero regressions — existing scripts remain untouched and runnable.

## Problem Statement
The transcription, analysis, and utility scripts (`transcribe/transcribe.py`, `transcribe/find_visual_gaps.py`, `transcribe/transfer_transcripts.py`, `acquire/video_analyzer_remote.py`, `ocr/extract_and_ocr.py`) are standalone with duplicated constants (SSH_HOST, SSH_OPTS, paths), no shared interfaces, and no way to compose them into an automated pipeline. Running the full workflow requires manually invoking 5+ scripts in sequence with path arguments. There is no single entry point, and the scripts cannot be tested without real media files or network access.

## Solution Approach
Extract logic from each script into a class or set of functions under `src/`, following the same patterns established in Phase 1 (config, protocols) and Phase 2 (engines, recorder, sources). Each module:
- Imports constants from `src/config.py` (no duplicated literals)
- Has lazy imports for heavy dependencies (faster-whisper, RapidOCR, av)
- Is independently testable with mocked subprocess/imports
- Can be used standalone or composed via the `Pipeline` orchestrator

The `Pipeline` class accepts a `Source` + `CaptureEngine` from Phase 2 and chains: record → analyze → transcribe → correct → find_gaps → extract_frames → ocr. Each step is independently runnable and skippable. A `cli.py` provides argparse subcommands that dispatch to the appropriate module.

## Relevant Files

### Phase 1+2 outputs (already implemented — import from these)
- `src/config.py` — Centralized constants (SSH_HOST, SSH_OPTS, BACKUP_DIR, paths, IS_WINDOWS)
- `src/cdp.py` — `CDPClient` async CDP WebSocket client
- `src/engines/base.py` — `CaptureEngine` Protocol + `EngineStatus`
- `src/engines/obs_engine.py` — `OBSEngine`
- `src/engines/ytdlp_engine.py` — `YtDlpEngine`
- `src/engines/null_engine.py` — `NullEngine`
- `src/capture/recorder.py` — `Recorder` single-video state machine + `RecordResult`
- `src/capture/batch.py` — `BatchOrchestrator`, queue/seen/shuffle functions
- `src/capture/preflight.py` — 7-gate preflight validation
- `src/sources/base.py` — `Source` Protocol + `Post` dataclass
- `src/sources/patreon.py` — `PatreonSource`
- `src/sources/youtube.py` — `YouTubeSource`
- `src/players/detector.py` — `detect_player()`
- `pyproject.toml` — Build config, dependencies, extras

### Existing scripts (extract logic from — do NOT modify or delete)
- `transcribe/transcribe.py` — Whisper transcription with ProcessPoolExecutor, per-worker model init, resumability, SRT + TXT output, correction application (167 lines)
- `transcribe/corrections.py` — Rule loading + application with regex and whole-word support (49 lines)
- `transcribe/corrections.txt` — FIRE Investing Masterclass correction rules
- `transcribe/apply_corrections.py` — Batch correction application with dry-run (63 lines)
- `transcribe/find_visual_gaps.py` — SRT pattern scanning, YAML output, context extraction (260 lines)
- `transcribe/transfer_transcripts.py` — SCP file sync between obs-machine and devbox-01 (172 lines)
- `acquire/video_analyzer_remote.py` — ffmpeg quality analysis: blackdetect, freezedetect, silencedetect, bitrate analysis, trim calculation, verdict computation (784 lines)
- `ocr/extract_and_ocr.py` — PyAV frame extraction + RapidOCR with dedup and interval/timestamp modes (107 lines)

### New files to create
- `src/transcribe/__init__.py` — Package marker
- `src/transcribe/whisper_runner.py` — `WhisperRunner` class
- `src/transcribe/corrections.py` — Correction engine (extracted)
- `src/transcribe/visual_gaps.py` — `Gap` dataclass + gap detection functions
- `src/analyze/__init__.py` — Package marker
- `src/analyze/quality.py` — `QualityAnalyzer` + `QualityReport`
- `src/analyze/frames.py` — Frame extraction at timestamps
- `src/analyze/ocr.py` — OCR wrapper with lazy RapidOCR
- `src/transfer/__init__.py` — Package marker
- `src/transfer/sync.py` — `TransferClient` SCP wrapper
- `src/pipeline/__init__.py` — Package marker
- `src/pipeline/runner.py` — `Pipeline` orchestrator
- `cli.py` — Unified CLI entry point
- `tests/test_whisper_runner.py` — WhisperRunner tests
- `tests/test_corrections.py` — Already exists; extend if needed (verify compatibility)
- `tests/test_visual_gaps.py` — Visual gap detection tests
- `tests/test_quality.py` — QualityAnalyzer tests
- `tests/test_frames.py` — Frame extraction tests
- `tests/test_pipeline.py` — Pipeline orchestrator tests
- `tests/test_cli.py` — CLI argument parsing tests

## Implementation Phases

### Phase 1: Foundation (transcription + corrections + gaps)
Build the transcription layer — the most complex extraction since it involves ProcessPoolExecutor, model loading, and GPU/CPU detection. Then corrections (mostly re-export) and visual gaps (straightforward extraction).

### Phase 2: Core Implementation (analysis + frames + OCR + transfer)
Build the analysis modules (quality, frames, OCR) and the transfer client. These are mostly subprocess wrappers around ffmpeg and SCP, plus lazy-imported OCR.

### Phase 3: Integration & Polish (pipeline + CLI + validation)
Wire everything together in the Pipeline orchestrator and CLI. Run the full test suite and validate backward compatibility.

## Step by Step Tasks
IMPORTANT: Execute every step in order, top to bottom.

### 1. Create package structure

- Create directories: `src/transcribe/`, `src/analyze/`, `src/transfer/`, `src/pipeline/`
- Create empty `__init__.py` files in each new directory
- Verify with: `uv run python -c "import src.transcribe, src.analyze, src.transfer, src.pipeline; print('OK')"`

### 2. Write `src/transcribe/corrections.py` — Correction engine

- Write `tests/test_corrections.py` first (or verify the existing test file covers what's needed).
  The existing `tests/test_corrections.py` tests the script at `transcribe/corrections.py`. The new `src/transcribe/corrections.py` must pass the same tests with the new import path. Write additional tests:
  ```python
  """Tests for src/transcribe/corrections — rule loading and application."""
  from pathlib import Path
  from src.transcribe.corrections import load_rules, apply_rules

  def test_load_rules_empty_file(tmp_path):
      rules_file = tmp_path / "empty.txt"
      rules_file.write_text("")
      assert load_rules(rules_file) == []

  def test_load_rules_comments_only(tmp_path):
      rules_file = tmp_path / "comments.txt"
      rules_file.write_text("# just a comment\n# another\n")
      assert load_rules(rules_file) == []

  def test_load_rules_literal(tmp_path):
      rules_file = tmp_path / "rules.txt"
      rules_file.write_text("foo => BAR\n")
      rules = load_rules(rules_file)
      assert len(rules) == 1

  def test_load_rules_regex(tmp_path):
      rules_file = tmp_path / "rules.txt"
      rules_file.write_text("re:\\bD[JG]I F\\b => DGIF\n")
      rules = load_rules(rules_file)
      assert len(rules) == 1

  def test_apply_rules_literal():
      rules = load_rules(Path("transcribe/corrections.txt"))
      text = "I bought d grow and S CHD today"
      result, counts = apply_rules(text, rules)
      assert "DGRO" in result
      assert "SCHD" in result

  def test_apply_rules_idempotent():
      rules = load_rules(Path("transcribe/corrections.txt"))
      text = "I bought DGRO and SCHD today"
      result, counts = apply_rules(text, rules)
      assert result == text
      assert not counts

  def test_apply_rules_regex():
      rules = load_rules(Path("transcribe/corrections.txt"))
      text = "The DJI F strategy is good"
      result, _ = apply_rules(text, rules)
      assert "DGIF" in result

  def test_load_rules_inline_comment(tmp_path):
      rules_file = tmp_path / "rules.txt"
      rules_file.write_text("foo => BAR  # this is a comment\n")
      rules = load_rules(rules_file)
      assert len(rules) == 1
      _, result = apply_rules("foo", rules)
      assert "BAR" in result

  def test_load_rules_missing_file():
      rules = load_rules(Path("/nonexistent/rules.txt"))
      assert rules == []
  ```

- Implement `src/transcribe/corrections.py` — direct extraction from `transcribe/corrections.py`:
  ```python
  """Deterministic post-processing corrections for transcripts.

  Rule file format (corrections.txt), one rule per line:
      wrong phrase => CORRECT     # literal, case-insensitive, whole-word
      re:PATTERN => REPLACEMENT   # raw regex (case-insensitive)
      # full-line and trailing "# ..." comments are ignored
  """
  from __future__ import annotations

  import re
  from pathlib import Path


  def load_rules(path: str | Path) -> list[tuple[re.Pattern, str]]:
      """Parse a rules file into (compiled_pattern, replacement) pairs."""
      rules: list[tuple[re.Pattern, str]] = []
      p = Path(path)
      if not p.exists():
          return rules
      for raw in p.read_text(encoding="utf-8").splitlines():
          line = raw.strip()
          if not line or line.startswith("#"):
              continue
          line = line.split("#", 1)[0].strip()
          if "=>" not in line:
              continue
          left, right = (s.strip() for s in line.split("=>", 1))
          if left.startswith("re:"):
              pat = re.compile(left[3:].strip(), re.IGNORECASE)
          else:
              pat = re.compile(rf"\b{re.escape(left)}\b", re.IGNORECASE)
          rules.append((pat, right))
      return rules


  def apply_rules(text: str, rules: list[tuple[re.Pattern, str]]) -> tuple[str, dict[str, int]]:
      """Apply all rules to text. Returns (corrected_text, {replacement: count})."""
      counts: dict[str, int] = {}
      for pat, repl in rules:
          text, n = pat.subn(repl, text)
          if n:
              counts[repl] = counts.get(repl, 0) + n
      return text, counts
  ```
- Run `uv run pytest tests/test_corrections.py`

### 3. Write `src/transcribe/whisper_runner.py` — Whisper transcription wrapper

- Write `tests/test_whisper_runner.py` first (mock faster-whisper):
  ```python
  """Tests for WhisperRunner — mock faster-whisper, test discovery and resumability."""
  import pytest
  from pathlib import Path
  from unittest.mock import patch, MagicMock, PropertyMock
  from src.transcribe.whisper_runner import WhisperRunner, VIDEO_EXTS

  @pytest.fixture
  def runner():
      return WhisperRunner(model="tiny", device="cpu", workers=1)

  def test_video_exts_includes_common():
      for ext in (".mp4", ".mkv", ".webm", ".mp3"):
          assert ext in VIDEO_EXTS

  def test_discover_videos(tmp_path):
      (tmp_path / "video1.mp4").touch()
      (tmp_path / "video2.mkv").touch()
      (tmp_path / "readme.txt").touch()
      (tmp_path / "image.png").touch()
      runner = WhisperRunner()
      vids = runner._discover_videos(tmp_path)
      assert len(vids) == 2
      names = {v.name for v in vids}
      assert "video1.mp4" in names
      assert "video2.mkv" in names

  def test_discover_videos_with_filter(tmp_path):
      (tmp_path / "Masterclass 1.mp4").touch()
      (tmp_path / "Masterclass 2.mp4").touch()
      (tmp_path / "Bonus.mp4").touch()
      runner = WhisperRunner()
      vids = runner._discover_videos(tmp_path, only="Masterclass 1")
      assert len(vids) == 1
      assert vids[0].name == "Masterclass 1.mp4"

  def test_is_done_both_exist(tmp_path):
      (tmp_path / "test.txt").write_text("hello")
      (tmp_path / "test.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n")
      runner = WhisperRunner()
      assert runner._is_done("test", tmp_path) is True

  def test_is_done_missing_srt(tmp_path):
      (tmp_path / "test.txt").write_text("hello")
      runner = WhisperRunner()
      assert runner._is_done("test", tmp_path) is False

  def test_is_done_both_missing(tmp_path):
      runner = WhisperRunner()
      assert runner._is_done("test", tmp_path) is False

  def test_fmt_ts():
      from src.transcribe.whisper_runner import fmt_ts
      assert fmt_ts(0.0) == "00:00:00,000"
      assert fmt_ts(3661.5) == "01:01:01,500"
      assert fmt_ts(59.999) == "00:01:00,000"  # rounding: 59999ms = 59.999s

  def test_transcribe_file_skips_done(tmp_path):
      video = tmp_path / "done.mp4"
      video.touch()
      out = tmp_path / "out"
      out.mkdir()
      (out / "done.txt").write_text("existing")
      (out / "done.srt").write_text("existing")
      runner = WhisperRunner()
      txt, srt = runner.transcribe_file(video, out)
      assert txt == out / "done.txt"
      assert srt == out / "done.srt"

  def test_transcribe_file_calls_whisper(tmp_path):
      video = tmp_path / "new.mp4"
      video.touch()
      out = tmp_path / "out"
      out.mkdir()

      mock_segment = MagicMock()
      mock_segment.text = " Hello world "
      mock_segment.start = 0.0
      mock_segment.end = 1.5

      mock_info = MagicMock()
      mock_info.duration = 1.5

      mock_model = MagicMock()
      mock_model.transcribe.return_value = ([mock_segment], mock_info)

      runner = WhisperRunner(model="tiny", device="cpu")
      runner._model = mock_model

      txt, srt = runner.transcribe_file(video, out)
      assert txt.exists()
      assert srt.exists()
      assert "Hello world" in txt.read_text()
      mock_model.transcribe.assert_called_once()

  def test_transcribe_file_applies_corrections(tmp_path):
      video = tmp_path / "new.mp4"
      video.touch()
      out = tmp_path / "out"
      out.mkdir()

      rules_file = tmp_path / "rules.txt"
      rules_file.write_text("hello => GOODBYE\n")

      mock_segment = MagicMock()
      mock_segment.text = " hello world "
      mock_segment.start = 0.0
      mock_segment.end = 1.5

      mock_info = MagicMock()
      mock_info.duration = 1.5

      mock_model = MagicMock()
      mock_model.transcribe.return_value = ([mock_segment], mock_info)

      runner = WhisperRunner(model="tiny", device="cpu")
      runner._model = mock_model

      txt, srt = runner.transcribe_file(video, out, corrections=rules_file)
      content = txt.read_text()
      assert "GOODBYE" in content
      assert "hello" not in content.lower().replace("goodbye", "")

  def test_device_auto_selects_cpu_or_cuda():
      """Auto device detection should not raise."""
      runner = WhisperRunner(device="auto")
      detected = runner._detect_device()
      assert detected in ("cpu", "cuda")
  ```

- Implement `src/transcribe/whisper_runner.py`:
  ```python
  """Whisper transcription wrapper — lazy model loading, resumable, with corrections."""
  from __future__ import annotations

  import logging
  import time
  from pathlib import Path

  from src.transcribe.corrections import apply_rules, load_rules

  log = logging.getLogger(__name__)

  VIDEO_EXTS = {".mkv", ".mp4", ".mov", ".m4v", ".webm", ".avi", ".mp3", ".m4a", ".wav"}


  def fmt_ts(seconds: float) -> str:
      """Seconds -> SRT timestamp HH:MM:SS,mmm."""
      ms = int(round(seconds * 1000))
      h, ms = divmod(ms, 3600_000)
      m, ms = divmod(ms, 60_000)
      s, ms = divmod(ms, 1000)
      return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


  class WhisperRunner:
      def __init__(
          self,
          model: str = "large-v3-turbo",
          device: str = "auto",
          workers: int = 1,
          compute_type: str = "int8",
          cpu_threads: int = 4,
          beam_size: int = 5,
          vocab_path: Path | None = None,
      ):
          self._model_name = model
          self._device = device
          self._workers = workers
          self._compute_type = compute_type
          self._cpu_threads = cpu_threads
          self._beam_size = beam_size
          self._model = None  # lazy loaded
          self._prompt = self._load_prompt(vocab_path) if vocab_path else None

      def _detect_device(self) -> str:
          if self._device != "auto":
              return self._device
          try:
              import torch
              return "cuda" if torch.cuda.is_available() else "cpu"
          except ImportError:
              return "cpu"

      def _ensure_model(self) -> None:
          if self._model is not None:
              return
          from faster_whisper import WhisperModel
          device = self._detect_device()
          log.info("Loading model %s on %s", self._model_name, device)
          self._model = WhisperModel(
              self._model_name,
              device=device,
              compute_type=self._compute_type,
              cpu_threads=self._cpu_threads,
          )

      @staticmethod
      def _load_prompt(path: Path) -> str | None:
          if path and path.exists():
              return " ".join(path.read_text(encoding="utf-8").split())
          return None

      @staticmethod
      def _is_done(stem: str, output_dir: Path) -> bool:
          return (output_dir / f"{stem}.txt").exists() and (output_dir / f"{stem}.srt").exists()

      def _discover_videos(self, folder: Path, only: str | None = None) -> list[Path]:
          return sorted(
              p for p in folder.iterdir()
              if p.suffix.lower() in VIDEO_EXTS
              and (not only or only.lower() in p.name.lower())
          )

      def transcribe_file(
          self,
          video_path: Path,
          output_dir: Path,
          corrections: Path | None = None,
      ) -> tuple[Path, Path]:
          """Transcribe a single video. Returns (txt_path, srt_path).

          Skips if both output files already exist (resumable).
          """
          stem = video_path.stem
          txt_path = output_dir / f"{stem}.txt"
          srt_path = output_dir / f"{stem}.srt"

          if self._is_done(stem, output_dir):
              log.info("SKIP %s (already done)", stem)
              return txt_path, srt_path

          self._ensure_model()
          rules = load_rules(corrections) if corrections else []

          t0 = time.monotonic()
          segments, info = self._model.transcribe(
              str(video_path),
              language="en",
              beam_size=self._beam_size,
              vad_filter=True,
              vad_parameters={"min_silence_duration_ms": 500},
              initial_prompt=self._prompt,
              condition_on_previous_text=True,
          )

          output_dir.mkdir(parents=True, exist_ok=True)
          tmp_srt = srt_path.with_suffix(".srt.part")
          txt_lines: list[str] = []

          with tmp_srt.open("w", encoding="utf-8") as srt:
              for i, seg in enumerate(segments, start=1):
                  text = seg.text.strip()
                  if rules:
                      text, _ = apply_rules(text, rules)
                  srt.write(f"{i}\n{fmt_ts(seg.start)} --> {fmt_ts(seg.end)}\n{text}\n\n")
                  txt_lines.append(text)

          tmp_srt.replace(srt_path)
          txt_path.write_text(" ".join(txt_lines) + "\n", encoding="utf-8")

          elapsed = time.monotonic() - t0
          duration = info.duration or 0.0
          rtf = (duration / elapsed) if elapsed else 0
          log.info("DONE %s (%.1fm audio / %.1fm wall, %.1fx)", stem, duration / 60, elapsed / 60, rtf)

          return txt_path, srt_path

      def transcribe_folder(
          self,
          folder: Path,
          output_dir: Path | None = None,
          only: str | None = None,
          corrections: Path | None = None,
      ) -> list[tuple[Path, Path]]:
          """Transcribe all videos in a folder. Returns list of (txt, srt) paths.

          Uses ProcessPoolExecutor when workers > 1 for parallel transcription.
          """
          out = output_dir or folder / "transcripts"
          vids = self._discover_videos(folder, only=only)
          if not vids:
              log.warning("No videos found in %s%s", folder, f" matching '{only}'" if only else "")
              return []

          log.info("%d video(s) to transcribe -> %s", len(vids), out)

          if self._workers <= 1:
              results = []
              for v in vids:
                  results.append(self.transcribe_file(v, out, corrections=corrections))
              return results

          # Multi-worker: use ProcessPoolExecutor like the original script
          from concurrent.futures import ProcessPoolExecutor, as_completed

          results = []
          with ProcessPoolExecutor(
              max_workers=min(self._workers, len(vids)),
              initializer=_init_worker,
              initargs=(
                  self._model_name, self._compute_type, self._cpu_threads,
                  self._prompt, self._beam_size,
                  str(corrections) if corrections else None,
              ),
          ) as ex:
              futs = {ex.submit(_transcribe_one_worker, str(v), str(out)): v for v in vids}
              for fut in as_completed(futs):
                  stem, status, txt_str, srt_str = fut.result()
                  results.append((Path(txt_str), Path(srt_str)))

          return results


  # --- Process pool worker functions (module-level for pickling) ---

  _WORKER_MODEL = None
  _WORKER_PROMPT = None
  _WORKER_BEAM = 5
  _WORKER_RULES: list = []


  def _init_worker(
      model_name: str, compute_type: str, cpu_threads: int,
      prompt: str | None, beam: int, corrections_path: str | None,
  ) -> None:
      global _WORKER_MODEL, _WORKER_PROMPT, _WORKER_BEAM, _WORKER_RULES
      from faster_whisper import WhisperModel
      _WORKER_MODEL = WhisperModel(model_name, device="cpu",
                                    compute_type=compute_type, cpu_threads=cpu_threads)
      _WORKER_PROMPT = prompt
      _WORKER_BEAM = beam
      _WORKER_RULES = load_rules(corrections_path) if corrections_path else []


  def _transcribe_one_worker(src_str: str, out_str: str) -> tuple[str, str, str, str]:
      """Worker function for ProcessPoolExecutor."""
      src = Path(src_str)
      out_dir = Path(out_str)
      stem = src.stem
      txt_path = out_dir / f"{stem}.txt"
      srt_path = out_dir / f"{stem}.srt"

      if txt_path.exists() and srt_path.exists():
          return (stem, "skip", str(txt_path), str(srt_path))

      segments, info = _WORKER_MODEL.transcribe(
          str(src), language="en", beam_size=_WORKER_BEAM,
          vad_filter=True, vad_parameters={"min_silence_duration_ms": 500},
          initial_prompt=_WORKER_PROMPT, condition_on_previous_text=True,
      )

      out_dir.mkdir(parents=True, exist_ok=True)
      tmp_srt = srt_path.with_suffix(".srt.part")
      txt_lines: list[str] = []
      with tmp_srt.open("w", encoding="utf-8") as srt:
          for i, seg in enumerate(segments, start=1):
              text = seg.text.strip()
              if _WORKER_RULES:
                  text, _ = apply_rules(text, _WORKER_RULES)
              srt.write(f"{i}\n{fmt_ts(seg.start)} --> {fmt_ts(seg.end)}\n{text}\n\n")
              txt_lines.append(text)
      tmp_srt.replace(srt_path)
      txt_path.write_text(" ".join(txt_lines) + "\n", encoding="utf-8")

      return (stem, "done", str(txt_path), str(srt_path))
  ```

  Key design decisions:
  - Single-worker mode uses `self._model` directly (lazy-loaded once)
  - Multi-worker mode uses ProcessPoolExecutor with module-level `_init_worker`/`_transcribe_one_worker` (same pattern as `transcribe/transcribe.py`)
  - `device="auto"` checks `torch.cuda.is_available()` with ImportError fallback to CPU
  - `faster_whisper` imported lazily inside `_ensure_model()`, not at module level

- Run `uv run pytest tests/test_whisper_runner.py`

### 4. Write `src/transcribe/visual_gaps.py` — Gap detector

- Write `tests/test_visual_gaps.py` first:
  ```python
  """Tests for visual gap detection — pattern matching on SRT content."""
  import pytest
  from pathlib import Path
  from src.transcribe.visual_gaps import (
      Gap, find_gaps, find_gaps_in_folder, parse_srt, DEFAULT_PATTERNS,
  )

  SAMPLE_SRT = """\
  1
  00:00:01,000 --> 00:00:05,000
  Welcome to the course.

  2
  00:00:05,000 --> 00:00:10,000
  Today we'll look at investing basics.

  3
  00:00:10,000 --> 00:00:15,000
  Take a look at this chart on the screen.

  4
  00:00:15,000 --> 00:00:20,000
  As you can see, the numbers are clear.

  5
  00:00:20,000 --> 00:00:25,000
  Let's move on to the next topic.
  """

  @pytest.fixture
  def srt_file(tmp_path):
      f = tmp_path / "test.srt"
      f.write_text(SAMPLE_SRT, encoding="utf-8")
      return f

  def test_parse_srt(srt_file):
      entries = parse_srt(srt_file)
      assert len(entries) == 5
      assert entries[0]["index"] == 1
      assert entries[0]["text"] == "Welcome to the course."
      assert "00:00:01" in entries[0]["timestamp"]

  def test_find_gaps_detects_visual_patterns(srt_file):
      gaps = find_gaps(srt_file)
      assert len(gaps) >= 2
      patterns = [g.pattern for g in gaps]
      assert "take a look" in patterns
      assert "as you can see" in patterns

  def test_find_gaps_includes_context(srt_file):
      gaps = find_gaps(srt_file)
      for gap in gaps:
          assert gap.context_before is not None
          assert gap.context_after is not None

  def test_find_gaps_custom_patterns(srt_file):
      gaps = find_gaps(srt_file, patterns=["investing"])
      assert len(gaps) == 1
      assert gaps[0].pattern == "investing"

  def test_find_gaps_no_matches(srt_file):
      gaps = find_gaps(srt_file, patterns=["xyznotfound"])
      assert gaps == []

  def test_find_gaps_in_folder(tmp_path):
      (tmp_path / "lesson1.srt").write_text(SAMPLE_SRT, encoding="utf-8")
      (tmp_path / "lesson2.srt").write_text(SAMPLE_SRT, encoding="utf-8")
      result = find_gaps_in_folder(tmp_path)
      assert len(result) == 2
      assert "lesson1" in result
      assert "lesson2" in result

  def test_find_gaps_in_folder_empty(tmp_path):
      result = find_gaps_in_folder(tmp_path)
      assert result == {}

  def test_gap_dataclass():
      gap = Gap(
          file="test.srt", subtitle_index=3, timestamp="00:00:10,000 --> 00:00:15,000",
          pattern="take a look", text="Take a look at this chart.",
          context_before=[], context_after=[],
      )
      assert gap.file == "test.srt"
      assert gap.pattern == "take a look"

  def test_default_patterns_not_empty():
      assert len(DEFAULT_PATTERNS) > 10
  ```

- Implement `src/transcribe/visual_gaps.py`:
  ```python
  """Visual-context gap detection in SRT transcripts.

  Scans for phrases indicating on-screen content that audio alone misses.
  """
  from __future__ import annotations

  import re
  from dataclasses import dataclass, field
  from pathlib import Path


  @dataclass
  class Gap:
      file: str
      subtitle_index: int
      timestamp: str
      pattern: str
      text: str
      context_before: list[dict] = field(default_factory=list)
      context_after: list[dict] = field(default_factory=list)


  DEFAULT_PATTERNS = [
      "as you can see", "you can see", "we can see", "i can see",
      "you'll see", "what you see", "if we look", "take a look",
      "look at", "let me show you", "i'll show you", "shown here",
      "displayed", "right here", "over here", "down here", "up here",
      "on screen", "on the screen", "on this slide",
      "this chart", "this graph", "the table", "this table",
      "the figure", "this figure", "on the blueprint",
      "in the portfolio", "on fidelity", "on seeking alpha",
      "the ticker", "this number", "these numbers",
      "this spreadsheet", "the spreadsheet", "on morningstar",
      "this formula", "the formula",
  ]


  def parse_srt(filepath: Path) -> list[dict]:
      """Parse an SRT file into a list of subtitle entries."""
      content = filepath.read_text(encoding="utf-8")
      entries = []
      blocks = re.split(r"\n\n+", content.strip())
      for block in blocks:
          lines = block.strip().split("\n")
          if len(lines) < 3:
              continue
          try:
              index = int(lines[0].strip())
          except ValueError:
              continue
          timestamp = lines[1].strip()
          text = " ".join(lines[2:]).strip()
          entries.append({"index": index, "timestamp": timestamp, "text": text})
      return entries


  def find_gaps(
      srt_path: Path,
      patterns: list[str] | None = None,
  ) -> list[Gap]:
      """Find visual-context gaps in an SRT file."""
      pats = patterns or DEFAULT_PATTERNS
      compiled = [(re.compile(rf"\b{re.escape(p)}\b", re.IGNORECASE), p) for p in pats]
      entries = parse_srt(srt_path)
      gaps = []

      for i, entry in enumerate(entries):
          for pat_re, pat_name in compiled:
              if pat_re.search(entry["text"]):
                  context_before = [
                      {"timestamp": entries[j]["timestamp"], "text": entries[j]["text"]}
                      for j in range(max(0, i - 2), i)
                  ]
                  context_after = [
                      {"timestamp": entries[j]["timestamp"], "text": entries[j]["text"]}
                      for j in range(i + 1, min(len(entries), i + 3))
                  ]
                  gaps.append(Gap(
                      file=srt_path.name,
                      subtitle_index=entry["index"],
                      timestamp=entry["timestamp"],
                      pattern=pat_name,
                      text=entry["text"],
                      context_before=context_before,
                      context_after=context_after,
                  ))
                  break

      return gaps


  def find_gaps_in_folder(
      transcripts_dir: Path,
      patterns: list[str] | None = None,
  ) -> dict[str, list[Gap]]:
      """Find visual gaps across all SRT files in a folder."""
      result: dict[str, list[Gap]] = {}
      srt_files = sorted(transcripts_dir.glob("*.srt"))
      for srt_file in srt_files:
          gaps = find_gaps(srt_file, patterns=patterns)
          if gaps:
              result[srt_file.stem] = gaps
      return result
  ```

  Key design decisions:
  - `Gap` is a dataclass (not a dict) for type safety and IDE support
  - `find_gaps` works on a single file; `find_gaps_in_folder` iterates a directory
  - Custom patterns override defaults entirely (not additive) — this matches how the user will likely want to use it per-course
  - Patterns are whole-word escaped (not raw regex like the original) since the default list contains plain phrases. Users can pass pre-compiled patterns for advanced use cases.

- Run `uv run pytest tests/test_visual_gaps.py`

### 5. Write `src/analyze/quality.py` — Video quality analysis

- Write `tests/test_quality.py` first (mock ffmpeg/ffprobe):
  ```python
  """Tests for QualityAnalyzer — mock ffmpeg output, test verdict logic."""
  import json
  import pytest
  from unittest.mock import patch, MagicMock
  from pathlib import Path
  from src.analyze.quality import (
      QualityAnalyzer, QualityReport,
      compute_verdict, compute_trim_points,
  )

  @pytest.fixture
  def analyzer():
      return QualityAnalyzer()

  def test_quality_report_dataclass():
      r = QualityReport(
          filename="test.mkv", duration=1800.0,
          resolution=(1920, 1080), verdict="clean",
          black_frames=[], silence_gaps=[], bitrate_drops=[],
          freezes=[], notes="No issues",
      )
      assert r.filename == "test.mkv"
      assert r.resolution == (1920, 1080)

  def test_verdict_clean():
      verdict, notes = compute_verdict(
          black_frames=[], freezes=[],
          silence_gaps=[], bitrate_drops=[],
          trim_start=None, trim_end=None,
      )
      assert verdict == "clean"

  def test_verdict_trim_needed():
      verdict, _ = compute_verdict(
          black_frames=[{"location": "start", "duration": 2.0}],
          freezes=[], silence_gaps=[], bitrate_drops=[],
          trim_start=2.0, trim_end=None,
      )
      assert verdict == "trim_needed"

  def test_verdict_has_issues_freezes():
      verdict, _ = compute_verdict(
          black_frames=[], silence_gaps=[], bitrate_drops=[],
          freezes=[{"duration": 5.0}],
          trim_start=None, trim_end=None,
      )
      assert verdict == "has_issues"

  def test_verdict_re_record_long_freeze():
      verdict, _ = compute_verdict(
          black_frames=[], silence_gaps=[], bitrate_drops=[],
          freezes=[{"duration": 15.0}],
          trim_start=None, trim_end=None,
      )
      assert verdict == "re_record"

  def test_verdict_re_record_many_freezes():
      verdict, _ = compute_verdict(
          black_frames=[], silence_gaps=[], bitrate_drops=[],
          freezes=[{"duration": 4.0}] * 5,
          trim_start=None, trim_end=None,
      )
      assert verdict == "re_record"

  def test_verdict_re_record_long_silence():
      verdict, _ = compute_verdict(
          black_frames=[], freezes=[], bitrate_drops=[],
          silence_gaps=[{"duration": 35.0}],
          trim_start=None, trim_end=None,
      )
      assert verdict == "re_record"

  def test_trim_points_start_black():
      trim_s, trim_e = compute_trim_points(
          duration=1800.0,
          black_frames=[{"location": "start", "start": 0.0, "end": 3.5, "duration": 3.5}],
      )
      assert trim_s == 3.5
      assert trim_e is None

  def test_trim_points_end_black():
      trim_s, trim_e = compute_trim_points(
          duration=1800.0,
          black_frames=[{"location": "end", "start": 1795.0, "end": 1800.0, "duration": 5.0}],
      )
      assert trim_s is None
      assert trim_e == 1795.0

  def test_trim_points_too_small_ignored():
      trim_s, trim_e = compute_trim_points(
          duration=1800.0,
          black_frames=[{"location": "start", "start": 0.0, "end": 0.3, "duration": 0.3}],
      )
      assert trim_s is None

  @patch("src.analyze.quality._run_cmd")
  def test_analyze_calls_ffprobe(mock_run, analyzer, tmp_path):
      video = tmp_path / "test.mkv"
      video.write_bytes(b"fake")

      probe_result = MagicMock()
      probe_result.returncode = 0
      probe_result.stdout = json.dumps({
          "format": {"duration": "1800.0", "bit_rate": "5000000"},
          "streams": [{"codec_type": "video", "width": 1920, "height": 1080, "codec_name": "h264"}],
      })

      # Return probe result for ffprobe, then empty for each ffmpeg detection pass
      empty_result = MagicMock()
      empty_result.returncode = 0
      empty_result.stderr = ""
      empty_result.stdout = ""

      mock_run.side_effect = [probe_result] + [empty_result] * 10

      report = analyzer.analyze(video)
      assert report.filename == "test.mkv"
      assert report.duration == 1800.0
      assert report.resolution == (1920, 1080)
      assert report.verdict == "clean"
  ```

- Implement `src/analyze/quality.py` — extract from `acquire/video_analyzer_remote.py`:
  ```python
  """Video quality analysis using ffmpeg subprocess calls."""
  from __future__ import annotations

  import json
  import logging
  import re
  import subprocess
  from dataclasses import dataclass, field
  from pathlib import Path

  log = logging.getLogger(__name__)

  # Detection thresholds (from video_analyzer_remote.py)
  BLACK_DETECT_DURATION = 0.5
  BLACK_DETECT_PIX_TH = 0.10
  BLACK_HEAD_WINDOW = 60
  BLACK_TAIL_WINDOW = 120
  FREEZE_NOISE_TH = 0.003
  FREEZE_MIN_DURATION = 3
  FREEZE_FLAG_DURATION = 10
  FREEZE_FLAG_COUNT = 3
  SILENCE_DB = -50
  SILENCE_MIN_DURATION = 5
  BITRATE_DROP_THRESHOLD = 0.50
  BITRATE_DROP_MIN_DURATION = 5


  @dataclass
  class QualityReport:
      filename: str
      duration: float
      resolution: tuple[int, int]
      verdict: str
      black_frames: list[dict] = field(default_factory=list)
      silence_gaps: list[dict] = field(default_factory=list)
      bitrate_drops: list[dict] = field(default_factory=list)
      freezes: list[dict] = field(default_factory=list)
      notes: str = ""
      trim_start: float | None = None
      trim_end: float | None = None
      codec: str = ""
      avg_bitrate_kbps: float = 0.0
      file_size_mb: float = 0.0


  def _run_cmd(cmd: list[str], *, timeout: int = 600) -> subprocess.CompletedProcess:
      try:
          return subprocess.run(
              cmd, capture_output=True, text=True,
              timeout=timeout, encoding="utf-8", errors="replace",
          )
      except subprocess.TimeoutExpired:
          return subprocess.CompletedProcess(
              args=cmd, returncode=-1, stdout="", stderr=f"TIMEOUT after {timeout}s",
          )


  def _parse_float(value: str | None, default: float = 0.0) -> float:
      if not value:
          return default
      try:
          return float(value)
      except (ValueError, TypeError):
          return default


  def compute_trim_points(
      duration: float, black_frames: list[dict],
  ) -> tuple[float | None, float | None]:
      # Extracted from video_analyzer_remote.py compute_trim_points
      trim_start: float | None = None
      trim_end: float | None = None
      for bf in black_frames:
          if bf["location"] == "start":
              candidate = bf["end"]
              if trim_start is None or candidate > trim_start:
                  trim_start = candidate
          elif bf["location"] == "end":
              candidate = bf["start"]
              if trim_end is None or candidate < trim_end:
                  trim_end = candidate
      if trim_start is not None and trim_end is not None and trim_start >= trim_end:
          trim_start = trim_end = None
      if trim_start is not None and trim_start < 0.5:
          trim_start = None
      if trim_end is not None and (duration - trim_end) < 0.5:
          trim_end = None
      return trim_start, trim_end


  def compute_verdict(
      *, black_frames, freezes, silence_gaps, bitrate_drops,
      trim_start, trim_end,
  ) -> tuple[str, str]:
      # Extracted from video_analyzer_remote.py compute_verdict (see source for full logic)
      ...


  class QualityAnalyzer:
      def __init__(self, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe"):
          self._ffmpeg = ffmpeg
          self._ffprobe = ffprobe

      def analyze(self, video_path: Path) -> QualityReport:
          """Run all analysis passes on a single video file."""
          ...

      def analyze_folder(
          self, folder: Path, single: str | None = None,
      ) -> list[QualityReport]:
          """Analyze all videos in a folder."""
          ...
  ```

  Implementation notes:
  - `ffmpeg` and `ffprobe` paths are configurable (default to PATH-resolved names, not the Windows hardcoded paths from `video_analyzer_remote.py`)
  - All five analysis passes extracted: `probe_metadata`, `detect_black_frames`, `detect_freezes`, `detect_silence`, `analyze_bitrate`
  - `compute_verdict` and `compute_trim_points` are standalone functions (testable without ffmpeg)
  - `_run_cmd` helper wraps subprocess with timeout handling

- Run `uv run pytest tests/test_quality.py`

### 6. Write `src/analyze/frames.py` — Frame extraction at timestamps

- Write `tests/test_frames.py` first (mock ffmpeg):
  ```python
  """Tests for frame extraction — mock ffmpeg, test timestamp formatting."""
  import pytest
  from pathlib import Path
  from unittest.mock import patch, MagicMock
  from src.analyze.frames import extract_frame, extract_frames_from_gaps
  from src.transcribe.visual_gaps import Gap

  @patch("src.analyze.frames._run_cmd")
  def test_extract_frame_calls_ffmpeg(mock_run, tmp_path):
      mock_run.return_value = MagicMock(returncode=0)
      video = tmp_path / "test.mp4"
      video.touch()
      output = tmp_path / "frame.jpg"

      result = extract_frame(video, 65.5, output)
      assert result == output
      cmd = mock_run.call_args[0][0]
      assert "-ss" in cmd
      assert "65.5" in cmd or "65.500" in cmd
      assert "-frames:v" in cmd
      assert "1" in cmd

  @patch("src.analyze.frames._run_cmd")
  def test_extract_frame_failure(mock_run, tmp_path):
      mock_run.return_value = MagicMock(returncode=1, stderr="error")
      video = tmp_path / "test.mp4"
      video.touch()
      output = tmp_path / "frame.jpg"

      result = extract_frame(video, 10.0, output)
      assert result is None

  @patch("src.analyze.frames.extract_frame")
  def test_extract_frames_from_gaps(mock_extract, tmp_path):
      mock_extract.side_effect = lambda v, t, o: o
      video = tmp_path / "test.mp4"
      video.touch()
      out_dir = tmp_path / "frames"
      out_dir.mkdir()

      gaps = [
          Gap(file="test.srt", subtitle_index=3,
              timestamp="00:01:05,000 --> 00:01:10,000",
              pattern="take a look", text="Take a look"),
          Gap(file="test.srt", subtitle_index=7,
              timestamp="00:02:30,500 --> 00:02:35,000",
              pattern="this chart", text="This chart"),
      ]

      paths = extract_frames_from_gaps(video, gaps, out_dir)
      assert len(paths) == 2
      assert mock_extract.call_count == 2

  def test_parse_srt_timestamp():
      from src.analyze.frames import parse_srt_timestamp
      assert parse_srt_timestamp("01:02:03,500") == 3723.5
      assert parse_srt_timestamp("00:00:10,000") == 10.0
      assert parse_srt_timestamp("00:01:05,000") == 65.0
  ```

- Implement `src/analyze/frames.py`:
  ```python
  """Frame extraction from videos at specific timestamps using ffmpeg."""
  from __future__ import annotations

  import logging
  import re
  import subprocess
  from pathlib import Path

  log = logging.getLogger(__name__)


  def _run_cmd(cmd: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess:
      try:
          return subprocess.run(
              cmd, capture_output=True, text=True, timeout=timeout,
          )
      except subprocess.TimeoutExpired:
          return subprocess.CompletedProcess(
              args=cmd, returncode=-1, stdout="", stderr="TIMEOUT",
          )


  def parse_srt_timestamp(ts: str) -> float:
      """Parse 'HH:MM:SS,mmm' or 'HH:MM:SS,mmm --> ...' to seconds."""
      # Take only the start timestamp if a range is given
      ts = ts.split("-->")[0].strip()
      match = re.match(r"(\d+):(\d+):(\d+)[,.](\d+)", ts)
      if not match:
          return 0.0
      h, m, s, ms = match.groups()
      return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


  def extract_frame(
      video_path: Path,
      timestamp: float,
      output_path: Path,
      ffmpeg: str = "ffmpeg",
  ) -> Path | None:
      """Extract a single frame at the given timestamp."""
      output_path.parent.mkdir(parents=True, exist_ok=True)
      result = _run_cmd([
          ffmpeg,
          "-ss", f"{timestamp:.3f}",
          "-i", str(video_path),
          "-frames:v", "1",
          "-q:v", "2",
          str(output_path),
      ])
      if result.returncode != 0:
          log.error("Frame extraction failed at %.1fs: %s", timestamp, result.stderr[:200])
          return None
      return output_path


  def extract_frames_from_gaps(
      video_path: Path,
      gaps: list,  # list[Gap] — avoid circular import
      output_dir: Path,
      ffmpeg: str = "ffmpeg",
  ) -> list[Path]:
      """Extract frames at each gap's timestamp."""
      output_dir.mkdir(parents=True, exist_ok=True)
      paths: list[Path] = []
      for i, gap in enumerate(gaps):
          ts = parse_srt_timestamp(gap.timestamp)
          out = output_dir / f"gap_{i:04d}_{ts:.0f}s.jpg"
          result = extract_frame(video_path, ts, out, ffmpeg=ffmpeg)
          if result:
              paths.append(result)
      return paths
  ```

- Run `uv run pytest tests/test_frames.py`

### 7. Write `src/analyze/ocr.py` — OCR wrapper

- No dedicated test file — OCR depends on `rapidocr-onnxruntime` which is in the `[ocr]` optional extra. Write minimal tests that verify the module imports and the interface, mocking the OCR engine:
  ```python
  # Add to tests/test_frames.py or create tests/test_ocr.py:
  """Tests for OCR wrapper — mock RapidOCR."""
  from pathlib import Path
  from unittest.mock import patch, MagicMock

  def test_ocr_image_mocked(tmp_path):
      # Create a fake image file
      img = tmp_path / "test.png"
      img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

      with patch("src.analyze.ocr._get_engine") as mock_engine:
          mock_engine.return_value = MagicMock(
              return_value=([[None, "Hello World", None]], None)
          )
          from src.analyze.ocr import ocr_image
          text = ocr_image(img)
          assert "Hello World" in text

  def test_ocr_frames_mocked(tmp_path):
      for i in range(3):
          (tmp_path / f"frame_{i}.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

      with patch("src.analyze.ocr._get_engine") as mock_engine:
          mock_engine.return_value = MagicMock(
              return_value=([[None, f"Text", None]], None)
          )
          from src.analyze.ocr import ocr_frames
          results = ocr_frames(tmp_path)
          assert len(results) == 3
  ```

- Implement `src/analyze/ocr.py`:
  ```python
  """OCR wrapper — lazy RapidOCR for frame text extraction."""
  from __future__ import annotations

  import logging
  from pathlib import Path

  log = logging.getLogger(__name__)

  _ENGINE = None


  def _get_engine():
      global _ENGINE
      if _ENGINE is None:
          from rapidocr_onnxruntime import RapidOCR
          _ENGINE = RapidOCR()
      return _ENGINE


  def ocr_image(image_path: Path) -> str:
      """Run OCR on a single image file. Returns extracted text."""
      import numpy as np
      from PIL import Image

      engine = _get_engine()
      img = np.array(Image.open(image_path))
      result, _ = engine(img)
      if not result:
          return ""
      return "\n".join(line[1] for line in result)


  def ocr_frames(frames_dir: Path) -> dict[str, str]:
      """Run OCR on all image files in a directory. Returns {filename: text}."""
      results: dict[str, str] = {}
      image_exts = {".png", ".jpg", ".jpeg", ".bmp", ".tiff"}
      for img_path in sorted(frames_dir.iterdir()):
          if img_path.suffix.lower() in image_exts:
              text = ocr_image(img_path)
              results[img_path.name] = text
      return results
  ```

  Implementation notes:
  - `_get_engine()` creates the RapidOCR engine lazily (one instance reused)
  - `rapidocr_onnxruntime`, `numpy`, `PIL` imported inside functions — not at module level
  - Interface matches what the Pipeline needs: `ocr_image(path) -> str` and `ocr_frames(dir) -> dict`

### 8. Write `src/transfer/sync.py` — Cross-machine transfer

- Write tests (mock subprocess for SSH/SCP):
  ```python
  # tests/test_transfer.py
  """Tests for TransferClient — mock SSH/SCP subprocess calls."""
  import pytest
  from pathlib import Path
  from unittest.mock import patch, MagicMock
  from src.transfer.sync import TransferClient

  @pytest.fixture
  def client():
      return TransferClient(host="testhost")

  @patch("src.transfer.sync.subprocess.run")
  def test_upload_success(mock_run, client, tmp_path):
      mock_run.return_value = MagicMock(returncode=0)
      local = tmp_path / "test.txt"
      local.write_text("hello")
      assert client.upload(local, "/remote/test.txt") is True

  @patch("src.transfer.sync.subprocess.run")
  def test_upload_failure(mock_run, client, tmp_path):
      mock_run.return_value = MagicMock(returncode=1, stderr="connection refused")
      local = tmp_path / "test.txt"
      local.write_text("hello")
      assert client.upload(local, "/remote/test.txt") is False

  @patch("src.transfer.sync.subprocess.run")
  def test_download_success(mock_run, client, tmp_path):
      mock_run.return_value = MagicMock(returncode=0)
      result = client.download("/remote/test.txt", tmp_path / "test.txt")
      assert result == tmp_path / "test.txt"

  @patch("src.transfer.sync.subprocess.run")
  def test_download_failure(mock_run, client, tmp_path):
      mock_run.return_value = MagicMock(returncode=1, stderr="not found")
      result = client.download("/remote/test.txt", tmp_path / "test.txt")
      assert result is None

  @patch("src.transfer.sync.subprocess.run")
  def test_sync_transcripts_filters_existing(mock_run, client, tmp_path):
      # First call: ssh ls returns file list
      ls_result = MagicMock(returncode=0, stdout="file1.srt\nfile2.txt\nfile3.srt\n")
      # Subsequent calls: scp
      scp_result = MagicMock(returncode=0)
      mock_run.side_effect = [ls_result, scp_result, scp_result]

      # file1.srt already exists locally
      (tmp_path / "file1.srt").write_text("existing")

      synced = client.sync_transcripts("/remote/dir/", tmp_path)
      assert "file2.txt" in synced
      assert "file3.srt" in synced
      assert "file1.srt" not in synced
  ```

- Implement `src/transfer/sync.py`:
  ```python
  """Cross-machine file transfer via SCP/SSH."""
  from __future__ import annotations

  import logging
  import subprocess
  from pathlib import Path

  from src.config import SSH_HOST, SSH_OPTS

  log = logging.getLogger(__name__)


  class TransferClient:
      def __init__(self, host: str = SSH_HOST, ssh_opts: list[str] | None = None):
          self._host = host
          self._ssh_opts = ssh_opts if ssh_opts is not None else list(SSH_OPTS)

      def _ssh_run(self, command: str, timeout: int = 30) -> subprocess.CompletedProcess:
          return subprocess.run(
              ["ssh", *self._ssh_opts, self._host, command],
              capture_output=True, text=True, timeout=timeout,
          )

      def upload(self, local: Path, remote: str) -> bool:
          result = subprocess.run(
              ["scp", *self._ssh_opts, str(local), f"{self._host}:{remote}"],
              capture_output=True, text=True, timeout=120,
          )
          if result.returncode != 0:
              log.error("Upload failed: %s", result.stderr.strip()[:200])
              return False
          return True

      def download(self, remote: str, local: Path) -> Path | None:
          local.parent.mkdir(parents=True, exist_ok=True)
          result = subprocess.run(
              ["scp", *self._ssh_opts, f"{self._host}:{remote}", str(local)],
              capture_output=True, text=True, timeout=120,
          )
          if result.returncode != 0:
              log.error("Download failed: %s", result.stderr.strip()[:200])
              return None
          return local

      def sync_transcripts(
          self, remote_dir: str, local_dir: Path, force: bool = False,
      ) -> list[str]:
          """Sync transcript files from remote to local, skipping existing."""
          local_dir.mkdir(parents=True, exist_ok=True)

          result = self._ssh_run(
              f'Get-ChildItem -Path "{remote_dir}" -File -Include "*.srt","*.txt" -Name'
          )
          if result.returncode != 0:
              log.error("Could not list remote files: %s", result.stderr.strip()[:200])
              return []

          remote_files = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
          if not remote_files:
              return []

          local_existing = {f.name for f in local_dir.iterdir() if f.is_file()}
          to_transfer = remote_files if force else [f for f in remote_files if f not in local_existing]

          synced: list[str] = []
          for filename in to_transfer:
              remote_path = f"{remote_dir}{filename}"
              local_path = local_dir / filename
              dl = self.download(remote_path, local_path)
              if dl:
                  synced.append(filename)

          return synced
  ```

- Run `uv run pytest tests/test_transfer.py`

### 9. Write `src/pipeline/runner.py` — End-to-end pipeline orchestrator

- Write `tests/test_pipeline.py` first (mock all components):
  ```python
  """Tests for Pipeline — mock all components, test step filtering and error handling."""
  import pytest
  from pathlib import Path
  from unittest.mock import AsyncMock, MagicMock, patch
  from src.pipeline.runner import Pipeline, STEPS

  def test_default_steps_all():
      assert len(STEPS) >= 5

  def test_step_names():
      for step in STEPS:
          assert isinstance(step, str)
      assert "transcribe" in STEPS
      assert "analyze" in STEPS

  @pytest.mark.asyncio
  async def test_pipeline_runs_selected_steps():
      mock_source = MagicMock()
      mock_engine = MagicMock()
      pipeline = Pipeline(source=mock_source, engine=mock_engine)

      with patch.object(pipeline, "_step_transcribe", new_callable=AsyncMock) as mock_t, \
           patch.object(pipeline, "_step_correct", new_callable=AsyncMock) as mock_c:
          await pipeline.run([], steps=["transcribe", "correct"])
          # With empty queue, the step methods are not called per-video,
          # but the filtering logic itself is validated

  @pytest.mark.asyncio
  async def test_pipeline_continues_on_failure():
      mock_source = MagicMock()
      mock_engine = MagicMock()
      pipeline = Pipeline(source=mock_source, engine=mock_engine)

      # Simulate two posts; first raises, second succeeds
      posts = [
          MagicMock(url="http://a", filename="a", title="A"),
          MagicMock(url="http://b", filename="b", title="B"),
      ]

      with patch.object(pipeline, "_process_one", new_callable=AsyncMock) as mock_p:
          mock_p.side_effect = [Exception("fail"), None]
          results = await pipeline.run(posts, steps=["transcribe"])
          assert mock_p.call_count == 2

  @pytest.mark.asyncio
  async def test_pipeline_step_filtering():
      mock_source = MagicMock()
      mock_engine = MagicMock()
      pipeline = Pipeline(source=mock_source, engine=mock_engine)

      valid = pipeline._validate_steps(["transcribe", "correct"])
      assert valid == ["transcribe", "correct"]

  @pytest.mark.asyncio
  async def test_pipeline_invalid_step_raises():
      mock_source = MagicMock()
      mock_engine = MagicMock()
      pipeline = Pipeline(source=mock_source, engine=mock_engine)

      with pytest.raises(ValueError, match="Unknown"):
          pipeline._validate_steps(["nonexistent_step"])
  ```

- Implement `src/pipeline/runner.py`:
  ```python
  """End-to-end pipeline orchestrator — chains record, analyze, transcribe, etc."""
  from __future__ import annotations

  import asyncio
  import logging
  from dataclasses import dataclass, field
  from pathlib import Path
  from typing import TYPE_CHECKING

  if TYPE_CHECKING:
      from src.engines.base import CaptureEngine
      from src.sources.base import Post, Source

  log = logging.getLogger(__name__)

  STEPS = [
      "record",
      "analyze",
      "transcribe",
      "correct",
      "find_gaps",
      "extract_frames",
      "ocr",
  ]


  @dataclass
  class PipelineResult:
      post_url: str
      post_title: str
      steps_completed: list[str] = field(default_factory=list)
      steps_failed: dict[str, str] = field(default_factory=dict)
      output_paths: dict[str, str] = field(default_factory=dict)


  class Pipeline:
      def __init__(self, source, engine, output_dir: Path | None = None):
          self._source = source
          self._engine = engine
          self._output_dir = output_dir or Path(".")

      def _validate_steps(self, steps: list[str]) -> list[str]:
          for s in steps:
              if s not in STEPS:
                  raise ValueError(f"Unknown step: {s}. Valid: {STEPS}")
          return steps

      async def run(
          self,
          queue: list,
          steps: list[str] | None = None,
      ) -> list[PipelineResult]:
          """Run pipeline steps on each post in queue.

          Continues on individual video failure.
          """
          active_steps = self._validate_steps(steps) if steps else STEPS
          results: list[PipelineResult] = []

          for post in queue:
              try:
                  result = await self._process_one(post, active_steps)
                  results.append(result)
              except Exception as exc:
                  log.error("Pipeline failed for %s: %s", getattr(post, 'url', post), exc)
                  results.append(PipelineResult(
                      post_url=getattr(post, 'url', str(post)),
                      post_title=getattr(post, 'title', ''),
                      steps_failed={"pipeline": str(exc)},
                  ))

          return results

      async def _process_one(self, post, steps: list[str]) -> PipelineResult:
          result = PipelineResult(
              post_url=post.url,
              post_title=post.title,
          )

          for step in steps:
              try:
                  method = getattr(self, f"_step_{step}")
                  await method(post, result)
                  result.steps_completed.append(step)
              except Exception as exc:
                  log.error("Step '%s' failed for %s: %s", step, post.title, exc)
                  result.steps_failed[step] = str(exc)

          return result

      async def _step_record(self, post, result: PipelineResult) -> None:
          from src.capture.recorder import Recorder
          from src.cdp import CDPClient
          recorder = Recorder(self._engine)
          async with CDPClient() as cdp:
              rec = await recorder.record_one(cdp, post.url, post.filename)
              if rec.ok:
                  result.output_paths["recording"] = rec.output_path or ""
              else:
                  raise RuntimeError(rec.error or "Recording failed")

      async def _step_analyze(self, post, result: PipelineResult) -> None:
          from src.analyze.quality import QualityAnalyzer
          recording = result.output_paths.get("recording")
          if not recording:
              log.warning("No recording path — skipping analyze")
              return
          analyzer = QualityAnalyzer()
          report = analyzer.analyze(Path(recording))
          if report.verdict == "re_record":
              log.warning("Quality verdict: RE_RECORD for %s", post.title)

      async def _step_transcribe(self, post, result: PipelineResult) -> None:
          from src.transcribe.whisper_runner import WhisperRunner
          recording = result.output_paths.get("recording")
          if not recording:
              log.warning("No recording path — skipping transcribe")
              return
          runner = WhisperRunner()
          out_dir = Path(recording).parent / "transcripts"
          txt, srt = runner.transcribe_file(Path(recording), out_dir)
          result.output_paths["transcript_txt"] = str(txt)
          result.output_paths["transcript_srt"] = str(srt)

      async def _step_correct(self, post, result: PipelineResult) -> None:
          from src.transcribe.corrections import apply_rules, load_rules
          srt_path = result.output_paths.get("transcript_srt")
          txt_path = result.output_paths.get("transcript_txt")
          if not srt_path or not txt_path:
              log.warning("No transcript paths — skipping correct")
              return
          corrections_file = Path("transcribe/corrections.txt")
          if not corrections_file.exists():
              return
          rules = load_rules(corrections_file)
          if not rules:
              return
          for path_str in (srt_path, txt_path):
              p = Path(path_str)
              if p.exists():
                  text = p.read_text(encoding="utf-8")
                  corrected, counts = apply_rules(text, rules)
                  if counts:
                      p.write_text(corrected, encoding="utf-8")
                      log.info("Applied %d corrections to %s", sum(counts.values()), p.name)

      async def _step_find_gaps(self, post, result: PipelineResult) -> None:
          from src.transcribe.visual_gaps import find_gaps
          srt_path = result.output_paths.get("transcript_srt")
          if not srt_path:
              return
          gaps = find_gaps(Path(srt_path))
          result.output_paths["gaps_count"] = str(len(gaps))

      async def _step_extract_frames(self, post, result: PipelineResult) -> None:
          from src.analyze.frames import extract_frames_from_gaps
          from src.transcribe.visual_gaps import find_gaps
          recording = result.output_paths.get("recording")
          srt_path = result.output_paths.get("transcript_srt")
          if not recording or not srt_path:
              return
          gaps = find_gaps(Path(srt_path))
          if not gaps:
              return
          frames_dir = Path(recording).parent / "frames"
          paths = extract_frames_from_gaps(Path(recording), gaps, frames_dir)
          result.output_paths["frames_dir"] = str(frames_dir)
          result.output_paths["frames_count"] = str(len(paths))

      async def _step_ocr(self, post, result: PipelineResult) -> None:
          from src.analyze.ocr import ocr_frames
          frames_dir = result.output_paths.get("frames_dir")
          if not frames_dir:
              return
          texts = ocr_frames(Path(frames_dir))
          result.output_paths["ocr_count"] = str(len(texts))
  ```

  Key design decisions:
  - Each step is a separate `_step_*` method — composable and individually testable
  - Pipeline continues on individual post failure (catches exceptions per-post)
  - Steps can also fail individually within a post — logged, not fatal
  - All heavy imports (`WhisperRunner`, `QualityAnalyzer`, etc.) are lazy inside each step
  - Step outputs are threaded through `PipelineResult.output_paths` so downstream steps can find upstream results (e.g., `_step_transcribe` uses `recording` from `_step_record`)

- Run `uv run pytest tests/test_pipeline.py`

### 10. Write `cli.py` — Unified CLI entry point

- Write `tests/test_cli.py` first (test argument parsing):
  ```python
  """Tests for cli.py — argument parsing for each subcommand."""
  import pytest
  from unittest.mock import patch
  import sys

  def test_cli_help(capsys):
      with patch.object(sys, "argv", ["cli.py", "--help"]):
          with pytest.raises(SystemExit) as exc:
              import importlib
              import cli as cli_mod
              importlib.reload(cli_mod)
              cli_mod.main()
          assert exc.value.code == 0

  def test_cli_transcribe_args():
      """Test that transcribe subcommand accepts expected arguments."""
      from cli import build_parser
      parser = build_parser()
      args = parser.parse_args(["transcribe", "/tmp/videos", "--model", "tiny", "--only", "test"])
      assert args.command == "transcribe"
      assert args.folder == "/tmp/videos"
      assert args.model == "tiny"
      assert args.only == "test"

  def test_cli_analyze_args():
      from cli import build_parser
      parser = build_parser()
      args = parser.parse_args(["analyze", "/tmp/videos", "--single", "test.mkv"])
      assert args.command == "analyze"
      assert args.folder == "/tmp/videos"
      assert args.single == "test.mkv"

  def test_cli_correct_args():
      from cli import build_parser
      parser = build_parser()
      args = parser.parse_args(["correct", "/tmp/transcripts", "--dry-run"])
      assert args.command == "correct"
      assert args.dry_run is True

  def test_cli_find_gaps_args():
      from cli import build_parser
      parser = build_parser()
      args = parser.parse_args(["find-gaps", "/tmp/transcripts"])
      assert args.command == "find-gaps"

  def test_cli_pipeline_args():
      from cli import build_parser
      parser = build_parser()
      args = parser.parse_args(["pipeline", "--queue", "/tmp/q.json", "--steps", "transcribe,correct"])
      assert args.command == "pipeline"
      assert args.queue == "/tmp/q.json"
      assert args.steps == "transcribe,correct"

  def test_cli_preflight_args():
      from cli import build_parser
      parser = build_parser()
      args = parser.parse_args(["preflight"])
      assert args.command == "preflight"

  def test_cli_extract_frames_args():
      from cli import build_parser
      parser = build_parser()
      args = parser.parse_args(["extract-frames", "--gaps", "gaps.yaml", "--videos", "/tmp", "--out", "/tmp/frames"])
      assert args.command == "extract-frames"

  def test_cli_transfer_args():
      from cli import build_parser
      parser = build_parser()
      args = parser.parse_args(["transfer-transcripts", "--apply-corrections"])
      assert args.command == "transfer-transcripts"
      assert args.apply_corrections is True
  ```

- Implement `cli.py` in the project root:
  ```python
  #!/usr/bin/env python3
  """Unified CLI for the media-transcribe pipeline.

  Usage:
      uv run cli.py transcribe <folder> [--only "name"] [--model large-v3-turbo]
      uv run cli.py analyze <folder> [--single "file.mp4"]
      uv run cli.py correct <transcripts-folder> [--dry-run]
      uv run cli.py find-gaps <transcripts-folder> [--output gaps.yaml]
      uv run cli.py extract-frames --gaps gaps.yaml --videos <folder> --out <folder>
      uv run cli.py preflight
      uv run cli.py record --queue data/queues/conference.json
      uv run cli.py pipeline --queue <file> [--steps record,transcribe,correct]
      uv run cli.py transfer-transcripts [--apply-corrections] [--force]
      uv run cli.py screenshot
  """
  from __future__ import annotations

  import argparse
  import sys
  from pathlib import Path


  def build_parser() -> argparse.ArgumentParser:
      ap = argparse.ArgumentParser(
          description="media-transcribe — unified pipeline CLI",
          formatter_class=argparse.RawDescriptionHelpFormatter,
      )
      sub = ap.add_subparsers(dest="command", required=True)

      # --- transcribe ---
      t = sub.add_parser("transcribe", help="Transcribe videos in a folder")
      t.add_argument("folder", help="Folder containing video files")
      t.add_argument("--model", default="large-v3-turbo")
      t.add_argument("--out", default=None, help="Output dir (default: <folder>/transcripts)")
      t.add_argument("--only", default=None, help="Substring filter on filename")
      t.add_argument("--workers", type=int, default=1)
      t.add_argument("--cpu-threads", type=int, default=4)
      t.add_argument("--corrections", default="transcribe/corrections.txt")

      # --- analyze ---
      a = sub.add_parser("analyze", help="Analyze video quality")
      a.add_argument("folder", help="Folder containing video files")
      a.add_argument("--single", default=None, help="Analyze only this file")
      a.add_argument("--output", default=None, help="Output JSON path")

      # --- correct ---
      c = sub.add_parser("correct", help="Apply corrections to transcripts")
      c.add_argument("path", help="Transcripts folder or single file")
      c.add_argument("--corrections", default="transcribe/corrections.txt")
      c.add_argument("--dry-run", action="store_true")

      # --- find-gaps ---
      fg = sub.add_parser("find-gaps", help="Find visual-context gaps in SRT transcripts")
      fg.add_argument("transcripts_dir", help="Directory containing .srt files")
      fg.add_argument("--output", "-o", default=None, help="Output YAML file")

      # --- extract-frames ---
      ef = sub.add_parser("extract-frames", help="Extract video frames at gap timestamps")
      ef.add_argument("--gaps", required=True, help="Gaps YAML file")
      ef.add_argument("--videos", required=True, help="Video folder")
      ef.add_argument("--out", required=True, help="Output frames folder")

      # --- preflight ---
      sub.add_parser("preflight", help="Run preflight validation checks")

      # --- record ---
      r = sub.add_parser("record", help="Record videos from a queue")
      r.add_argument("--queue", required=True, help="Queue JSON file")

      # --- pipeline ---
      p = sub.add_parser("pipeline", help="Run the full pipeline")
      p.add_argument("--queue", required=True, help="Queue JSON file")
      p.add_argument("--steps", default=None, help="Comma-separated step names")

      # --- transfer-transcripts ---
      tt = sub.add_parser("transfer-transcripts", help="Sync transcripts from obs-machine")
      tt.add_argument("--apply-corrections", action="store_true")
      tt.add_argument("--force", action="store_true")
      tt.add_argument("--dry-run", action="store_true")

      # --- screenshot ---
      sub.add_parser("screenshot", help="Take a screenshot via OBS")

      return ap


  def main() -> int:
      parser = build_parser()
      args = parser.parse_args()

      if args.command == "transcribe":
          from src.transcribe.whisper_runner import WhisperRunner
          corrections = Path(args.corrections) if args.corrections else None
          runner = WhisperRunner(
              model=args.model, workers=args.workers,
              cpu_threads=args.cpu_threads,
          )
          out = Path(args.out) if args.out else None
          runner.transcribe_folder(
              Path(args.folder), output_dir=out,
              only=args.only, corrections=corrections,
          )

      elif args.command == "analyze":
          from src.analyze.quality import QualityAnalyzer
          analyzer = QualityAnalyzer()
          reports = analyzer.analyze_folder(Path(args.folder), single=args.single)
          for r in reports:
              print(f"{r.filename}: {r.verdict} — {r.notes}")

      elif args.command == "correct":
          from src.transcribe.corrections import apply_rules, load_rules
          rules = load_rules(args.corrections)
          if not rules:
              print(f"No rules loaded from {args.corrections}", file=sys.stderr)
              return 1
          root = Path(args.path)
          files = [root] if root.is_file() else sorted(root.rglob("*.txt")) + sorted(root.rglob("*.srt"))
          changed = 0
          for f in files:
              text = f.read_text(encoding="utf-8")
              new, counts = apply_rules(text, rules)
              if counts:
                  changed += 1
                  summary = ", ".join(f"{k}x{v}" for k, v in sorted(counts.items()))
                  print(f"{'(dry) ' if args.dry_run else ''}{f.name}: {summary}")
                  if not args.dry_run:
                      f.write_text(new, encoding="utf-8")
          print(f"{'Would change' if args.dry_run else 'Changed'} {changed}/{len(files)} files.")

      elif args.command == "find-gaps":
          from src.transcribe.visual_gaps import find_gaps_in_folder
          import yaml
          result = find_gaps_in_folder(Path(args.transcripts_dir))
          all_gaps = [g.__dict__ for gaps in result.values() for g in gaps]
          output_data = {"total_gaps": len(all_gaps), "gaps": all_gaps}
          yaml_str = yaml.dump(output_data, default_flow_style=False, sort_keys=False)
          if args.output:
              Path(args.output).write_text(yaml_str, encoding="utf-8")
              print(f"Saved {len(all_gaps)} gaps to {args.output}")
          else:
              print(yaml_str)

      elif args.command == "extract-frames":
          import yaml
          from src.analyze.frames import extract_frame, parse_srt_timestamp
          gaps_data = yaml.safe_load(Path(args.gaps).read_text(encoding="utf-8"))
          out_dir = Path(args.out)
          out_dir.mkdir(parents=True, exist_ok=True)
          videos_dir = Path(args.videos)
          for i, gap in enumerate(gaps_data.get("gaps", [])):
              ts = parse_srt_timestamp(gap.get("timestamp", "00:00:00,000"))
              video_file = gap.get("file", "").replace(".srt", ".mp4")
              video_path = videos_dir / video_file
              if video_path.exists():
                  out = out_dir / f"gap_{i:04d}_{ts:.0f}s.jpg"
                  extract_frame(video_path, ts, out)

      elif args.command == "preflight":
          from src.capture.preflight import Preflight
          pf = Preflight()
          ok, gates = pf.run_all()
          return 0 if ok else 1

      elif args.command == "record":
          import asyncio
          from src.capture.batch import load_queue
          # Actual recording requires the capture environment (OBS, Chrome)
          queue = load_queue(Path(args.queue))
          print(f"Loaded {len(queue)} entries from {args.queue}")
          # Batch recording orchestration would go here

      elif args.command == "pipeline":
          import asyncio
          from src.pipeline.runner import Pipeline
          from src.capture.batch import load_queue
          from src.sources.base import Post
          queue_data = load_queue(Path(args.queue))
          posts = [Post(url=e["url"], title=e.get("title", e["filename"]),
                        filename=e["filename"]) for e in queue_data]
          steps = args.steps.split(",") if args.steps else None
          # Pipeline requires source + engine — construct from context
          pipeline = Pipeline(source=None, engine=None)
          asyncio.run(pipeline.run(posts, steps=steps))

      elif args.command == "transfer-transcripts":
          from src.transfer.sync import TransferClient
          from src.config import LOCAL_TRANSCRIPTS
          client = TransferClient()
          remote_dir = "D:/MasterClass Video Backup/transcripts/"
          synced = client.sync_transcripts(remote_dir, LOCAL_TRANSCRIPTS, force=args.force)
          print(f"Synced {len(synced)} file(s)")
          if args.apply_corrections and synced:
              from src.transcribe.corrections import apply_rules, load_rules
              rules = load_rules("transcribe/corrections.txt")
              for fname in synced:
                  fpath = LOCAL_TRANSCRIPTS / fname
                  if fpath.exists():
                      text = fpath.read_text(encoding="utf-8")
                      new, counts = apply_rules(text, rules)
                      if counts and not args.dry_run:
                          fpath.write_text(new, encoding="utf-8")

      elif args.command == "screenshot":
          from src.engines.obs_engine import OBSEngine
          engine = OBSEngine()
          engine.connect()
          data = engine.get_screenshot()
          if data:
              print(f"Screenshot captured ({len(data)} bytes base64)")
          else:
              print("Screenshot failed", file=sys.stderr)
              return 1

      return 0


  if __name__ == "__main__":
      raise SystemExit(main())
  ```

  Key design decisions:
  - `build_parser()` is a standalone function so tests can validate arg parsing without importing heavy modules
  - All `src/` imports happen inside the command handlers (lazy) — the CLI is importable even without faster-whisper
  - Each subcommand maps directly to one or two `src/` module calls
  - `record` and `pipeline` need engine/source construction — these are platform-specific and will evolve as the project matures
  - The CLI is a thin dispatch layer, not a second implementation of any logic

- Run `uv run pytest tests/test_cli.py`

### 11. Wire up `__init__.py` exports

- `src/transcribe/__init__.py`:
  ```python
  from src.transcribe.corrections import apply_rules, load_rules
  from src.transcribe.whisper_runner import WhisperRunner

  __all__ = ["apply_rules", "load_rules", "WhisperRunner"]
  ```

- `src/analyze/__init__.py`:
  ```python
  from src.analyze.quality import QualityAnalyzer, QualityReport

  __all__ = ["QualityAnalyzer", "QualityReport"]
  ```

- `src/transfer/__init__.py`:
  ```python
  from src.transfer.sync import TransferClient

  __all__ = ["TransferClient"]
  ```

- `src/pipeline/__init__.py`:
  ```python
  from src.pipeline.runner import Pipeline, PipelineResult

  __all__ = ["Pipeline", "PipelineResult"]
  ```

### 12. Add `pyyaml` dependency

- The `find_visual_gaps.py` script and the CLI's `find-gaps` command use `yaml` (PyYAML). Check if `pyyaml` is already in `pyproject.toml`. If not:
  ```bash
  uv add pyyaml
  ```
  This is a lightweight, widely-used dependency — acceptable for a core feature.

### 13. Run full test suite and validate

- Run `uv run pytest` — all tests (Phase 1 + Phase 2 + Phase 3 + existing) must pass
- Run `uv run python -m py_compile` on all new modules:
  ```bash
  uv run python -m py_compile src/transcribe/whisper_runner.py src/transcribe/corrections.py src/transcribe/visual_gaps.py src/analyze/quality.py src/analyze/frames.py src/analyze/ocr.py src/transfer/sync.py src/pipeline/runner.py cli.py
  ```
- Verify existing scripts still compile:
  ```bash
  uv run python -m py_compile transcribe/transcribe.py transcribe/corrections.py transcribe/find_visual_gaps.py transcribe/transfer_transcripts.py
  ```
- Verify all imports:
  ```bash
  uv run python -c "
  from src.transcribe import WhisperRunner, apply_rules, load_rules
  from src.transcribe.visual_gaps import find_gaps, Gap
  from src.analyze import QualityAnalyzer, QualityReport
  from src.analyze.frames import extract_frame
  from src.transfer import TransferClient
  from src.pipeline import Pipeline, PipelineResult
  print('All Phase 3 imports OK')
  "
  ```
- Verify CLI help:
  ```bash
  uv run python cli.py --help
  uv run python cli.py transcribe --help
  uv run python cli.py analyze --help
  ```

## Testing Strategy

All new code uses **TDD** — tests are written before implementation for each module.

| Module | Test File | What's Tested | Mocking Strategy |
|--------|-----------|---------------|------------------|
| `src/transcribe/corrections.py` | `tests/test_corrections.py` | Rule loading (literal, regex, comments, empty), application, idempotency | No mocks — pure functions with tmp files |
| `src/transcribe/whisper_runner.py` | `tests/test_whisper_runner.py` | Video discovery, filter, resumability, fmt_ts, correction application, device detection | Mock `faster_whisper.WhisperModel` |
| `src/transcribe/visual_gaps.py` | `tests/test_visual_gaps.py` | SRT parsing, pattern matching, context extraction, folder scanning | No mocks — pure functions with tmp SRT files |
| `src/analyze/quality.py` | `tests/test_quality.py` | Verdict logic (clean/trim/issues/re_record), trim point calculation, ffprobe parsing | Mock `subprocess.run` for ffmpeg/ffprobe |
| `src/analyze/frames.py` | `tests/test_frames.py` | ffmpeg command construction, timestamp parsing, batch extraction | Mock `subprocess.run` |
| `src/analyze/ocr.py` | `tests/test_ocr.py` | Single image OCR, batch directory OCR | Mock `RapidOCR`, `PIL`, `numpy` |
| `src/transfer/sync.py` | `tests/test_transfer.py` | Upload/download success/failure, sync with skip-existing | Mock `subprocess.run` for ssh/scp |
| `src/pipeline/runner.py` | `tests/test_pipeline.py` | Step filtering, continuation on failure, step validation, output threading | Mock all step methods |
| `cli.py` | `tests/test_cli.py` | Argument parsing for every subcommand | No mocks — parse args only |

### Edge cases to cover
- **WhisperRunner**: Empty folder, all files already transcribed, `faster_whisper` not installed (ImportError handled)
- **WhisperRunner multi-worker**: Worker initialization failure, single video in multi-worker mode (workers clamped to video count)
- **Corrections**: Empty corrections file, missing corrections file, rule with no `=>`, idempotent application (running twice = same result)
- **Visual gaps**: Empty SRT file, SRT with no patterns, malformed SRT entries (missing index), single subtitle (no context before/after)
- **QualityAnalyzer**: ffprobe failure (returns error report), ffmpeg timeout, video with no audio stream, bitrate of 0
- **Frames**: Invalid timestamp format, ffmpeg frame extraction failure, video file doesn't exist
- **OCR**: No image files in directory, OCR returns no results, RapidOCR not installed
- **TransferClient**: SSH connection refused, SCP timeout, remote directory empty
- **Pipeline**: Empty queue, all steps filtered out, step that depends on missing upstream output (e.g., transcribe without record)
- **CLI**: No subcommand given (should error), unknown subcommand, missing required args

## Acceptance Criteria

1. `uv run python -c "from src.transcribe import WhisperRunner; print(WhisperRunner)"` — imports without error (no `faster_whisper` needed at import time)
2. `uv run python -c "from src.transcribe.corrections import load_rules, apply_rules; print('OK')"` — corrections module works
3. `uv run python -c "from src.transcribe.visual_gaps import find_gaps, Gap; print('OK')"` — gap detection works
4. `uv run python -c "from src.analyze import QualityAnalyzer; print(QualityAnalyzer)"` — quality analyzer imports
5. `uv run python -c "from src.analyze.frames import extract_frame; print('OK')"` — frames module imports
6. `uv run python -c "from src.transfer import TransferClient; print(TransferClient)"` — transfer client imports
7. `uv run python -c "from src.pipeline import Pipeline; print(Pipeline)"` — pipeline imports
8. `uv run python cli.py --help` — CLI help prints without error
9. `uv run python cli.py transcribe --help` — subcommand help works
10. `uv run pytest tests/test_whisper_runner.py tests/test_visual_gaps.py tests/test_quality.py tests/test_frames.py tests/test_pipeline.py tests/test_cli.py` — all Phase 3 tests pass
11. `uv run pytest` — full suite passes (no regressions in Phase 1, Phase 2, or existing tests)
12. Existing scripts still compile: `uv run python -m py_compile transcribe/transcribe.py transcribe/corrections.py transcribe/find_visual_gaps.py`
13. The `Pipeline` class runs with mocked components — verified by `test_pipeline.py`
14. Each `src/` module is independently importable and usable without other pipeline stages

## Validation Commands
Execute these commands to validate the task is complete:

- `uv run pytest` — Full test suite (Phase 1 + Phase 2 + Phase 3 + existing) passes
- `uv run pytest tests/test_whisper_runner.py tests/test_visual_gaps.py tests/test_quality.py tests/test_frames.py tests/test_pipeline.py tests/test_cli.py -v` — All Phase 3 tests pass with verbose output
- `uv run python -c "from src.transcribe import WhisperRunner; from src.analyze import QualityAnalyzer; from src.transfer import TransferClient; from src.pipeline import Pipeline; print('Phase 3 OK')"` — Core imports work
- `uv run python -c "from src.transcribe.visual_gaps import find_gaps, Gap, DEFAULT_PATTERNS; print(f'{len(DEFAULT_PATTERNS)} patterns')"` — Gap detection module loads
- `uv run python -c "from src.analyze.frames import extract_frame, parse_srt_timestamp; print('Frames OK')"` — Frames module loads
- `uv run python cli.py --help` — CLI entry point works
- `uv run python -m py_compile cli.py src/transcribe/whisper_runner.py src/transcribe/corrections.py src/transcribe/visual_gaps.py src/analyze/quality.py src/analyze/frames.py src/analyze/ocr.py src/transfer/sync.py src/pipeline/runner.py` — All new modules compile
- `uv run python -m py_compile transcribe/transcribe.py transcribe/corrections.py transcribe/find_visual_gaps.py transcribe/transfer_transcripts.py` — Existing scripts still compile

## Notes

- **Lazy imports for heavy dependencies**: `faster_whisper`, `rapidocr_onnxruntime`, `av`, `numpy`, `PIL`, `torch` are all imported inside functions/methods, never at module level. This ensures all modules are importable on devbox-01 (CPU-only, no CUDA) and on machines without the `[ocr]` extra.
- **`pyyaml` dependency**: The `find_visual_gaps.py` script already uses `yaml` (PyYAML). Add it to core dependencies with `uv add pyyaml` since gap detection is a core feature.
- **Existing `tests/test_corrections.py`**: This test file exists and tests the original `transcribe/corrections.py` via `sys.path` manipulation. The new `src/transcribe/corrections.py` is a direct copy. Keep the old test working (it tests the old script) and add new tests for the `src/` version. Both should pass.
- **`corrections.txt` location**: The correction rules file stays at `transcribe/corrections.txt` (not moved to `src/`). The `cli.py` defaults to this path. The `WhisperRunner` accepts a `corrections` parameter so the caller decides where rules live.
- **`cli.py` in project root**: Placed at the project root (not in `src/`) because it's the user-facing entry point invoked via `uv run cli.py`. This matches the existing pattern where scripts in `acquire/` and `transcribe/` are run directly.
- **Pipeline `source` and `engine` construction**: The `pipeline` and `record` CLI commands currently accept a queue file but don't construct a Source + Engine automatically. This is intentional — the engine/source selection depends on the platform (OBS on Windows, yt-dlp elsewhere) and the content type. Future work: add `--source patreon|youtube` and `--engine obs|ytdlp|null` flags.
- **No new dependencies beyond PyYAML**: All modules use only what's already in `pyproject.toml`. `subprocess`, `json`, `re`, `pathlib`, `dataclasses` are stdlib. `faster_whisper` is a core dep. OCR deps are in the `[ocr]` extra. Capture deps are in the `[capture]` extra.
- **Backward compatibility**: Do NOT modify or delete any existing files in `transcribe/`, `acquire/`, or `ocr/`. They continue to run independently with their inline constants. The `src/` modules are the canonical future API, but migration happens gradually.
- **`compute_verdict` full implementation**: The plan shows `...` for brevity in `src/analyze/quality.py`, but the implementation should be a direct extraction of the full `compute_verdict` function from `acquire/video_analyzer_remote.py` lines 470-566. Same for all detection functions.
