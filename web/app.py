from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from web.services import AgentAuthError, AgentUnavailableError

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from web.config import AGENT_HOST, AGENT_PORT, AGENT_TOKEN, CATALOG_JSON_PATH, DB_PATH
    from web.database import init_db, migrate_from_json
    from web.services.event_bus import EventBus
    from web.services.obs_client import ObsClient

    db = await init_db(DB_PATH)
    db.row_factory = __import__("aiosqlite").Row
    app.state.db = db

    cursor = await db.execute("SELECT COUNT(*) FROM posts")
    count = (await cursor.fetchone())[0]
    if count == 0 and CATALOG_JSON_PATH.exists():
        imported = await migrate_from_json(db, CATALOG_JSON_PATH)
        log.info("Auto-migrated %d posts from catalog JSON", imported)

    obs_client = ObsClient(AGENT_HOST, AGENT_PORT, AGENT_TOKEN)
    await obs_client.connect()
    app.state.obs_client = obs_client

    event_bus = EventBus()
    app.state.event_bus = event_bus

    relay_task = asyncio.create_task(_relay_grpc_events(obs_client, db, event_bus))

    yield

    relay_task.cancel()
    try:
        await relay_task
    except asyncio.CancelledError:
        pass
    await obs_client.close()
    await db.close()


async def _relay_grpc_events(obs_client, db, event_bus):
    from web.services.pipeline_service import PipelineService

    pipeline_svc = PipelineService(db, obs_client, event_bus)

    async def on_event(event_dict):
        await pipeline_svc.handle_event(event_dict)
        await event_bus.publish(event_dict)

    try:
        await obs_client.stream_events(on_event)
    except asyncio.CancelledError:
        return


def create_app() -> FastAPI:
    app = FastAPI(title="Media Transcribe Dashboard", lifespan=lifespan)

    from web.config import CORS_ORIGINS

    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from web.routes import api_router

    app.include_router(api_router)

    from web.routes.ws import router as ws_router

    app.include_router(ws_router)

    @app.post("/api/chat")
    async def chat_stub():
        raise HTTPException(status_code=501, detail="AI chat available in Phase 2")

    @app.exception_handler(AgentUnavailableError)
    async def agent_unavailable_handler(request, exc):
        return JSONResponse(status_code=503, content={"detail": "Agent server unavailable"})

    @app.exception_handler(AgentAuthError)
    async def agent_auth_handler(request, exc):
        return JSONResponse(status_code=502, content={"detail": "Agent authentication failed"})

    return app
