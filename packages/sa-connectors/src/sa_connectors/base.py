"""Connector contracts.

A *connector* owns a live relationship with something outside the process — an
HTTP API, an MCP server, a model provider. It manages the connection lifecycle
and reports health; it does not decide policy.

Connectors that can expose callable operations implement
:class:`ToolProvider`, which is how OpenAPI specs and MCP servers become tools
in the registry without the rest of the platform knowing where they came from.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

from sa_platform.health import CheckResult
from sa_platform.logging import get_logger

logger = get_logger(__name__)


class ConnectorState(str, Enum):
    CREATED = "created"
    CONNECTING = "connecting"
    READY = "ready"
    DEGRADED = "degraded"
    CLOSED = "closed"
    FAILED = "failed"


class Connector(ABC):
    """Base class for outbound integrations."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._state = ConnectorState.CREATED

    @property
    def state(self) -> ConnectorState:
        return self._state

    @property
    def is_ready(self) -> bool:
        return self._state in (ConnectorState.READY, ConnectorState.DEGRADED)

    @abstractmethod
    async def connect(self) -> None:
        """Establish the connection. Must be idempotent."""

    @abstractmethod
    async def close(self) -> None:
        """Release resources. Must be safe to call when never connected."""

    async def health(self) -> CheckResult:
        """Report liveness. Override with a real probe where one exists."""
        if self._state is ConnectorState.READY:
            return CheckResult.healthy(f"connector '{self.name}' is ready")
        if self._state is ConnectorState.DEGRADED:
            return CheckResult.degraded(f"connector '{self.name}' is degraded")
        return CheckResult.unhealthy(f"connector '{self.name}' is {self._state.value}")

    def _set_state(self, state: ConnectorState) -> None:
        if state is not self._state:
            logger.info(
                "connector state changed",
                extra={"connector": self.name, "from": self._state.value, "to": state.value},
            )
            self._state = state

    async def __aenter__(self) -> Connector:
        await self.connect()
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.close()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} {self.name} ({self._state.value})>"


class ToolProvider(ABC):
    """A connector that can surface its operations as platform tools."""

    @abstractmethod
    async def list_tools(self) -> list[Any]:
        """Return :class:`~sa_tools.base.Tool` instances for this connector."""

    async def refresh_tools(self) -> list[Any]:
        """Re-read the remote capability list. Defaults to a plain re-list."""
        return await self.list_tools()


__all__ = ["Connector", "ConnectorState", "ToolProvider"]
