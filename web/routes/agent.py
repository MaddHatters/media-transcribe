from __future__ import annotations

from fastapi import APIRouter, Request

from web.models import AgentHealth
from web.services import AgentUnavailableError

router = APIRouter()


@router.get("/health")
async def agent_health(request: Request):
    obs_client = request.app.state.obs_client
    try:
        return await obs_client.health_check()
    except AgentUnavailableError:
        return AgentHealth(
            healthy=False, obs_connected=False, chrome_available=False,
            disk_ok=False, error="Agent server unreachable",
        )


@router.get("/status")
async def agent_status(request: Request):
    obs_client = request.app.state.obs_client
    try:
        return await obs_client.get_status()
    except AgentUnavailableError:
        return {
            "health": {"healthy": False, "error": "Agent server unreachable"},
            "watcher": {"running": False},
            "pipeline": {"running": False},
            "disk": {},
        }
