import hmac

import grpc
import grpc.aio

from agent.config import AGENT_TOKEN


def _abort_with_unauthenticated(request, context):
    context.abort(grpc.StatusCode.UNAUTHENTICATED, "Invalid or missing authentication token")


def _unauthenticated_handler():
    return grpc.unary_unary_rpc_method_handler(_abort_with_unauthenticated)


class AuthInterceptor(grpc.aio.ServerInterceptor):

    def __init__(self, token: str | None = None):
        self._token = token or AGENT_TOKEN

    async def intercept_service(self, continuation, handler_call_details):
        method = handler_call_details.method
        if method.endswith("/HealthCheck"):
            return await continuation(handler_call_details)

        metadata = dict(handler_call_details.invocation_metadata)
        auth_value = metadata.get("authorization", "")

        parts = auth_value.split(None, 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return _unauthenticated_handler()

        if not hmac.compare_digest(parts[1], self._token):
            return _unauthenticated_handler()

        return await continuation(handler_call_details)
