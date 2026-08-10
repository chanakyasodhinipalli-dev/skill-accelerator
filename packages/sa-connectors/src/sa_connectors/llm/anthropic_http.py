"""Anthropic Messages API over plain HTTP.

Used for the ``dialect: anthropic`` gateway case, not for direct Anthropic
access — direct access goes through
:class:`~sa_connectors.llm.anthropic_provider.AnthropicProvider` and the official
SDK, which brings streaming helpers, typed errors, and beta features this class
deliberately does not reimplement.

This exists because a gateway changes the two things an SDK is least willing to
change: the endpoint and the auth header. A broker that authenticates with
``x-virtual-key`` and routes Claude traffic by policy speaks the Messages API
faithfully otherwise, and that is what this covers.

The Anthropic parameter rules still apply here — ``temperature``, ``top_p``,
``top_k``, and ``budget_tokens`` are never sent, and depth is set with
``output_config.effort``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .base import LLMResponse, Message, Role, StopReason, ToolCall, Usage
from .http_base import HttpLLMProvider

_STOP_REASONS = {
    "end_turn": StopReason.END_TURN,
    "max_tokens": StopReason.MAX_TOKENS,
    "stop_sequence": StopReason.STOP_SEQUENCE,
    "tool_use": StopReason.TOOL_USE,
    "pause_turn": StopReason.PAUSE_TURN,
    "refusal": StopReason.REFUSAL,
}

#: Required by the Messages API when it is called without an SDK.
ANTHROPIC_VERSION = "2023-06-01"


class AnthropicHttpProvider(HttpLLMProvider):
    """Anthropic Messages API reached over HTTP, typically through a gateway."""

    wire = "anthropic"
    default_base_url = "https://api.anthropic.com/v1"
    default_auth_header = "x-api-key"
    default_auth_scheme = ""

    def _headers(self) -> dict[str, str]:
        headers = super()._headers()
        headers.setdefault("anthropic-version", ANTHROPIC_VERSION)
        return headers

    def _completion_path(self, model: str, *, stream: bool) -> str:
        return "/messages"

    def _models_path(self) -> str | None:
        return "/models"

    def _parse_models(self, data: Any) -> list[str]:
        entries = (data or {}).get("data", []) if isinstance(data, dict) else []
        return sorted(str(e.get("id")) for e in entries if isinstance(e, dict) and e.get("id"))

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
        body: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens or self.profile.max_tokens,
            "messages": [
                {
                    "role": "assistant" if m.role is Role.ASSISTANT else m.role.value,
                    "content": m.content,
                }
                for m in messages
            ],
        }
        system_text = self._system_text(system)
        if system_text:
            body["system"] = system_text
        if stream:
            body["stream"] = True

        thinking = self.profile.thinking or "adaptive"
        body["thinking"] = {"type": thinking} if thinking == "disabled" else {"type": "adaptive"}

        effort = self.profile.effort or "high"
        # Disabling thinking above `high` effort is rejected; clamp instead.
        if thinking == "disabled" and effort in ("xhigh", "max"):
            effort = "high"
        output_config: dict[str, Any] = {"effort": effort}
        if schema:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        body["output_config"] = output_config

        if tools:
            body["tools"] = list(tools)

        body.update(self.profile.extra_body)
        body.update(extra)
        return body

    def _parse(self, data: dict[str, Any]) -> LLMResponse:
        blocks = [b for b in (data.get("content") or []) if isinstance(b, dict)]
        text = "".join(str(b.get("text", "")) for b in blocks if b.get("type") == "text")
        thinking = "".join(
            str(b.get("thinking", "")) for b in blocks if b.get("type") == "thinking"
        )
        tool_calls = [
            ToolCall(
                id=str(b.get("id", "")),
                name=str(b.get("name", "")),
                arguments=b.get("input") or {},
            )
            for b in blocks
            if b.get("type") == "tool_use"
        ]
        usage_raw = data.get("usage") or {}
        details = data.get("stop_details")
        return LLMResponse(
            text=text,
            thinking=thinking,
            content_blocks=blocks,
            tool_calls=tool_calls,
            stop_reason=self._stop_reason(data.get("stop_reason"), _STOP_REASONS),
            stop_details=details if isinstance(details, dict) else None,
            model=str(data.get("model", "")),
            usage=Usage(
                input_tokens=int(usage_raw.get("input_tokens") or 0),
                output_tokens=int(usage_raw.get("output_tokens") or 0),
                cache_creation_input_tokens=int(usage_raw.get("cache_creation_input_tokens") or 0),
                cache_read_input_tokens=int(usage_raw.get("cache_read_input_tokens") or 0),
            ),
        )

    def _delta_text(self, chunk: dict[str, Any]) -> str:
        if chunk.get("type") != "content_block_delta":
            return ""
        delta = chunk.get("delta") or {}
        return str(delta.get("text", "")) if delta.get("type") == "text_delta" else ""

    async def count_tokens(
        self,
        messages: Sequence[Message],
        *,
        system: str | None = None,
        tools: Sequence[dict[str, Any]] | None = None,
        model: str | None = None,
    ) -> int:
        body: dict[str, Any] = {
            "model": model or self.profile.model,
            "messages": [
                {
                    "role": "assistant" if m.role is Role.ASSISTANT else m.role.value,
                    "content": m.content,
                }
                for m in messages
            ],
        }
        if system:
            body["system"] = system
        if tools:
            body["tools"] = list(tools)
        data = await self._request("POST", "/messages/count_tokens", body)
        return int((data or {}).get("input_tokens") or 0)


__all__ = ["ANTHROPIC_VERSION", "AnthropicHttpProvider"]
