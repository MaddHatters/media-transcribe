# media-transcribe

## Context
Local, private pipeline that turns a library of videos into transcripts (+ optional
slide OCR). Everything runs offline — no API keys, no uploads.

## Architecture

**Two machines, one pipeline:**

| Machine | Role | What lives there |
|---------|------|-----------------|
| **devbox-01** (localhost) | Development, storage, orchestration | Source repo at `/home/tuna/repos/media-transcribe/` |
| **obs-machine** (Windows) | Runtime — recording, transcription (GPU), analysis | Deployed project at `C:\Users\Matt\transcribe\` |

**The repo is separate from where it runs.** Code is developed on devbox-01, deployed to the obs-machine via SCP, and executed there via `cli.py`.

### Deployment

```bash
# Deploy from devbox-01 to obs-machine:
cd /home/tuna/repos/media-transcribe
scp -r src/ cli.py corrections.txt finance_vocab.txt Matt@100.66.194.100:"C:/Users/Matt/transcribe/"
```

## Release / Deploy

One-command deploy from devbox-01 to obs-machine:

```bash
bash scripts/release.sh            # test → deploy → verify
bash scripts/release.sh --verify   # also runs preflight on obs-machine
```

The script:
1. Checks you're on `main` with a clean working tree
2. Verifies obs-machine is reachable via SSH
3. Runs `uv run pytest` — aborts on failure
4. SCPs project files to `C:\Users\Matt\transcribe\`
5. Runs `uv sync --extra capture` on obs-machine
6. Verifies deployed version matches local
7. Runs `cli.py --help` on obs-machine to check imports

### Checking deploy status

```bash
uv run cli.py release-info    # shows version, commit, deploy target, remote version
```

### After deploying

```bash
ssh Matt@100.66.194.100 "cd C:\Users\Matt\transcribe; uv run cli.py pipeline --queue <file>"
```

### Execution

**All operations go through `cli.py`** — the single entry point on the obs-machine. Never invoke scripts in `src/` directly.

```bash
# Long-running commands (auto-background over SSH):
ssh Matt@100.66.194.100 "cd C:\Users\Matt\transcribe; uv run cli.py record --queue queue.json"
ssh Matt@100.66.194.100 "cd C:\Users\Matt\transcribe; uv run cli.py transcribe <folder> --only <name>"
ssh Matt@100.66.194.100 "cd C:\Users\Matt\transcribe; uv run cli.py analyze <folder> --single <file>"
ssh Matt@100.66.194.100 "cd C:\Users\Matt\transcribe; uv run cli.py pipeline --queue queue.json"

# Schedule for later:
ssh Matt@100.66.194.100 "cd C:\Users\Matt\transcribe; uv run cli.py pipeline --queue queue.json --start-at '22:00'"

# Short commands (inline):
ssh Matt@100.66.194.100 "cd C:\Users\Matt\transcribe; uv run cli.py preflight"
ssh Matt@100.66.194.100 "cd C:\Users\Matt\transcribe; uv run cli.py correct <transcripts-folder>"
ssh Matt@100.66.194.100 "cd C:\Users\Matt\transcribe; uv run cli.py find-gaps <transcripts-folder>"
ssh Matt@100.66.194.100 "cd C:\Users\Matt\transcribe; uv run cli.py screenshot"

# Force foreground (debugging only):
uv run cli.py transcribe ... --foreground
```

Long-running commands auto-detach when run via SSH. Output goes to log files in `C:\Users\Matt\agent-control\logs\`.

### Automated Watch

```bash
# Start autonomous content pipeline — discover + record every 24h at 10pm:
ssh Matt@100.66.194.100 "cd C:\Users\Matt\transcribe; uv run cli.py watch --source patreon --every 24h --start-at '22:00'"

# Check watcher status:
ssh Matt@100.66.194.100 "cd C:\Users\Matt\transcribe; uv run cli.py watch --status"

# Dry-run — discover but don't record:
ssh Matt@100.66.194.100 "cd C:\Users\Matt\transcribe; uv run cli.py watch --source patreon --every 24h --dry-run"

