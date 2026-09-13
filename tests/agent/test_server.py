"""Tests for AgentServiceServicer with all external dependencies mocked."""
import asyncio

import pytest
import grpc
import grpc.aio
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from proto import agent_pb2, agent_pb2_grpc
from agent.server import AgentServiceServicer

TEST_TOKEN = "b" * 64


@pytest.fixture
async def server_and_stub():
    """Start agent server with auth bypassed, return stub."""
    from agent.interceptors import AuthInterceptor

    interceptor = AuthInterceptor(token=TEST_TOKEN)
    server = grpc.aio.server(interceptors=[interceptor])
    servicer = AgentServiceServicer()
    agent_pb2_grpc.add_AgentServiceServicer_to_server(servicer, server)
    port = server.add_insecure_port("[::]:0")
    await server.start()

    channel = grpc.aio.insecure_channel(f"localhost:{port}")
    stub = agent_pb2_grpc.AgentServiceStub(channel)

    yield servicer, stub

    await channel.close()
    await server.stop(grace=0)


def _auth_metadata():
    return [("authorization", f"bearer {TEST_TOKEN}")]


@pytest.mark.asyncio
async def test_health_check_returns_valid_response(server_and_stub):
    servicer, stub = server_and_stub

    mock_cl = MagicMock()
    mock_cl.get_version.return_value = MagicMock(obs_version="31.0.0")
    mock_cl.disconnect = MagicMock()

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    mock_usage = MagicMock()
    mock_usage.total = 500 * 1024**3
    mock_usage.free = 100 * 1024**3

    with patch("agent.server.shutil.disk_usage", return_value=mock_usage), \
         patch.dict("sys.modules", {"obsws_python": MagicMock()}), \
         patch("builtins.__import__", side_effect=_mock_import_obs(mock_cl)), \
         patch("urllib.request.urlopen", return_value=mock_resp):
        response = await stub.HealthCheck(agent_pb2.Empty())

    assert response.healthy is True
    assert response.obs_connected is True
    assert response.chrome_available is True
    assert response.disk_ok is True


@pytest.mark.asyncio
async def test_health_check_reports_obs_down(server_and_stub):
    servicer, stub = server_and_stub

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    mock_usage = MagicMock()
    mock_usage.total = 500 * 1024**3
    mock_usage.free = 100 * 1024**3

    with patch("agent.server.shutil.disk_usage", return_value=mock_usage), \
         patch("builtins.__import__", side_effect=_mock_import_obs_fail()), \
         patch("urllib.request.urlopen", return_value=mock_resp):
        response = await stub.HealthCheck(agent_pb2.Empty())

    assert response.healthy is False
    assert response.obs_connected is False


@pytest.mark.asyncio
async def test_get_status_returns_combined(server_and_stub):
    servicer, stub = server_and_stub

    mock_usage = MagicMock()
    mock_usage.total = 500 * 1024**3
    mock_usage.free = 100 * 1024**3

    with patch("agent.server.shutil.disk_usage", return_value=mock_usage), \
         patch("builtins.__import__", side_effect=_mock_import_obs_fail()), \
         patch("urllib.request.urlopen", side_effect=OSError("no chrome")), \
         patch("src.pipeline.watcher.ContentWatcher.read_status", return_value=None):
        response = await stub.GetStatus(agent_pb2.Empty(), metadata=_auth_metadata())

    assert response.health is not None
    assert response.pipeline is not None
    assert response.disk is not None


@pytest.mark.asyncio
async def test_trigger_discovery_with_mocked_api(server_and_stub):
    servicer, stub = server_and_stub

    from src.sources.discovery import DiscoveredPost

    fake_posts = [
        DiscoveredPost(
            post_id="1001", url="https://patreon.com/posts/1001",
            title="Test Video", created_at="2024-01-01", post_type="video_external_file",
            has_video=True, published_at="2024-01-01",
        ),
        DiscoveredPost(
            post_id="1002", url="https://patreon.com/posts/1002",
            title="Test Post", created_at="2024-01-02", post_type="text_only",
            has_video=False,
        ),
    ]

    mock_catalog = MagicMock()
    mock_catalog.merge_discovered.return_value = ([], 1)

    with patch("src.sources.discovery.PatreonDiscovery.fetch_posts", return_value=fake_posts), \
         patch("src.sources.discovery.PatreonDiscovery.diff_catalog", return_value=fake_posts[:1]), \
         patch("src.catalog.CatalogManager", return_value=mock_catalog):
        request = agent_pb2.DiscoveryRequest(campaign_id="5008493")
        response = await stub.TriggerDiscovery(request, metadata=_auth_metadata())

    assert response.total_found == 2
    assert response.new_posts == 1
    assert response.video_posts == 1


