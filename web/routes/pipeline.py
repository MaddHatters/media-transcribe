from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from web.database import get_db
from web.models import PipelineRunRequest
from web.services.event_bus import EventBus
from web.services.pipeline_service import PipelineService

router = APIRouter()


def _pipeline_service(request: Request, db=Depends(get_db)) -> PipelineService:
    return PipelineService(db, request.app.state.obs_client, request.app.state.event_bus)


@router.get("/status")
async def pipeline_status(service: PipelineService = Depends(_pipeline_service)):
    return await service.get_status()


@router.post("/run")
async def run_pipeline(
    body: PipelineRunRequest, service: PipelineService = Depends(_pipeline_service),
):
    return await service.run(body.post_ids, body.steps)
