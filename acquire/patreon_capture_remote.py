#!/usr/bin/env python3
"""Patreon video capture via CDP + OBS.

Supported players:
  - Vimeo (HLS.js) embedded in Patreon posts via <iframe> (older content).
  - Native Patreon video player using Mux HLS (newer content, 2024+).

Browser control: Chrome DevTools Protocol (CDP) on localhost:9222.
  Uses the existing Chrome session (trusted by Patreon, no automation detection).
  Playback triggered by clicking the player centre (Input.dispatchMouseEvent),
  NOT by calling video.play() (which fails due to autoplay policy).
Recording: OBS WebSocket API (start/stop/status).

Usage (on the obs-machine):
  py -3 patreon_capture.py "https://www.patreon.com/posts/12345"
  py -3 patreon_capture.py --urls-file episodes.txt
  py -3 patreon_capture.py "https://www.patreon.com/posts/12345" --no-obs
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import time
import urllib.request

import websockets

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CDP_URL = "http://localhost:9222"
OBS_HOST = "localhost"
OBS_PORT = 4455
OBS_PASSWORD = "DK4HLJPKgslAhEgD"
VIDEOS_DIR = r"C:\Users\Matt\Videos"
BACKUP_DIR = r"D:\MasterClass Video Backup"
VIMEO_SDK_URL = "https://player.vimeo.com/api/player.js"

PAGE_LOAD_WAIT = 10       # seconds after navigation
PLAYER_DETECT_TIMEOUT = 30  # seconds to find a player element
PLAYBACK_POLL = 5         # seconds between progress checks
STALL_TIMEOUT = 90        # seconds of no progress before nudging


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def safe_filename(title: str) -> str:
    bad = '<>:"/\\|?*'
    cleaned = "".join("_" if c in bad else c for c in title).strip()
    return cleaned if cleaned.strip("_ ") else "episode"


async def get_ws_url() -> str:
    data = urllib.request.urlopen(f"{CDP_URL}/json").read()
    pages = json.loads(data)
    page = next(p for p in pages if p["type"] == "page")
    return page["webSocketDebuggerUrl"]


# ---------------------------------------------------------------------------
# CDP primitives
# ---------------------------------------------------------------------------
async def _make_cdp(ws):
    """Return (cdp, js, click, move) closures bound to *ws*."""
    msg_id = [0]

    async def cdp(method: str, params: dict | None = None) -> dict:
        msg_id[0] += 1
        mid = msg_id[0]
        await ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        while True:
            resp = json.loads(await ws.recv())
            if resp.get("id") == mid:
                return resp

    async def js(expr: str, *, await_promise: bool = False):
        """Evaluate JS; return the value or None on error."""
        params: dict = {"expression": expr, "returnByValue": True}
        if await_promise:
            params["awaitPromise"] = True
        r = await cdp("Runtime.evaluate", params)
        inner = r.get("result", {})
        if "exceptionDetails" in inner:
            return None
        return inner.get("result", {}).get("value")

    async def click(x: float, y: float) -> None:
        await cdp("Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": x, "y": y,
            "button": "left", "clickCount": 1,
        })
        await asyncio.sleep(0.05)
        await cdp("Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": x, "y": y,
            "button": "left", "clickCount": 1,
        })

    async def move(x: float, y: float) -> None:
        await cdp("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})

    return cdp, js, click, move


# ---------------------------------------------------------------------------
# OBS control
# ---------------------------------------------------------------------------
class Recorder:
    """Thin OBS wrapper; no-op when disabled."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.client = None
        if not enabled:
            return
        import obsws_python as obs
        self.client = obs.ReqClient(
            host=OBS_HOST, port=OBS_PORT, password=OBS_PASSWORD, timeout=10,
        )
        # Stop any stale recording
        try:
            if self.client.get_record_status().output_active:
                self.client.stop_record()
                time.sleep(2)
        except Exception:
            pass
        print("  [obs] connected", flush=True)

    def start(self, name: str) -> None:
        if not self.enabled:
            return
        self.client.set_profile_parameter("Output", "FilenameFormatting", name)
        self.client.start_record()
        print(f"  [obs] recording -> {name}", flush=True)
        time.sleep(2)  # let OBS stabilise

    def stop(self) -> str | None:
        if not self.enabled:
            return None
        resp = self.client.stop_record()
        path = getattr(resp, "output_path", None)
        print(f"  [obs] saved -> {path}", flush=True)
        return path


