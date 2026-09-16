from __future__ import annotations


class AgentUnavailableError(Exception):
    """Raised when the obs-machine gRPC agent is unreachable."""


class AgentAuthError(Exception):
    """Raised when gRPC auth fails (bad or missing AGENT_TOKEN)."""
