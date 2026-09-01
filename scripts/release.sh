#!/usr/bin/env bash
set -euo pipefail

REMOTE="Matt@100.66.194.100"
REMOTE_DIR="C:/Users/Matt/transcribe"

# -- Color helpers --
if [ -t 1 ]; then
    GREEN='\033[0;32m'
    RED='\033[0;31m'
    YELLOW='\033[0;33m'
    BOLD='\033[1m'
    RESET='\033[0m'
else
    GREEN=''
    RED=''
    YELLOW=''
    BOLD=''
    RESET=''
fi

ok()   { echo -e "${GREEN}✓${RESET} $*"; }
fail() { echo -e "${RED}✗${RESET} $*"; }
warn() { echo -e "${YELLOW}!${RESET} $*"; }

# -- Parse flags --
VERIFY=false
for arg in "$@"; do
    case "$arg" in
        --verify) VERIFY=true ;;
        *) fail "Unknown flag: $arg"; exit 1 ;;
    esac
done

# ==========================================================
# Section 1 — Pre-flight checks
# ==========================================================
echo -e "\n${BOLD}==> Pre-flight checks${RESET}"

BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$BRANCH" != "main" ]; then
    fail "Not on main branch (on '$BRANCH'). Switch to main before releasing."
    exit 1
fi
ok "On branch main"

if ! git diff --quiet || ! git diff --cached --quiet; then
    fail "Working tree is dirty. Commit or stash changes first."
    exit 1
fi
ok "Working tree clean"

if ! ssh -o ConnectTimeout=5 "$REMOTE" "echo ok" >/dev/null 2>&1; then
    fail "obs-machine unreachable at $REMOTE"
    exit 1
fi
ok "obs-machine reachable"

VERSION=$(uv run python -c "from src import __version__; print(__version__)")
COMMIT=$(git rev-parse --short HEAD)
echo -e "  Version: ${BOLD}${VERSION}${RESET}"
echo -e "  Commit:  ${BOLD}${COMMIT}${RESET}"

# ==========================================================
# Section 2 — Run tests
# ==========================================================
echo -e "\n${BOLD}==> Running tests${RESET}"

if ! uv run pytest; then
    fail "Tests failed — aborting release."
    exit 1
fi
ok "All tests passed"

# ==========================================================
# Section 3 — Deploy
# ==========================================================
echo -e "\n${BOLD}==> Deploying to obs-machine${RESET}"

scp -r src/ cli.py pyproject.toml launch_chrome.bat \
    transcribe/corrections.txt transcribe/finance_vocab.txt \
    "$REMOTE:$REMOTE_DIR/"
ok "Files copied"

ssh "$REMOTE" "cd $REMOTE_DIR; uv sync --extra capture"
ok "Dependencies synced"

FILE_COUNT=$(ssh "$REMOTE" "cd $REMOTE_DIR; powershell -Command \"(Get-ChildItem -Path src -Recurse -Filter *.py).Count\"")
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
echo "  Files deployed: $FILE_COUNT Python files"
echo "  Timestamp: $TIMESTAMP"

# ==========================================================
# Section 4 — Post-deploy verification
# ==========================================================
echo -e "\n${BOLD}==> Post-deploy verification${RESET}"

LOCAL_VER=$(uv run python -c "from src import __version__; print(__version__)")
REMOTE_VER=$(ssh "$REMOTE" "cd $REMOTE_DIR; uv run python -c \"from src import __version__; print(__version__)\"")

if [ "$LOCAL_VER" = "$REMOTE_VER" ]; then
    ok "Version match: $LOCAL_VER"
else
    warn "Version mismatch — local=$LOCAL_VER remote=$REMOTE_VER"
fi

ssh "$REMOTE" "cd $REMOTE_DIR; uv run cli.py --help" >/dev/null 2>&1
ok "CLI imports OK on obs-machine"

if [ "$VERIFY" = true ]; then
    echo "  Running preflight on obs-machine..."
    ssh "$REMOTE" "cd $REMOTE_DIR; uv run cli.py preflight"
    ok "Preflight passed on obs-machine"
fi

# ==========================================================
# Section 5 — Summary
# ==========================================================
echo -e "\n${BOLD}==> Release complete${RESET}"
echo "  Version:  $VERSION"
echo "  Commit:   $COMMIT"
echo "  Target:   $REMOTE:$REMOTE_DIR"
echo "  Time:     $TIMESTAMP"
echo ""
echo "To run pipeline:"
echo "  ssh $REMOTE \"cd C:\\Users\\Matt\\transcribe; uv run cli.py pipeline --queue <file>\""
