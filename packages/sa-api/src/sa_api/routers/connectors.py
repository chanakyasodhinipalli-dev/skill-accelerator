"""Connector inspection and management endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from sa_platform.errors import NotFoundError

from ..dependencies import ConnectorRegistryDep, ToolRegistryDep

router = APIRouter(prefix="/connectors", tags=["connectors"])


@router.get("", summary="List connectors and their state")
async def list_connectors(registry: ConnectorRegistryDep) -> dict[str, Any]:
    return {
        "count": len(registry.names()),
        "connectors": [
            {
                "name": c.name,
                "type": type(c).__name__,
                "state": c.state.value,
                "provides_tools": hasattr(c, "list_tools"),
            }
            for c in registry.all()
        ],
    }


@router.get("/health", summary="Probe every connector")
async def connector_health(registry: ConnectorRegistryDep) -> dict[str, Any]:
    report = await registry.health()
    return {name: result.to_dict() for name, result in report.items()}


@router.post("/{name}/reconnect", summary="Reconnect one connector")
async def reconnect(name: str, registry: ConnectorRegistryDep) -> dict[str, Any]:
    """Close and re-open a connector. Use after rotating a credential."""
    connector = registry.require(name)
    await connector.close()
    await connector.connect()
    return {"connector": name, "state": connector.state.value}


@router.post("/{name}/refresh-tools", summary="Re-read a connector's tool catalogue")
async def refresh_tools(
    name: str,
    registry: ConnectorRegistryDep,
    tools: ToolRegistryDep,
) -> dict[str, Any]:
    """Re-discover tools from an MCP server or OpenAPI spec and re-register them."""
    connector = registry.require(name)
    refresh = getattr(connector, "refresh_tools", None)
    if refresh is None:
        raise NotFoundError(
            f"connector '{name}' does not provide tools",
            details={"connector": name},
        )
    discovered = await refresh()
    tools.register_many(discovered, replace=True)
    return {
        "connector": name,
        "tools": [t.spec.name for t in discovered],
        "count": len(discovered),
    }
