#!/usr/bin/env python3
"""Automated OBS capture of Patreon (Vimeo-embedded) videos on Windows.

Drives a *real* browser (Edge/Chrome, so Widevine works and playback looks like
genuine viewing) to play each episode at 1x, while controlling OBS over
obs-websocket to record one file per episode. Capture is real-time, so a full
collection is an unattended overnight run.

Pairs with ../transcribe/transcribe.py: copy the recordings to the transcription
box and run the transcriber over them.

Setup (Windows, once):
    1. OBS 28+  ->  Tools > WebSocket Server Settings > enable, note port/password.
       Set OBS recording format to mkv and pick a recording folder.
    2. uv sync --extra capture          # installs playwright + obsws-python
    3. uv run playwright install         # browser binaries (only if using --browser chromium)
    4. Copy obs_config.example.toml -> obs_config.toml and fill in the password.
    5. uv run acquire/obs_capture.py --login      # log into Patreon once (persisted)

Run:
    # one episode, no OBS, just verify playback works:
    uv run acquire/obs_capture.py --test "https://www.patreon.com/posts/68412694" --no-obs
    # one episode end-to-end:
    uv run acquire/obs_capture.py --test "https://www.patreon.com/posts/68412694"
    # a whole list:
    uv run acquire/obs_capture.py --urls-file episodes.txt
"""
from __future__ import annotations

import argparse
import sys
import time
import tomllib
from pathlib import Path

VIMEO_SDK = "https://player.vimeo.com/api/player.js"
PROFILE_DIR = Path(__file__).parent / ".browser-profile"   # persisted login


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #
def load_config(path: Path) -> dict:
    cfg = {"obs": {"host": "localhost", "port": 4455, "password": ""},
           "browser": {"channel": "msedge"}}
    if path.exists():
        with path.open("rb") as f:
            user = tomllib.load(f)
        for section, vals in user.items():
            cfg.setdefault(section, {}).update(vals)
    return cfg


def safe_name(title: str) -> str:
    bad = '<>:"/\\|?*'
    cleaned = "".join("_" if c in bad else c for c in title).strip()
    return cleaned if cleaned.strip("_ ") else "episode"


# --------------------------------------------------------------------------- #
# OBS control (obs-websocket v5 via obsws-python)
# --------------------------------------------------------------------------- #
class Recorder:
    """Thin wrapper around OBS; a no-op when disabled (for playback testing)."""

    def __init__(self, cfg: dict, enabled: bool = True):
        self.enabled = enabled
        self.client = None
        if not enabled:
            return
        import obsws_python as obs
        o = cfg["obs"]
        self.client = obs.ReqClient(host=o["host"], port=int(o["port"]),
                                    password=o["password"], timeout=5)
        print(f"  [obs] connected to {o['host']}:{o['port']}")

    def start(self, name: str) -> None:
        if not self.enabled:
            return
        # name the next file via OBS filename formatting, then record
        self.client.set_profile_parameter("Output", "FilenameFormatting", name)
        self.client.start_record()
        print(f"  [obs] recording -> {name}")

    def stop(self) -> str | None:
        if not self.enabled:
            return None
        resp = self.client.stop_record()
        path = getattr(resp, "output_path", None)
        print(f"  [obs] saved -> {path}")
        return path


# --------------------------------------------------------------------------- #
# browser / Vimeo playback
# --------------------------------------------------------------------------- #
def find_vimeo_iframe(page) -> bool:
    try:
        page.wait_for_selector("iframe[src*='vimeo']", timeout=30_000)
        return True
    except Exception:
        return False


def start_playback(page) -> float:
    """Begin playback (unmuted) and return the video duration in seconds."""
    page.add_script_tag(url=VIMEO_SDK)
    page.evaluate(
        """() => {
            const iframe = document.querySelector("iframe[src*='vimeo']");
            window.__p = new Vimeo.Player(iframe);
            window.__ended = false;
            window.__p.on('ended', () => { window.__ended = true; });
        }"""
    )
    # a real click provides the user-gesture browsers require to play with sound
    page.click("iframe[src*='vimeo']")
    page.evaluate("() => window.__p.setVolume(1.0)")
    page.evaluate("() => window.__p.play()")
    # fill the screen so OBS display-capture gets clean, full-resolution slides
    try:
        page.evaluate("() => document.querySelector(\"iframe[src*='vimeo']\").requestFullscreen()")
    except Exception:
        pass
    return float(page.evaluate("() => window.__p.getDuration()"))


