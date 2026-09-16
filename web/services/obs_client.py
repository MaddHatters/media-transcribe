from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

import grpc
import grpc.aio

from proto import agent_pb2, agent_pb2_grpc
from web.models import AgentHealth
from web.services import AgentAuthError, AgentUnavailableError

log = logging.getLogger(__name__)


class ObsClient:
    def __init__(self, host: str, port: int, token: str) -> None:
        self._target = f"{host}:{port}"
        self._metadata = [("authorization", f"bearer {token}")]
        self._channel: grpc.aio.Channel | None = None
        self._stub: agent_pb2_grpc.AgentServiceStub | None = None

    async def connect(self) -> None:
        self._channel = grpc.aio.insecure_channel(self._target)
        self._stub = agent_pb2_grpc.AgentServiceStub(self._channel)

    async def close(self) -> None:
        if self._channel:
            await self._channel.close()
            self._channel = None
            self._stub = None

    def _handle_grpc_error(self, err: grpc.aio.AioRpcError) -> None:
        code = err.code()
        if code == grpc.StatusCode.UNAVAILABLE:
            raise AgentUnavailableError(str(err)) from err
        if code == grpc.StatusCode.UNAUTHENTICATED:
            raise AgentAuthError(str(err)) from err
        raise

    async def health_check(self) -> AgentHealth:
        try:
            resp = await self._stub.HealthCheck(
                agent_pb2.Empty(), metadata=self._metadata, timeout=5,
            )
            return AgentHealth(
                healthy=resp.healthy,
                obs_connected=resp.obs_connected,
                chrome_available=resp.chrome_available,
                disk_ok=resp.disk_ok,
                obs_version=resp.obs_version or None,
                error=resp.error or None,
            )
        except grpc.aio.AioRpcError as e:
            self._handle_grpc_error(e)

    async def get_status(self) -> dict[str, Any]:
        try:
            resp = await self._stub.GetStatus(
                agent_pb2.Empty(), metadata=self._metadata, timeout=5,
            )
            return {
                "health": {
                    "healthy": resp.health.healthy,
                    "obs_connected": resp.health.obs_connected,
                    "chrome_available": resp.health.chrome_available,
                    "disk_ok": resp.health.disk_ok,
                    "obs_version": resp.health.obs_version,
                    "error": resp.health.error,
                },
                "watcher": {
                    "running": resp.watcher.running,
                    "pid": resp.watcher.pid,
                    "cycle": resp.watcher.cycle,
                    "interval_hours": resp.watcher.interval_hours,
                    "last_run": resp.watcher.last_run,
                    "next_run": resp.watcher.next_run,
                    "total_recorded": resp.watcher.total_recorded,
                },
                "pipeline": {
                    "running": resp.pipeline.running,
                    "run_id": resp.pipeline.run_id,
                    "total": resp.pipeline.total,
                    "completed": resp.pipeline.completed,
                    "failed": resp.pipeline.failed,
                    "current_post": resp.pipeline.current_post,
                    "current_step": resp.pipeline.current_step,
                },
                "disk": {
                    "total_bytes": resp.disk.total_bytes,
                    "free_bytes": resp.disk.free_bytes,
                    "drive": resp.disk.drive,
                },
            }
        except grpc.aio.AioRpcError as e:
            self._handle_grpc_error(e)

    async def run_pipeline(
        self,
        posts: list[dict],
        steps: list[str] | None = None,
        shuffle: bool = False,
        breaks: bool = True,
    ) -> dict[str, Any]:
        try:
            entries = [
                agent_pb2.PostEntry(
                    post_id=p.get("post_id", ""),
                    url=p.get("url", ""),
                    title=p.get("title", ""),
                    filename=p.get("filename", ""),
                    post_type=p.get("post_type", ""),
                )
                for p in posts
            ]
            request = agent_pb2.PipelineRequest(
                posts=entries,
                steps=steps or [],
                shuffle=shuffle,
                enable_breaks=breaks,
            )
            resp = await self._stub.RunPipeline(request, metadata=self._metadata)
            return {
                "started": resp.started,
                "run_id": resp.run_id,
                "queue_size": resp.queue_size,
                "error": resp.error,
            }
        except grpc.aio.AioRpcError as e:
            self._handle_grpc_error(e)

    async def start_watcher(self, config: dict) -> dict[str, Any]:
        try:
            config_msg = agent_pb2.WatcherConfig(
                interval_hours=config.get("interval_hours", 24.0),
                steps=config.get("steps", []),
                max_per_run=config.get("max_per_run", 3),
                dry_run=config.get("dry_run", False),
            )
            resp = await self._stub.StartWatcher(config_msg, metadata=self._metadata)
            return {"success": resp.success, "message": resp.message}
        except grpc.aio.AioRpcError as e:
            self._handle_grpc_error(e)

    async def stop_watcher(self) -> dict[str, Any]:
        try:
            resp = await self._stub.StopWatcher(
                agent_pb2.Empty(), metadata=self._metadata,
            )
            return {"success": resp.success, "message": resp.message}
        except grpc.aio.AioRpcError as e:
            self._handle_grpc_error(e)

    async def trigger_discovery(
        self, full_catalog: bool = False, force: bool = False,
    ) -> dict[str, Any]:
        try:
            request = agent_pb2.DiscoveryRequest(
                full_catalog=full_catalog, force=force,
            )
            resp = await self._stub.TriggerDiscovery(
                request, metadata=self._metadata, timeout=30,
            )
            return {
                "total_found": resp.total_found,
                "new_posts": resp.new_posts,
                "video_posts": resp.video_posts,
                "new_post_list": [
                    {
                        "post_id": p.post_id,
                        "title": p.title,
                        "url": p.url,
                        "published_at": p.published_at,
                        "post_type": p.post_type,
                        "has_video": p.has_video,
                    }
                    for p in resp.new_post_list
                ],
                "error": resp.error,
            }
        except grpc.aio.AioRpcError as e:
            self._handle_grpc_error(e)

    async def stream_events(self, callback: Callable) -> None:
        backoff = 1.0
        while True:
            try:
                subscription = agent_pb2.EventSubscription()
                stream = self._stub.StreamEvents(
                    subscription, metadata=self._metadata,
                )
                backoff = 1.0
                async for event in stream:
                    event_dict = {
                        "type": event.type,
                        "run_id": event.run_id,
                        "post_id": event.post_id,
                        "step": event.step,
                        "status": event.status,
                        "error": event.error,
                        "output_path": event.output_path,
                        "duration_seconds": event.duration_seconds,
                        "timestamp": event.timestamp,
                    }
                    await callback(event_dict)
            except grpc.aio.AioRpcError as e:
                if e.code() == grpc.StatusCode.UNAUTHENTICATED:
                    raise AgentAuthError(str(e)) from e
                log.warning("gRPC stream disconnected: %s — retrying in %.0fs", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)
            except asyncio.CancelledError:
                return
