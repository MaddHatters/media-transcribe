# Plan: Deploy Insights Web App to Production on devbox-01

## Task Description

Deploy the Insights web app (media-transcribe pipeline dashboard) to production on devbox-01. The app is functionally complete — all 21 implementation steps have been built, all 66 web tests pass — but it has never been deployed. This plan covers creating the deploy infrastructure: systemd service, Caddy reverse proxy, DNS record, `.env` configuration, and database initialization.

**Task type:** Chore
**Complexity:** Medium

## Objective

When this plan is complete:
- `https://insights.tunalab.dev` serves the Insights pipeline dashboard to any Tailscale device
- The FastAPI backend runs as a systemd user service that auto-starts on boot and restarts on failure
- The SQLite database is initialized with data migrated from `data/patreon_full_catalog.json`
- The Vue 3 SPA is served by Caddy with proper caching headers and SPA fallback routing
- API routes (`/api/*`) and WebSocket (`/ws/*`) are proxied to FastAPI on port 8420

## Solution Approach

Follow the established devbox-01 deployment pattern used by orchestrator, life-tracker, and portfolio-api:

1. **Caddy serves the frontend** — Caddy handles TLS, static files from `frontend/dist/`, SPA fallback, and caching. Only `/api/*` and `/ws/*` are reverse-proxied to FastAPI. This avoids modifying `web/app.py` and matches the machine's existing conventions.
2. **systemd user service** — Consistent with all other services on devbox-01 (`portfolio-api.service`, `life-tracker.service`, `orchestrator-backend.service`). Runs as user `tuna`, managed without `sudo`.
3. **`caddy-vhost` + `cf-dns`** — Use the existing deployment tools at `/usr/local/bin/` to safely add the Caddy config and DNS record.

> **Note:** The architecture doc (`app_docs/insights-app-architecture.md`) specifies a system-level service at `/etc/systemd/system/` and a simple `reverse_proxy` in Caddy with FastAPI serving static files. This plan deviates to match the machine's actual conventions (user services, Caddy-served frontends), avoiding application code changes. The architecture doc should be updated after deployment to reflect the actual setup.

## Relevant Files

### Existing Files

- `web/app.py` — FastAPI app factory. Lifespan handler auto-creates SQLite DB and migrates from JSON on first run. **Do not modify.**
- `web/config.py` — Reads `AGENT_HOST`, `AGENT_PORT`, `AGENT_TOKEN` from env vars. Default host=`0.0.0.0`, port=`8420`.
- `web/database.py` — Schema, `init_db()`, `migrate_from_json()`. Auto-creates tables and indexes.
- `web/routes/__init__.py` — API router. All routes prefixed with `/api/` (catalog, queue, watcher, discovery, pipeline, agent).
- `web/routes/ws.py` — WebSocket endpoint at `/ws/events`.
- `cli.py` — `web` subcommand (line 832): starts uvicorn with `web.app:create_app`. Args: `--host` (default `0.0.0.0`), `--port` (default `8420`), `--dev` (reload).
- `frontend/dist/` — Pre-built Vue 3 SPA (already exists: `index.html`, `assets/`, `favicon.svg`, `icons.svg`).
- `frontend/package.json` — Build script: `npm run build` → `vue-tsc -b && vite build`.
- `data/patreon_full_catalog.json` — Source data for SQLite migration (1,640+ posts).
- `app_docs/insights-app-architecture.md` — Architecture reference (topology, gRPC contract, security model). Update post-deployment.

### New Files

- `deploy/caddy-insights.conf` — Caddy vhost snippet for `insights.tunalab.dev`
- `deploy/insights-backend.service` — systemd user service unit file
- `.env` — Agent credentials (gitignored, created manually)

## Implementation Phases

### Phase 1: Foundation
Create the deploy directory and configuration files (Caddy vhost, systemd unit). Generate `.env` credentials. Rebuild the frontend to ensure it's current.

