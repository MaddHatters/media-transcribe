# acquire — get the source media

Two ways to obtain the videos. For transcripts you only need **audio**; capture
**video** too if you want slide OCR later.

| | `obs_capture.py` (OBS) | `patreon_download.sh` (yt-dlp) |
|---|---|---|
| How | Real browser plays at 1x, OBS records the screen | Pulls the file directly via Patreon API/Vimeo |
| Speed | Real-time (overnight for a full collection) | Faster than real-time |
| Risk | Very low — indistinguishable from watching | Small ToS/ban risk (automated access) |
| Gets | Whatever's on screen (video + audio) | Best video/audio stream |
| DRM | Works (real browser has Widevine) | Fails on DRM'd videos |

If you want zero account risk, use OBS. If speed matters more and the content
isn't DRM'd, use yt-dlp **throttled** (one at a time).

---

## Option A — automated OBS (recommended for video, runs on Windows)

A real Edge/Chrome plays each episode while OBS records one file per episode.
Because it's genuine playback, it emits real player heartbeats and runs all the
page JS — it looks like watching, not scraping.

**Setup (once, on the Windows box):**
1. OBS 28+ → **Tools → WebSocket Server Settings** → enable; note port/password.
   Set recording format to **mkv** and choose a recording folder.
2. `uv sync --extra capture`
3. `cp obs_config.example.toml obs_config.toml` and fill in the password.
4. `uv run acquire/obs_capture.py --login` → log into Patreon once (persisted).

**Run:**
```bash
# 1) verify playback only (no recording):
uv run acquire/obs_capture.py --test "https://www.patreon.com/posts/68412694" --no-obs
# 2) one episode end-to-end:
uv run acquire/obs_capture.py --test "https://www.patreon.com/posts/68412694"
# 3) the whole list (one URL per line):
uv run acquire/obs_capture.py --urls-file episodes.txt
```

Then copy the recordings to the transcription box and run `transcribe/`.

**Notes / tuning:** capture is real-time, so leave the machine logged in and
untouched (screen capture needs an active session). The Vimeo play/fullscreen
selectors in `obs_capture.py` may need a tweak after the first `--no-obs` test —
that's exactly what the test mode is for.

---

## Option B — direct download (yt-dlp)

Uses your logged-in browser cookies. Personal use, your own paid content.

```bash
# audio only (smallest/fastest for transcripts):
AUDIO=1 ./patreon_download.sh firefox "/mnt/secondary/FIRE Investing Masterclass" \
    "https://www.patreon.com/posts/68412694"
```

Firefox cookies are the most reliable; recent Chrome/Edge encrypt cookies in a
way that often breaks `--cookies-from-browser` (export a `cookies.txt` instead).
To minimize footprint, fetch one at a time and add `--sleep-requests`/`--limit-rate`.

---

## YouTube — captions shortcut (`youtube_transcript.py`)

When a YouTube video already has captions, skip Whisper entirely and pull them
directly. One `[M:SS] text` line per cue, written to a per-video folder:

```
<dest>/<channel>/<title> [<video_id>]/transcript.txt
```

The video id keeps folders unique (channels reuse titles across uploads).
`--keep-vtt` also drops the raw `.vtt` + `.info.json` in that folder.

```bash
uv run acquire/youtube_transcript.py "https://www.youtube.com/watch?v=<id>" --dest /mnt/secondary/media/youtube
```

Uses `uvx yt-dlp` (no new dependency, no API key). This is the **fast** path — it
trades quality for speed: YouTube captions are unpunctuated and skip this repo's
finance vocab + ticker corrections. For best quality, download the audio and run
`transcribe.py` instead.

### Watch a channel for new videos (`youtube_channel.py`)

Poll a channel's public RSS feed and save a transcript for each video not seen
before. Point it at a channel id, URL, or `@handle`:

```bash
uv run acquire/youtube_channel.py "https://www.youtube.com/@SomeChannel" --dest transcripts
```

Processed video ids are recorded in `<dest>/.seen-<channel_id>.txt`, so re-runs
only fetch new uploads — run it on a schedule (a systemd user timer) to catch
them as they land. `--dry-run` lists new videos without fetching; `--limit N`
caps a run (oldest first, handy for draining a backlog). The RSS feed only
carries the ~15 most recent uploads; for a full back-catalogue, enumerate with
`uvx yt-dlp --flat-playlist <channel>/videos` and feed ids to `youtube_transcript.py`.
