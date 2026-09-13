# Deployment Guide

## Architecture

| Machine | Role | OS | Path |
|---------|------|----|------|
| **Dev** (devbox-01) | Development, testing, discovery | Linux | `/home/tuna/repos/media-transcribe/` |
| **OBS** (obs-machine) | Screen recording, pipeline execution | Windows | `C:\Users\Matt\transcribe\` |

Both machines are git repos pointing at the same GitHub origin. Code flows dev → GitHub → OBS.

## Prerequisites

- **Git** installed on both machines
- **SSH access** to OBS machine: `Matt@100.66.194.100` (Tailscale VPN)
- **GitHub repo**: `https://github.com/MaddHatters/media-transcribe.git` (public read, no auth needed for pull)
- **Dev machine**: Python 3.12+, `uv` package manager
- **OBS machine**: Python 3.8.2 (32-bit), `.venv` at `C:\Users\Matt\transcribe\.venv`

> **Python 3.8 compatibility**: All source code must avoid 3.9+ syntax. Use `Optional[list]` not `Optional[list[str]]`, `Union[X, Y]` not `X | Y` in annotations (or use `from __future__ import annotations`), etc.

## Deploy a Change

```bash
# 1. Develop and test locally
uv run pytest tests/ -v

# 2. Commit and push
git add <files>
git commit -m "description"
git push origin main

# 3. Deploy to OBS machine
ssh Matt@100.66.194.100 "powershell -Command \"git -C 'C:\Users\Matt\transcribe' pull origin main\""

# 4. Verify
ssh Matt@100.66.194.100 "powershell -Command \"Set-Location 'C:\Users\Matt\transcribe'; python cli.py release-info\""
```

### Legacy SCP-based deploy

The `scripts/release.sh` script uses SCP to copy files directly. This still works but the git-based approach above is preferred — it tracks what's deployed, supports rollback, and avoids drift.

```bash
# Only use if git pull is broken on OBS machine
bash scripts/release.sh [--verify]
```

## What .gitignore Protects

These files exist on the OBS machine but are never committed or overwritten by `git pull`:

| Pattern | Purpose |
|---------|---------|
| `catalog_*.json`, `*_queue.json` | Generated catalogs and recording queues |
| `data/patreon_full_catalog.json` | Full discovery catalog |
| `.venv/`, `__pycache__/` | Runtime artifacts |
| `logs/`, `output/`, `transcripts/` | Pipeline output |
| `*.mkv`, `*.mp4`, `*.srt`, `*.vtt` | Media files |
| `acquire/obs_config.toml` | OBS connection config |
| `acquire/.browser-profile/` | Chrome profile data |
| `app_review/` | Generated review reports |

## Rollback

```bash
# Roll back to a specific commit
ssh Matt@100.66.194.100 "powershell -Command \"git -C 'C:\Users\Matt\transcribe' checkout <commit-hash> -- .\""

# Roll back to previous commit
ssh Matt@100.66.194.100 "powershell -Command \"git -C 'C:\Users\Matt\transcribe' reset --hard HEAD~1\""
```

## Troubleshooting

**`git pull` fails with merge conflicts** — OBS machine should never have local source edits. Force-reset:
```bash
ssh Matt@100.66.194.100 "powershell -Command \"git -C 'C:\Users\Matt\transcribe' reset --hard origin/main\""
```

**Python import errors after deploy** — Dependencies may need updating:
```bash
ssh Matt@100.66.194.100 "powershell -Command \"Set-Location 'C:\Users\Matt\transcribe'; pip install -e .\""
```

**SSH connectivity check**:
```bash
ssh -o ConnectTimeout=5 Matt@100.66.194.100 "git --version"
```

**PowerShell quoting** — Use `powershell -Command "..."` with `Set-Location` instead of `cd ... &&` (PowerShell doesn't support `&&` in older versions). Avoid nested double-quotes with single-character Python commands — use a script file instead.

## Initial Setup (Reference)

One-time setup already completed on the OBS machine (2026-09-13). Documented here for disaster recovery.

```powershell
cd C:\Users\Matt\transcribe
git init
git remote add origin https://github.com/MaddHatters/media-transcribe.git
git fetch --depth 1 origin main    # shallow fetch — history has Linux-only paths
git reset origin/main
git checkout -- .
git branch -m master main
git branch --set-upstream-to=origin/main main
```

> **Why `--depth 1`?** Early commits contain files with literal backslash characters in their paths (Linux SSH transfer artifacts). Git for Windows rejects these tree entries. A shallow clone avoids fetching that history.
