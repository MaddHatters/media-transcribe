#!/usr/bin/env python3
"""Patreon video capture via Playwright + OBS.

Supported players:
  - Vimeo (HLS.js) embedded in Patreon posts via <iframe> (older content, ~2020-2024).
  - Native HTML5 <video> / Mux <mux-player> (newer Patreon content, 2024+).

Browser control: Playwright (persistent browser context) — real user gestures,
    satisfies autoplay/HLS policies. Preferred for Patreon.
Recording: OBS WebSocket API (start/stop/status).
Login: --login flag opens browser for manual Patreon login (persisted in .browser-profile/).
       Or use sync_patreon_session.py to copy cookies from a CDP Chrome session.
"""
from __future__ import annotations

import argparse
import sys
import time
import tomllib
from pathlib import Path

VIMEO_SDK = "https://player.vimeo.com/api/player.js"
PROFILE_DIR = Path(__file__).parent / ".browser-profile"   # persisted login

# JS snippet: given a player element handle (could be <video>, <mux-player>,
# or a wrapper div), resolve the underlying <video> element.  Used with
# element.evaluate("el => ...") which Playwright auto-pierces shadow DOM for.
_RESOLVE_VIDEO = (
    "el.tagName === 'VIDEO' ? el"
    " : (el.shadowRoot?.querySelector('video')"
    " || el.querySelector('video') || el)"
)


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
# player detection
# --------------------------------------------------------------------------- #
def find_player(page) -> tuple[str, object] | None:
    """Detect the video player and return ``(type, element_handle)``.

    Returns:
      - ``("vimeo", <iframe element>)`` for Vimeo embeds.
      - ``("native", <mux-player or video element>)`` for native players.
      - ``None`` if no player is found within 30 seconds.

    The returned element handle is the best click-target for the player.
    Playwright's ``query_selector`` pierces Shadow DOM automatically.
    """
    try:
        page.wait_for_selector(
            "iframe[src*='vimeo'], mux-player, video", timeout=30_000,
        )
    except Exception:
        return None

    iframe = page.query_selector("iframe[src*='vimeo']")
    if iframe:
        return ("vimeo", iframe)

    # Prefer mux-player (the outer custom element) as click target —
    # its built-in UI handles play/pause/fullscreen via standard shortcuts.
    mux = page.query_selector("mux-player")
    if mux:
        return ("native", mux)

    video = page.query_selector("video")
    if video:
        return ("native", video)

    return None


# --------------------------------------------------------------------------- #
# Vimeo playback (older Patreon content)
# --------------------------------------------------------------------------- #
def start_vimeo_playback(page) -> float:
    """Begin Vimeo iframe playback (unmuted) and return duration in seconds."""
    page.add_script_tag(url=VIMEO_SDK)
    page.evaluate(
        """() => {
            const iframe = document.querySelector("iframe[src*='vimeo']");
            window.__p = new Vimeo.Player(iframe);
            window.__ended = false;
            window.__p.on('ended', () => { window.__ended = true; });
        }"""
    )
    page.click("iframe[src*='vimeo']")
    page.evaluate("() => window.__p.setVolume(1.0)")
    page.evaluate("() => window.__p.play()")
    try:
        page.evaluate(
            """() => document.querySelector("iframe[src*='vimeo']").requestFullscreen()"""
        )
    except Exception:
        pass
    return float(page.evaluate("() => window.__p.getDuration()"))


