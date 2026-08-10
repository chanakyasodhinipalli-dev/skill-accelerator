"""Anthropic Claude provider.

Implements :class:`~sa_connectors.llm.base.LLMProvider` against the official
``anthropic`` SDK, with the platform's error taxonomy, telemetry, and tool
executor wired in.

Model-behaviour notes that shape this implementation:

* The default model is ``claude-opus-5``. Thinking is **on by default** there;
  depth is controlled by ``output_config.effort``, not a token budget.
* ``temperature`` / ``top_p`` / ``top_k`` and ``budget_tokens`` are rejected
  with a 400 on current models — they are never sent.
* Assistant-turn prefill is not supported; use structured outputs instead.
* ``max_tokens`` caps thinking *and* response text together, so streaming is
  the default to avoid HTTP timeouts on long turns.
* Safety classifiers can decline a request: HTTP 200 with
  ``stop_reason: "refusal"``. Content is checked only after that.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

from sa_platform.config import LLMSettings, get_settings
from sa_platform.context import ExecutionContext, current_context
from sa_platform.errors import (
    AuthenticationError,
    ConfigurationError,
    DependencyError,
    RateLimitError,
    TimeoutError_,
    ValidationError,
)
from sa_platform.events import Events, event_bus
from sa_platform.health import CheckResult
from sa_platform.logging import get_logger
from sa_platform.telemetry import get_tracer, metrics

from ..base import Connector, ConnectorState
from .base import (
    AgentResult,
    LLMProvider,
    LLMResponse,
    Message,
    StopReason,
    ToolCall,
    Usage,
)

logger = get_logger(__name__)
tracer = get_tracer("sa.llm.anthropic")

#: Beta flag for the server-side refusal fallback (`fallbacks: "default"` form).
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider(Connector, LLMProvider):
    """Claude access with retries, telemetry, tool execution, and caching."""

    def __init__(
        self,
        settings: LLMSettings | None = None,
        *,
        name: str = "anthropic",
        enable_refusal_fallback: bool = True,
    ) -> None:
        Connector.__init__(self, name)
        self._settings = settings or get_settings().llm
        self._client: Any = None
        # On Opus 5 / Fable 5 a policy decline otherwise just stops the request.
        # `fallbacks: "default"` re-serves it on Anthropic's recommended model,
        # routed by refusal category, inside the same call.
        self._enable_fallback = enable_refusal_fallback
        # Resolved at connect time — `fallbacks` is newer than the minimum SDK
        # this package supports, so it cannot be assumed present.
        self._supports_fallbacks = False

    # -- lifecycle --------------------------------------------------------
    async def connect(self) -> None:
        if self._client is not None:
            return
        self._set_state(ConnectorState.CONNECTING)
        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:  # pragma: no cover - optional dependency
            self._set_state(ConnectorState.FAILED)
            raise ConfigurationError(
                "the Anthropic provider requires the 'anthropic' package "
                "(install sa-connectors[anthropic])",
                cause=exc,
            ) from exc

        kwargs: dict[str, Any] = {
            "timeout": self._settings.timeout_seconds,
            "max_retries": self._settings.max_retries,
        }
        if self._settings.base_url:
            kwargs["base_url"] = self._settings.base_url
        if self._settings.api_key is not None:
            kwargs["api_key"] = self._settings.api_key.get_secret_value()
        # With no explicit key the SDK resolves ANTHROPIC_API_KEY, then
        # ANTHROPIC_AUTH_TOKEN, then an `ant auth login` profile — so a
        # zero-arg client is correct, not a missing-credential bug.

        self._client = AsyncAnthropic(**kwargs)
        self._supports_fallbacks = self._detect_fallback_support(self._client)

        if self._enable_fallback and not self._supports_fallbacks:
            # Degrade rather than fail: without this the parameter is rejected
            # by the SDK and *every* request errors out.
            logger.warning(
                "the installed anthropic SDK does not accept the 'fallbacks' parameter, so "
                "server-side refusal fallback is disabled. Upgrade the SDK to enable it; "
                "refusals will surface as stop_reason='refusal' until then.",
                extra={"anthropic_version": self._sdk_version()},
            )

        self._set_state(ConnectorState.READY)
        logger.info(
            "anthropic provider ready",
            extra={
                "model": self._settings.model,
                "effort": self._settings.effort,
                "refusal_fallback": self._use_beta_endpoint(),
            },
        )

    @staticmethod
    def _detect_fallback_support(client: Any) -> bool:
        """Probe whether this SDK build accepts ``fallbacks``.

        Checked by signature rather than by version string: a version
        comparison would break the moment the parameter moves, and the
        signature is the thing that actually matters.
        """
        import inspect

        try:
            beta_messages = client.beta.messages
        except AttributeError:  # pragma: no cover - very old SDK
            return False

        for method_name in ("stream", "create"):
            method = getattr(beta_messages, method_name, None)
            if method is None:
                return False
            try:
                parameters = inspect.signature(method).parameters
            except (TypeError, ValueError):  # pragma: no cover - unintrospectable
                return False
            if "fallbacks" not in parameters:
                return False
        return True

    @staticmethod
    def _sdk_version() -> str:
        try:
            import anthropic

            return getattr(anthropic, "__version__", "unknown")
        except ImportError:  # pragma: no cover
            return "unknown"

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None
        self._set_state(ConnectorState.CLOSED)

    async def health(self) -> CheckResult:
        if self._client is None:
            return CheckResult.unhealthy("anthropic provider is not connected")
        try:
            # Token counting is the cheapest call that proves credentials work.
            await self.count_tokens([Message.user("ping")])
        except Exception as exc:  # noqa: BLE001
            return CheckResult.unhealthy(f"anthropic provider unreachable: {exc}")
        return CheckResult.healthy("anthropic provider is ready", model=self._settings.model)

    async def _require_client(self) -> Any:
        if self._client is None:
            await self.connect()
        return self._client

    # -- request construction ---------------------------------------------
    def _build_params(
        self,
        messages: Sequence[Message],
        *,
        system: str | list[dict[str, Any]] | None,
        tools: Sequence[dict[str, Any]] | None,
        max_tokens: int | None,
        model: str | None,
        effort: str | None,
        extra: dict[str, Any],
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": model or self._settings.model,
            "max_tokens": max_tokens or self._settings.max_tokens,
            "messages": [m.model_dump(mode="json") for m in messages],
        }

        if system is not None:
            params["system"] = self._build_system(system)

        # Adaptive thinking is the only supported on-mode on current models.
        if self._settings.thinking == "adaptive":
            params["thinking"] = {
                "type": "adaptive",
                "display": self._settings.thinking_display,
            }
        else:
            params["thinking"] = {"type": "disabled"}

        output_config: dict[str, Any] = {"effort": effort or self._settings.effort}
        # Disabling thinking is only accepted at effort `high` or below;
        # pairing it with xhigh/max is a 400.
        if params["thinking"]["type"] == "disabled" and output_config["effort"] in (
            "xhigh",
            "max",
        ):
            output_config["effort"] = "high"
        params["output_config"] = output_config

        if tools:
            params["tools"] = list(tools)

        # NOTE: temperature / top_p / top_k / budget_tokens are deliberately
        # never set — they are rejected with a 400 on current models. Steer
        # behaviour through the system prompt and `effort` instead.
        extra = dict(extra)
        # Merge rather than replace, so a caller supplying `format` (structured
        # outputs) does not silently drop the configured effort level.
        caller_output_config = extra.pop("output_config", None)
        if caller_output_config:
            params["output_config"] = {**output_config, **caller_output_config}
        params.update(extra)
        return params

    def _build_system(self, system: str | list[dict[str, Any]]) -> Any:
        """Render the system prompt, attaching a cache breakpoint when enabled.

        The breakpoint goes on the last system block so tools + system cache
        together (render order is tools → system → messages).
        """
        if isinstance(system, str):
            if not self._settings.enable_prompt_caching:
                return system
            return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]

        blocks = [dict(b) for b in system]
        if blocks and self._settings.enable_prompt_caching:
            blocks[-1]["cache_control"] = {"type": "ephemeral"}
        return blocks

    def _use_beta_endpoint(self) -> bool:
        # The beta endpoint is only worth using for the fallback parameter; if
        # this SDK cannot carry it, the plain endpoint is the correct path.
        return self._enable_fallback and self._supports_fallbacks

    def _beta_kwargs(self) -> dict[str, Any]:
        if not self._use_beta_endpoint():
            return {}
        return {"betas": [FALLBACK_BETA], "fallbacks": "default"}

    # -- completion -------------------------------------------------------
    async def complete(
        self,
        messages: Sequence[Message],
        *,
        system: str | list[dict[str, Any]] | None = None,
        tools: Sequence[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
        effort: str | None = None,
        stream: bool | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Issue one request and return the parsed response.

        Streams by default: ``max_tokens`` covers thinking plus output, so a
        non-streaming request at a realistic budget risks an HTTP timeout.
        """
        client = await self._require_client()
        params = self._build_params(
            messages,
            system=system,
            tools=tools,
            max_tokens=max_tokens,
            model=model,
            effort=effort,
            extra=kwargs,
        )
        params.update(self._beta_kwargs())

        should_stream = self._settings.stream if stream is None else stream
        api = client.beta.messages if self._use_beta_endpoint() else client.messages

        with tracer.span(
            "llm.complete",
            model=params["model"],
            tool_count=len(params.get("tools", [])),
            streaming=should_stream,
        ) as span:
            await event_bus.emit(
                Events.LLM_REQUEST,
                model=params["model"],
                message_count=len(messages),
                tool_count=len(params.get("tools", [])),
            )

            try:
                if should_stream:
                    async with api.stream(**params) as stream_ctx:
                        raw = await stream_ctx.get_final_message()
                else:
                    raw = await api.create(**params)
            except Exception as exc:  # noqa: BLE001 - translated below
                raise self._translate(exc) from exc

            response = self._parse(raw)
            span.set_attributes(
                {
                    "stop_reason": response.stop_reason.value,
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                    "cache_read_tokens": response.usage.cache_read_input_tokens,
                }
            )
            metrics.increment("llm.requests", model=params["model"])
            metrics.observe("llm.output_tokens", response.usage.output_tokens)
            metrics.observe("llm.cache_hit_ratio", response.usage.cache_hit_ratio)

            if response.was_refused:
                metrics.increment("llm.refusals", category=response.refusal_category or "unknown")
                logger.warning(
                    "model declined the request",
                    extra={
                        "category": response.refusal_category,
                        "model": response.model,
                    },
                )

            await event_bus.emit(
                Events.LLM_RESPONSE,
                model=response.model,
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
        """Yield text deltas as the model produces them."""
        client = await self._require_client()
        params = self._build_params(
            messages,
            system=system,
            tools=tools,
            max_tokens=max_tokens,
            model=model,
            effort=kwargs.pop("effort", None),
            extra=kwargs,
        )
        params.update(self._beta_kwargs())
        api = client.beta.messages if self._use_beta_endpoint() else client.messages

        try:
            async with api.stream(**params) as stream_ctx:
                async for text in stream_ctx.text_stream:
                    yield text
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from exc

    async def count_tokens(
        self,
        messages: Sequence[Message],
        *,
        system: str | None = None,
        tools: Sequence[dict[str, Any]] | None = None,
        model: str | None = None,
    ) -> int:
        client = await self._require_client()
        params: dict[str, Any] = {
            "model": model or self._settings.model,
            "messages": [m.model_dump(mode="json") for m in messages],
        }
        if system:
            params["system"] = system
        if tools:
            params["tools"] = list(tools)

        try:
            result = await client.messages.count_tokens(**params)
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from exc
        return int(result.input_tokens)

    # -- agentic loop -----------------------------------------------------
    async def run_agent(
        self,
        messages: Sequence[Message],
        *,
        system: str | list[dict[str, Any]] | None = None,
        tool_executor: Any | None = None,
        tool_names: Sequence[str] | None = None,
        max_iterations: int | None = None,
        ctx: ExecutionContext | None = None,
        approvals: dict[str, bool] | None = None,
        **kwargs: Any,
    ) -> AgentResult:
        """Drive a tool-use loop until the model stops calling tools.

        A manual loop rather than the SDK tool runner, because tool execution
        must pass through the platform's :class:`~sa_tools.executor.ToolExecutor`
        — policy, permissions, audit — and because a gated tool has to *pause*
        the loop and return control to a human approver rather than fail.
        """
        from sa_tools.executor import tool_executor as default_executor
        from sa_tools.models import ToolStatus

        executor = tool_executor or default_executor
        ctx = ctx or current_context()
        limit = max_iterations or self._settings.max_tool_iterations

        tool_definitions = executor.registry.to_anthropic_tools(names=tool_names)
        history: list[Message] = list(messages)
        total = Usage()
        collected: list[dict[str, Any]] = []
        iterations = 0
        stop_reason = StopReason.UNKNOWN
        final_text = ""

        while iterations < limit:
            iterations += 1
            ctx.check_deadline()

            response = await self.complete(
                history,
                system=system,
                tools=tool_definitions or None,
                **kwargs,
            )
            total = total + response.usage
            stop_reason = response.stop_reason

            if response.text:
                final_text = response.text

            # A refusal ends the loop: content is empty or partial and the
            # conversation cannot be usefully continued.
            if response.was_refused:
                break

            # Echo the assistant turn back verbatim — thinking blocks must be
            # passed through unmodified or the next request is rejected.
            history.append(Message.assistant(response.content_blocks))

            # A server-side tool hit its iteration cap; re-send to resume.
            # No extra user message: the API detects the paused turn itself.
            if response.stop_reason is StopReason.PAUSE_TURN:
                continue

            if not response.wants_tools:
                break

            tool_use_blocks = [b for b in response.content_blocks if b.get("type") == "tool_use"]
            results = await executor.execute_many(
                [self._to_invocation(block, approvals) for block in tool_use_blocks],
                ctx=ctx,
            )

            pending = [r for r in results if r.status is ToolStatus.APPROVAL_REQUIRED]
            if pending:
                # Stop and hand the decision to a human. The caller resumes by
                # re-invoking with `approvals` populated.
                return AgentResult(
                    text=final_text,
                    messages=history,
                    iterations=iterations,
                    usage=total,
                    stop_reason=StopReason.TOOL_USE,
                    tool_results=collected,
                    pending_approvals=[
                        {
                            "tool": r.tool,
                            "invocation_id": r.invocation_id,
                            "reason": (r.error or {}).get("message", ""),
                            "details": (r.error or {}).get("details", {}),
                        }
                        for r in pending
                    ],
                )

            blocks = [r.to_anthropic_tool_result() for r in results]
            collected.extend(blocks)
            # All results for one turn go back in a single user message.
            history.append(Message.tool_results(blocks))
        else:
            logger.warning(
                "agent loop hit its iteration limit",
                extra={"limit": limit, "correlation_id": ctx.correlation_id},
            )

        return AgentResult(
            text=final_text,
            messages=history,
            iterations=iterations,
            usage=total,
            stop_reason=stop_reason,
            tool_results=collected,
        )

    @staticmethod
    def _to_invocation(block: dict[str, Any], approvals: dict[str, bool] | None) -> Any:
        from sa_tools.models import ToolInvocation

        block_id = block.get("id", "")
        return ToolInvocation(
            tool=block.get("name", ""),
            arguments=block.get("input") or {},
            invocation_id=block_id,
            approved=(approvals or {}).get(block_id),
        )

    # -- parsing ----------------------------------------------------------
    def _parse(self, raw: Any) -> LLMResponse:
        blocks: list[dict[str, Any]] = []
        text_parts: list[str] = []
        thinking_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for block in getattr(raw, "content", []) or []:
            as_dict = self._block_to_dict(block)
            blocks.append(as_dict)

            kind = as_dict.get("type")
            if kind == "text":
                text_parts.append(as_dict.get("text", ""))
            elif kind == "thinking":
                # Empty unless thinking.display is "summarized".
                thinking_parts.append(as_dict.get("thinking", ""))
            elif kind == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=as_dict.get("id", ""),
                        name=as_dict.get("name", ""),
                        arguments=as_dict.get("input") or {},
                    )
                )

        raw_usage = getattr(raw, "usage", None)
        usage = Usage(
            input_tokens=getattr(raw_usage, "input_tokens", 0) or 0,
            output_tokens=getattr(raw_usage, "output_tokens", 0) or 0,
            cache_creation_input_tokens=getattr(raw_usage, "cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=getattr(raw_usage, "cache_read_input_tokens", 0) or 0,
        )

        raw_stop = getattr(raw, "stop_reason", None)
        try:
            stop_reason = StopReason(raw_stop) if raw_stop else StopReason.UNKNOWN
        except ValueError:
            stop_reason = StopReason.UNKNOWN

        # stop_details is populated only on a refusal, and can still be null.
        stop_details = None
        details = getattr(raw, "stop_details", None)
        if details is not None:
            stop_details = {
                "type": getattr(details, "type", None),
                "category": getattr(details, "category", None),
                "explanation": getattr(details, "explanation", None),
            }

        return LLMResponse(
            text="".join(text_parts),
            thinking="".join(thinking_parts),
            content_blocks=blocks,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            stop_details=stop_details,
            model=getattr(raw, "model", "") or "",
            usage=usage,
        )

    @staticmethod
    def _block_to_dict(block: Any) -> dict[str, Any]:
        if isinstance(block, dict):
            return block
        for attribute in ("model_dump", "to_dict", "dict"):
            method = getattr(block, attribute, None)
            if callable(method):
                try:
                    return method(mode="json") if attribute == "model_dump" else method()
                except TypeError:
                    return method()
        return {"type": getattr(block, "type", "unknown")}

    # -- error translation ------------------------------------------------
    @staticmethod
    def _translate(exc: BaseException) -> BaseException:
        """Map SDK exceptions onto the platform taxonomy.

        Uses the SDK's typed exception classes rather than string matching, so
        retryability is decided correctly downstream.
        """
        try:
            import anthropic
        except ImportError:  # pragma: no cover
            return DependencyError(f"anthropic call failed: {exc}", cause=exc)

        if isinstance(exc, anthropic.AuthenticationError):
            return AuthenticationError(
                "Anthropic rejected the credentials. Check ANTHROPIC_API_KEY or the "
                "active `ant auth login` profile.",
                cause=exc,
            )
        if isinstance(exc, anthropic.PermissionDeniedError):
            return AuthenticationError(
                "the API key lacks permission for this model or feature", cause=exc
            )
        if isinstance(exc, anthropic.NotFoundError):
            return ConfigurationError(
                f"unknown model or endpoint: {exc}. Verify the model id.", cause=exc
            )
        if isinstance(exc, anthropic.RateLimitError):
            retry_after = None
            response = getattr(exc, "response", None)
            if response is not None:
                header = response.headers.get("retry-after")
                if header and header.isdigit():
                    retry_after = float(header)
            return RateLimitError(
                "Anthropic rate limit reached", retry_after=retry_after, cause=exc
            )
        if isinstance(exc, anthropic.BadRequestError):
            return ValidationError(f"Anthropic rejected the request: {exc}", cause=exc)
        if isinstance(exc, anthropic.APITimeoutError):
            return TimeoutError_("the Anthropic request timed out", cause=exc)
        if isinstance(exc, anthropic.APIConnectionError):
            return DependencyError(f"could not reach the Anthropic API: {exc}", cause=exc)
        if isinstance(exc, anthropic.APIStatusError):
            status = getattr(exc, "status_code", 500)
            return DependencyError(
                f"Anthropic returned HTTP {status}",
                details={"status_code": status},
                cause=exc,
            )
        return DependencyError(f"anthropic call failed: {exc}", cause=exc)

    # -- structured output ------------------------------------------------
    async def complete_structured(
        self,
        messages: Sequence[Message],
        schema: dict[str, Any],
        *,
        system: str | list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Request a response constrained to ``schema`` and return parsed JSON.

        This replaces assistant-turn prefill, which is rejected on current
        models.
        """
        response = await self.complete(
            messages,
            system=system,
            output_config={"format": {"type": "json_schema", "schema": schema}},
            **kwargs,
        )
        if response.was_refused:
            raise ValidationError(
                "the model declined to produce a structured response",
                details={"category": response.refusal_category},
            )
        try:
            return json.loads(response.text)
        except json.JSONDecodeError as exc:
            raise ValidationError(
                "structured output was not valid JSON",
                details={"text": response.text[:500]},
                cause=exc,
            ) from exc


__all__ = ["FALLBACK_BETA", "AnthropicProvider"]
