from fastapi import APIRouter

from web.routes import agent, catalog, discovery, pipeline, queue, watcher

api_router = APIRouter()
api_router.include_router(catalog.router, prefix="/api/catalog", tags=["catalog"])
api_router.include_router(queue.router, prefix="/api/queue", tags=["queue"])
api_router.include_router(watcher.router, prefix="/api/watcher", tags=["watcher"])
api_router.include_router(discovery.router, prefix="/api/discovery", tags=["discovery"])
api_router.include_router(pipeline.router, prefix="/api/pipeline", tags=["pipeline"])
api_router.include_router(agent.router, prefix="/api/agent", tags=["agent"])