# --------------------------------------------------------------------------- #
# Native / Mux playback — interact like a real user
# --------------------------------------------------------------------------- #
def start_native_playback(page, player_el) -> float:
    """Begin native video playback and return duration in seconds.

    Interacts with the player like a real user would:
      1. Scroll into view so the player initialises.
      2. Click the player to start playback (real Playwright click).
      3. Press ``f`` for fullscreen (standard video-player shortcut).

    Uses ``element.evaluate("el => ...")`` for property access — Playwright
    passes the element handle directly, so Shadow DOM is never an issue.
    """
    # --- Register ended listener ---
    player_el.evaluate(
        f"el => {{"
        f"  const v = {_RESOLVE_VIDEO};"
        f"  window.__ended = false;"
        f"  v.addEventListener('ended', () => {{ window.__ended = true; }});"
        f"}}"
    )

    # --- Scroll into view ---
    # Patreon lazy-inits its HLS player via Intersection Observer; the JS
    # polyfill won't run until the element is visible in the viewport.
    player_el.scroll_into_view_if_needed()
    page.wait_for_timeout(2000)

    # --- Wait for readyState >= 1 (metadata loaded) ---
    # Chrome can't play .m3u8 natively; the site's JS must set up a
    # MediaSource and feed it segments.  readyState stays 0 until that
    # happens.  We poll via the element handle (shadow-DOM-safe).
    print("  [native] waiting for player to load...", flush=True)
    ready = False
    for i in range(30):
        rs = player_el.evaluate(
            f"el => {{ const v = {_RESOLVE_VIDEO}; return v.readyState; }}"
        )
        if rs >= 1:
            print(f"  [native] ready (readyState={rs})", flush=True)
            ready = True
            break
        if i > 0 and i % 5 == 0:
            ns = player_el.evaluate(
                f"el => {{ const v = {_RESOLVE_VIDEO}; return v.networkState; }}"
            )
            print(f"  [native] ... readyState={rs}, networkState={ns} ({i}s)",
                  flush=True)
        page.wait_for_timeout(1000)

    if not ready:
        print("  [warn] player not ready after 30 s — clicking anyway", flush=True)

    # --- Click to play ---
    player_el.click()
    page.wait_for_timeout(3000)

    # Check if playing; if still paused, try Space then another click
    paused = player_el.evaluate(
        f"el => {{ const v = {_RESOLVE_VIDEO}; return v.paused; }}"
    )
    if paused:
        print("  [native] paused after click — pressing Space", flush=True)
        player_el.focus()
        page.keyboard.press("Space")
        page.wait_for_timeout(1000)
        paused = player_el.evaluate(
            f"el => {{ const v = {_RESOLVE_VIDEO}; return v.paused; }}"
        )
    if paused:
        print("  [native] still paused — trying second click", flush=True)
        player_el.click()
        page.wait_for_timeout(2000)

    # --- Unmute ---
    player_el.evaluate(
        f"el => {{ const v = {_RESOLVE_VIDEO}; v.volume = 1.0; v.muted = false; }}"
    )

    # --- Fullscreen via 'f' shortcut ---
    player_el.focus()
    page.keyboard.press("f")
    page.wait_for_timeout(1000)

    # --- Get duration ---
    duration = 0.0
    for _ in range(10):
        d = player_el.evaluate(
            f"el => {{ const v = {_RESOLVE_VIDEO};"
            f" return (v && isFinite(v.duration)) ? v.duration : 0; }}"
        )
        if d and float(d) > 0:
            duration = float(d)
            break
        page.wait_for_timeout(2000)

    return duration


# --------------------------------------------------------------------------- #
# unified wait-until-done
# --------------------------------------------------------------------------- #
def wait_until_done(
    page, duration: float, player_type: str, player_el=None,
    poll: float = 5.0,
) -> None:
    """Poll playback position until the video ends, with a stall watchdog."""
    deadline = time.monotonic() + duration * 1.3 + 120  # generous hard cap
    last_t, last_change = -1.0, time.monotonic()

    while time.monotonic() < deadline:
        if page.evaluate("() => window.__ended"):
            return

        # Get current playback position
        if player_type == "vimeo":
            t = float(page.evaluate("() => window.__p.getCurrentTime()"))
        else:
            t = float(player_el.evaluate(
                f"el => {{ const v = {_RESOLVE_VIDEO}; return v.currentTime; }}"
            ))

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
            page.goto(url, wait_until="networkidle")

            found = find_player(page)
            if not found:
                print("  [skip] no video player found (access? not a video post?)")
                continue

            player_type, player_el = found
            print(f"  player: {player_type}")
            name = safe_name(episode_title(page, url))
            try:
                if player_type == "vimeo":
                    duration = start_vimeo_playback(page)
                else:
                    duration = start_native_playback(page, player_el)
                print(f"  duration {duration/60:.1f} min")
                rec.start(name)
                wait_until_done(page, duration, player_type, player_el)
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