@pytest.mark.asyncio
async def test_run_pipeline_starts_background_task(server_and_stub):
    servicer, stub = server_and_stub

    request = agent_pb2.PipelineRequest(
        posts=[
            agent_pb2.PostEntry(
                post_id="123", url="http://test", title="Test", filename="test.mkv",
            ),
        ],
        steps=["transcribe"],
    )

    response = await stub.RunPipeline(request, metadata=_auth_metadata())

    assert response.started is True
    assert response.run_id != ""
    assert response.queue_size == 1
    assert servicer._pipeline_task is not None


@pytest.mark.asyncio
async def test_run_pipeline_rejects_when_already_running(server_and_stub):
    servicer, stub = server_and_stub

    servicer._pipeline_task = asyncio.ensure_future(asyncio.sleep(100))
    servicer._pipeline_run_id = "existing_run"

    try:
        request = agent_pb2.PipelineRequest(
            posts=[agent_pb2.PostEntry(url="http://test", title="Test", filename="t.mkv")],
        )
        response = await stub.RunPipeline(request, metadata=_auth_metadata())

        assert response.started is False
        assert "already running" in response.error.lower()
    finally:
        servicer._pipeline_task.cancel()
        try:
            await servicer._pipeline_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_stream_events_receives_pipeline_events(server_and_stub):
    servicer, stub = server_and_stub

    sub_request = agent_pb2.EventSubscription()
    stream = stub.StreamEvents(sub_request, metadata=_auth_metadata())

    await asyncio.sleep(0.1)

    event = agent_pb2.PipelineEvent(
        type="step_completed",
        run_id="test_run",
        post_id="http://test",
        step="transcribe",
        timestamp="2024-01-01T00:00:00Z",
    )
    await servicer._broadcast(event)

    received = await asyncio.wait_for(stream.read(), timeout=5)
    assert received.type == "step_completed"
    assert received.run_id == "test_run"
    assert received.step == "transcribe"

    stream.cancel()
    try:
        await stream.read()
    except (grpc.aio.AioRpcError, asyncio.CancelledError):
        pass


@pytest.mark.asyncio
async def test_start_watcher_validates_interval(server_and_stub):
    servicer, stub = server_and_stub

    with patch("src.pipeline.watcher.ContentWatcher") as MockWatcher:
        mock_instance = MagicMock()
        mock_instance.run_forever = AsyncMock()
        mock_instance.interval_hours = 12.0
        MockWatcher.return_value = mock_instance

        request = agent_pb2.WatcherConfig(interval_hours=6.0, max_per_run=2)
        response = await stub.StartWatcher(request, metadata=_auth_metadata())

    assert response.success is True
    assert servicer._watcher is not None
    call_kwargs = MockWatcher.call_args[1]
    assert call_kwargs["interval_hours"] == 12.0


@pytest.mark.asyncio
async def test_stop_watcher_graceful(server_and_stub):
    servicer, stub = server_and_stub

    mock_watcher = MagicMock()
    mock_watcher._shutdown = False
    servicer._watcher = mock_watcher
    servicer._watcher_task = asyncio.ensure_future(asyncio.sleep(100))

    try:
        response = await stub.StopWatcher(agent_pb2.Empty(), metadata=_auth_metadata())
        assert response.success is True
        assert mock_watcher._shutdown is True
    finally:
        servicer._watcher_task.cancel()
        try:
            await servicer._watcher_task
        except asyncio.CancelledError:
            pass


def _mock_import_obs(mock_client):
    """Create a side_effect for __import__ that provides a mock obsws_python."""
    original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

    def custom_import(name, *args, **kwargs):
        if name == "obsws_python":
            mod = MagicMock()
            mod.ReqClient.return_value = mock_client
            return mod
        return original_import(name, *args, **kwargs)

    return custom_import


def _mock_import_obs_fail():
    """Create a side_effect for __import__ that raises on obsws_python."""
    original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

    def custom_import(name, *args, **kwargs):
        if name == "obsws_python":
            raise ConnectionError("OBS not available")
        return original_import(name, *args, **kwargs)

    return custom_import
