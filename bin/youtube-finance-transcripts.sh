#!/usr/bin/env bash
# Poll the "Mr. FIRED Up Wealth" YouTube channel for new uploads and save a
# timestamped transcript for each. Driven by the youtube-finance-transcripts
# systemd user timer (daily). Safe to run by hand for a manual poll.
set -euo pipefail

REPO_DIR="/home/tuna/repos/media-transcribe"
DEST="/mnt/secondary/youtube/finance"
CHANNEL_ID="UCqqHGGPbhISeKkpEx8676sw"
LOG_FILE="${REPO_DIR}/logs/youtube-finance-transcripts.log"

# systemd's minimal PATH won't include uv (~/.local/bin).
export PATH="${HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin"

cd "${REPO_DIR}"

{
    echo
    echo "=== $(date -Iseconds) ==="
    uv run acquire/youtube_channel.py "${CHANNEL_ID}" --dest "${DEST}"
} >> "${LOG_FILE}" 2>&1
