from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from web.database import get_db
from web.models import DiscoveryTriggerRequest
from web.services.discovery_service import DiscoveryService

router = APIRouter()


def _discovery_service(request: Request, db=Depends(get_db)) -> DiscoveryService:
    return DiscoveryService(db, request.app.state.obs_client)


@router.post("/trigger")
async def trigger_discovery(
    body: DiscoveryTriggerRequest, service: DiscoveryService = Depends(_discovery_service),
):
    return await service.trigger(body.full_catalog, body.force)


@router.get("/history")
async def discovery_history(service: DiscoveryService = Depends(_discovery_service)):
    return await service.get_history()


@router.get("/new")
async def new_posts(service: DiscoveryService = Depends(_discovery_service)):
    return await service.get_new_posts()
