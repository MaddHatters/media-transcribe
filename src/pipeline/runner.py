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
    def __init__(self, source, engine, output_dir: Path | None = None,
                 enable_breaks: bool = False, preflight=None):
        self._source = source
        self._engine = engine
        self._output_dir = output_dir or Path(".")
        self._enable_breaks = enable_breaks
        self._preflight = preflight

    def _validate_steps(self, steps: list[str]) -> list[str]:
        for s in steps:
            if s not in STEPS:
                raise ValueError(f"Unknown step: {s}. Valid: {STEPS}")
        return steps

    def _health_check(self) -> None:
        if not self._preflight:
            return
        chrome_ok = self._preflight._ensure_chrome()
        if not chrome_ok:
            log.warning("[health] Chrome CDP lost — attempting recovery")
        obs_ok = self._preflight._ensure_obs()
        if not obs_ok:
            log.warning("[health] OBS WebSocket lost — attempting recovery")

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

        try:
            for i, post in enumerate(queue):
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

                if "record" in active_steps and i < len(queue) - 1:
                    self._health_check()
                    if self._enable_breaks:
                        from src.capture.batch import human_break
                        await asyncio.to_thread(human_break, i + 1, len(queue))
        except BaseException:
            log.critical("PIPELINE FAILED — stopping OBS recording", exc_info=True)
            raise
        finally:
            self._emergency_stop_engine()

        return results

    def _emergency_stop_engine(self) -> None:
        if self._engine is None:
            return
        try:
            if self._engine.is_recording():
                self._engine.stop()
                log.warning("[pipeline-guard] Stopped recording after crash")
        except Exception:
            pass

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
        from src.capture.window import focus_chrome
        from src.capture.batch import mark_seen
        from src.cdp import CDPClient
        from src.config import IS_WINDOWS

        if IS_WINDOWS:
            focus_chrome()
            await asyncio.sleep(1)

        recorder = Recorder(self._engine)
        async with CDPClient() as cdp:
            rec = await recorder.record_one(cdp, post.url, post.filename)
            if rec.ok:
                if rec.output_path and hasattr(self._engine, 'move_to_backup'):
                    moved = self._engine.move_to_backup(rec.output_path, post.filename)
                    result.output_paths["recording"] = moved or rec.output_path
                else:
                    result.output_paths["recording"] = rec.output_path or ""
                mark_seen(post.url)
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
        out_dir = self._output_dir / "transcripts"
        out_dir.mkdir(parents=True, exist_ok=True)
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

        corrections_file = None
        for candidate in [Path("corrections.txt"), Path("transcribe/corrections.txt")]:
            if candidate.exists():
                corrections_file = candidate
                break
        if not corrections_file:
            log.warning("No corrections file found — skipping")
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
