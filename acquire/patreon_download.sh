#!/usr/bin/env bash
# Download Patreon videos/audio you have access to, using your logged-in browser
# session (cookies). You must be a paying member and logged into Patreon in the
# browser you name below. Personal use: fetch your own accessible content to
# transcribe locally.
#
# Usage:
#   ./fetch_patreon.sh <BROWSER> <DEST_DIR> <URL...>
#   BROWSER = firefox | chrome | brave | edge | chromium  (whichever you use for Patreon)
#
# Examples:
#   # one post, audio only (smallest/fastest for transcripts):
#   ./fetch_patreon.sh firefox "/mnt/secondary/FIRE Investing Masterclass" \
#       "https://www.patreon.com/posts/68412694"
#
#   # a whole collection:
#   ./fetch_patreon.sh firefox "/mnt/secondary/FIRE Investing Masterclass" \
#       "https://www.patreon.com/collection/31667"
set -euo pipefail

BROWSER="${1:?browser, e.g. firefox/chrome/brave}"
DEST="${2:?destination folder}"; shift 2
[ "$#" -ge 1 ] || { echo "give at least one Patreon URL"; exit 1; }

# AUDIO=1 (default) grabs bestaudio only; AUDIO=0 grabs full video (for slide OCR later).
AUDIO="${AUDIO:-1}"
if [ "$AUDIO" = "1" ]; then FMT=(-f bestaudio -x --audio-format m4a); else FMT=(-f "bv*+ba/b"); fi

mkdir -p "$DEST"
uvx yt-dlp \
  --cookies-from-browser "$BROWSER" \
  "${FMT[@]}" \
  --no-warnings --ignore-errors \
  -o "$DEST/%(title)s.%(ext)s" \
  "$@"

echo "Done. Now transcribe with:"
echo "  uv run transcribe.py \"$DEST\" --model large-v3-turbo --workers 4 --cpu-threads 4"