# ---------------------------------------------------------------------------
# Player detection
# ---------------------------------------------------------------------------
async def detect_player(js) -> str | None:
    """Poll for a Vimeo iframe or native <video>.  Returns type or None."""
    deadline = time.monotonic() + PLAYER_DETECT_TIMEOUT
    while time.monotonic() < deadline:
        if await js("!!document.querySelector(\"iframe[src*='vimeo']\")"):
            return "vimeo"
        if await js("!!document.querySelector('video')"):
            return "native"
        await asyncio.sleep(2)
    return None


async def get_player_centre(js, selector: str) -> tuple[float, float]:
    """Return (cx, cy) of the player element's bounding box."""
    raw = await js(f"""
    (() => {{
        const el = document.querySelector('{selector}');
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return JSON.stringify({{x: r.x + r.width/2, y: r.y + r.height/2}});
    }})()
    """)
    if raw:
        d = json.loads(raw)
        return d["x"], d["y"]
    return 640.0, 400.0  # fallback


# ---------------------------------------------------------------------------
# Vimeo capture
# ---------------------------------------------------------------------------
async def play_vimeo(js, click, move) -> float:
    """Start Vimeo playback, enter fullscreen, return duration."""
    # Inject Vimeo SDK
    await js(f"""(() => {{
        if (window.Vimeo) return;
        const s = document.createElement('script');
        s.src = '{VIMEO_SDK_URL}';
        document.head.appendChild(s);
    }})()""")
    for _ in range(20):
        if await js("typeof Vimeo !== 'undefined'"):
            break
        await asyncio.sleep(0.5)

    # Create player, register ended event
    await js("""(() => {
        const iframe = document.querySelector("iframe[src*='vimeo']");
        window.__p = new Vimeo.Player(iframe);
        window.__ended = false;
        window.__p.on('ended', () => { window.__ended = true; });
    })()""")
    await asyncio.sleep(1)

    # Get duration
    duration = 0.0
    for _ in range(15):
        d = await js("window.__p.getDuration()", await_promise=True)
        if d and float(d) > 0:
            duration = float(d)
            break
        await asyncio.sleep(1)

    # Reset to start
    await js("window.__p.setCurrentTime(0)", await_promise=True)
    await js("window.__p.setVolume(1.0)", await_promise=True)
    await asyncio.sleep(1)

    # Click to play
    cx, cy = await get_player_centre(js, "iframe[src*='vimeo']")
    await click(cx, cy)
    await asyncio.sleep(2)

    # Verify playing; if paused, try SDK play
    paused = await js("window.__p.getPaused()", await_promise=True)
    if paused:
        await js("window.__p.play()", await_promise=True)
        await asyncio.sleep(2)

    # Fullscreen
    await js("""(() => {
        const iframe = document.querySelector("iframe[src*='vimeo']");
        iframe.requestFullscreen().catch(() => {
            iframe.style.cssText = 'position:fixed!important;top:0!important;left:0!important;'
                + 'width:100vw!important;height:100vh!important;z-index:999999!important;border:none!important;';
        });
    })()""")
    await asyncio.sleep(2)
    await move(0, 0)

    return duration


async def poll_vimeo(js) -> tuple[float, bool]:
    """Return (currentTime, ended) for Vimeo."""
    ended = await js("window.__ended")
    ct = await js("window.__p.getCurrentTime()", await_promise=True)
    return float(ct or 0), bool(ended)


