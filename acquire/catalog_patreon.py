#!/usr/bin/env python3
"""Orchestrate Patreon content cataloging from devbox-01.

Deploys the CDP-based catalog script to the obs-machine (Windows box), runs
it via SSH, and transfers the catalog JSON back to local storage.

Prerequisites:
  - SSH key-based access to Matt@100.66.194.100 (the obs-machine)
  - Chrome already running with CDP on the obs-machine (Launch-Chrome task)
  - Chrome logged into Patreon on the obs-machine

Usage:
  # Full catalog (scroll through all posts):
  uv run acquire/catalog_patreon.py

  # Check for new posts only (fast, minimal scrolling):
  uv run acquire/catalog_patreon.py --new-only

  # List available collections:
  uv run acquire/catalog_patreon.py --list-collections

  # Catalog a specific collection:
  uv run acquire/catalog_patreon.py --collection "Beginner Lessons"

  # Deploy the remote script without running it:
  uv run acquire/catalog_patreon.py --deploy-only

  # Custom creator URL:
  uv run acquire/catalog_patreon.py --creator-url "https://www.patreon.com/cw/other/posts"
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
OBS_HOST = "Matt@100.66.194.100"
REMOTE_PROJECT = r"C:\Users\Matt\agent-control"
REMOTE_SCRIPT_REL = r"scripts\patreon_catalog.py"   # relative to REMOTE_PROJECT
REMOTE_CATALOG = r"C:\Users\Matt\agent-control\state\patreon_catalog.json"
REMOTE_KNOWN_URLS = r"state\known_urls.json"         # relative to REMOTE_PROJECT

LOCAL_SCRIPT = Path(__file__).parent / "patreon_catalog_remote.py"
LOCAL_CATALOG = Path("data/patreon_catalog_firedupwealth.json")

DEFAULT_CREATOR_URL = "https://www.patreon.com/cw/firedupwealth/posts"

# SSH options shared across all connections
SSH_OPTS = ["-o", "ConnectTimeout=15", "-o", "StrictHostKeyChecking=no"]


# ---------------------------------------------------------------------------
# SSH / SCP helpers  (same pattern as record_patreon.py)
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
    line (used for the long-running catalog crawl).
    """
    full_cmd = [
        "ssh", *SSH_OPTS,
        "-o", "ServerAliveInterval=60",
        OBS_HOST,
        command,
    ]
    if stream:
        return subprocess.Popen(
            full_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    return subprocess.run(
        full_cmd,
        capture_output=capture,
        text=True,
        timeout=timeout,
    )


def scp_to_remote(local: Path, remote_relpath: str) -> bool:
    """SCP a file TO the obs-machine (path relative to home dir)."""
    result = subprocess.run(
        ["scp", *SSH_OPTS, str(local), f"{OBS_HOST}:{remote_relpath}"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        print(f"  SCP upload error: {result.stderr}", file=sys.stderr, flush=True)
    return result.returncode == 0


def scp_from_remote(remote_path: str, local_dest: Path) -> Path | None:
    """SCP a file FROM the obs-machine.

    *remote_path* may use backslashes (Windows); they're normalised for SCP.
    Returns the local path on success, None on failure.
    """
    local_dest.mkdir(parents=True, exist_ok=True)
    filename = Path(remote_path).name
    local_file = local_dest / filename
    scp_remote = remote_path.replace("\\", "/")

    result = subprocess.run(
        ["scp", *SSH_OPTS, f"{OBS_HOST}:{scp_remote}", str(local_file)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        print(f"  SCP download error: {result.stderr}", file=sys.stderr, flush=True)
        return None
    return local_file


# ---------------------------------------------------------------------------
# Deploy
# ---------------------------------------------------------------------------
def deploy_script() -> bool:
    """Push the catalog script to the obs-machine and ensure dirs exist."""
    print("[deploy] Deploying catalog script to obs-machine...", flush=True)
    if not LOCAL_SCRIPT.exists():
        print(f"  ERROR: local script not found: {LOCAL_SCRIPT}", file=sys.stderr)
        return False

    # Ensure remote directories exist
    ssh_run(
        f"cd '{REMOTE_PROJECT}'; "
        "mkdir state 2>$null; mkdir scripts 2>$null; echo ok",
        timeout=15,
    )

    ok = scp_to_remote(LOCAL_SCRIPT, f"agent-control/{REMOTE_SCRIPT_REL}")
    print("  OK" if ok else "  FAILED", flush=True)
    return ok


# ---------------------------------------------------------------------------
# Local catalog operations
# ---------------------------------------------------------------------------
def load_local_catalog(path: Path) -> dict | None:
    """Load the existing catalog from disk, or None if absent/corrupt."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(
            f"  WARNING: could not load existing catalog: {e}",
            file=sys.stderr,
            flush=True,
        )
        return None


def extract_known_urls(catalog: dict) -> list[str]:
    """Return the list of post URLs from a catalog dict."""
    return [p["url"] for p in catalog.get("posts", []) if p.get("url")]


def upload_known_urls(urls: list[str]) -> bool:
    """Write known URLs to a temp file and SCP it to the obs-machine."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8",
    ) as f:
        json.dump(urls, f)
        tmp_path = Path(f.name)

    try:
        ok = scp_to_remote(tmp_path, f"agent-control/{REMOTE_KNOWN_URLS}")
        return ok
    finally:
        tmp_path.unlink(missing_ok=True)


def merge_catalogs(existing: dict, new_posts: list[dict]) -> dict:
    """Prepend *new_posts* to *existing*, deduplicating by URL."""
    existing_urls = {p["url"] for p in existing.get("posts", []) if p.get("url")}
    truly_new = [p for p in new_posts if p.get("url") not in existing_urls]

    if not truly_new:
        print("  [merge] No new posts to add", flush=True)
        return existing

    merged = truly_new + existing.get("posts", [])
    existing["posts"] = merged
    existing["total_posts"] = len(merged)
    # Keep the latest cataloged_at timestamp
    from datetime import datetime, timezone
    existing["cataloged_at"] = datetime.now(timezone.utc).isoformat()

    print(
        f"  [merge] Prepended {len(truly_new)} new post(s) "
        f"(total: {len(merged)})",
        flush=True,
    )
    return existing


# ---------------------------------------------------------------------------
# Run the remote catalog script
# ---------------------------------------------------------------------------
def _stream_remote(cmd: str) -> dict | None:
    """SSH *cmd* to the obs-machine, stream stdout, parse RESULT/CATALOG.

    Shared helper for both catalog and list-collections flows.
    Returns the parsed RESULT dict (with ``catalog_path`` attached when
    a CATALOG: line was seen), or None on failure.
    """
    proc = ssh_run(cmd, stream=True)
    assert isinstance(proc, subprocess.Popen)

    result_line: str | None = None
    catalog_path: str | None = None

    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            line = line.rstrip("\n\r")
            if line.startswith("RESULT:"):
                result_line = line[7:]
            elif line.startswith("CATALOG:"):
                catalog_path = line[8:]
            print(f"  [remote] {line}", flush=True)
    except KeyboardInterrupt:
        print("\n  [interrupted] killing remote process...", flush=True)
        proc.terminate()
        raise

    proc.wait()

    if proc.returncode != 0 and not result_line:
        stderr = proc.stderr.read() if proc.stderr else ""  # type: ignore[union-attr]
        print(
            f"  SSH error (exit {proc.returncode}): {stderr}",
            file=sys.stderr,
            flush=True,
        )
        return None

    if result_line:
        try:
            result = json.loads(result_line)
            if catalog_path and "catalog_path" not in result:
                result["catalog_path"] = catalog_path
            return result
        except json.JSONDecodeError:
            print(
                f"  Could not parse RESULT: {result_line}",
                file=sys.stderr,
                flush=True,
            )
    return None


def run_remote_catalog(
    creator_url: str,
    *,
    new_only: bool = False,
    collection: str | None = None,
) -> dict | None:
    """SSH to the obs-machine and run the catalog script.

    Streams stdout in real time.  Returns the parsed RESULT dict, or None
    on failure.
    """
    mode = "collection" if collection else ("new-only" if new_only else "full catalog")
    print(f"\n{'=' * 60}", flush=True)
    print(f"[catalog] {creator_url}", flush=True)
    print(f"[mode]    {mode}", flush=True)
    if collection:
        print(f"[collection] {collection}", flush=True)
    print(f"{'=' * 60}", flush=True)

    extra_flags = ""
    if new_only:
        extra_flags += f" --known-urls {REMOTE_KNOWN_URLS}"
    if collection:
        extra_flags += f' --collection "{collection}"'

    cmd = (
        f"cd '{REMOTE_PROJECT}'; "
        f"uv run {REMOTE_SCRIPT_REL} \"{creator_url}\"{extra_flags}"
    )
    return _stream_remote(cmd)


def run_list_collections(creator_url: str) -> dict | None:
    """SSH to the obs-machine and list collections.

    Returns the parsed RESULT dict (contains a ``collections`` list).
    """
    print(f"\n{'=' * 60}", flush=True)
    print(f"[list-collections] {creator_url}", flush=True)
    print(f"{'=' * 60}", flush=True)

    cmd = (
        f"cd '{REMOTE_PROJECT}'; "
        f"uv run {REMOTE_SCRIPT_REL} \"{creator_url}\" --list-collections"
    )
    return _stream_remote(cmd)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--creator-url",
        default=DEFAULT_CREATOR_URL,
        help=f"Creator posts page URL (default: {DEFAULT_CREATOR_URL})",
    )
    ap.add_argument(
        "--new-only",
        action="store_true",
        help="Only catalog new posts (stop at the first known post)",
    )
    ap.add_argument(
        "--list-collections",
        action="store_true",
        help="List available collections from the creator page and exit",
    )
    ap.add_argument(
        "--collection",
        metavar="NAME",
        help="Catalog posts from a specific collection (by name or substring)",
    )
    ap.add_argument(
        "--deploy-only",
        action="store_true",
        help="Deploy the catalog script to the obs-machine and exit",
    )
    ap.add_argument(
        "--skip-deploy",
        action="store_true",
        help="Skip deploying the script (use existing version on obs-machine)",
    )
    ap.add_argument(
        "--output",
        type=Path,
        default=LOCAL_CATALOG,
        help=f"Local catalog output path (default: {LOCAL_CATALOG})",
    )
    args = ap.parse_args()

    # ---- Deploy ----------------------------------------------------------
    if not args.skip_deploy:
        if not deploy_script():
            return 1
    if args.deploy_only:
        return 0

    # ---- List-collections (quick query, no catalog transfer) -------------
    if args.list_collections:
        result = run_list_collections(args.creator_url)
        if not result or not result.get("ok"):
            err = result.get("error", "unknown") if result else "SSH failure"
            print(f"\nFAILED: {err}", file=sys.stderr, flush=True)
            return 1
        return 0

    # ---- New-only prep: upload known URLs --------------------------------
    if args.new_only:
        existing = load_local_catalog(args.output)
        if existing:
            known = extract_known_urls(existing)
            print(
                f"[prep] Uploading {len(known)} known URL(s) to obs-machine...",
                flush=True,
            )
            if not upload_known_urls(known):
                print("  FAILED to upload known URLs", file=sys.stderr, flush=True)
                return 1
            print("  OK", flush=True)
        else:
            print(
                "[prep] No existing catalog found — running full catalog instead",
                flush=True,
            )
            args.new_only = False

    # ---- Run remote catalog ----------------------------------------------
    result = run_remote_catalog(
        args.creator_url,
        new_only=args.new_only,
        collection=args.collection,
    )

    if not result or not result.get("ok"):
        err = result.get("error", "unknown") if result else "SSH failure"
        print(f"\nFAILED: {err}", file=sys.stderr, flush=True)
        return 1

    # ---- Transfer catalog JSON back --------------------------------------
    print("\n[transfer] Downloading catalog from obs-machine...", flush=True)
    remote_path = result.get("catalog_path", REMOTE_CATALOG)

    with tempfile.TemporaryDirectory() as tmpdir:
        local_file = scp_from_remote(remote_path, Path(tmpdir))
        if not local_file:
            print("  FAILED to download catalog", file=sys.stderr, flush=True)
            return 1

        try:
            remote_catalog = json.loads(
                local_file.read_text(encoding="utf-8"),
            )
        except (json.JSONDecodeError, OSError) as e:
            print(
                f"  ERROR reading downloaded catalog: {e}",
                file=sys.stderr,
                flush=True,
            )
            return 1

    print("  OK", flush=True)

    # ---- Merge (--new-only) or replace -----------------------------------
    if args.new_only:
        existing = load_local_catalog(args.output)
        if existing:
            final = merge_catalogs(existing, remote_catalog.get("posts", []))
        else:
            final = remote_catalog
    else:
        final = remote_catalog

    # ---- Save locally ----------------------------------------------------
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(final, indent=2, ensure_ascii=False), encoding="utf-8",
    )

    # ---- Summary ---------------------------------------------------------
    total = final.get("total_posts", len(final.get("posts", [])))
    video_count = sum(1 for p in final.get("posts", []) if p.get("has_video"))
    fsize_kb = args.output.stat().st_size / 1024

    print(f"\n{'=' * 60}", flush=True)
    print(f"CATALOG SAVED: {args.output}", flush=True)
    print(f"  Total posts: {total}", flush=True)
    print(f"  Videos:      {video_count}", flush=True)
    print(f"  File size:   {fsize_kb:.1f} KB", flush=True)
    print(f"{'=' * 60}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
