"""Connector registry and lifecycle management."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable

from sa_platform.errors import NotFoundError
from sa_platform.health import CheckResult, health_registry
from sa_platform.logging import get_logger
from sa_platform.registry import Registry

from .base import Connector, ToolProvider

logger = get_logger(__name__)


class ConnectorRegistry:
    """Owns connector lifecycle so the application has one place to start and
    stop every outbound integration."""

    def __init__(self) -> None:
        self._registry: Registry[Connector] = Registry("connector")

    def register(self, connector: Connector, *, replace: bool = False) -> Connector:
        self._registry.register(connector.name, connector, replace=replace)
        # Connectors are non-critical by default: an unavailable integration
        # degrades the service rather than failing readiness outright.
        health_registry.register(f"connector:{connector.name}", connector.health, critical=False)
        return connector

    def unregister(self, name: str) -> None:
        self._registry.unregister(name)
        health_registry.unregister(f"connector:{name}")

    def get(self, name: str) -> Connector:
        return self._registry.get(name)

    def require(self, name: str) -> Connector:
        found = self._registry.try_get(name)
        if found is None:
            raise NotFoundError(
                f"connector '{name}' is not registered",
                details={"connector": name, "available": self.names()},
            )
        return found

    def names(self) -> list[str]:
        return self._registry.names()

    def all(self) -> list[Connector]:
        return self._registry.all()

    def tool_providers(self) -> list[ToolProvider]:
        return [c for c in self.all() if isinstance(c, ToolProvider)]

    async def connect_all(self, *, fail_fast: bool = False) -> dict[str, bool]:
        """Connect every registered connector concurrently."""
        connectors = self.all()

        async def attempt(connector: Connector) -> tuple[str, bool]:
            try:
                await connector.connect()
                return connector.name, True
            except Exception as exc:  # noqa: BLE001
                if fail_fast:
                    raise
                logger.error(
                    "connector failed to connect",
                    extra={"connector": connector.name, "error": str(exc)},
                )
                return connector.name, False

        outcomes = await asyncio.gather(*(attempt(c) for c in connectors))
        return dict(outcomes)

    async def close_all(self) -> None:
        async def attempt(connector: Connector) -> None:
            try:
                await connector.close()
            except Exception as exc:  # noqa: BLE001 - shutdown must not raise
                logger.warning(
                    "connector failed to close",
                    extra={"connector": connector.name, "error": str(exc)},
                )

        await asyncio.gather(*(attempt(c) for c in self.all()))

    async def publish_tools(self, tool_registry: object | None = None) -> int:
        """Register every tool-provider connector's tools into the tool registry."""
        from sa_tools.registry import tool_registry as default_registry

        target = tool_registry if tool_registry is not None else default_registry
        published = 0
        for provider in self.tool_providers():
            try:
                tools = await provider.list_tools()
                target.register_many(tools, replace=True)  # type: ignore[attr-defined]
                published += len(tools)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "failed to publish connector tools",
                    extra={"connector": getattr(provider, "name", "?"), "error": str(exc)},
                )
        return published

    async def health(self) -> dict[str, CheckResult]:
        results = await asyncio.gather(*(c.health() for c in self.all()), return_exceptions=True)
        report: dict[str, CheckResult] = {}
        for connector, outcome in zip(self.all(), results, strict=True):
            report[connector.name] = (
                outcome if isinstance(outcome, CheckResult) else CheckResult.unhealthy(str(outcome))
            )
        return report

    def register_many(self, connectors: Iterable[Connector], *, replace: bool = False) -> None:
        for connector in connectors:
            self.register(connector, replace=replace)


connector_registry = ConnectorRegistry()

__all__ = ["ConnectorRegistry", "connector_registry"]
