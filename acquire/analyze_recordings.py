#!/usr/bin/env python3
"""Orchestrate MasterClass video quality analysis from devbox-01.

Deploys the video analyzer script to the obs-machine (Windows box), runs it
via SSH against the MasterClass video directory, and transfers the quality
report back to local storage.

Prerequisites:
  - SSH key-based access to Matt@100.66.194.100 (the obs-machine)
  - ffmpeg and ffprobe installed on the obs-machine (via WinGet)
  - MasterClass recordings in D:\\MasterClass Video Backup\\ on the obs-machine

Usage:
  # Analyze all recordings:
  uv run acquire/analyze_recordings.py

  # Analyze a single recording:
  uv run acquire/analyze_recordings.py --single "Masterclass 1 - Stock Market Investing - History & Intro.mkv"

  # Deploy script only (don't run analysis):
  uv run acquire/analyze_recordings.py --deploy-only

  # Skip deployment (use existing script on obs-machine):
  uv run acquire/analyze_recordings.py --skip-deploy

  # Skip per-frame bitrate analysis (faster):
  uv run acquire/analyze_recordings.py --skip-bitrate

  # Custom video directory:
  uv run acquire/analyze_recordings.py --video-dir "D:\\Other Videos"
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
REMOTE_SCRIPT_REL = r"scripts\video_analyzer.py"        # relative to REMOTE_PROJECT
REMOTE_REPORT = r"C:\Users\Matt\agent-control\state\video_quality_report.json"

LOCAL_SCRIPT = Path(__file__).parent / "video_analyzer_remote.py"
LOCAL_REPORT = Path("data/masterclass_quality_report.json")

DEFAULT_VIDEO_DIR = r"D:\MasterClass Video Backup"

# SSH options shared across all connections
SSH_OPTS = ["-o", "ConnectTimeout=15", "-o", "StrictHostKeyChecking=no"]


# ---------------------------------------------------------------------------
# SSH / SCP helpers  (same pattern as record_patreon.py / catalog_patreon.py)
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
    line (used for long-running analysis sessions).
    """
    full_cmd = [
        "ssh", *SSH_OPTS,
        "-o", "ServerAliveInterval=60",  # keep alive during long analysis
        OBS_HOST,
        command,
    ]
    if stream:
        return subprocess.Popen(
            full_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
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
    """Push the analyzer script to the obs-machine and ensure dirs exist."""
    print("[deploy] Deploying video analyzer script to obs-machine...", flush=True)
    if not LOCAL_SCRIPT.exists():
        print(
            f"  ERROR: local script not found: {LOCAL_SCRIPT}",
            file=sys.stderr,
        )
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
# Run remote analysis
# ---------------------------------------------------------------------------
def run_remote_analysis(
    video_dir: str,
    *,
    single: str | None = None,
    skip_bitrate: bool = False,
) -> dict | None:
    """SSH to the obs-machine and run the video analyzer.

    Streams stdout in real time.  Returns the parsed RESULT dict, or None
    on failure.
    """
    print(f"\n{'=' * 60}", flush=True)
    print(f"[analyze] Starting video quality analysis", flush=True)
    print(f"[dir]     {video_dir}", flush=True)
    if single:
        print(f"[single]  {single}", flush=True)
    print(f"{'=' * 60}", flush=True)

    extra_flags = ""
    if single:
        extra_flags += f' --single "{single}"'
    if skip_bitrate:
        extra_flags += " --skip-bitrate"

    cmd = (
        f"cd '{REMOTE_PROJECT}'; "
        f"python {REMOTE_SCRIPT_REL} \"{video_dir}\"{extra_flags}"
    )

    proc = ssh_run(cmd, stream=True)
    assert isinstance(proc, subprocess.Popen)

    result_line: str | None = None
    report_path: str | None = None

    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            line = line.rstrip("\n\r")
            if line.startswith("RESULT:"):
                result_line = line[7:]
            elif line.startswith("REPORT:"):
                report_path = line[7:]
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
            if report_path and "report_path" not in result:
                result["report_path"] = report_path
            return result
        except json.JSONDecodeError:
            print(
                f"  Could not parse RESULT: {result_line}",
                file=sys.stderr,
                flush=True,
            )
    return None


# ---------------------------------------------------------------------------
# Human-readable summary
# ---------------------------------------------------------------------------
VERDICT_EMOJI = {
    "clean": "✅",
    "trim_needed": "✂️",
    "has_issues": "⚠️",
    "re_record": "❌",
}

VERDICT_LABEL = {
    "clean": "Clean",
    "trim_needed": "Trim needed",
    "has_issues": "Has issues",
    "re_record": "Re-record",
}


def print_summary(report: dict) -> None:
    """Print a human-readable summary of the analysis report."""
    summary = report.get("summary", {})
    videos = report.get("videos", [])

    print(f"\n{'=' * 70}", flush=True)
    print("MASTERCLASS RECORDING QUALITY REPORT", flush=True)
    print(f"{'=' * 70}", flush=True)
    print(f"Analyzed: {report.get('analyzed_at', 'unknown')}", flush=True)
    print(f"Total videos: {report.get('total_videos', len(videos))}", flush=True)
    print(flush=True)

    # Summary counts
    print("Summary:", flush=True)
    for verdict_key in ("clean", "trim_needed", "has_issues", "re_record"):
        count = summary.get(verdict_key, 0)
        emoji = VERDICT_EMOJI.get(verdict_key, "?")
        label = VERDICT_LABEL.get(verdict_key, verdict_key)
        print(f"  {emoji} {label}: {count}", flush=True)
    print(flush=True)

    # Per-video details
    print(f"{'—' * 70}", flush=True)
    print("Per-video details:", flush=True)
    print(f"{'—' * 70}", flush=True)

    # Sort: re_record first, then has_issues, then trim_needed, then clean
    priority = {"re_record": 0, "has_issues": 1, "trim_needed": 2, "clean": 3}
    sorted_videos = sorted(
        videos,
        key=lambda v: (priority.get(v.get("verdict", "re_record"), 99), v.get("filename", "")),
    )

    for v in sorted_videos:
        verdict = v.get("verdict", "unknown")
        emoji = VERDICT_EMOJI.get(verdict, "?")
        label = VERDICT_LABEL.get(verdict, verdict)
        filename = v.get("filename", "?")
        duration = v.get("duration_display", "?")
        size = v.get("file_size_mb", 0)
        notes = v.get("notes", "")

        print(f"\n  {emoji} [{label}] {filename}", flush=True)
        print(f"     Duration: {duration}  |  Size: {size:.0f} MB", flush=True)

        if v.get("error"):
            print(f"     Error: {v['error']}", flush=True)
            continue

        print(f"     Notes: {notes}", flush=True)

        # Trim points
        if v.get("trim_start") is not None or v.get("trim_end") is not None:
            ts = v.get("trim_start", 0)
            te = v.get("trim_end", v.get("duration_seconds", 0))
            from_dur = _format_duration(ts)
            to_dur = _format_duration(te)
            print(f"     Suggested trim: {from_dur} → {to_dur}", flush=True)

        # Freezes
        freezes = v.get("freezes", [])
        if freezes:
            print(f"     Freezes ({len(freezes)}):", flush=True)
            for f in freezes[:5]:  # show first 5
                print(
                    f"       at {f.get('start_display', '?')} — "
                    f"{f['duration']:.1f}s",
                    flush=True,
                )
            if len(freezes) > 5:
                print(f"       ... and {len(freezes) - 5} more", flush=True)

        # Silence gaps
        silences = v.get("silence_gaps", [])
        if silences:
            print(f"     Silence gaps ({len(silences)}):", flush=True)
            for s in silences[:5]:
                print(
                    f"       at {s.get('start_display', '?')} — "
                    f"{s['duration']:.1f}s",
                    flush=True,
                )
            if len(silences) > 5:
                print(f"       ... and {len(silences) - 5} more", flush=True)

        # Bitrate drops
        drops = v.get("bitrate_drops", [])
        if drops:
            print(f"     Bitrate drops ({len(drops)}):", flush=True)
            for d in drops[:3]:
                print(
                    f"       at {d.get('start_display', '?')} — "
                    f"{d['duration']}s "
                    f"(min {d['min_bitrate_kbps']:.0f} kbps "
                    f"vs avg {d['avg_bitrate_kbps']:.0f} kbps)",
                    flush=True,
                )
            if len(drops) > 3:
                print(f"       ... and {len(drops) - 3} more", flush=True)

    print(f"\n{'=' * 70}", flush=True)


def _format_duration(seconds: float) -> str:
    """Format seconds as H:MM:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h}:{m:02d}:{s:02d}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--video-dir",
        default=DEFAULT_VIDEO_DIR,
        help=f"Video directory on obs-machine (default: {DEFAULT_VIDEO_DIR})",
    )
    ap.add_argument(
        "--single",
        metavar="FILENAME",
        help="Analyze only this file (basename, e.g. 'Masterclass 1.mkv')",
    )
    ap.add_argument(
        "--deploy-only",
        action="store_true",
        help="Deploy the analyzer script to the obs-machine and exit",
    )
    ap.add_argument(
        "--skip-deploy",
        action="store_true",
        help="Skip deploying the script (use existing version on obs-machine)",
    )
    ap.add_argument(
        "--skip-bitrate",
        action="store_true",
        help="Skip per-frame bitrate analysis (much faster)",
    )
    ap.add_argument(
        "--output",
        type=Path,
        default=LOCAL_REPORT,
        help=f"Local report output path (default: {LOCAL_REPORT})",
    )
    args = ap.parse_args()

    # ---- Deploy ----------------------------------------------------------
    if not args.skip_deploy:
        if not deploy_script():
            return 1
    if args.deploy_only:
        return 0

    # ---- Run remote analysis ---------------------------------------------
    result = run_remote_analysis(
        args.video_dir,
        single=args.single,
        skip_bitrate=args.skip_bitrate,
    )

    if not result or not result.get("ok"):
        err = result.get("error", "unknown") if result else "SSH failure"
        print(f"\nFAILED: {err}", file=sys.stderr, flush=True)
        return 1

    # ---- Transfer report JSON back ---------------------------------------
    print("\n[transfer] Downloading quality report from obs-machine...", flush=True)
    remote_path = result.get("report_path", REMOTE_REPORT)

    with tempfile.TemporaryDirectory() as tmpdir:
        local_file = scp_from_remote(remote_path, Path(tmpdir))
        if not local_file:
            print("  FAILED to download report", file=sys.stderr, flush=True)
            return 1

        try:
            report = json.loads(
                local_file.read_text(encoding="utf-8"),
            )
        except (json.JSONDecodeError, OSError) as e:
            print(
                f"  ERROR reading downloaded report: {e}",
                file=sys.stderr,
                flush=True,
            )
            return 1

    print("  OK", flush=True)

    # ---- Save locally ----------------------------------------------------
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    fsize_kb = args.output.stat().st_size / 1024
    print(f"\n[saved] Report: {args.output} ({fsize_kb:.1f} KB)", flush=True)

    # ---- Print human-readable summary ------------------------------------
    print_summary(report)

    # ---- Actionable next steps -------------------------------------------
    summary = report.get("summary", {})
    if summary.get("re_record", 0) > 0:
        print(
            "\n⚡ Action required: some recordings need to be re-recorded. "
            "See the details above.",
            flush=True,
        )
    if summary.get("trim_needed", 0) > 0:
        print(
            "\n✂️  Trim needed: use ffmpeg to cut black frames. Example:",
            flush=True,
        )
        print(
            '  ffmpeg -i input.mkv -ss <trim_start> -to <trim_end> '
            '-c copy output.mkv',
            flush=True,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
