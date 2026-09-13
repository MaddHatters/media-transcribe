import asyncio
import logging
import shutil
import uuid
from datetime import datetime, timezone

import grpc
import grpc.aio

from proto import agent_pb2, agent_pb2_grpc
from agent.config import PORT, validate_config
from agent.interceptors import AuthInterceptor

log = logging.getLogger(__name__)


class AgentServiceServicer(agent_pb2_grpc.AgentServiceServicer):

    def __init__(self):
        self._watcher = None
        self._watcher_task = None
        self._pipeline_task = None
        self._pipeline_run_id = None
        self._pipeline_total = 0
        self._pipeline_completed = 0
        self._pipeline_failed = 0
        self._pipeline_current_post = ""
        self._pipeline_current_step = ""
        self._subscribers: list[asyncio.Queue] = []
        self._subscriber_lock = asyncio.Lock()

    @staticmethod
    def _check_obs() -> tuple[bool, str, str]:
        try:
            import obsws_python as obs
            from src.config import OBS_HOST, OBS_PORT, OBS_PASSWORD
            cl = obs.ReqClient(host=OBS_HOST, port=OBS_PORT, password=OBS_PASSWORD, timeout=3)
            version = cl.get_version().obs_version
            cl.disconnect()
            return True, version, ""
        except Exception as exc:
            return False, "", f"OBS: {exc}"

    @staticmethod
    def _check_chrome() -> bool:
        try:
            import urllib.request
            with urllib.request.urlopen("http://localhost:9222/json/version", timeout=3) as resp:
                return resp.status == 200
        except Exception:
            return False

    async def HealthCheck(self, request, context):
        obs_connected, obs_version, error = await asyncio.to_thread(self._check_obs)
        chrome_available = await asyncio.to_thread(self._check_chrome)

        disk_ok = False
        try:
            from src.config import BACKUP_DIR
            usage = shutil.disk_usage(str(BACKUP_DIR))
            disk_ok = usage.free >= 5 * 1024**3
        except Exception:
            pass

        healthy = obs_connected and chrome_available and disk_ok

        return agent_pb2.HealthResponse(
            healthy=healthy,
            obs_connected=obs_connected,
            chrome_available=chrome_available,
            disk_ok=disk_ok,
            obs_version=obs_version,
            error=error,
        )

    async def GetStatus(self, request, context):
        health = await self.HealthCheck(request, context)

        from src.pipeline.watcher import ContentWatcher
        watcher_data = ContentWatcher.read_status()
        watcher_state = agent_pb2.WatcherState()
        if watcher_data:
            watcher_state = agent_pb2.WatcherState(
                running=watcher_data.get("running", False),
                pid=watcher_data.get("pid", 0),
                cycle=watcher_data.get("cycle", 0),
                interval_hours=self._watcher.interval_hours if self._watcher else 0,
                last_run=watcher_data.get("last_run", ""),
                next_run=watcher_data.get("next_run", "") or "",
                new_found=watcher_data.get("last_result", {}).get("new_found", 0),
                recorded=watcher_data.get("last_result", {}).get("recorded", 0),
                failed=watcher_data.get("last_result", {}).get("failed", 0),
                total_recorded=watcher_data.get("total_recorded", 0),
                started_at=watcher_data.get("started_at", ""),
            )

        pipeline_state = agent_pb2.PipelineState(
            running=self._pipeline_task is not None and not self._pipeline_task.done(),
            run_id=self._pipeline_run_id or "",
            total=self._pipeline_total,
            completed=self._pipeline_completed,
            failed=self._pipeline_failed,
            current_post=self._pipeline_current_post,
            current_step=self._pipeline_current_step,
        )

        from src.config import BACKUP_DIR
        try:
            usage = shutil.disk_usage(str(BACKUP_DIR))
            disk_info = agent_pb2.DiskInfo(
                total_bytes=usage.total, free_bytes=usage.free, drive=str(BACKUP_DIR)[:2],
            )
        except Exception:
            disk_info = agent_pb2.DiskInfo()

        return agent_pb2.AgentStatus(
            health=health, watcher=watcher_state,
            pipeline=pipeline_state, disk=disk_info,
        )

    async def RunPipeline(self, request, context):
        if self._pipeline_task and not self._pipeline_task.done():
            return agent_pb2.PipelineResponse(
                started=False, error="Pipeline already running",
                run_id=self._pipeline_run_id or "",
            )

        run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        self._pipeline_run_id = run_id
        self._pipeline_total = 0
        self._pipeline_completed = 0
        self._pipeline_failed = 0

        self._pipeline_task = asyncio.create_task(
            self._run_pipeline_task(request, run_id)
        )

        return agent_pb2.PipelineResponse(
            started=True, run_id=run_id,
            queue_size=len(request.posts),
        )

    async def _run_pipeline_task(self, request, run_id):
        from src.pipeline.runner import Pipeline, STEPS
        from src.sources.base import Post
        from src.config import BACKUP_DIR

        posts = [
            Post(url=p.url, title=p.title, filename=p.filename, post_type=p.post_type)
            for p in request.posts
        ]
        steps = list(request.steps) if request.steps else None
        active_steps = steps or list(STEPS)
        self._pipeline_total = len(posts) * len(active_steps)

        engine = None
        if "record" in active_steps:
            from src.engines.obs_engine import OBSEngine
            engine = OBSEngine()

        def on_step_start(post, step):
            self._pipeline_current_post = post.title
            self._pipeline_current_step = step
            event = agent_pb2.PipelineEvent(
                type="step_started",
                run_id=run_id,
                post_id=getattr(post, "url", ""),
                step=step,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            asyncio.create_task(self._broadcast(event))

        def on_step_complete(post, step, result):
            self._pipeline_completed += 1
            event = agent_pb2.PipelineEvent(
                type="step_completed",
                run_id=run_id,
                post_id=getattr(post, "url", ""),
                step=step,
                status="completed",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            asyncio.create_task(self._broadcast(event))

        def on_step_fail(post, step, error):
            self._pipeline_failed += 1
            event = agent_pb2.PipelineEvent(
                type="step_failed",
                run_id=run_id,
                post_id=getattr(post, "url", ""),
                step=step,
                error=error,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            asyncio.create_task(self._broadcast(event))

        try:
            pipeline = Pipeline(
                source=None, engine=engine, output_dir=BACKUP_DIR,
                enable_breaks=request.enable_breaks,
                on_step_start=on_step_start,
                on_step_complete=on_step_complete,
                on_step_fail=on_step_fail,
            )
            await pipeline.run(posts, steps=steps)

            event = agent_pb2.PipelineEvent(
                type="pipeline_complete",
                run_id=run_id,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            await self._broadcast(event)
        except Exception as exc:
            log.error("Pipeline run %s failed: %s", run_id, exc)
            event = agent_pb2.PipelineEvent(
                type="pipeline_failed",
                run_id=run_id,
                error=str(exc),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            await self._broadcast(event)

    async def StartWatcher(self, request, context):
        if self._watcher_task and not self._watcher_task.done():
            return agent_pb2.WatcherResponse(
                success=False, message="Watcher already running",
            )

        interval = max(request.interval_hours, 12.0)
        steps = list(request.steps) or ["record", "analyze", "transcribe", "correct"]

        from src.pipeline.watcher import ContentWatcher
        self._watcher = ContentWatcher(
            source="patreon",
            interval_hours=interval,
            steps=steps,
            max_per_run=request.max_per_run or 3,
            dry_run=request.dry_run,
        )

        self._watcher_task = asyncio.create_task(self._watcher.run_forever())

        return agent_pb2.WatcherResponse(
            success=True,
            message=f"Watcher started (interval={interval}h, max_per_run={request.max_per_run or 3})",
        )

    async def StopWatcher(self, request, context):
        if not self._watcher:
            return agent_pb2.WatcherResponse(success=False, message="No watcher running")

        self._watcher._shutdown = True
        return agent_pb2.WatcherResponse(
            success=True, message="Watcher shutdown initiated",
        )

    @staticmethod
    def _discover_sync(campaign_id, max_pages, full_catalog, force):
        from src.sources.discovery import PatreonDiscovery
        from src.catalog import CatalogManager
        from src.config import CATALOG_PATH

        discovery = PatreonDiscovery(campaign_id=campaign_id)

        if full_catalog and not force:
            if not discovery.check_cooldown(CATALOG_PATH.parent):
                return None, None, "Cooldown active"

        fetched = discovery.fetch_posts(media_type="video", max_pages=max_pages)
        new_posts = discovery.diff_catalog(fetched, CATALOG_PATH)

        catalog = CatalogManager(CATALOG_PATH)
        merged, new_count = catalog.merge_discovered(fetched)
        catalog.save(merged)

        if full_catalog:
            discovery.update_cooldown(CATALOG_PATH.parent)

        return fetched, new_posts, ""

    async def TriggerDiscovery(self, request, context):
        from src.sources.discovery import MAX_PAGES

        campaign_id = request.campaign_id or "5008493"
        max_pages = MAX_PAGES if request.full_catalog else 1

        fetched, new_posts, err = await asyncio.to_thread(
            self._discover_sync, campaign_id, max_pages,
            request.full_catalog, request.force,
        )

        if err:
            return agent_pb2.DiscoveryResponse(error=err)

        new_post_list = [
            agent_pb2.DiscoveredPostInfo(
                post_id=p.post_id, title=p.title, url=p.url,
                published_at=p.published_at or "", post_type=p.post_type,
                has_video=p.has_video,
            )
            for p in new_posts
        ]

        return agent_pb2.DiscoveryResponse(
            total_found=len(fetched), new_posts=len(new_posts),
            video_posts=sum(1 for p in fetched if p.has_video),
            new_post_list=new_post_list,
        )

    async def StreamEvents(self, request, context):
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        async with self._subscriber_lock:
            self._subscribers.append(queue)

        event_types = set(request.event_types) if request.event_types else None

        try:
            while not context.cancelled():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30)
                except asyncio.TimeoutError:
                    continue
                if event_types and event.type not in event_types:
                    continue
                yield event
        except asyncio.CancelledError:
            pass
        finally:
            async with self._subscriber_lock:
                self._subscribers.remove(queue)

    async def _broadcast(self, event: agent_pb2.PipelineEvent) -> None:
        async with self._subscriber_lock:
            for queue in self._subscribers:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    log.warning("Subscriber queue full — dropping event")


async def run_server(port: int | None = None) -> None:
    validate_config()

    server_port = port if port is not None else PORT
    interceptor = AuthInterceptor()
    server = grpc.aio.server(interceptors=[interceptor])
    servicer = AgentServiceServicer()
    agent_pb2_grpc.add_AgentServiceServicer_to_server(servicer, server)
    server.add_insecure_port(f"0.0.0.0:{server_port}")

    log.info("Agent server starting on 0.0.0.0:%d", server_port)
    await server.start()
    log.info("Agent server ready")

    try:
        await server.wait_for_termination()
    except KeyboardInterrupt:
        log.info("Shutting down agent server")
        await server.stop(grace=5)
