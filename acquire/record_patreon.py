#!/usr/bin/env python3
"""Orchestrate Patreon video capture from devbox-01 via Playwright + OBS.

Deploys the Playwright capture script (obs_capture.py) to the obs-machine
(Windows box), runs it via SSH for each Patreon URL.  Recordings are moved
to D:\\MasterClass Video Backup\\ on the obs-machine (not transferred back).

Uses Playwright for browser control — real user gestures satisfy Vimeo/HLS.js
autoplay policies.  Replaced the prior CDP approach (patreon_capture_remote.py)
which could not satisfy Vimeo autoplay policies.

Prerequisites:
  - SSH key-based access to Matt@100.66.194.100 (the obs-machine)
  - OBS running with WebSocket enabled on the obs-machine
  - Playwright browser profile logged into Patreon (--login to set up)
  - Python 3.12+ on the obs-machine (invoked via ``py -3``)

Usage:
  # Log into Patreon on the obs-machine (one-time setup):
  uv run acquire/record_patreon.py --login

  # Single URL:
  uv run acquire/record_patreon.py --url "https://www.patreon.com/posts/12345"

  # Multiple URLs from a file:
  uv run acquire/record_patreon.py --urls-file episodes.txt

  # Record unrecorded videos from the masterclass catalog:
  uv run acquire/record_patreon.py --collection

  # Deploy only (push script to obs-machine without recording):
  uv run acquire/record_patreon.py --deploy-only

  # Dry run (show what would be captured):
  uv run acquire/record_patreon.py --collection --dry-run
"""
from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
OBS_HOST = "Matt@100.66.194.100"
REMOTE_SCRIPTS_DIR = r"C:\Users\Matt\agent-control\scripts"
REMOTE_CAPTURE_SCRIPT = "obs_capture.py"
REMOTE_CONFIG = "obs_config.toml"
REMOTE_BACKUP_DIR = r"D:\MasterClass Video Backup"

# Local paths
LOCAL_CAPTURE_SCRIPT = Path(__file__).parent / "obs_capture.py"
LOCAL_CONFIG = Path(__file__).parent / "obs_config.toml"
DEFAULT_CATALOG = Path(__file__).parent.parent / "data" / "masterclass_catalog.json"
SEEN_FILE = Path("/mnt/secondary/media/patreon/.seen-patreon.txt")

# Human-like timing between videos (300-1500s = 5-25 min)
BREAK_MIN_SECONDS = 300
BREAK_MAX_SECONDS = 1500

# Python on the obs-machine — ``python`` is 3.8.2 (too old), ``py -3`` is 3.12
REMOTE_PYTHON = "py -3"

# SSH options used for all connections
SSH_OPTS = ["-o", "ConnectTimeout=15", "-o", "StrictHostKeyChecking=no"]