# ---------------------------------------------------------------------------
# Native video capture
# ---------------------------------------------------------------------------
async def play_native(js, click, move) -> float:
    """Start native video playback, enter fullscreen, return duration."""
    # Scroll into view (triggers Patreon's lazy HLS init)
    await js("""(() => {
        const v = document.querySelector('video');
        if (v) v.scrollIntoView({behavior: 'instant', block: 'center'});
    })()""")
    await asyncio.sleep(2)

    # Register ended listener
    await js("""(() => {
        const v = document.querySelector('video');
        window.__ended = false;
        v.addEventListener('ended', () => { window.__ended = true; });
    })()""")

    # Wait for HLS to initialise (readyState > 0)
    print("  waiting for HLS...", flush=True)
    for i in range(30):
        rs = await js("document.querySelector('video').readyState")
        if rs is not None and int(rs) >= 1:
            print(f"  HLS ready (readyState={rs})", flush=True)
            break
        if i > 0 and i % 5 == 0:
            ns = await js("document.querySelector('video').networkState")
            print(f"  ... readyState={rs}, networkState={ns} ({i}s)", flush=True)
        await asyncio.sleep(1)

    # Get duration
    duration = 0.0
    for _ in range(15):
        d = await js(
            "(() => { const v = document.querySelector('video');"
            " return isFinite(v.duration) ? v.duration : 0; })()"
        )
        if d and float(d) > 0:
            duration = float(d)
            break
        await asyncio.sleep(1)

    # Reset to start, unmute
    await js("document.querySelector('video').currentTime = 0")
    await js("document.querySelector('video').volume = 1.0")
    await js("document.querySelector('video').muted = false")
    await asyncio.sleep(1)

    # Click centre to play
    cx, cy = await get_player_centre(js, "video")
    await click(cx, cy)
    await asyncio.sleep(3)

    # Check playing; retry if paused
    paused = await js("document.querySelector('video').paused")
    if paused:
        print("  paused after click — clicking again", flush=True)
        await click(cx, cy)
        await asyncio.sleep(2)

    # Fullscreen
    await js("""(() => {
        const v = document.querySelector('video');
        v.requestFullscreen().catch(() => {
            v.style.cssText = 'position:fixed!important;top:0!important;left:0!important;'
                + 'width:100vw!important;height:100vh!important;z-index:999999!important;'
                + 'object-fit:contain!important;background:#000!important;';
        });
    })()""")
    await asyncio.sleep(2)
    await move(0, 0)

    return duration


async def poll_native(js) -> tuple[float, bool]:
    """Return (currentTime, ended) for native video."""
    ended = await js("window.__ended")
    ct = await js("document.querySelector('video').currentTime")
    return float(ct or 0), bool(ended)


# ---------------------------------------------------------------------------
# Playback monitor (shared by both player types)
# ---------------------------------------------------------------------------
async def monitor_playback(
    js, poll_fn, duration: float, move,
) -> None:
    """Poll playback until the video ends or stalls."""
    deadline = time.monotonic() + duration * 1.3 + 120
    last_t, last_change = -1.0, time.monotonic()
    last_log = time.time()

    while time.monotonic() < deadline:
        ct, ended = await poll_fn(js)

        if ended:
            print(f"\n  video ended at {ct:.0f}s / {duration:.0f}s", flush=True)
            return
        if duration > 0 and ct >= duration - 2:
            print(f"\n  reached end: {ct:.0f}s / {duration:.0f}s", flush=True)
            return

        # Log every 60 seconds
        if time.time() - last_log > 60:
            pct = ct / duration * 100 if duration else 0
            print(f"  {ct:.0f}s / {duration:.0f}s ({pct:.0f}%)", flush=True)
            last_log = time.time()
            # Move mouse to corner to keep controls hidden
            await move(0, 0)

        # Stall detection
        if abs(ct - last_t) > 0.1:
            last_t, last_change = ct, time.monotonic()
        elif time.monotonic() - last_change > STALL_TIMEOUT:
            print(f"\n  [warn] stalled at {ct:.0f}s; moving on", flush=True)
            return

        print(f"\r  ...playing {ct:6.0f}s / {duration:.0f}s", end="", flush=True)
        await asyncio.sleep(PLAYBACK_POLL)

    print("\n  [warn] hit hard time cap", flush=True)


# ---------------------------------------------------------------------------
# File management
# ---------------------------------------------------------------------------
def move_to_backup(src_path: str, title: str) -> str | None:
    """Rename with episode title and move to backup directory."""
    if not src_path or not os.path.exists(src_path):
        return None

    ext = os.path.splitext(src_path)[1]
    fname = safe_filename(title) + ext
    os.makedirs(BACKUP_DIR, exist_ok=True)
    dest = os.path.join(BACKUP_DIR, fname)

    time.sleep(2)  # let OBS flush
    try:
        if os.path.exists(dest):
            os.remove(dest)
        shutil.move(src_path, dest)
        fsize = os.path.getsize(dest) / (1024 * 1024)
        print(f"  [move] {fname} ({fsize:.1f} MB) -> {BACKUP_DIR}", flush=True)
        return dest
    except Exception as e:
        print(f"  [move] FAILED: {e}", file=sys.stderr, flush=True)
        return src_path


