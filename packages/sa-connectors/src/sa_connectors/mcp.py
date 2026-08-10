"""Model Context Protocol (MCP) connector.

Connects to an MCP server over stdio or streamable HTTP, discovers its tools,
and adapts each one into a platform :class:`~sa_tools.base.Tool` so it flows
through the same registry, policy, approval gate, and audit trail as everything
else. An MCP server does not get a privileged side channel.

The ``mcp`` package is an optional dependency; without it this module imports
cleanly and fails only when a connection is actually attempted.
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from typing import Any

from sa_platform.config import MCPServerConfig
from sa_platform.context import ExecutionContext
from sa_platform.errors import ConfigurationError, DependencyError, ExecutionError
from sa_platform.health import CheckResult
from sa_platform.logging import get_logger
from sa_platform.resilience import with_timeout
from sa_platform.security import resolve_secret
from sa_tools.base import Tool
from sa_tools.models import DangerLevel, ToolKind, ToolSpec

from .base import Connector, ConnectorState, ToolProvider

logger = get_logger(__name__)


def _mcp_available() -> bool:
    try:  # pragma: no cover - capability probe
        import mcp  # noqa: F401

        return True
    except ImportError:  # pragma: no cover
        return False


class MCPTool(Tool):
    """A single remote MCP tool, proxied through the platform."""

    def __init__(self, spec: ToolSpec, connector: MCPConnector, remote_name: str) -> None:
        super().__init__(spec)
        self._connector = connector
        self._remote_name = remote_name

    async def invoke(self, ctx: ExecutionContext, arguments: dict[str, Any]) -> Any:
        return await self._connector.call_tool(self._remote_name, arguments, ctx=ctx)


class MCPConnector(Connector, ToolProvider):
    """Client for one MCP server.

    MCP sessions are stateful and bound to the task that opened them, so the
    session is owned by a dedicated worker task and all traffic is funnelled
    through a request queue. That keeps the transport's cancel-scope invariants
    intact regardless of which caller task issues a request.
    """

    def __init__(self, config: MCPServerConfig) -> None:
        super().__init__(config.name)
        self._config = config
        self._session: Any = None
        self._exit_stack: AsyncExitStack | None = None
        self._tools: list[Tool] | None = None
        self._lock = asyncio.Lock()
        self._server_info: dict[str, Any] = {}

    @property
    def config(self) -> MCPServerConfig:
        return self._config

    # -- lifecycle --------------------------------------------------------
    async def connect(self) -> None:
        if self._session is not None:
            return
        if not self._config.enabled:
            logger.info("mcp server disabled by config", extra={"server": self.name})
            self._set_state(ConnectorState.CLOSED)
            return
        if not _mcp_available():
            raise ConfigurationError(
                "MCP support requires the 'mcp' package (install sa-connectors[mcp])",
                details={"server": self.name},
            )

        async with self._lock:
            if self._session is not None:
                return
            self._set_state(ConnectorState.CONNECTING)
            try:
                await with_timeout(
                    self._open_session(),
                    self._config.timeout_seconds,
                    operation=f"mcp:connect:{self.name}",
                )
            except Exception as exc:  # noqa: BLE001 - re-raised as DependencyError
                self._set_state(ConnectorState.FAILED)
                await self._teardown()
                raise DependencyError(
                    f"could not connect to MCP server '{self.name}': {exc}",
                    details={"server": self.name, "transport": self._config.transport},
                    cause=exc,
                ) from exc
            self._set_state(ConnectorState.READY)

    async def _open_session(self) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        stack = AsyncExitStack()
        self._exit_stack = stack

        if self._config.transport == "stdio":
            if not self._config.command:
                raise ConfigurationError(
                    f"MCP server '{self.name}' uses stdio transport but declares no command"
                )
            # Environment values may be secret references.
            env = {key: (resolve_secret(value) or "") for key, value in self._config.env.items()}
            params = StdioServerParameters(
                command=self._config.command, args=self._config.args, env=env or None
            )
            read, write = await stack.enter_async_context(stdio_client(params))
        else:
            from mcp.client.streamable_http import streamablehttp_client

            if not self._config.url:
                raise ConfigurationError(
                    f"MCP server '{self.name}' uses http transport but declares no url"
                )
            headers = {
                key: (resolve_secret(value) or "") for key, value in self._config.headers.items()
            }
            transport = await stack.enter_async_context(
                streamablehttp_client(self._config.url, headers=headers or None)
            )
            # The streamable-HTTP client yields (read, write, get_session_id).
            read, write = transport[0], transport[1]

        session = await stack.enter_async_context(ClientSession(read, write))
        initialize_result = await session.initialize()
        self._session = session

        info = getattr(initialize_result, "serverInfo", None)
        self._server_info = {
            "name": getattr(info, "name", self.name),
            "version": getattr(info, "version", "unknown"),
        }
        logger.info(
            "connected to mcp server",
            extra={"server": self.name, **self._server_info},
        )

    async def close(self) -> None:
        async with self._lock:
            await self._teardown()
            self._set_state(ConnectorState.CLOSED)

    async def _teardown(self) -> None:
        self._session = None
        self._tools = None
        if self._exit_stack is not None:
            try:
                await self._exit_stack.aclose()
            except Exception as exc:  # noqa: BLE001 - shutdown must not raise
                logger.warning(
                    "error closing mcp session", extra={"server": self.name, "error": str(exc)}
                )
            finally:
                self._exit_stack = None

    async def health(self) -> CheckResult:
        if not self._config.enabled:
            return CheckResult.healthy(f"mcp server '{self.name}' is disabled")
        if self._session is None:
            return CheckResult.unhealthy(f"mcp server '{self.name}' is not connected")
        try:
            await with_timeout(self._session.list_tools(), 5.0, operation=f"mcp:ping:{self.name}")
        except Exception as exc:  # noqa: BLE001
            return CheckResult.unhealthy(f"mcp server '{self.name}' did not respond: {exc}")
        return CheckResult.healthy(f"mcp server '{self.name}' is ready", **self._server_info)

    # -- tools ------------------------------------------------------------
    async def list_tools(self) -> list[Tool]:
        if self._tools is not None:
            return list(self._tools)
        if self._session is None:
            await self.connect()
        if self._session is None:  # disabled
            return []

        try:
            listing = await with_timeout(
                self._session.list_tools(),
                self._config.timeout_seconds,
                operation=f"mcp:list_tools:{self.name}",
            )
        except Exception as exc:  # noqa: BLE001 - re-raised as DependencyError
            raise DependencyError(
                f"failed to list tools on MCP server '{self.name}': {exc}",
                details={"server": self.name},
                cause=exc,
            ) from exc

        allowlist = set(self._config.tool_allowlist)
        adapted: list[Tool] = []

        for remote in listing.tools:
            if allowlist and remote.name not in allowlist:
                continue
            try:
                adapted.append(self._adapt(remote))
            except Exception as exc:  # noqa: BLE001 - isolate one bad tool
                logger.warning(
                    "skipping mcp tool",
                    extra={"server": self.name, "tool": remote.name, "error": str(exc)},
                )

        self._tools = adapted
        logger.info("discovered mcp tools", extra={"server": self.name, "count": len(adapted)})
        return list(adapted)

    async def refresh_tools(self) -> list[Tool]:
        self._tools = None
        return await self.list_tools()

    def _adapt(self, remote: Any) -> MCPTool:
        schema = getattr(remote, "inputSchema", None) or {
            "type": "object",
            "properties": {},
        }
        annotations = getattr(remote, "annotations", None)

        # MCP tool annotations are advisory hints from the server. Treat a
        # missing hint as unsafe: an unannotated remote tool is assumed to
        # mutate state rather than assumed harmless.
        read_only = bool(getattr(annotations, "readOnlyHint", False)) if annotations else False
        destructive = bool(getattr(annotations, "destructiveHint", True)) if annotations else True
        idempotent = bool(getattr(annotations, "idempotentHint", False)) if annotations else False

        if read_only:
            danger = DangerLevel.SAFE
        elif destructive:
            danger = DangerLevel.HIGH
        else:
            danger = DangerLevel.MEDIUM

        description = (getattr(remote, "description", "") or "").strip()
        if not description:
            description = f"Tool '{remote.name}' provided by the '{self.name}' MCP server."

        spec = ToolSpec(
            # Namespaced so two servers can expose the same tool name.
            name=f"mcp_{self.name}_{remote.name}"[:128].replace(".", "_").replace("/", "_"),
            description=description,
            parameters=schema,
            kind=ToolKind.MCP,
            danger=danger,
            tags=["mcp", self.name],
            idempotent=idempotent or read_only,
            parallel_safe=read_only,
            timeout_seconds=self._config.timeout_seconds,
            source=f"mcp:{self.name}",
            # Remote schemas rarely satisfy the strict-tool-use requirements
            # (additionalProperties: false + required), so don't claim strict.
            strict=False,
        )
        return MCPTool(spec, self, remote.name)

    # -- invocation -------------------------------------------------------
    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        ctx: ExecutionContext | None = None,
    ) -> Any:
        """Call a remote MCP tool and normalise its result."""
        if self._session is None:
            await self.connect()
        if self._session is None:
            raise DependencyError(f"MCP server '{self.name}' is not available")

        timeout = self._config.timeout_seconds
        if ctx is not None:
            timeout = ctx.budget(timeout) or timeout

        try:
            result = await with_timeout(
                self._session.call_tool(name, arguments),
                timeout,
                operation=f"mcp:call:{self.name}:{name}",
            )
        except Exception as exc:  # noqa: BLE001 - re-raised as DependencyError
            raise DependencyError(
                f"MCP tool '{name}' on server '{self.name}' failed: {exc}",
                details={"server": self.name, "tool": name},
                cause=exc,
            ) from exc

        if getattr(result, "isError", False):
            raise ExecutionError(
                f"MCP tool '{name}' reported an error",
                details={"server": self.name, "tool": name, "content": self._render(result)},
            )

        # Prefer the server's structured output when it provides one.
        structured = getattr(result, "structuredContent", None)
        if structured:
            return structured
        return self._render(result)

    @staticmethod
    def _render(result: Any) -> Any:
        """Flatten MCP content blocks into plain Python values."""
        blocks = getattr(result, "content", None) or []
        rendered: list[Any] = []
        for block in blocks:
            kind = getattr(block, "type", None)
            if kind == "text":
                rendered.append(getattr(block, "text", ""))
            elif kind == "resource":
                resource = getattr(block, "resource", None)
                rendered.append(
                    {
                        "uri": str(getattr(resource, "uri", "")),
                        "text": getattr(resource, "text", None),
                    }
                )
            else:
                rendered.append({"type": kind or "unknown"})

        if not rendered:
            return None
        if len(rendered) == 1:
            return rendered[0]
        return rendered


async def register_mcp_servers(
    configs: list[MCPServerConfig],
    tool_registry: Any | None = None,
    *,
    fail_fast: bool = False,
) -> dict[str, MCPConnector]:
    """Connect to each configured server and register its tools.

    A server that fails to connect is logged and skipped unless ``fail_fast``
    is set — one unavailable integration should not prevent startup.
    """
    from sa_tools.registry import tool_registry as default_registry

    registry = tool_registry if tool_registry is not None else default_registry
    connectors: dict[str, MCPConnector] = {}

    for config in configs:
        if not config.enabled:
            continue
        connector = MCPConnector(config)
        try:
            await connector.connect()
            registry.register_many(await connector.list_tools(), replace=True)
            connectors[config.name] = connector
        except Exception as exc:  # noqa: BLE001
            await connector.close()
            if fail_fast:
                raise
            logger.error(
                "mcp server unavailable; continuing without it",
                extra={"server": config.name, "error": str(exc)},
            )

    return connectors


__all__ = ["MCPConnector", "MCPTool", "register_mcp_servers"]
