from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import grpc

from web.models import AgentHealth
from web.services import AgentAuthError, AgentUnavailableError
from web.services.obs_client import ObsClient


@pytest.fixture
def obs_client():
    client = ObsClient("localhost", 8421, "test-token")
    client._stub = AsyncMock()
    client._channel = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_health_check(obs_client):
    mock_resp = MagicMock()
    mock_resp.healthy = True
    mock_resp.obs_connected = True
    mock_resp.chrome_available = True
    mock_resp.disk_ok = True
    mock_resp.obs_version = "30.2"
    mock_resp.error = ""
    obs_client._stub.HealthCheck = AsyncMock(return_value=mock_resp)

    result = await obs_client.health_check()

    assert isinstance(result, AgentHealth)
    assert result.healthy is True
    assert result.obs_connected is True
    assert result.obs_version == "30.2"


@pytest.mark.asyncio
async def test_get_status(obs_client):
    mock_health = MagicMock()
    mock_health.healthy = True
    mock_health.obs_connected = True
    mock_health.chrome_available = True
    mock_health.disk_ok = True
    mock_health.obs_version = "30.2"
    mock_health.error = ""

    mock_watcher = MagicMock()
    mock_watcher.running = False
    mock_watcher.pid = 0
    mock_watcher.cycle = 0
    mock_watcher.interval_hours = 24.0
    mock_watcher.last_run = ""
    mock_watcher.next_run = ""
    mock_watcher.total_recorded = 0

    mock_pipeline = MagicMock()
    mock_pipeline.running = False
    mock_pipeline.run_id = ""
    mock_pipeline.total = 0
    mock_pipeline.completed = 0
    mock_pipeline.failed = 0
    mock_pipeline.current_post = ""
    mock_pipeline.current_step = ""

    mock_disk = MagicMock()
    mock_disk.total_bytes = 1000000000000
    mock_disk.free_bytes = 500000000000
    mock_disk.drive = "D:"

    mock_resp = MagicMock()
    mock_resp.health = mock_health
    mock_resp.watcher = mock_watcher
    mock_resp.pipeline = mock_pipeline
    mock_resp.disk = mock_disk
    obs_client._stub.GetStatus = AsyncMock(return_value=mock_resp)

    result = await obs_client.get_status()

    assert result["health"]["healthy"] is True
    assert result["watcher"]["running"] is False
    assert result["pipeline"]["running"] is False
    assert result["disk"]["total_bytes"] == 1000000000000


@pytest.mark.asyncio
async def test_run_pipeline(obs_client):
    mock_resp = MagicMock()
    mock_resp.started = True
    mock_resp.run_id = "run_001"
    mock_resp.queue_size = 2
    mock_resp.error = ""
    obs_client._stub.RunPipeline = AsyncMock(return_value=mock_resp)

    posts = [
        {"post_id": "p1", "url": "https://example.com/1", "title": "Post 1",
         "filename": "post_1", "post_type": "video"},
    ]
    result = await obs_client.run_pipeline(posts)

    assert result["started"] is True
    assert result["run_id"] == "run_001"
    obs_client._stub.RunPipeline.assert_called_once()


@pytest.mark.asyncio
async def test_auth_metadata_attached(obs_client):
    mock_resp = MagicMock()
    mock_resp.healthy = True
    mock_resp.obs_connected = True
    mock_resp.chrome_available = True
    mock_resp.disk_ok = True
    mock_resp.obs_version = ""
    mock_resp.error = ""
    obs_client._stub.HealthCheck = AsyncMock(return_value=mock_resp)

    await obs_client.health_check()

    call_kwargs = obs_client._stub.HealthCheck.call_args
    assert call_kwargs.kwargs["metadata"] == [("authorization", "bearer test-token")]


@pytest.mark.asyncio
async def test_unavailable_raises_error(obs_client):
    err = grpc.aio.AioRpcError(
        code=grpc.StatusCode.UNAVAILABLE,
        initial_metadata=grpc.aio.Metadata(),
        trailing_metadata=grpc.aio.Metadata(),
        details="Connection refused",
    )
    obs_client._stub.HealthCheck = AsyncMock(side_effect=err)

    with pytest.raises(AgentUnavailableError):
        await obs_client.health_check()


@pytest.mark.asyncio
async def test_unauthenticated_raises_error(obs_client):
    err = grpc.aio.AioRpcError(
        code=grpc.StatusCode.UNAUTHENTICATED,
        initial_metadata=grpc.aio.Metadata(),
        trailing_metadata=grpc.aio.Metadata(),
        details="Bad token",
    )
    obs_client._stub.HealthCheck = AsyncMock(side_effect=err)

    with pytest.raises(AgentAuthError):
        await obs_client.health_check()


@pytest.mark.asyncio
async def test_stream_events_callback(obs_client):
    import asyncio

    mock_event = MagicMock()
    mock_event.type = "step_completed"
    mock_event.run_id = "run_001"
    mock_event.post_id = "p1"
    mock_event.step = "record"
    mock_event.status = "completed"
    mock_event.error = ""
    mock_event.output_path = "/out/video.mp4"
    mock_event.duration_seconds = 120.5
    mock_event.timestamp = "2026-01-01T00:00:00Z"

    stop = asyncio.Event()

    async def mock_stream(*args, **kwargs):
        yield mock_event
        await stop.wait()

    obs_client._stub.StreamEvents = mock_stream

    received = []

    async def callback(event_dict):
        received.append(event_dict)

    task = asyncio.create_task(obs_client.stream_events(callback))
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert len(received) == 1
    assert received[0]["type"] == "step_completed"
    assert received[0]["post_id"] == "p1"
