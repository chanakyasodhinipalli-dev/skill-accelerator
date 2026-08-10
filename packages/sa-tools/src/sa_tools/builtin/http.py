"""Outbound HTTP tool with an explicit host allowlist."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from sa_platform.context import ExecutionContext
from sa_platform.errors import ConfigurationError, DependencyError, ValidationError

from ..base import Tool
from ..models import DangerLevel, ToolSpec

MAX_RESPONSE_BYTES = 200_000


class HttpRequestTool(Tool):
    """Perform an HTTP request against an allowlisted host.

    The allowlist is mandatory and has no wildcard-everything default: an
    unrestricted HTTP tool hands a model server-side request forgery as a
    first-class capability.
    """

    def __init__(
        self,
        *,
        allowed_hosts: list[str] | None = None,
        timeout_seconds: float = 20.0,
        default_headers: dict[str, str] | None = None,
    ) -> None:
        if not allowed_hosts:
            raise ConfigurationError(
                "HttpRequestTool requires an explicit allowed_hosts list; "
                "an unrestricted HTTP tool is an SSRF primitive"
            )
        self._allowed_hosts = [h.lower() for h in allowed_hosts]
        self._timeout = timeout_seconds
        self._default_headers = default_headers or {}

        super().__init__(
            ToolSpec(
                name="http_request",
                description=(
                    "Send an HTTP request to an approved external API and return the "
                    "response. Call this when the answer depends on live data from one of "
                    f"the approved hosts: {', '.join(self._allowed_hosts)}. "
                    "Do not use it for hosts outside that list — they will be rejected."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Absolute https:// URL."},
                        "method": {
                            "type": "string",
                            "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                            "description": "HTTP method (default GET).",
                        },
                        "headers": {
                            "type": "object",
                            "description": "Additional request headers.",
                            "additionalProperties": {"type": "string"},
                        },
                        "json_body": {
                            "type": "object",
                            "description": "JSON request body for write methods.",
                            "additionalProperties": True,
                        },
                        "query": {
                            "type": "object",
                            "description": "Query string parameters.",
                            "additionalProperties": {"type": "string"},
                        },
                    },
                    "required": ["url"],
                    "additionalProperties": False,
                },
                danger=DangerLevel.MEDIUM,
                tags=["http", "integration"],
                required_permissions=["http:request"],
                timeout_seconds=timeout_seconds,
                idempotent=False,
                parallel_safe=True,
            )
        )

    def _check_url(self, raw_url: str) -> None:
        parsed = urlparse(raw_url)
        if parsed.scheme not in ("https", "http"):
            raise ValidationError(
                f"unsupported URL scheme '{parsed.scheme}'; only http and https are allowed"
            )
        host = (parsed.hostname or "").lower()
        if not host:
            raise ValidationError("URL has no host")

        # Exact match, or a subdomain of an allowlisted apex.
        allowed = any(host == entry or host.endswith(f".{entry}") for entry in self._allowed_hosts)
        if not allowed:
            raise ValidationError(
                f"host '{host}' is not in the allowlist",
                details={"host": host, "allowed_hosts": self._allowed_hosts},
            )

    async def invoke(self, ctx: ExecutionContext, arguments: dict[str, Any]) -> Any:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ConfigurationError(
                "http_request requires the 'httpx' package (install sa-tools[http])",
                cause=exc,
            ) from exc

        url: str = arguments["url"]
        self._check_url(url)

        method = str(arguments.get("method", "GET")).upper()
        headers = {**self._default_headers, **(arguments.get("headers") or {})}

        timeout = ctx.budget(self._timeout) or self._timeout

        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    params=arguments.get("query"),
                    json=arguments.get("json_body"),
                )
        except httpx.HTTPError as exc:
            raise DependencyError(
                f"HTTP request to {url} failed: {exc}",
                details={"url": url, "method": method},
                cause=exc,
            ) from exc

        body = response.content[:MAX_RESPONSE_BYTES]
        payload: Any
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                payload = response.json()
            except ValueError:
                payload = body.decode("utf-8", errors="replace")
        else:
            payload = body.decode("utf-8", errors="replace")

        return {
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "body": payload,
            "truncated": len(response.content) > MAX_RESPONSE_BYTES,
        }


__all__ = ["HttpRequestTool"]