### Phase 2: Core Deployment
Install the systemd service, create the DNS record, install the Caddy vhost, and start the backend. The database initializes automatically on first request.

### Phase 3: Verification
Verify the full stack: service running, API responding, frontend loading, WebSocket connecting, catalog data populated.

## Step by Step Tasks

IMPORTANT: Execute every step in order, top to bottom.

### 1. Rebuild the Frontend

The `frontend/dist/` directory already exists, but rebuild to ensure it reflects the latest source.

- `cd /home/tuna/repos/media-transcribe/frontend && npm run build`
- Verify output: `ls frontend/dist/index.html frontend/dist/assets/`
- The build runs `vue-tsc -b && vite build` (type-check then bundle)

### 2. Create the `deploy/` Directory

- `mkdir -p /home/tuna/repos/media-transcribe/deploy`

### 3. Create the Caddy Vhost Config

Create `deploy/caddy-insights.conf` following the life-tracker/orchestrator pattern:

```
# ─── Insights (Media Transcribe Dashboard) ────────────────────────────────────

insights.tunalab.dev {
    bind 100.126.202.43

    handle /api/* {
        reverse_proxy localhost:8420
    }

    handle /ws/* {
        reverse_proxy localhost:8420
    }

    handle {
        root * /home/tuna/repos/media-transcribe/frontend/dist
        try_files {path} /index.html
        file_server

        @assets path /assets/*
        header @assets Cache-Control "public, max-age=31536000, immutable"

        @html path / /index.html
        header @html Cache-Control "no-cache"
    }

    tls {
        dns cloudflare {file./etc/caddy/cloudflare-api-token}
    }

    log {
        output file /var/log/caddy/insights.log {
            roll_size 10mb
            roll_keep 3
        }
    }
}
```

Key decisions:
- `bind 100.126.202.43` — Tailscale IP only (not LAN, not localhost)
- `/api/*` and `/ws/*` proxied to FastAPI (WebSocket is at `/ws/events`)
- SPA fallback: `try_files {path} /index.html` for Vue Router history mode
- Hashed assets cached immutably; `index.html` served as no-cache for instant deploys
- TLS via Cloudflare DNS-01 challenge (same as orchestrator, life-tracker)

### 4. Create the systemd User Service

Create `deploy/insights-backend.service` following the portfolio-api/life-tracker pattern:

