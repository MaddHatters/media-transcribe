from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from web.models import WatcherConfigUpdate, WatcherStatus

router = APIRouter()


@router.get("/status")
async def watcher_status(request: Request):
    obs_client = request.app.state.obs_client
    status = await obs_client.get_status()
    w = status.get("watcher", {})
    return WatcherStatus(
        running=w.get("running", False),
        pid=w.get("pid"),
        cycle=w.get("cycle", 0),
        interval_hours=w.get("interval_hours", 24.0),
        last_run=w.get("last_run"),
        next_run=w.get("next_run"),
        total_recorded=w.get("total_recorded", 0),
    )


@router.post("/start")
async def start_watcher(body: WatcherConfigUpdate, request: Request):
    obs_client = request.app.state.obs_client
    config = {}
    if body.interval_hours is not None:
        config["interval_hours"] = body.interval_hours
    if body.max_per_run is not None:
        config["max_per_run"] = body.max_per_run
    if body.steps is not None:
        config["steps"] = body.steps
    return await obs_client.start_watcher(config)


@router.post("/stop")
async def stop_watcher(request: Request):
    obs_client = request.app.state.obs_client
    return await obs_client.stop_watcher()


@router.patch("/config")
async def update_config(body: WatcherConfigUpdate, request: Request):
    if body.interval_hours is not None and body.interval_hours < 12:
        raise HTTPException(status_code=422, detail="interval_hours must be >= 12")
    obs_client = request.app.state.obs_client
    config = {}
    if body.interval_hours is not None:
        config["interval_hours"] = body.interval_hours
    if body.max_per_run is not None:
        config["max_per_run"] = body.max_per_run
    if body.steps is not None:
        config["steps"] = body.steps
    return await obs_client.start_watcher(config)