# Custom pipeline steps and batch size:
ssh Matt@100.66.194.100 "cd C:\Users\Matt\transcribe; uv run cli.py watch --every 24h --steps record,transcribe,correct --max-per-run 5"
```

**Safety:** 12h minimum interval enforced, default 3 videos per cycle, graceful shutdown on SIGTERM/SIGINT (finishes current video).

## Infrastructure

### obs-machine
- **Tailscale IP**: 100.66.194.100 (unattended mode)
- **LAN IP**: 192.168.222.87 (1 Gbps ethernet)
- **SSH**: `ssh Matt@100.66.194.100` (default shell is PowerShell, use `;` not `&&`)
- **RDP**: `DESKTOP-44D8KSU`
- **Wake-on-LAN**: `wakeonlan D8:50:E6:4D:30:A2`
- **HDMI dongle**: installed (allows monitor off during recording)

### obs-machine runtime paths
- **Pipeline project**: `C:\Users\Matt\transcribe\` (cli.py + src/)
- **Chrome profile**: `C:\Users\Matt\agent-control\chrome-profile\`
- **Recordings output**: `D:\MasterClass Video Backup\`
- **Transcripts output**: `D:\MasterClass Video Backup\transcripts\`
- **Logs**: `C:\Users\Matt\agent-control\logs\`
- **Queue files**: `C:\Users\Matt\agent-control\state\record_queue.json`
- **Seen URLs**: `C:\Users\Matt\agent-control\state\seen_urls.txt`

### obs-machine capabilities
- **CPU**: Intel Core i7-4770, 4 cores / 8 threads
- **GPU**: NVIDIA GTX 1060 6 GB VRAM (CUDA 12.6)
- **Whisper**: GPU-accelerated, `large-v3-turbo` model fits in VRAM
- **OBS**: WebSocket on localhost:4455
- **Chrome**: CDP on localhost:9222
- **Python**: Use `py -3` (3.12). Never `python` (3.8.2, too old).

### devbox-01 paths
- Source repo: `/home/tuna/repos/media-transcribe/`
- Patreon recordings: `/mnt/secondary/media/patreon/FIRE Investing Masterclass/`
- Existing transcripts: `/mnt/secondary/media/patreon/FIRE Investing Masterclass/transcripts/`
- YouTube videos: `/mnt/secondary/media/youtube/Mr. FIRED Up Wealth/`
- Catalog data: `data/` (in repo)

## Pipeline

### Steps + data dependencies
```
record         → video.mp4           requires: queue entry (url + filename)
analyze        → quality_report      requires: video.mp4
transcribe     → .txt + .srt         requires: video.mp4
correct        → .txt + .srt (fixed) requires: .txt + .srt
find-gaps      → visual_gaps.yaml    requires: .srt
extract-frames → screenshots/*.jpg   requires: visual_gaps.yaml + video.mp4
ocr            → slides/*.md         requires: screenshots/*.jpg
```

Each step checks if its input files exist. Resume is free — re-run the same command and it skips completed files.

### Player auto-detection
The recorder detects the video player type with a single DOM query:
- **Mux** (newer Patreon, 2024+): native `<video>` or `<mux-player>`
- **Vimeo** (older Patreon, 2020-2024): `<iframe src*="vimeo">`
- **HTML5**: fallback for plain `<video>` elements

### Preflight (7 self-healing gates)
1. Chrome CDP → auto-launch
2. OBS WebSocket → auto-launch
3. Patreon session → auto-login via Windows Credential Manager (`patreon_02_ai`)
4. Disk space ≥ 5GB
5. Test recording video (blackdetect)
6. Test recording audio (silencedetect)
7. Resolution (1920x1080)

### Critical settings
- **OBS Desktop Audio**: Must be `default` (not a specific device ID)
- **OBS Window Capture**: Must target Chrome window
- **Screensaver/lock**: Disabled (registry + powercfg)
- **Patreon creds**: Windows Credential Manager `patreon_02_ai`

### Queue file format
```json
[
  {"url": "https://www.patreon.com/posts/119811238", "filename": "Masterclass 19 - Munger Mental Models"}
]
```

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

## Project Structure
```
src/
├── config.py           ← constants (paths, credentials, OBS config)
├── cdp.py              ← Chrome DevTools Protocol client
├── players/            ← mux.py, vimeo.py, html5.py, detector.py
├── sources/            ← patreon.py, youtube.py
├── engines/            ← obs_engine.py, ytdlp_engine.py, null_engine.py
├── capture/            ← recorder.py, batch.py, preflight.py, window.py
├── transcribe/         ← whisper_runner.py, corrections.py, visual_gaps.py
├── analyze/            ← quality.py, frames.py, ocr.py
├── pipeline/           ← runner.py (end-to-end orchestration)
└── transfer/           ← sync.py (SCP between machines)
cli.py                  ← single entry point
```

## Tooling
- Python 3.11+ (devbox-01), 3.12 (obs-machine via `py -3`)
- uv — package & runtime management
- faster-whisper (CTranslate2) — transcription
- pytest — tests (`uv run pytest`)
- obsws-python — OBS control (capture box only)
- websockets — CDP communication (capture box only)
- yt-dlp — YouTube downloads (`uvx yt-dlp`)

## Key Commands
- `uv run pytest` — Run tests (303 tests, run before committing)
- `uv sync` — Install deps; add `--extra capture` on the obs-machine

## Development Guidelines
1. Write tests first (TDD); validate every change with `uv run pytest`.
2. Keep functions small and single-purpose.
3. All capture/transcribe operations go through `cli.py` — no standalone script invocation.
4. Core stays CPU-compatible. GPU/Windows-only deps imported lazily.
5. Never upload, redistribute, or add a cloud step for media content.
6. Do NOT commit media, transcripts, `obs_config.toml`, cookies, or `.browser-profile/`.
7. Correction rules must be idempotent — preview with `--dry-run`.

## Authentication
Credential and account details are documented in [`app_docs/auth.md`](app_docs/auth.md).