```ini
[Unit]
Description=Insights - Media Transcribe Pipeline Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/tuna/repos/media-transcribe
Environment=PATH=/home/tuna/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=HOME=/home/tuna
EnvironmentFile=%h/repos/media-transcribe/.env
ExecStart=/home/tuna/.local/bin/uv run cli.py web --host 127.0.0.1 --port 8420
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

Key decisions:
- **User service** (not system) — consistent with all other services on devbox-01
- `--host 127.0.0.1` — binds to localhost only; Caddy handles external access
- `--port 8420` — matches architecture doc
- `EnvironmentFile=%h/repos/media-transcribe/.env` — **critical**: `web/config.py` reads env vars with `os.getenv()` but never calls `load_dotenv()`. The `EnvironmentFile` directive loads `.env` values into the service environment. `%h` expands to the user's home directory.
- `Restart=on-failure` — auto-restarts on crashes but not on clean shutdown
- `WantedBy=default.target` — starts on user login (lingering should already be enabled)

### 5. Create the `.env` File

The `.env` file is gitignored and must be created manually. The gRPC connection to obs-machine may not be available — the app will still start and serve the catalog/dashboard.

- Generate a token (or reuse an existing one if the obs-machine already has one):
  ```bash
  python3 -c "import secrets; print(f'AGENT_TOKEN={secrets.token_hex(32)}')"
  ```
- Create `/home/tuna/repos/media-transcribe/.env`:
  ```
  AGENT_TOKEN=<generated-or-existing-token>
  AGENT_HOST=100.66.194.100
  AGENT_PORT=8421
  ```
- Verify `.env` is in `.gitignore`:
  ```bash
  grep -q '\.env' .gitignore && echo "OK" || echo "ADD .env to .gitignore"
  ```
- **Important:** If the obs-machine agent server is also being set up, copy the same `AGENT_TOKEN` value to `C:\Users\Matt\transcribe\.env` on the obs-machine.

### 6. Install the systemd User Service

- Copy the unit file:
  ```bash
  cp deploy/insights-backend.service ~/.config/systemd/user/insights-backend.service
  ```
- Reload systemd:
  ```bash
  systemctl --user daemon-reload
  ```
- Enable the service (auto-start on boot):
  ```bash
  systemctl --user enable insights-backend.service
  ```
- Verify lingering is enabled (required for user services to run without active login):
  ```bash
  loginctl show-user tuna --property=Linger
  ```
  If `Linger=no`, enable it:
  ```bash
  sudo loginctl enable-linger tuna
  ```

### 7. Create the Cloudflare DNS Record

- Create the A record pointing `insights.tunalab.dev` to the devbox-01 Tailscale IP:
  ```bash
  sudo cf-dns create insights 100.126.202.43
  ```
- This creates a DNS-only (gray cloud) A record — Cloudflare provides DNS management only, not proxying. Only Tailscale devices can reach this IP.

### 8. Install the Caddy Vhost Config

- Use the `caddy-vhost` tool to safely append the config:
  ```bash
  sudo caddy-vhost /home/tuna/repos/media-transcribe/deploy/caddy-insights.conf
  ```
- The tool automatically:
  1. Backs up the current Caddyfile
  2. Appends the snippet
  3. Validates with `caddy validate`
  4. Restores backup on failure
  5. Reloads Caddy on success
- Create the log directory if needed:
  ```bash
  sudo mkdir -p /var/log/caddy
  ```

### 9. Start the Backend Service

- Start the service:
  ```bash
  systemctl --user start insights-backend.service
  ```
- Check status:
  ```bash
  systemctl --user status insights-backend.service
  ```
- The first startup will:
  1. Create `data/media_transcribe.db` (SQLite database)
  2. Auto-migrate 1,640+ posts from `data/patreon_full_catalog.json`
  3. Attempt gRPC connection to obs-machine (may fail silently — that's OK)

### 10. Verify the Full Stack

Run these checks in order:

1. **Backend health** — API responds on localhost:
   ```bash
   curl -s http://127.0.0.1:8420/api/catalog/posts?limit=1 | python3 -m json.tool | head -5
   ```
   Expected: JSON response with post data (confirms DB migration worked).

2. **Frontend via Caddy** — SPA loads through the reverse proxy:
   ```bash
   curl -s -o /dev/null -w "%{http_code}" https://insights.tunalab.dev/
   ```
   Expected: `200`

3. **API via Caddy** — API proxied correctly:
   ```bash
   curl -s https://insights.tunalab.dev/api/catalog/stats | python3 -m json.tool
   ```
   Expected: JSON with catalog statistics.

4. **SPA routing** — Vue Router history mode works (deep links don't 404):
   ```bash
   curl -s -o /dev/null -w "%{http_code}" https://insights.tunalab.dev/queue
   ```
   Expected: `200` (returns `index.html` via `try_files` fallback).

5. **Database populated** — SQLite has migrated data:
   ```bash
   sqlite3 data/media_transcribe.db "SELECT COUNT(*) FROM posts;"
   ```
   Expected: ~1640+ rows.

6. **Service logs** — no errors:
   ```bash
   journalctl --user -u insights-backend.service --no-pager -n 20
   ```

7. **Open in browser** — navigate to `https://insights.tunalab.dev` from any Tailscale device and verify:
   - Dashboard loads with catalog data
   - Agent health badge shows status (may be red if obs-machine is unreachable — that's expected)
   - Catalog filter/search works
   - Navigation between views works (catalog, queue, watcher, discovery)

### 11. Update Architecture Documentation

After successful deployment, update `app_docs/insights-app-architecture.md` to reflect the actual deployment:

- systemd service is a **user** service at `~/.config/systemd/user/insights-backend.service`, not a system service
- Caddy serves the frontend directly (not FastAPI)
- Update the service management commands from `sudo systemctl` to `systemctl --user`
- Confirm the `.env` section is accurate

## Acceptance Criteria

- [ ] `systemctl --user status insights-backend.service` shows `active (running)`
- [ ] `https://insights.tunalab.dev` loads the Vue SPA dashboard from any Tailscale device
- [ ] `https://insights.tunalab.dev/api/catalog/stats` returns JSON with catalog statistics
- [ ] `https://insights.tunalab.dev/queue` returns 200 (SPA routing, not 404)
- [ ] `sqlite3 data/media_transcribe.db "SELECT COUNT(*) FROM posts;"` returns 1600+ rows
- [ ] Service auto-restarts after simulated crash: `systemctl --user kill insights-backend.service && sleep 6 && systemctl --user is-active insights-backend.service` returns `active`
- [ ] Service survives reboot (or `systemctl --user restart insights-backend.service`)
- [ ] No existing application code (`web/`, `frontend/src/`, `cli.py`) was modified
- [ ] All 66 web tests still pass: `uv run pytest tests/web/ -v`

## Validation Commands

Execute these commands to validate the task is complete:

- `systemctl --user is-active insights-backend.service` — Should print `active`
- `curl -sf http://127.0.0.1:8420/api/catalog/posts?limit=1 | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'{len(d)} posts returned')"` — Should print `1 posts returned`
- `curl -sf -o /dev/null -w "%{http_code}\n" https://insights.tunalab.dev/` — Should print `200`
- `curl -sf https://insights.tunalab.dev/api/catalog/stats | python3 -m json.tool` — Should print JSON stats
- `curl -sf -o /dev/null -w "%{http_code}\n" https://insights.tunalab.dev/queue` — Should print `200` (SPA fallback)
- `sqlite3 /home/tuna/repos/media-transcribe/data/media_transcribe.db "SELECT COUNT(*) FROM posts;"` — Should be 1600+
- `uv run pytest tests/web/ -v` — All 66 tests pass

## Notes

- **gRPC connectivity:** The obs-machine agent server at `100.66.194.100:8421` may not be running. The web app handles this gracefully — the `ObsClient.connect()` in the lifespan is non-blocking, and the agent health badge in the UI will show the connection status. All local features (catalog browsing, filtering, queue management) work without the gRPC connection.
- **CORS origins:** `web/config.py` currently allows `http://localhost:5173` and `http://localhost:8420`. Since Caddy serves the frontend on `insights.tunalab.dev` and proxies API calls, the browser's origin matches the API origin — no CORS issue. The existing CORS config supports the Vite dev server for development.
- **Frontend rebuilds:** After code changes to `frontend/src/`, rebuild with `cd frontend && npm run build`. Caddy serves files directly from `frontend/dist/`, so no backend restart needed — just clear the browser cache (or hard refresh, since `index.html` is served as `no-cache`).
- **Environment loading:** `web/config.py` uses raw `os.getenv()` and does NOT call `load_dotenv()` (unlike `agent/config.py` which has its own `_load_dotenv()`). The systemd unit's `EnvironmentFile=` directive handles this for production. For local development, either source the `.env` manually (`set -a; source .env; set +a; uv run cli.py web`) or add `load_dotenv()` to `web/config.py` in a future PR.
- **Log rotation:** Caddy logs rotate automatically (10mb, keep 3). Backend logs go to journald which handles its own rotation.
- **Alternative:** If FastAPI-served static files are preferred later (per the architecture doc), add `StaticFiles` mount to `web/app.py` and simplify the Caddy config to a plain `reverse_proxy localhost:8420`. This is a valid follow-up but not required for initial deployment.
