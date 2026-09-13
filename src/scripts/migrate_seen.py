"""One-time migration: backfill catalog from seen_urls.txt and recording files.

Reads seen_urls.txt from the obs-machine via SSH, matches URLs to catalog entries,
and sets ingested_status='complete'. Also normalizes the CDP-scraped catalog and
conference catalog into the main catalog.

Usage:
    uv run python src/scripts/migrate_seen.py [--catalog data/patreon_full_catalog.json]
                                               [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

from src.catalog import extract_post_id
from src.config import CATALOG_PATH

DEFAULT_CATALOG = str(CATALOG_PATH)
CDP_CATALOG = "data/patreon_catalog_firedupwealth.json"
CONFERENCE_CATALOG = "data/fuw_2026_conference_catalog.json"
SSH_HOST = "obs-machine"
SEEN_URLS_PATH = r"C:\Users\Matt\agent-control\state\seen_urls.txt"
BACKUP_DIR = r"D:\MasterClass Video Backup"


def _ssh_read_file(host: str, remote_path: str) -> str | None:
    try:
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=10", host, f'type "{remote_path}"'],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return result.stdout
        log.warning("SSH read failed for %s: %s", remote_path, result.stderr.strip())
        return None
    except (subprocess.TimeoutExpired, OSError) as exc:
        log.warning("SSH failed: %s", exc)
        return None


def _ssh_list_dir(host: str, remote_dir: str) -> list[dict]:
    try:
        cmd = f'powershell -Command "Get-ChildItem -Path \'{remote_dir}\' -File -Recurse | Select-Object FullName, Length, LastWriteTime | ConvertTo-Json"'
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=10", host, cmd],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            log.warning("SSH dir listing failed: %s", result.stderr.strip())
            return []
        data = json.loads(result.stdout)
        if isinstance(data, dict):
            data = [data]
        return data
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as exc:
        log.warning("SSH dir listing failed: %s", exc)
        return []


def _normalize_cdp_entry(entry: dict) -> dict | None:
    url = entry.get("url", "")
    post_id = extract_post_id(url)
    if not post_id:
        return None
    return {
        "post_id": post_id,
        "url": f"https://www.patreon.com/posts/{post_id}",
        "title": entry.get("title", ""),
        "created_at": entry.get("date", ""),
        "post_type": entry.get("type", ""),
        "has_video": entry.get("has_video", False),
        "recorded": entry.get("recorded", False),
    }


def _normalize_conference_session(session: dict) -> dict | None:
    url = session.get("url", "")
    post_id = extract_post_id(url)
    if not post_id:
        return None
    return {
        "post_id": post_id,
        "url": url,
        "title": session.get("title", ""),
        "created_at": "",
        "post_type": "video_external_file",
        "has_video": True,
        "recorded": session.get("recorded", False),
    }


def migrate(catalog_path: str = DEFAULT_CATALOG, dry_run: bool = False) -> dict:
    main_path = Path(catalog_path)
    stats = {"seen_matched": 0, "cdp_merged": 0, "conference_merged": 0, "total": 0}

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from src.catalog import CatalogManager

    cm = CatalogManager(main_path)
    posts = cm.load()
    posts_by_id = {p["post_id"]: p for p in posts if "post_id" in p}
    posts_by_url: dict[str, dict] = {}
    for p in posts:
        if "url" in p:
            posts_by_url[p["url"]] = p

    # 1. Merge CDP-scraped catalog
    cdp_path = Path(CDP_CATALOG)
    if cdp_path.exists():
        try:
            cdp_data = json.loads(cdp_path.read_text(encoding="utf-8"))
            for entry in cdp_data.get("posts", []):
                normalized = _normalize_cdp_entry(entry)
                if normalized and normalized["post_id"] not in posts_by_id:
                    posts_by_id[normalized["post_id"]] = normalized
                    stats["cdp_merged"] += 1
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Could not read CDP catalog: %s", exc)

    # 2. Merge conference catalog
    conf_path = Path(CONFERENCE_CATALOG)
    if conf_path.exists():
        try:
            conf_data = json.loads(conf_path.read_text(encoding="utf-8"))
            for session in conf_data.get("sessions", []):
                normalized = _normalize_conference_session(session)
                if normalized and normalized["post_id"] not in posts_by_id:
                    posts_by_id[normalized["post_id"]] = normalized
                    stats["conference_merged"] += 1
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Could not read conference catalog: %s", exc)

    # 3. Backfill from seen_urls.txt
    seen_content = _ssh_read_file(SSH_HOST, SEEN_URLS_PATH)
    if seen_content:
        seen_urls = {line.strip() for line in seen_content.splitlines() if line.strip()}
        for url in seen_urls:
            pid = extract_post_id(url)
            entry = posts_by_id.get(pid) or posts_by_url.get(url)
            if entry and not entry.get("ingested_status"):
                entry["ingested_status"] = "complete"
                entry["recorded"] = True
                stats["seen_matched"] += 1
    else:
        log.info("Could not read seen_urls.txt — skipping SSH backfill")

    merged = sorted(posts_by_id.values(), key=lambda p: p.get("created_at", ""), reverse=True)
    stats["total"] = len(merged)

    if not dry_run:
        cm.save(merged)
        log.info("Catalog updated: %s", main_path)
    else:
        log.info("Dry run — no changes written")

    log.info("Migration stats: %s", stats)
    return stats


def main():
    parser = argparse.ArgumentParser(description="Migrate seen_urls.txt into catalog")
    parser.add_argument("--catalog", default=DEFAULT_CATALOG, help="Main catalog path")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    migrate(catalog_path=args.catalog, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
