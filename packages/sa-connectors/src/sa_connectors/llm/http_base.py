"""Shared machinery for HTTP-based model providers.

Anthropic access goes through the official SDK. Every *other* vendor here —
OpenAI, Gemini, and whatever sits behind an enterprise gateway — is reached over
plain HTTP, and this class is the part they share: client lifecycle, retries,
deadline propagation, SSE streaming, error translation, telemetry, and events.

Why raw HTTP rather than each vendor's SDK:

* An enterprise gateway is the main deployment target, and a gateway is defined
  by a different ``base_url``, different auth header, and extra routing headers.
  That is exactly what an SDK abstracts away and then makes awkward to override.
* Three vendor SDKs would be three optional dependencies, three release
  cadences, and three sets of breaking changes for one small surface.
* ``httpx`` is already a hard dependency of this package.

A subclass supplies four things: where the endpoint is, how to build the request
body, how to read the response, and how to read a stream chunk. Everything else
is inherited.
"""

from __future__ import annotations

import json
from abc import abstractmethod
from collections.abc import AsyncIterator, Sequence
from typing import Any, ClassVar

import httpx

from sa_platform.config import LLMProfile
from sa_platform.context import current_context
from sa_platform.errors import (
    ConfigurationError,
    DependencyError,
    TimeoutError_,
    ValidationError,
)
from sa_platform.events import Events, event_bus
from sa_platform.health import CheckResult
from sa_platform.logging import get_logger
from sa_platform.resilience import RetryPolicy, retry_async
from sa_platform.telemetry import get_tracer, metrics

from ..base import Connector, ConnectorState
from ..http import _classify
from .base import LLMProvider, LLMResponse, Message, StopReason, Usage

logger = get_logger(__name__)
tracer = get_tracer("sa.llm.http")

#: Bodies larger than this are truncated before they reach a log or an error
#: payload. Prompts are unbounded and error details are not the place for them.
MAX_ERROR_BODY = 800


