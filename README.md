# media-transcribe

Local, private pipeline for recording, analyzing, and transcribing video content
into searchable transcripts with optional OCR'd slide text. Built for the FIRE
Investing Masterclass on Patreon, reusable for any video source.

## Architecture

```
CLI (cli.py)
 └─ Pipeline (src/pipeline/runner.py)
     ├─ record     → Chrome (CDP) + OBS (WebSocket) capture
     ├─ analyze    → ffmpeg quality checks (black frames, silence, resolution)
     ├─ transcribe → Whisper large-v3-turbo (CPU, offline)
     └─ correct    → rule-based transcript corrections
```

**Components:**

| Component | Role | Protocol |
|-----------|------|----------|
| Chrome | Browser for video playback | CDP (port 9222) |
| OBS Studio | Screen + audio capture | WebSocket (port 4455) |
| Whisper | Speech-to-text | Local CLI (faster-whisper) |
| ffmpeg/ffprobe | Video analysis, test video generation | CLI |
| Player handlers | Mux, Vimeo, HTML5 auto-detection | CDP JS injection |

## Setup

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (package manager)
- ffmpeg + ffprobe (on PATH)
- Google Chrome (with `--remote-debugging-port=9222`)
- OBS Studio with [obs-websocket](https://github.com/obsproject/obs-websocket) plugin (port 4455)

### Installation

```bash
git clone <repo-url>
cd media-transcribe
uv sync
```

### Configuration

Key constants in `src/config.py`:

| Constant | Default | Description |
|----------|---------|-------------|
| `CDP_URL` | `http://localhost:9222` | Chrome DevTools Protocol endpoint |
| `OBS_HOST` | `localhost` | OBS WebSocket host |
| `OBS_PORT` | `4455` | OBS WebSocket port |
| `OBS_PASSWORD` | (set in config) | OBS WebSocket password |
| `CHROME_PATH` | `C:\Program Files (x86)\...\chrome.exe` | Chrome executable |
| `OBS_PATH` | `C:\Program Files\obs-studio\...\obs64.exe` | OBS executable |
| `BACKUP_DIR` | `D:\MasterClass Video Backup` | Default output directory |

### Obs-machine access

The recording runs on a dedicated Windows machine accessible via SSH:

```bash
ssh Matt@100.66.194.100
cd C:/Users/Matt/transcribe
```

All CLI commands run from the project directory on that machine. When invoked
over SSH, long-running commands automatically background via Windows Scheduled
Tasks (with `/it` flag for interactive-session UI access).

## Usage

### Full pipeline

```bash
# Run all steps (record + analyze + transcribe + correct)
uv run cli.py pipeline --queue data/queues/conference.json --steps record,analyze,transcribe,correct

# Select specific steps
uv run cli.py pipeline --queue data/queues/conference.json --steps transcribe,correct

# Foreground mode (stay attached to terminal)
uv run cli.py pipeline --queue data/queues/conference.json --foreground

# Delayed start
uv run cli.py pipeline --queue data/queues/conference.json --start-at "22:00"

# Test mode (no Patreon needed)
uv run cli.py pipeline --queue test_assets/test_queue.json --test-mode --steps record,analyze,transcribe,correct --foreground
```

### Individual commands

```bash
uv run cli.py preflight              # Run 7-gate startup validation
uv run cli.py setup                  # Launch Chrome + OBS (clean slate)
uv run cli.py teardown               # Stop recording, close Chrome + OBS
uv run cli.py screenshot             # Capture OBS screenshot
uv run cli.py status                 # Check running pipeline status
uv run cli.py release-info           # Show version + deploy status

uv run cli.py transcribe <folder> --model large-v3-turbo
uv run cli.py analyze <folder>
uv run cli.py correct <transcripts-folder>
uv run cli.py transfer-transcripts --apply-corrections
```

### Queue file format

A JSON array of `{url, filename}` objects:

```json
[
  {
    "url": "https://www.patreon.com/posts/12345",
    "filename": "Episode 1 - Introduction"
  },
  {
    "url": "https://www.patreon.com/posts/67890",
    "filename": "Episode 2 - Portfolio Theory"
  }
]
```

### Background vs foreground

By default, long-running commands (`record`, `transcribe`, `analyze`, `pipeline`,
`watch`) background automatically. The process detaches, output goes to a log
file, and you get back PID + log path.

Use `--foreground` to run attached to the terminal instead.

Over SSH on Windows, backgrounding uses Windows Scheduled Tasks so the process
survives the SSH session ending.

## QA Runbook — Testing Without Patreon

This section documents the full local testing flow. No Patreon account or
network access is needed.

### 1. Generate test video (one-time setup)

```bash
uv run cli.py generate-test-video
```

This creates `test_assets/test_video.mp4` — a 60-second SMPTE color-bars video
with timestamp overlay and 440 Hz sine tone. Requires ffmpeg on PATH.

### 2. Run pipeline in test mode

```bash
uv run cli.py pipeline \
  --queue test_assets/test_queue.json \
  --test-mode \
  --steps record,analyze,transcribe,correct \
  --foreground
```

**What `--test-mode` does:**

- Uses `TestSource` instead of `PatreonSource` (no authentication needed)
- Skips the Patreon session preflight gate
- Navigates Chrome to the local test video HTML page
- Everything else runs identically to production

### 3. Expected output

```
test_output/<filename>/recording.mkv    # 60s SMPTE color bars recording
test_output/<filename>/transcript.txt   # Plain text transcript
test_output/<filename>/transcript.srt   # SRT subtitle file
```

Console output should show:

```
*** TEST MODE — using local test video ***
Chrome: OK
OBS: OK
OBS config: OK
[preflight] Chrome CDP ................... OK
[preflight] OBS WebSocket ............... OK
[preflight] Patreon session ............. OK (skipped (test mode))
[preflight] Disk space .................. OK (XX.X GB free)
[preflight] Test recording (video) ...... OK
[preflight] Test recording (audio) ...... OK
[preflight] Test recording (resolution) . OK (1920x1080)
```

### 4. Validating output

```bash
# Check recording exists and has reasonable size (should be >1 MB for 60s)
ls -lh test_output/*/recording.mkv

# Verify recording has video stream
ffprobe -v quiet -show_streams test_output/*/recording.mkv | grep codec_type

# Check transcript was generated
cat test_output/*/transcript.txt

# Verify SRT has timestamps
head -20 test_output/*/transcript.srt
```

### 5. When to use test mode vs production

| Scenario | Mode | Command |
|----------|------|---------|
| Verifying pipeline mechanics (Chrome/OBS/Whisper) | Test | `--test-mode` |
| Validating a code change | Test | `--test-mode --foreground` |
| Recording actual Patreon content | Production | (no `--test-mode`) |
| CI/automated validation | Test | `--test-mode --foreground` |

### 6. Troubleshooting test mode

| Symptom | Cause | Fix |
|---------|-------|-----|
| `test_video.mp4` not found | Haven't generated it | `uv run cli.py generate-test-video` |
| Recording is all black | OBS Window Capture targeting wrong window | Fixed by clean-slate restart |
| No audio in recording | OBS Desktop Audio not configured | Fixed by `_configure_obs()` on setup |
| Transcript is empty | Recording too short or silent | Ensure test video has the 440 Hz tone |

## Clean-Slate Behavior

The pipeline kills and restarts both Chrome and OBS fresh at the start of
every run. This is intentional.

### Why

Previous runs can leave behind:

- **Ghost Chrome processes** — CDP responds to health checks but there's no
  visible UI window, so OBS Window Capture records a black screen
- **Stale OBS Window Capture sources** — OBS is pinned to a window title from
  a prior run (e.g., an `about:blank` tab) instead of the new video tab
- **Stuck OBS recordings** — a crashed run left OBS in "recording" state,
  blocking the next `start_record` call

### How it works

1. `restart_chrome()` — kills all `chrome.exe` processes via `taskkill /f`,
   waits 2 seconds, relaunches with correct flags, polls CDP for up to 30
   seconds
2. `restart_obs()` — gracefully stops any active recording, kills `obs64.exe`
   via `taskkill /f`, waits 2 seconds, relaunches minimized-to-tray, polls
   OBS WebSocket for up to 30 seconds
3. `_configure_obs()` — re-targets Window Capture to the current Chrome
   window (not `about:blank`), sets Desktop Audio device

The `teardown` step at the end of a pipeline run stops recording, closes
Chrome via CDP, kills OBS, and cleans up temporary scheduled-task files.

## Troubleshooting

### "Video test recording FAIL"

The preflight test recording detected an all-black video. Causes:

- Ghost Chrome process (CDP responds but no visible window)
- OBS Window Capture targeting a stale window from a prior run

**Fix:** The clean-slate startup (`restart_chrome()` + `restart_obs()`)
resolves this automatically. If it persists, kill all Chrome/OBS processes
manually and re-run.

### "Chrome CDP not responding"

```bash
# Check if Chrome is running
tasklist | findstr chrome.exe

# Kill manually if needed
taskkill /f /im chrome.exe

# Re-run setup
uv run cli.py setup
```

### "OBS WebSocket not responding"

```bash
# Check if OBS is running
tasklist | findstr obs64.exe

# Kill manually if needed
taskkill /f /im obs64.exe

# Re-run setup
uv run cli.py setup
```

### Preflight gate explanations

| Gate | What it checks |
|------|---------------|
| Chrome CDP | Chrome is running and CDP endpoint responds on port 9222 |
| OBS WebSocket | OBS is running and WebSocket responds on port 4455 |
| Patreon session | Chrome has a valid Patreon login cookie (skipped in test mode) |
| Disk space | At least 5 GB free on the recording drive |
| Test recording (video) | 10-second test recording is not all-black |
| Test recording (audio) | 10-second test recording is not all-silent |
| Test recording (resolution) | Recording resolution (should be 1920x1080) |

### Pipeline stuck or unresponsive

```bash
# Check status
uv run cli.py status

# View latest log
Get-Content (Get-ChildItem C:\Users\Matt\agent-control\logs\*.log | Sort-Object LastWriteTime | Select-Object -Last 1).FullName -Tail 20 -Wait

# Force teardown
uv run cli.py teardown
```

## Development

### Running tests

```bash
uv run pytest tests/ -v                    # All tests
uv run pytest tests/test_environment.py -v # Environment/clean-slate tests
uv run pytest tests/test_pipeline.py -v    # Pipeline tests
uv run pytest tests/test_preflight.py -v   # Preflight gate tests
```

### Code structure

```
src/
├── capture/
│   ├── environment.py    # Chrome + OBS lifecycle (restart, setup, teardown)
│   ├── preflight.py      # 7-gate startup validation
│   ├── recorder.py       # Single-video recording orchestrator
│   ├── batch.py          # Queue loading, seen-URL tracking, shuffling
│   ├── credentials.py    # Windows Credential Manager access
│   └── window.py         # Chrome window management (focus, close stale)
├── sources/
│   ├── base.py           # Source protocol + Post dataclass
│   ├── patreon.py        # Patreon content source (authentication + navigation)
│   ├── youtube.py        # YouTube content source
│   ├── test_source.py    # Local test video source (no auth needed)
│   └── discovery.py      # Patreon catalog discovery + diffing
├── players/
│   ├── base.py           # Player protocol (play, pause, seek, fullscreen)
│   ├── detector.py       # Auto-detect player type on page
│   ├── mux.py            # Mux.com player handler
│   ├── vimeo.py          # Vimeo embedded player handler
│   └── html5.py          # Generic HTML5 <video> player handler
├── engines/
│   ├── base.py           # CaptureEngine protocol
│   ├── obs_engine.py     # OBS Studio capture via WebSocket
│   ├── null_engine.py    # No-op engine for testing
│   └── ytdlp_engine.py   # yt-dlp direct download engine
├── pipeline/
│   ├── runner.py         # Pipeline orchestrator (chains steps)
│   └── watcher.py        # Autonomous discovery + recording loop
├── transcribe/
│   ├── whisper_runner.py # Whisper transcription (CPU, offline)
│   ├── corrections.py   # Rule-based transcript corrections
│   └── visual_gaps.py   # Find visual-context gaps in SRT files
├── analyze/
│   ├── quality.py        # Video quality analysis
│   ├── frames.py         # Frame extraction at timestamps
│   └── ocr.py            # OCR on extracted frames
├── transfer/
│   └── sync.py           # SSH-based transcript sync
├── config.py             # All paths, ports, constants
├── cdp.py                # Chrome DevTools Protocol client
└── logging_config.py     # Logging setup
```

### Adding new sources

Implement the `Source` protocol defined in `src/sources/base.py`:

```python
@runtime_checkable
class Source(Protocol):
    name: str

    async def authenticate(self, cdp: CDPClient) -> bool: ...
    async def get_posts(self, cdp: CDPClient, query: str | None = None) -> list[Post]: ...
    async def navigate_to(self, cdp: CDPClient, url: str) -> None: ...
```

See `src/sources/test_source.py` for a minimal example.

### Adding new capture engines

Implement the `CaptureEngine` protocol defined in `src/engines/base.py`:

```python
@runtime_checkable
class CaptureEngine(Protocol):
    name: str

    def start(self, filename: str) -> None: ...
    def stop(self) -> str | None: ...
    def is_recording(self) -> bool: ...
    def get_status(self) -> EngineStatus: ...
```

See `src/engines/null_engine.py` for a minimal example.