# ---------------------------------------------------------------------------
# SSH / SCP helpers
# ---------------------------------------------------------------------------
def ssh_run(
    command: str,
    *,
    timeout: int | None = None,
    capture: bool = True,
    stream: bool = False,
) -> subprocess.CompletedProcess | subprocess.Popen:
    """Run a command on the obs-machine via SSH.

    With *stream=True*, returns a Popen whose stdout can be iterated line by
    line (used for long-running capture sessions).
    """
    full_cmd = [
        "ssh", *SSH_OPTS,
        "-o", "ServerAliveInterval=60",  # keep alive during long captures
        OBS_HOST,
        command,
    ]
    if stream:
        return subprocess.Popen(
            full_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
    return subprocess.run(
        full_cmd,
        capture_output=capture,
        text=True,
        timeout=timeout,
    )


def scp_to_remote(local: Path, remote_path: str) -> bool:
    """SCP a file TO the obs-machine."""
    result = subprocess.run(
        ["scp", *SSH_OPTS, str(local), f"{OBS_HOST}:{remote_path}"],
        capture_output=True, text=True, timeout=60,
    )
    return result.returncode == 0


# ---------------------------------------------------------------------------
# Deploy
# ---------------------------------------------------------------------------
def deploy(skip: bool = False) -> bool:
    """Push obs_capture.py (and obs_config.toml if present) to the obs-machine."""
    if skip:
        return True

    print("[deploy] Deploying capture script to obs-machine...", flush=True)

    if not LOCAL_CAPTURE_SCRIPT.exists():
        print(f"  ERROR: {LOCAL_CAPTURE_SCRIPT} not found", file=sys.stderr)
        return False

    remote_script = f"{REMOTE_SCRIPTS_DIR}\\{REMOTE_CAPTURE_SCRIPT}"
    ok = scp_to_remote(LOCAL_CAPTURE_SCRIPT, remote_script)
    print(f"  obs_capture.py: {'OK' if ok else 'FAILED'}", flush=True)
    if not ok:
        return False

    # Deploy config only if a local copy exists (the obs-machine already has
    # one with the OBS password; we don't want to overwrite it with a blank).
    if LOCAL_CONFIG.exists():
        remote_cfg = f"{REMOTE_SCRIPTS_DIR}\\{REMOTE_CONFIG}"
        ok_cfg = scp_to_remote(LOCAL_CONFIG, remote_cfg)
        print(f"  obs_config.toml: {'OK' if ok_cfg else 'FAILED'}", flush=True)
    else:
        print("  obs_config.toml: skipped (no local copy; using existing on obs-machine)",
              flush=True)

    return True


# ---------------------------------------------------------------------------
# Seen-file tracking
# ---------------------------------------------------------------------------
def load_seen() -> set[str]:
    """Load already-captured URLs from the seen file."""
    if not SEEN_FILE.exists():
        return set()
    return {ln.strip() for ln in SEEN_FILE.read_text().splitlines() if ln.strip()}


def mark_seen(url: str) -> None:
    """Append a URL to the seen file."""
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with SEEN_FILE.open("a") as f:
        f.write(url.strip() + "\n")


# ---------------------------------------------------------------------------
# Catalog / collection
# ---------------------------------------------------------------------------
def load_catalog(catalog_path: Path) -> list[dict]:
    """Load the masterclass catalog and return unrecorded, unseen posts."""
    if not catalog_path.exists():
        print(f"ERROR: catalog not found: {catalog_path}", file=sys.stderr)
        sys.exit(1)

    with catalog_path.open() as f:
        data = json.load(f)

    posts = data.get("posts", [])
    seen = load_seen()

    unrecorded = [
        p for p in posts
        if not p.get("recorded") and p.get("url") not in seen
    ]
    recorded_count = len(posts) - len(unrecorded)
    print(f"[collection] {len(posts)} total, {recorded_count} recorded/seen, "
          f"{len(unrecorded)} to capture", flush=True)
    return unrecorded


# ---------------------------------------------------------------------------
# URL collection & ordering
# ---------------------------------------------------------------------------
def collect_urls(args) -> list[str]:
    """Collect URLs from --url, --urls-file, and --collection."""
    urls: list[str] = []

    if args.url:
        urls.append(args.url)

    if args.urls_file:
        p = Path(args.urls_file)
        if not p.exists():
            print(f"ERROR: file not found: {p}", file=sys.stderr)
            sys.exit(1)
        urls.extend(
            ln.strip() for ln in p.read_text().splitlines()
            if ln.strip() and not ln.startswith("#")
        )

    if args.collection:
        catalog_path = Path(args.catalog_file) if args.catalog_file else DEFAULT_CATALOG
        unrecorded = load_catalog(catalog_path)
        urls.extend(p["url"] for p in unrecorded)

    # De-duplicate while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for u in urls:
        if u not in seen:
            deduped.append(u)
            seen.add(u)

    return deduped


def mild_shuffle(urls: list[str]) -> list[str]:
    """Lightly shuffle a URL list — swap ~30% of adjacent pairs.

    Preserves the general ordering (e.g. older-to-newer from the catalog)
    while introducing enough randomness that the access pattern doesn't look
    like a bot marching through a list in order.
    """
    if len(urls) <= 2:
        return urls[:]

    result = urls[:]
    for i in range(len(result) - 1):
        if random.random() < 0.3:
            result[i], result[i + 1] = result[i + 1], result[i]
    return result


# ---------------------------------------------------------------------------
# Capture one URL
# ---------------------------------------------------------------------------
def capture_one(url: str, *, use_obs: bool = True) -> dict:
    """SSH to the obs-machine and capture one Patreon video via obs_capture.py.

    Parses the text output from obs_capture.py to extract:
      - Whether the Vimeo iframe was found or skipped
      - The video duration
      - The recording title (from the OBS filename)
      - The saved file path on the obs-machine

    Returns a dict: ``{ok, url, title, duration, output_path, error}``.
    """
    print(f"\n{'=' * 60}", flush=True)
    print(f"[capture] {url}", flush=True)
    print(f"{'=' * 60}", flush=True)

    obs_flag = " --no-obs" if not use_obs else ""
    cmd = (
        f"cd {REMOTE_SCRIPTS_DIR}; "
        f"{REMOTE_PYTHON} {REMOTE_CAPTURE_SCRIPT} "
        f"--config {REMOTE_CONFIG} --test '{url}'{obs_flag} 2>&1"
    )

    # Stream stdout so the user sees real-time progress
    proc = ssh_run(cmd, stream=True)
    assert isinstance(proc, subprocess.Popen)

    output_path = None
    duration = None
    title = None
    skipped = False

    try:
        for line in proc.stdout:
            line = line.rstrip("\n\r")
            print(f"  [remote] {line}", flush=True)

            # Parse key output lines from obs_capture.py
            if "[skip]" in line:
                skipped = True

            saved_match = re.search(r"\[obs\] saved -> (.+)", line)
            if saved_match:
                output_path = saved_match.group(1).strip()

            rec_match = re.search(r"\[obs\] recording -> (.+)", line)
            if rec_match:
                title = rec_match.group(1).strip()

            dur_match = re.search(r"duration\s+([\d.]+)\s*min", line)
            if dur_match:
                duration = float(dur_match.group(1)) * 60  # to seconds

    except KeyboardInterrupt:
        print("\n  [interrupted] killing remote process...", flush=True)
        proc.terminate()
        raise

    proc.wait()

    # Collect stderr for diagnostics
    stderr = ""
    if proc.stderr:
        stderr = proc.stderr.read().strip()

    if skipped:
        return {"ok": False, "url": url, "error": "no Vimeo player found"}

    if proc.returncode != 0:
        return {"ok": False, "url": url, "error": f"exit {proc.returncode}: {stderr}"}

    return {
        "ok": True,
        "url": url,
        "title": title,
        "duration": duration or 0,
        "output_path": output_path,
    }


# ---------------------------------------------------------------------------
# Move recording on the obs-machine
# ---------------------------------------------------------------------------
def _ps_escape(s: str) -> str:
    """Escape a string for use inside PowerShell single-quoted strings."""
    return s.replace("'", "''")


def move_recording_remote(remote_src: str) -> str | None:
    """Move a recording to D:\\MasterClass Video Backup\\ on the obs-machine.

    OBS saves recordings to C:\\Users\\Matt\\Videos\\ by default.  This moves
    the file to the backup directory where the existing masterclass videos
    are stored.

    Returns the new path on success, or None on failure.
    """
    # Normalise to backslashes for Windows
    src = remote_src.replace("/", "\\")
    filename = src.rsplit("\\", 1)[-1] if "\\" in src else src
    dest = f"{REMOTE_BACKUP_DIR}\\{filename}"

    print(f"[move] {filename}", flush=True)
    print(f"  from: {src}", flush=True)
    print(f"  to:   {dest}", flush=True)

    # Ensure dest dir exists, then move
    cmd = (
        f"if (-not (Test-Path '{_ps_escape(REMOTE_BACKUP_DIR)}')) "
        f"{{ New-Item -ItemType Directory -Path '{_ps_escape(REMOTE_BACKUP_DIR)}' "
        f"-Force | Out-Null }}; "
        f"Move-Item -LiteralPath '{_ps_escape(src)}' "
        f"-Destination '{_ps_escape(dest)}' -Force; "
        f"Write-Output 'MOVED'"
    )
    result = ssh_run(cmd, timeout=120)
    stdout = result.stdout or ""

    if result.returncode == 0 and "MOVED" in stdout:
        print("  OK", flush=True)
        return dest

    stderr = (result.stderr or "").strip()
    print(f"  FAILED: {stderr}", file=sys.stderr, flush=True)
    return None


# ---------------------------------------------------------------------------
# Human-like break
# ---------------------------------------------------------------------------
def human_break(index: int, total: int) -> None:
    """Wait a random interval between captures to mimic a real viewer."""
    delay = random.randint(BREAK_MIN_SECONDS, BREAK_MAX_SECONDS)
    mins = delay / 60
    print(f"\n  [break] Waiting {mins:.0f} min before next video "
          f"({index}/{total} done)...", flush=True)
    try:
        time.sleep(delay)
    except KeyboardInterrupt:
        print("\n  [break] Interrupted — skipping remaining wait", flush=True)
        raise


# ---------------------------------------------------------------------------
# Login pass-through
# ---------------------------------------------------------------------------
def remote_login() -> int:
    """Trigger Patreon login on the obs-machine via obs_capture.py --login.

    This opens a Playwright browser on the obs-machine.  Someone with a
    display/keyboard on that machine must complete the login and press Enter
    in the terminal.
    """
    print("[login] Opening Playwright browser on obs-machine for Patreon login...",
          flush=True)
    print("        You need a display/keyboard on the obs-machine to complete this.",
          flush=True)
    print("        Log in, then press Enter in the obs-machine terminal.\n",
          flush=True)

    cmd = (
        f"cd {REMOTE_SCRIPTS_DIR}; "
        f"{REMOTE_PYTHON} {REMOTE_CAPTURE_SCRIPT} --config {REMOTE_CONFIG} --login"
    )

    # This blocks until the user finishes logging in on the obs-machine
    proc = ssh_run(cmd, stream=True)
    assert isinstance(proc, subprocess.Popen)

    try:
        for line in proc.stdout:
            print(f"  [remote] {line.rstrip()}", flush=True)
    except KeyboardInterrupt:
        proc.terminate()
        raise

    proc.wait()
    if proc.returncode == 0:
        print("[login] Login saved successfully.", flush=True)
    else:
        stderr = proc.stderr.read().strip() if proc.stderr else ""
        print(f"[login] FAILED (exit {proc.returncode}): {stderr}",
              file=sys.stderr, flush=True)
    return proc.returncode


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # URL sources
    ap.add_argument("--url", metavar="URL",
                    help="Capture a single Patreon post URL")
    ap.add_argument("--urls-file", metavar="FILE",
                    help="File with one Patreon URL per line")
    ap.add_argument("--collection", action="store_true",
                    help="Capture unrecorded videos from the masterclass catalog")
    ap.add_argument("--catalog-file", metavar="FILE",
                    help=f"Catalog JSON file (default: {DEFAULT_CATALOG})")

    # Login
    ap.add_argument("--login", action="store_true",
                    help="Open Playwright browser on obs-machine for Patreon login")

    # Behaviour
    ap.add_argument("--no-obs", action="store_true",
                    help="Pass --no-obs to obs_capture.py (playback only, no recording)")
    ap.add_argument("--no-shuffle", action="store_true",
                    help="Capture in original order (don't shuffle for human-like pattern)")
    ap.add_argument("--deploy-only", action="store_true",
                    help="Deploy capture script to obs-machine and exit")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would be captured without doing it")
    ap.add_argument("--skip-deploy", action="store_true",
                    help="Skip deploying the capture script (use already-deployed version)")

    args = ap.parse_args()

    # ---- Login ---------------------------------------------------------------
    if args.login:
        if not deploy(skip=args.skip_deploy):
            return 1
        return remote_login()

    # ---- Deploy --------------------------------------------------------------
    if not deploy(skip=args.skip_deploy):
        return 1
    if args.deploy_only:
        return 0

    # ---- Collect URLs --------------------------------------------------------
    urls = collect_urls(args)

    if not urls:
        print("Nothing to do.  Provide --url, --urls-file, or --collection.",
              file=sys.stderr)
        return 2

    # Mild shuffle for multi-video runs (unless --no-shuffle or single URL)
    if len(urls) > 1 and not args.no_shuffle:
        urls = mild_shuffle(urls)
        print(f"[order] Mildly shuffled {len(urls)} URLs "
              "(use --no-shuffle to keep original order)", flush=True)

    # ---- Dry run -------------------------------------------------------------
    if args.dry_run:
        already_seen = load_seen()
        print(f"\n[dry-run] Would capture {len(urls)} video(s):", flush=True)
        for i, u in enumerate(urls, 1):
            tag = " (already seen)" if u in already_seen else ""
            print(f"  {i}. {u}{tag}", flush=True)
        avg_break = (BREAK_MIN_SECONDS + BREAK_MAX_SECONDS) / 2
        est_break_mins = (len(urls) - 1) * avg_break / 60
        print(f"\n  Estimated break time between videos: ~{est_break_mins:.0f} min "
              f"({BREAK_MIN_SECONDS}-{BREAK_MAX_SECONDS}s per break)", flush=True)
        return 0

    # ---- Capture loop --------------------------------------------------------
    results: list[tuple[str, dict, str | None]] = []

    for i, url in enumerate(urls, 1):
        print(f"\n\n{'#' * 60}", flush=True)
        print(f"# [{i}/{len(urls)}] {url}", flush=True)
        print(f"{'#' * 60}", flush=True)

        result = capture_one(url, use_obs=not args.no_obs)
        final_path: str | None = None

        if result["ok"]:
            # Move recording to backup dir on the obs-machine
            if result.get("output_path"):
                final_path = move_recording_remote(result["output_path"])
            mark_seen(url)
        else:
            print(f"  FAILED: {result.get('error', 'unknown error')}", flush=True)

        results.append((url, result, final_path))

        # Human-like break between captures (not after the last one)
        if i < len(urls):
            human_break(i, len(urls))

    # ---- Summary -------------------------------------------------------------
    print(f"\n\n{'=' * 60}", flush=True)
    print("SUMMARY", flush=True)
    print(f"{'=' * 60}", flush=True)

    ok_count = 0
    for url, result, final_path in results:
        if result["ok"]:
            ok_count += 1
            title = result.get("title") or url.rsplit("/", 1)[-1]
            dur = result.get("duration", 0)
            dest = final_path or "(playback only)"
            print(f"  [OK]   {title} ({dur / 60:.0f} min) -> {dest}", flush=True)
        else:
            print(f"  [FAIL] {url} -- {result.get('error', '?')}", flush=True)

    print(f"\n  {ok_count}/{len(results)} succeeded", flush=True)
    print(f"{'=' * 60}", flush=True)

    if ok_count > 0:
        print(f"\nRecordings saved to {REMOTE_BACKUP_DIR} on {OBS_HOST}", flush=True)

    return 0 if ok_count == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