class HttpLLMProvider(Connector, LLMProvider):
    """Base class for a model provider reached over HTTP."""

    #: Wire format this class implements. Used for reporting and for gateway
    #: dialect selection.
    wire: ClassVar[str] = ""
    #: Endpoint used when the profile does not override ``base_url``.
    default_base_url: ClassVar[str] = ""
    #: Where the credential goes when the profile does not override it.
    default_auth_header: ClassVar[str] = "Authorization"
    default_auth_scheme: ClassVar[str] = "Bearer"

    def __init__(self, profile: LLMProfile, *, name: str | None = None) -> None:
        Connector.__init__(self, name or profile.name)
        self.profile = profile
        self._client: httpx.AsyncClient | None = None
        self._retry_policy = RetryPolicy.from_settings(max_attempts=profile.max_retries + 1)

    # -- configuration -----------------------------------------------------
    @property
    def base_url(self) -> str:
        return (self.profile.base_url or self.default_base_url).rstrip("/")

    @property
    def via_gateway(self) -> bool:
        return self.profile.vendor == "gateway"

    def describe(self) -> dict[str, Any]:
        """What the console shows for this provider. Never includes the key."""
        return {
            "name": self.profile.name,
            "label": self.profile.display_label,
            "vendor": self.profile.vendor,
            "wire": self.wire,
            "model": self.profile.model,
            "base_url": self.base_url,
            "via_gateway": self.via_gateway,
            "state": self.state.value,
            "credential_present": self.profile.resolve_api_key() is not None,
            "streaming": self.profile.stream,
        }

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {
            "content-type": "application/json",
            "accept": "application/json",
        }
        key = self.profile.resolve_api_key()
        if key:
            header = self.profile.auth_header or self.default_auth_header
            scheme = self.profile.auth_scheme or (
                self.default_auth_scheme if not self.profile.auth_header else ""
            )
            headers[header] = f"{scheme} {key}".strip() if scheme else key
        # Profile headers last so a deployment can override anything above —
        # gateways routinely need a tenant id or a virtual key in a set place.
        headers.update(self.profile.headers)
        return headers

    # -- subclass contract -------------------------------------------------
    @abstractmethod
    def _completion_path(self, model: str, *, stream: bool) -> str:
        """Path appended to ``base_url`` for a completion request."""

    @abstractmethod
    def _build_body(
        self,
        messages: Sequence[Message],
        *,
        system: str | list[dict[str, Any]] | None,
        tools: Sequence[dict[str, Any]] | None,
        max_tokens: int | None,
        model: str,
        stream: bool,
        schema: dict[str, Any] | None,
        extra: dict[str, Any],
    ) -> dict[str, Any]:
        """Build the vendor's request body."""

    @abstractmethod
    def _parse(self, data: dict[str, Any]) -> LLMResponse:
        """Read a completed response into the neutral shape."""

    @abstractmethod
    def _delta_text(self, chunk: dict[str, Any]) -> str:
        """Extract the text delta from one streamed chunk. '' when there is none."""

    def _models_path(self) -> str | None:
        """Path listing available models, when the vendor exposes one."""
        return None

    def _parse_models(self, data: Any) -> list[str]:
        return []

    # -- lifecycle ---------------------------------------------------------
    async def connect(self) -> None:
        if self._client is not None:
            return
        self._set_state(ConnectorState.CONNECTING)
        if not self.base_url:
            self._set_state(ConnectorState.FAILED)
            raise ConfigurationError(
                f"profile '{self.profile.name}' has no endpoint: set base_url",
                details={"profile": self.profile.name, "vendor": self.profile.vendor},
            )
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.profile.timeout_seconds, connect=10.0),
            follow_redirects=False,
        )
        if self.profile.requires_credential() and self.profile.resolve_api_key() is None:
            # Degraded rather than failed: the endpoint may authenticate by
            # network identity (mTLS, workload identity, a sidecar), which is
            # common for gateways and cannot be detected from here.
            self._set_state(ConnectorState.DEGRADED)
            logger.warning(
                "no credential resolved for llm profile; requests may be rejected",
                extra={"profile": self.profile.name, "vendor": self.profile.vendor},
            )
        else:
            self._set_state(ConnectorState.READY)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._set_state(ConnectorState.CLOSED)

    async def health(self) -> CheckResult:
        """Probe the endpoint without spending tokens where possible."""
        path = self._models_path()
        try:
            if path:
                await self._request("GET", path)
            else:
                await self.complete([Message.user("ping")], max_tokens=1)
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            return CheckResult.unhealthy(f"{self.profile.name} unreachable: {exc}")
        return CheckResult.healthy(
            f"{self.profile.name} is reachable",
            vendor=self.profile.vendor,
            model=self.profile.model,
        )

    async def list_models(self) -> list[str]:
        """Model ids this endpoint will serve.

        Worth having for its own sake: pointed at a gateway, this is the list of
        everything the organisation has approved, which is otherwise a wiki page
        that goes stale.
        """
        path = self._models_path()
        if not path:
            return [self.profile.model]
        try:
            return self._parse_models(await self._request("GET", path))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "could not list models",
                extra={"profile": self.profile.name, "error": str(exc)},
            )
            return [self.profile.model]

    async def _require_client(self) -> httpx.AsyncClient:
        if self._client is None:
            await self.connect()
        if self._client is None:  # pragma: no cover - connect() sets it or raises
            raise ConfigurationError(f"provider '{self.profile.name}' failed to connect")
        return self._client

    # -- transport ---------------------------------------------------------
    async def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        """One JSON request, retried under the platform policy."""
        client = await self._require_client()

        async def send() -> Any:
            ctx = current_context()
            ctx.check_deadline()
            try:
                response = await client.request(
                    method,
                    path,
                    json=body,
                    headers=self._headers(),
                    timeout=ctx.budget(self.profile.timeout_seconds),
                )
            except httpx.TimeoutException as exc:
                raise TimeoutError_(
                    f"{self.profile.name} timed out after {self.profile.timeout_seconds}s",
                    details={"profile": self.profile.name, "path": path},
                    cause=exc,
                ) from exc
            except httpx.HTTPError as exc:
                raise DependencyError(
                    f"could not reach {self.profile.name}: {exc}",
                    details={"profile": self.profile.name, "base_url": self.base_url},
                    cause=exc,
                ) from exc

            # Shared with the HTTP connector so a 429 from a model endpoint is
            # classified — and therefore retried — the same as any other.
            _classify(response, f"{self.base_url}{path}")
            try:
                return response.json()
            except ValueError as exc:
                raise DependencyError(
                    f"{self.profile.name} returned a non-JSON body",
                    details={"body": response.text[:MAX_ERROR_BODY]},
                    cause=exc,
                ) from exc

        return await retry_async(send, policy=self._retry_policy, operation=f"llm:{self.name}")

    async def _sse(self, path: str, body: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        """Yield decoded ``data:`` events from a server-sent-event stream.

        Streaming is not retried: a partially delivered turn cannot be resumed,
        and replaying it would duplicate output the caller has already seen.
        """
        client = await self._require_client()
        ctx = current_context()
        ctx.check_deadline()
        try:
            async with client.stream(
                "POST",
                path,
                json=body,
                headers={**self._headers(), "accept": "text/event-stream"},
                timeout=ctx.budget(self.profile.timeout_seconds),
            ) as response:
                if response.status_code >= 400:
                    await response.aread()
                    _classify(response, f"{self.base_url}{path}")
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if not payload or payload == "[DONE]":
                        continue
                    try:
                        yield json.loads(payload)
                    except json.JSONDecodeError:
                        logger.debug("skipping unparseable stream chunk")
        except httpx.TimeoutException as exc:
            raise TimeoutError_(f"{self.profile.name} stream timed out", cause=exc) from exc
        except httpx.HTTPError as exc:
            raise DependencyError(f"{self.profile.name} stream failed: {exc}", cause=exc) from exc

    # -- LLMProvider -------------------------------------------------------
    async def complete(
        self,
        messages: Sequence[Message],
        *,
        system: str | list[dict[str, Any]] | None = None,
        tools: Sequence[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
        schema: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        resolved_model = model or self.profile.model
        # Anthropic-only knobs travel through the same call sites; drop them
        # here rather than making every caller branch on vendor.
        kwargs.pop("effort", None)
        kwargs.pop("output_config", None)
        kwargs.pop("stream", None)

        body = self._build_body(
            messages,
            system=system,
            tools=tools,
            max_tokens=max_tokens,
            model=resolved_model,
            stream=False,
            schema=schema,
            extra=kwargs,
        )
        path = self._completion_path(resolved_model, stream=False)

        with tracer.span(
            "llm.complete",
            provider=self.profile.name,
            vendor=self.profile.vendor,
            model=resolved_model,
        ) as span:
            await event_bus.emit(
                Events.LLM_REQUEST,
                model=resolved_model,
                provider=self.profile.name,
                message_count=len(messages),
                tool_count=len(tools or []),
            )
            data = await self._request("POST", path, body)
            response = self._parse(data)
            span.set_attributes(
                {
                    "stop_reason": response.stop_reason.value,
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                }
            )
            metrics.increment("llm.requests", model=resolved_model, provider=self.profile.name)
            metrics.observe("llm.output_tokens", response.usage.output_tokens)
            await event_bus.emit(
                Events.LLM_RESPONSE,
                model=response.model or resolved_model,
                provider=self.profile.name,
                stop_reason=response.stop_reason.value,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            )
            return response

    async def stream(  # type: ignore[override]
        self,
        messages: Sequence[Message],
        *,
        system: str | list[dict[str, Any]] | None = None,
        tools: Sequence[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        resolved_model = model or self.profile.model
        kwargs.pop("effort", None)
        body = self._build_body(
            messages,
            system=system,
            tools=tools,
            max_tokens=max_tokens,
            model=resolved_model,
            stream=True,
            schema=kwargs.pop("schema", None),
            extra=kwargs,
        )
        async for chunk in self._sse(self._completion_path(resolved_model, stream=True), body):
            text = self._delta_text(chunk)
            if text:
                yield text

    async def count_tokens(
        self,
        messages: Sequence[Message],
        *,
        system: str | None = None,
        tools: Sequence[dict[str, Any]] | None = None,
        model: str | None = None,
    ) -> int:
        """Count prompt tokens with the vendor's own tokenizer.

        Raised rather than estimated where the vendor has no endpoint: a count
        from the wrong tokenizer silently mis-budgets context, which is worse
        than not having one.
        """
        raise ConfigurationError(
            f"{self.profile.vendor} exposes no token-counting endpoint; "
            "read `usage` from a response instead",
            details={"profile": self.profile.name, "vendor": self.profile.vendor},
        )

    async def complete_structured(
        self,
        messages: Sequence[Message],
        schema: dict[str, Any],
        *,
        system: str | list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Request JSON constrained to ``schema`` and return it parsed."""
        response = await self.complete(messages, system=system, schema=schema, **kwargs)
        if response.was_refused:
            raise ValidationError(
                "the model declined to produce a structured response",
                details={"category": response.refusal_category, "provider": self.profile.name},
            )
        return _parse_json_payload(response.text, provider=self.profile.name)

    # -- helpers for subclasses -------------------------------------------
    @staticmethod
    def _flatten_content(content: str | list[dict[str, Any]]) -> str:
        """Reduce neutral content blocks to text.

        Only Anthropic round-trips thinking and tool_use blocks; the other
        vendors have their own block types and reject foreign ones, so a
        conversation carried across providers is flattened to its text.
        """
        if isinstance(content, str):
            return content
        parts: list[str] = []
        for block in content:
            kind = block.get("type")
            if kind == "text":
                parts.append(str(block.get("text", "")))
            elif kind == "tool_result":
                inner = block.get("content")
                parts.append(inner if isinstance(inner, str) else json.dumps(inner, default=str))
        return "\n".join(p for p in parts if p)

    @staticmethod
    def _system_text(system: str | list[dict[str, Any]] | None) -> str:
        if system is None:
            return ""
        if isinstance(system, str):
            return system
        return "\n\n".join(str(block.get("text", "")) for block in system)

    def _usage(self, raw: dict[str, Any] | None, *, input_key: str, output_key: str) -> Usage:
        raw = raw or {}
        return Usage(
            input_tokens=int(raw.get(input_key) or 0),
            output_tokens=int(raw.get(output_key) or 0),
        )

    @staticmethod
    def _stop_reason(value: str | None, mapping: dict[str, StopReason]) -> StopReason:
        return mapping.get(value or "", StopReason.UNKNOWN)


def _parse_json_payload(text: str, *, provider: str) -> Any:
    """Parse a structured-output body, tolerating a fenced code block.

    Constrained decoding returns bare JSON, but a gateway that silently routes
    to a model without schema support returns it fenced. Recovering here turns a
    hard failure into a working call.
    """
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.split("\n", 1)[-1] if "\n" in candidate else candidate
        candidate = candidate.rsplit("```", 1)[0].strip()
        if candidate.startswith("json"):
            candidate = candidate[4:].strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValidationError(
            "structured output was not valid JSON",
            details={"provider": provider, "text": text[:500]},
            cause=exc,
        ) from exc


__all__ = ["MAX_ERROR_BODY", "HttpLLMProvider"]