# ---------------------------------------------------------------------------
# Capture one video
# ---------------------------------------------------------------------------
async def capture_one(url: str, *, use_obs: bool = True) -> dict:
    """Capture a single Patreon video.  Returns result dict."""
    ws_url = await get_ws_url()

    async with websockets.connect(
        ws_url, max_size=50 * 1024 * 1024, ping_interval=30,
    ) as ws:
        _, js, click, move = await _make_cdp(ws)

        # 1. Navigate
        print(f"\n[capture] {url}", flush=True)
        await js('if(document.fullscreenElement) document.exitFullscreen(); "ok"')
        await asyncio.sleep(1)
        await js(f'window.location.href = "{url}"; "navigating"')
        await asyncio.sleep(PAGE_LOAD_WAIT)

        # 2. Detect player
        player_type = await detect_player(js)
        if not player_type:
            return {"ok": False, "error": "no video player found"}
        print(f"  player: {player_type}", flush=True)

        # 3. Title
        raw_title = await js("document.title") or ""
        title = raw_title.split(" | ")[0].strip() or url.rsplit("/", 1)[-1]
        print(f"  title: {title}", flush=True)

        # 4. Play + fullscreen
        if player_type == "vimeo":
            duration = await play_vimeo(js, click, move)
            poll_fn = poll_vimeo
        else:
            duration = await play_native(js, click, move)
            poll_fn = poll_native

        print(f"  duration: {duration/60:.1f} min ({duration:.0f}s)", flush=True)

        if duration <= 0:
            return {"ok": False, "error": "could not get video duration"}

        # 5. Record
        rec = Recorder(enabled=use_obs)
        rec.start(safe_filename(title))

        # 6. Monitor
        await monitor_playback(js, poll_fn, duration, move)
        await asyncio.sleep(3)

        # 7. Stop recording
        raw_path = rec.stop()

        # 8. Exit fullscreen
        await js('if(document.fullscreenElement) document.exitFullscreen(); "ok"')
        await js("""(() => {
            const v = document.querySelector('video');
            if (v) v.style.cssText = '';
            const iframe = document.querySelector("iframe[src*='vimeo']");
            if (iframe) iframe.style.cssText = '';
        })()""")

    # 9. Move to backup dir
    final_path = move_to_backup(raw_path, title) if raw_path else None

    return {
        "ok": True,
        "title": title,
        "duration": duration,
        "output_path": final_path,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
async def async_main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url", nargs="?", help="Patreon post URL")
    ap.add_argument("--urls-file", metavar="FILE",
                    help="File with one URL per line")
    ap.add_argument("--no-obs", action="store_true",
                    help="Play only, no OBS recording")
    args = ap.parse_args()

    # Collect URLs
    urls: list[str] = []
    if args.url:
        urls.append(args.url)
    if args.urls_file:
        from pathlib import Path
        urls.extend(
            ln.strip() for ln in Path(args.urls_file).read_text().splitlines()
            if ln.strip() and not ln.startswith("#")
        )
    if not urls:
        print("Nothing to do. Provide a URL or --urls-file.", file=sys.stderr)
        return 2

    # Capture each
    results = []
    for i, url in enumerate(urls, 1):
        print(f"\n{'#' * 60}", flush=True)
        print(f"# [{i}/{len(urls)}] {url}", flush=True)
        print(f"{'#' * 60}", flush=True)

        result = await capture_one(url, use_obs=not args.no_obs)
        results.append(result)

        if result["ok"]:
            print(f"  SUCCESS: {result['title']}", flush=True)
        else:
            print(f"  FAILED: {result['error']}", flush=True)

        # Machine-readable result line
        print(f"RESULT:{json.dumps(result)}", flush=True)

    # Summary
    ok = sum(1 for r in results if r["ok"])
    print(f"\n{'=' * 60}", flush=True)
    print(f"  {ok}/{len(results)} succeeded", flush=True)
    print(f"{'=' * 60}", flush=True)

    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main()))
