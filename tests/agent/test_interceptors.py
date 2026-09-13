"""Tests for the gRPC auth interceptor using an in-process server."""
import pytest
import grpc
import grpc.aio
from proto import agent_pb2, agent_pb2_grpc
from agent.interceptors import AuthInterceptor

TEST_TOKEN = "a" * 64


class MinimalServicer(agent_pb2_grpc.AgentServiceServicer):

    async def HealthCheck(self, request, context):
        return agent_pb2.HealthResponse(healthy=True, obs_connected=False)

    async def GetStatus(self, request, context):
        return agent_pb2.AgentStatus()


@pytest.fixture
async def grpc_channel():
    """Start a minimal gRPC server with AuthInterceptor and return a channel."""
    interceptor = AuthInterceptor(token=TEST_TOKEN)
    server = grpc.aio.server(interceptors=[interceptor])
    agent_pb2_grpc.add_AgentServiceServicer_to_server(MinimalServicer(), server)
    port = server.add_insecure_port("[::]:0")
    await server.start()

    channel = grpc.aio.insecure_channel(f"localhost:{port}")
    yield channel

    await channel.close()
    await server.stop(grace=0)


@pytest.mark.asyncio
async def test_valid_token_passes(grpc_channel):
    stub = agent_pb2_grpc.AgentServiceStub(grpc_channel)
    metadata = [("authorization", f"bearer {TEST_TOKEN}")]
    response = await stub.GetStatus(agent_pb2.Empty(), metadata=metadata)
    assert response is not None


@pytest.mark.asyncio
async def test_invalid_token_rejected(grpc_channel):
    stub = agent_pb2_grpc.AgentServiceStub(grpc_channel)
    metadata = [("authorization", "bearer wrong_token")]
    with pytest.raises(grpc.aio.AioRpcError) as exc_info:
        await stub.GetStatus(agent_pb2.Empty(), metadata=metadata)
    assert exc_info.value.code() == grpc.StatusCode.UNAUTHENTICATED


@pytest.mark.asyncio
async def test_missing_token_rejected(grpc_channel):
    stub = agent_pb2_grpc.AgentServiceStub(grpc_channel)
    with pytest.raises(grpc.aio.AioRpcError) as exc_info:
        await stub.GetStatus(agent_pb2.Empty())
    assert exc_info.value.code() == grpc.StatusCode.UNAUTHENTICATED


@pytest.mark.asyncio
async def test_healthcheck_exempt_from_auth(grpc_channel):
    stub = agent_pb2_grpc.AgentServiceStub(grpc_channel)
    response = await stub.HealthCheck(agent_pb2.Empty())
    assert response.healthy is True
