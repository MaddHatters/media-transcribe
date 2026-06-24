# media-transcribe

## Context
Local, private pipeline that turns a library of videos into transcripts (+ optional
slide OCR). Two stages on two machines: **acquire** (capture/download the media) and
**transcribe** (Whisper on the CPU). Everything runs offline — no API keys, no uploads.

## Tooling
- Python 3.11+
- uv — package & runtime management
- faster-whisper (CTranslate2) — transcription, CPU-only here
- pytest — tests
- Optional `[capture]` extra (Windows box only): playwright, obsws-python
- yt-dlp — run via `uvx yt-dlp` (not a core dep)
- Always use `uv` over `pip`, `poetry`, or raw `python`.

## Key Commands
- `uv run pytest` - Run tests (run before committing)
- `uv sync` - Install core deps; add `--extra capture` on the capture box
- `uv run transcribe/transcribe.py "<folder>" --model large-v3-turbo --workers 4 --cpu-threads 4` - Transcribe
- `uv run transcribe/apply_corrections.py "<transcripts>" --dry-run` - Preview ticker fixes
- `uv run acquire/obs_capture.py --test "<url>" --no-obs` - Verify playback without recording

## Project Structure
- `acquire/` - Get the media: `obs_capture.py` (OBS+browser), `patreon_download.sh` (yt-dlp)
- `transcribe/` - Media → transcripts: `transcribe.py`, `corrections.py`, `apply_corrections.py`, `*.txt` dicts
- `tests/` - Unit tests (run with `uv run pytest`)

## Development Guidelines
1. Write tests first (TDD); validate every change with `uv run pytest`.
2. Keep scripts runnable standalone via `uv run <script>` — match the existing argparse style.
3. Keep functions small and single-purpose; match surrounding naming and comment density.
4. Core stays CPU-only and dependency-light. Capture-only deps live in the `[capture]` extra, imported lazily.

## Important Notes
- IMPORTANT: This processes **paywalled, personal** course content. Never upload, redistribute, or
  add a cloud/third-party step without an explicit request. Media stays local.
- IMPORTANT: Do NOT commit unless explicitly asked. Never commit media, transcripts, `obs_config.toml`,
  cookies, or `.browser-profile/` — they are gitignored; keep them that way.
- Correction rules (`corrections.txt`) are per-course and whole-word. They must be **idempotent** —
  preview with `--dry-run` before writing, and never map a correct term onto another correct term.
- Transcription is CPU-only: prefer many parallel `--workers` over more `--cpu-threads` per worker;
  `large-v3-turbo` is the default model (≈ large-v3 quality on English, ~2× faster).
- Never silently swallow errors. If you catch one, log it and re-raise.
- Keep this file concise. DO NOT bloat it with implementation details.
