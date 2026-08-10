"""Turn an OpenAPI specification into platform tools.

Each operation becomes a :class:`~sa_tools.base.Tool` whose parameter schema is
assembled from the operation's path, query, and body parameters. This is how an
existing REST estate becomes model-callable without hand-writing a wrapper per
endpoint.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from sa_platform.context import ExecutionContext
from sa_platform.errors import ConfigurationError, ValidationError
from sa_platform.logging import get_logger
from sa_tools.base import Tool
from sa_tools.models import DangerLevel, ToolKind, ToolSpec

from .base import Connector, ConnectorState, ToolProvider
from .http import HttpConnector

logger = get_logger(__name__)

# Methods that mutate state, mapped to the danger level they imply.
_METHOD_DANGER = {
    "get": DangerLevel.SAFE,
    "head": DangerLevel.SAFE,
    "options": DangerLevel.SAFE,
    "post": DangerLevel.MEDIUM,
    "put": DangerLevel.MEDIUM,
    "patch": DangerLevel.MEDIUM,
    "delete": DangerLevel.HIGH,
}

_IDEMPOTENT_METHODS = {"get", "head", "options", "put", "delete"}


def _sanitize_tool_name(raw: str) -> str:
    """Coerce an operationId into a legal tool name."""
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "_", raw).strip("_")
    return (cleaned or "operation")[:128]


class OpenApiOperationTool(Tool):
    """One OpenAPI operation, exposed as a tool."""

    def __init__(
        self,
        spec: ToolSpec,
        connector: HttpConnector,
        *,
        method: str,
        path_template: str,
        path_params: list[str],
        query_params: list[str],
        body_param: str | None,
    ) -> None:
        super().__init__(spec)
        self._connector = connector
        self._method = method.upper()
        self._path_template = path_template
        self._path_params = path_params
        self._query_params = query_params
        self._body_param = body_param

    async def invoke(self, ctx: ExecutionContext, arguments: dict[str, Any]) -> Any:
        path = self._path_template
        for name in self._path_params:
            if name not in arguments:
                raise ValidationError(
                    f"missing required path parameter '{name}'", details={"parameter": name}
                )
            # Percent-encode so a value cannot inject extra path segments.
            from urllib.parse import quote

            path = path.replace("{" + name + "}", quote(str(arguments[name]), safe=""))

        query = {k: arguments[k] for k in self._query_params if k in arguments}
        body = arguments.get(self._body_param) if self._body_param else None

        response = await self._connector.request(
            self._method, path, params=query or None, json=body
        )

        if not response.content:
            return {"status_code": response.status_code}
        try:
            return response.json()
        except ValueError:
            return {"status_code": response.status_code, "body": response.text[:100_000]}


class OpenApiConnector(Connector, ToolProvider):
    """Loads an OpenAPI document and exposes its operations as tools."""

    def __init__(
        self,
        name: str,
        spec: dict[str, Any],
        connector: HttpConnector,
        *,
        operation_allowlist: list[str] | None = None,
        tag_filter: list[str] | None = None,
        required_permissions: list[str] | None = None,
    ) -> None:
        Connector.__init__(self, name)
        self._spec = spec
        self._connector = connector
        self._allowlist = set(operation_allowlist or ())
        self._tag_filter = set(tag_filter or ())
        self._required_permissions = required_permissions or []
        self._tools: list[Tool] | None = None

    # -- construction -----------------------------------------------------
    @classmethod
    def from_file(
        cls,
        name: str,
        spec_path: Path | str,
        connector: HttpConnector,
        **kwargs: Any,
    ) -> OpenApiConnector:
        path = Path(spec_path)
        if not path.is_file():
            raise ConfigurationError(f"OpenAPI spec not found: {path}")
        text = path.read_text(encoding="utf-8")
        try:
            spec = yaml.safe_load(text) if path.suffix in (".yaml", ".yml") else json.loads(text)
        except (yaml.YAMLError, json.JSONDecodeError) as exc:
            raise ConfigurationError(
                f"could not parse OpenAPI spec {path}: {exc}", cause=exc
            ) from exc
        return cls(name, spec, connector, **kwargs)

    # -- lifecycle --------------------------------------------------------
    async def connect(self) -> None:
        self._set_state(ConnectorState.CONNECTING)
        await self._connector.connect()
        self._tools = self._build_tools()
        self._set_state(ConnectorState.READY)
        logger.info(
            "openapi connector ready",
            extra={"connector": self.name, "operations": len(self._tools)},
        )

    async def close(self) -> None:
        await self._connector.close()
        self._tools = None
        self._set_state(ConnectorState.CLOSED)

    async def list_tools(self) -> list[Tool]:
        if self._tools is None:
            await self.connect()
        return list(self._tools or [])

    # -- spec translation -------------------------------------------------
    def _resolve_ref(self, node: Any, _depth: int = 0) -> Any:
        """Resolve local ``$ref`` pointers. Remote refs are not followed."""
        if _depth > 10 or not isinstance(node, dict):
            return node
        ref = node.get("$ref")
        if not isinstance(ref, str) or not ref.startswith("#/"):
            return node
        target: Any = self._spec
        for part in ref[2:].split("/"):
            if not isinstance(target, dict) or part not in target:
                return {}
            target = target[part]
        return self._resolve_ref(target, _depth + 1)

    def _build_tools(self) -> list[Tool]:
        tools: list[Tool] = []
        paths: dict[str, Any] = self._spec.get("paths", {}) or {}

        for path_template, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue
            shared_params = path_item.get("parameters", [])

            for method, operation in path_item.items():
                if method.lower() not in _METHOD_DANGER or not isinstance(operation, dict):
                    continue

                tags = set(operation.get("tags", []))
                if self._tag_filter and not (tags & self._tag_filter):
                    continue

                operation_id = operation.get("operationId") or f"{method}_{path_template}"
                if self._allowlist and operation_id not in self._allowlist:
                    continue

                try:
                    tools.append(
                        self._build_tool(
                            method, path_template, operation, shared_params, operation_id
                        )
                    )
                except Exception as exc:  # noqa: BLE001 - isolate one bad operation
                    logger.warning(
                        "skipping OpenAPI operation",
                        extra={"operation": operation_id, "error": str(exc)},
                    )

        return tools

    def _build_tool(
        self,
        method: str,
        path_template: str,
        operation: dict[str, Any],
        shared_params: list[Any],
        operation_id: str,
    ) -> Tool:
        properties: dict[str, Any] = {}
        required: list[str] = []
        path_params: list[str] = []
        query_params: list[str] = []

        for raw in [*shared_params, *operation.get("parameters", [])]:
            param = self._resolve_ref(raw)
            name = param.get("name")
            location = param.get("in")
            if not name or location not in ("path", "query"):
                continue

            schema = self._resolve_ref(param.get("schema", {})) or {"type": "string"}
            schema = dict(schema)
            if param.get("description"):
                schema["description"] = param["description"]
            properties[name] = schema

            # Path parameters are always required by definition.
            if location == "path":
                path_params.append(name)
                required.append(name)
            else:
                query_params.append(name)
                if param.get("required"):
                    required.append(name)

        body_param: str | None = None
        request_body = self._resolve_ref(operation.get("requestBody", {}))
        if request_body:
            content = request_body.get("content", {})
            json_schema = self._resolve_ref(content.get("application/json", {}).get("schema", {}))
            if json_schema:
                body_param = "body"
                properties["body"] = {
                    **json_schema,
                    "description": request_body.get("description", "JSON request body."),
                }
                if request_body.get("required"):
                    required.append("body")

        method_lower = method.lower()
        description = (
            operation.get("description")
            or operation.get("summary")
            or f"{method.upper()} {path_template}"
        )
        # State the endpoint explicitly — it gives the model a concrete trigger
        # condition rather than a vague summary.
        description = f"{description.strip()} (calls {method.upper()} {path_template})"

        spec = ToolSpec(
            name=_sanitize_tool_name(f"{self.name}_{operation_id}"),
            description=description,
            parameters={
                "type": "object",
                "properties": properties,
                "required": sorted(set(required)),
                "additionalProperties": False,
            },
            kind=ToolKind.OPENAPI,
            danger=_METHOD_DANGER[method_lower],
            tags=list(operation.get("tags", [])),
            required_permissions=self._required_permissions,
            idempotent=method_lower in _IDEMPOTENT_METHODS,
            parallel_safe=method_lower in ("get", "head", "options"),
            source=f"openapi:{self.name}",
        )

        return OpenApiOperationTool(
            spec,
            self._connector,
            method=method,
            path_template=path_template,
            path_params=path_params,
            query_params=query_params,
            body_param=body_param,
        )


__all__ = ["OpenApiConnector", "OpenApiOperationTool"]
