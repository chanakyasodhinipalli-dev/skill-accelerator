"""sa-connectors — outbound integrations.

Everything the platform reaches out to lives behind a :class:`Connector`:

* :class:`HttpConnector` — resilient HTTP with retry, circuit breaking, and
  error classification
* :class:`OpenApiConnector` — turns an OpenAPI spec into callable tools
* :class:`MCPConnector` — connects to MCP servers and adapts their tools
* :mod:`sa_connectors.llm` — model providers (Anthropic)

Connectors that expose operations implement :class:`ToolProvider`, so their
capabilities land in the same registry — and therefore under the same policy,
approval gate, and audit trail — as native tools.
"""

from __future__ import annotations

from .auth import (
    ApiKeyAuth,
    AuthStrategy,
    BasicAuth,
    BearerAuth,
    NoAuth,
    OAuth2ClientCredentials,
    build_auth,
)
from .base import Connector, ConnectorState, ToolProvider
from .http import HttpConnector
from .llm import LLMProvider, LLMResponse, Message, Usage, build_provider
from .mcp import MCPConnector, register_mcp_servers
from .openapi import OpenApiConnector
from .registry import ConnectorRegistry, connector_registry

__version__ = "0.1.0"

__all__ = [
    "ApiKeyAuth",
    "AuthStrategy",
    "BasicAuth",
    "BearerAuth",
    "Connector",
    "ConnectorRegistry",
    "ConnectorState",
    "HttpConnector",
    "LLMProvider",
    "LLMResponse",
    "MCPConnector",
    "Message",
    "NoAuth",
    "OAuth2ClientCredentials",
    "OpenApiConnector",
    "ToolProvider",
    "Usage",
    "__version__",
    "build_auth",
    "build_provider",
    "connector_registry",
    "register_mcp_servers",
]
