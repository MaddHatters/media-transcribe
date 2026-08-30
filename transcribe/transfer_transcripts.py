#!/usr/bin/env python3
"""Transfer new transcripts from obs-machine and optionally apply corrections.

SCPs transcript files (.srt, .txt) from the obs-machine to devbox-01,
skipping files that already exist locally (unless --force).

Usage:
    uv run transcribe/transfer_transcripts.py
    uv run transcribe/transfer_transcripts.py --apply-corrections
    uv run transcribe/transfer_transcripts.py --apply-corrections --dry-run
    uv run transcribe/transfer_transcripts.py --force   # re-download all
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
OBS_HOST = "Matt@100.66.194.100"
REMOTE_DIR = "D:/MasterClass Video Backup/transcripts/"
LOCAL_DIR = Path("/mnt/secondary/media/patreon/FIRE Investing Masterclass/transcripts")
SSH_OPTS = ["-o", "ConnectTimeout=15", "-o", "StrictHostKeyChecking=no"]
CORRECTIONS_SCRIPT = Path(__file__).parent / "apply_corrections.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def ssh_run(command: str) -> subprocess.CompletedProcess:
    """Run a command on the obs-machine via SSH."""
    return subprocess.run(
        ["ssh", *SSH_OPTS, OBS_HOST, command],
        capture_output=True, text=True, timeout=30,
    )


def list_remote_files() -> list[str]:
    """List transcript files on the obs-machine."""
    # PowerShell: list .srt and .txt files in the remote directory
    result = ssh_run(
        f'Get-ChildItem -Path "{REMOTE_DIR}" -File '
        f'-Include "*.srt","*.txt" -Name'
    )
    if result.returncode != 0:
        print(f"ERROR: Could not list remote files: {result.stderr.strip()}",
              file=sys.stderr)
        return []

    files = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip()
    ]
    return files


def scp_file(remote_name: str) -> bool:
    """SCP a single file from the obs-machine to the local directory."""
    remote_path = f"{REMOTE_DIR}{remote_name}"
    local_path = LOCAL_DIR / remote_name

    result = subprocess.run(
        [
            "scp", *SSH_OPTS,
            f"{OBS_HOST}:{remote_path}",
            str(local_path),
        ],
        capture_output=True, text=True, timeout=120,
    )

    if result.returncode != 0:
        print(f"  ERROR: {remote_name}: {result.stderr.strip()}")
        return False
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--apply-corrections", action="store_true",
        help="Run apply_corrections.py on newly transferred files",
    )
    ap.add_argument(
        "--force", action="store_true",
        help="Re-download all files (overwrite local copies)",
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be transferred without doing it",
    )
    args = ap.parse_args()

    # Ensure local directory exists
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)

    # List what's on the obs-machine
    print(f"Listing transcripts on obs-machine ({OBS_HOST})...")
    remote_files = list_remote_files()

    if not remote_files:
        print("No transcript files found on obs-machine.")
        return 0

    print(f"Found {len(remote_files)} file(s) on obs-machine")

    # Determine which files need transfer
    local_files = {f.name for f in LOCAL_DIR.iterdir() if f.is_file()}
    if args.force:
        to_transfer = remote_files
    else:
        to_transfer = [f for f in remote_files if f not in local_files]

    if not to_transfer:
        print("All files already present locally. Use --force to re-download.")
        return 0

    skipped = len(remote_files) - len(to_transfer)
    if skipped > 0:
        print(f"Skipping {skipped} file(s) already present locally")

    print(f"{'Would transfer' if args.dry_run else 'Transferring'} "
          f"{len(to_transfer)} file(s):\n")

    transferred = []
    for filename in sorted(to_transfer):
        if args.dry_run:
            print(f"  (dry) {filename}")
            transferred.append(filename)
        else:
            print(f"  {filename}...", end=" ", flush=True)
            if scp_file(filename):
                print("OK")
                transferred.append(filename)
            else:
                print("FAILED")

    print(f"\n{'Would transfer' if args.dry_run else 'Transferred'} "
          f"{len(transferred)}/{len(to_transfer)} file(s) to {LOCAL_DIR}")

    # Apply corrections if requested
    if args.apply_corrections and transferred and not args.dry_run:
        print(f"\nApplying corrections to {LOCAL_DIR}...")
        if not CORRECTIONS_SCRIPT.exists():
            print(f"ERROR: {CORRECTIONS_SCRIPT} not found", file=sys.stderr)
            return 1

        result = subprocess.run(
            [sys.executable, str(CORRECTIONS_SCRIPT), str(LOCAL_DIR)],
            timeout=120,
        )
        if result.returncode != 0:
            print("WARNING: Corrections script returned non-zero exit code",
                  file=sys.stderr)
    elif args.apply_corrections and args.dry_run:
        print(f"\n(dry) Would apply corrections to {LOCAL_DIR}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
