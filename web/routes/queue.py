from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from web.database import get_db
from web.models import QueueAddRequest
from web.services.queue_service import QueueService

router = APIRouter()


class PriorityUpdate(BaseModel):
    priority: int


class ReorderRequest(BaseModel):
    post_ids: list[str]


def _queue_service(request: Request, db=Depends(get_db)) -> QueueService:
    return QueueService(db, request.app.state.obs_client)


@router.get("/")
async def get_queue(service: QueueService = Depends(_queue_service)):
    return await service.get_queue()


@router.post("/")
async def add_to_queue(body: QueueAddRequest, service: QueueService = Depends(_queue_service)):
    count = await service.add_to_queue(body.post_ids, body.priority)
    return {"added": count}


@router.delete("/{post_id}")
async def remove_from_queue(post_id: str, service: QueueService = Depends(_queue_service)):
    removed = await service.remove_from_queue(post_id)
    return {"removed": removed}


@router.patch("/{post_id}")
async def update_priority(
    post_id: str, body: PriorityUpdate, service: QueueService = Depends(_queue_service),
):
    await service.update_priority(post_id, body.priority)
    return {"ok": True}


@router.post("/reorder")
async def reorder(body: ReorderRequest, service: QueueService = Depends(_queue_service)):
    await service.reorder(body.post_ids)
    return {"ok": True}


@router.post("/start")
async def start_queue(service: QueueService = Depends(_queue_service)):
    return await service.start_queue()


@router.post("/pause")
async def pause_queue(service: QueueService = Depends(_queue_service)):
    await service.pause_queue()
    return {"ok": True}


@router.post("/clear")
async def clear_completed(service: QueueService = Depends(_queue_service)):
    await service.clear_completed()
    return {"ok": True}
