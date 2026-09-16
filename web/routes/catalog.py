from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from web.config import CATALOG_JSON_PATH
from web.database import get_db
from web.services.catalog_service import CatalogService

router = APIRouter()


class ImportRequest(BaseModel):
    json_path: str | None = None


@router.get("/stats")
async def catalog_stats(db=Depends(get_db)):
    service = CatalogService(db)
    return await service.get_stats()


@router.get("/{post_id}")
async def get_post(post_id: str, db=Depends(get_db)):
    service = CatalogService(db)
    post = await service.get_post(post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    return post


@router.get("/")
async def list_posts(
    type: str | None = None,
    status: str | None = None,
    step: str | None = None,
    search: str | None = None,
    tag: str | None = None,
    source_id: str | None = None,
    sort: str = "published_at",
    order: str = "desc",
    page: int = 1,
    per_page: int = 50,
    db=Depends(get_db),
):
    service = CatalogService(db)
    posts, total = await service.list_posts(
        type=type, status=status, step_filter=step, search=search,
        tag=tag, source_id=source_id, sort=sort, order=order,
        page=page, per_page=per_page,
    )
    return {"posts": posts, "total": total, "page": page, "per_page": per_page}


@router.post("/import")
async def import_catalog(body: ImportRequest, db=Depends(get_db)):
    service = CatalogService(db)
    path = Path(body.json_path) if body.json_path else CATALOG_JSON_PATH
    imported = await service.import_from_json(path)
    return {"imported": imported}