def wait_until_done(page, duration: float, poll: float = 5.0) -> None:
    """Poll playback position until the video ends, with a stall watchdog."""
    deadline = time.monotonic() + duration * 1.3 + 120     # generous hard cap
    last_t, last_change = -1.0, time.monotonic()
    while time.monotonic() < deadline:
        if page.evaluate("() => window.__ended"):
            return
        t = float(page.evaluate("() => window.__p.getCurrentTime()"))
        if duration and t >= duration - 1.5:
            return
        if abs(t - last_t) > 0.1:
            last_t, last_change = t, time.monotonic()
        elif time.monotonic() - last_change > 90:
            print(f"  [warn] playback stalled at {t:.0f}s; moving on")
            return
        print(f"\r  ...playing {t:6.0f}s / {duration:.0f}s", end="", flush=True)
        time.sleep(poll)
    print("\n  [warn] hit hard time cap")


def episode_title(page, url: str) -> str:
    try:
        t = page.title().split(" | ")[0].strip()
        return t or url.rsplit("/", 1)[-1]
    except Exception:
        return url.rsplit("/", 1)[-1]


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #
def read_urls(args) -> list[str]:
    if args.test:
        return [args.test]
    if args.urls_file:
        return [ln.strip() for ln in Path(args.urls_file).read_text().splitlines()
                if ln.strip() and not ln.startswith("#")]
    return []


def login(cfg: dict) -> None:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE_DIR), channel=cfg["browser"]["channel"], headless=False)
        page = ctx.new_page()
        page.goto("https://www.patreon.com/login")
        input("Log into Patreon in the browser window, then press Enter here... ")
        ctx.close()
    print("Login saved.")


def capture(urls: list[str], cfg: dict, use_obs: bool) -> None:
    from playwright.sync_api import sync_playwright
    rec = Recorder(cfg, enabled=use_obs)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE_DIR), channel=cfg["browser"]["channel"],
            headless=False, no_viewport=True, args=["--start-maximized"])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        for i, url in enumerate(urls, 1):
            print(f"\n[{i}/{len(urls)}] {url}")
            page.goto(url, wait_until="domcontentloaded")
            if not find_vimeo_iframe(page):
                print("  [skip] no Vimeo player found (access? not a video post?)")
                continue
            name = safe_name(episode_title(page, url))
            try:
                duration = start_playback(page)
                print(f"  duration {duration/60:.1f} min")
                rec.start(name)
                wait_until_done(page, duration)
            finally:
                print()
                rec.stop()
                try:
                    page.keyboard.press("Escape")   # leave fullscreen
                except Exception:
                    pass
                time.sleep(2)
        ctx.close()
    print("\nDone. Copy the recordings to the transcription box and run:")
    print('  uv run transcribe/transcribe.py "<folder>" --model large-v3-turbo --workers 4 --cpu-threads 4')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=str(Path(__file__).parent / "obs_config.toml"))
    ap.add_argument("--login", action="store_true", help="Open browser to log into Patreon once")
    ap.add_argument("--test", metavar="URL", help="Capture a single URL")
    ap.add_argument("--urls-file", help="File with one Patreon post URL per line")
    ap.add_argument("--no-obs", action="store_true", help="Play only, don't record (debug)")
    args = ap.parse_args()

    cfg = load_config(Path(args.config))
    if args.login:
        login(cfg)
        return 0

    urls = read_urls(args)
    if not urls:
        print("Nothing to do: pass --login, --test URL, or --urls-file FILE", file=sys.stderr)
        return 2
    capture(urls, cfg, use_obs=not args.no_obs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
