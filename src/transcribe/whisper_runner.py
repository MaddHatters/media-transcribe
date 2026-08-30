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
        self._model = None
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
        """Transcribe all videos in a folder. Returns list of (txt, srt) paths."""
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
