"""OpenAI-dialect provider.

Implements the Chat Completions shape (``POST /chat/completions``). That is a
deliberate choice over the newer Responses API: Chat Completions is the format
every OpenAI-compatible server speaks — Azure OpenAI, vLLM, Ollama, LiteLLM,
Bedrock access gateways, and most enterprise brokers — so one implementation
covers direct access and the gateway case.

Translation notes:

* The platform's canonical tool definition is Anthropic-shaped
  (``{name, description, input_schema}``) because that is what the tool registry
  emits. It is translated to the OpenAI ``{type: "function", function: {...}}``
  envelope here, so tools authored once work on every vendor.
* Tool call arguments arrive as a JSON *string* and are decoded into a dict, to
  match the neutral :class:`~sa_connectors.llm.base.ToolCall`.
* Refusals are a populated ``message.refusal`` field rather than a distinct
  stop reason, and are mapped onto the platform's refusal handling.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from sa_platform.errors import ValidationError
from sa_platform.logging import get_logger

from .base import LLMResponse, Message, Role, StopReason, ToolCall
from .http_base import HttpLLMProvider

logger = get_logger(__name__)

_STOP_REASONS = {
    "stop": StopReason.END_TURN,
    "length": StopReason.MAX_TOKENS,
    "tool_calls": StopReason.TOOL_USE,
    "function_call": StopReason.TOOL_USE,
    "content_filter": StopReason.REFUSAL,
}

#: Newer servers require `max_completion_tokens`; older OpenAI-compatible ones
#: only accept `max_tokens`. Which one a gateway wants is not knowable up front,
#: so the provider starts modern and falls back once on rejection.
_MODERN_TOKEN_PARAM = "max_completion_tokens"  # noqa: S105 - a parameter name, not a secret
_LEGACY_TOKEN_PARAM = "max_tokens"  # noqa: S105 - a parameter name, not a secret


class OpenAIProvider(HttpLLMProvider):
    """OpenAI and any OpenAI-compatible endpoint."""

    wire = "openai"
    default_base_url = "https://api.openai.com/v1"
    default_auth_header = "Authorization"
    default_auth_scheme = "Bearer"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._token_param = _MODERN_TOKEN_PARAM

    # -- endpoints ---------------------------------------------------------
    def _completion_path(self, model: str, *, stream: bool) -> str:
        return self._with_version("/chat/completions")

    def _models_path(self) -> str | None:
        return self._with_version("/models")

    def _with_version(self, path: str) -> str:
        # Azure OpenAI rejects a request without api-version; everyone else
        # ignores the parameter.
        if self.profile.api_version:
            return f"{path}?api-version={self.profile.api_version}"
        return path

    def _parse_models(self, data: Any) -> list[str]:
        entries = (data or {}).get("data", []) if isinstance(data, dict) else []
        return sorted(str(e.get("id")) for e in entries if isinstance(e, dict) and e.get("id"))

    # -- request -----------------------------------------------------------
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
        wire_messages: list[dict[str, Any]] = []
        system_text = self._system_text(system)
        if system_text:
            wire_messages.append({"role": "system", "content": system_text})
        for message in messages:
            wire_messages.append(
                {
                    # The neutral SYSTEM role is a mid-conversation instruction;
                    # OpenAI has no such turn, so it becomes a system message.
                    "role": "assistant" if message.role is Role.ASSISTANT else message.role.value,
                    "content": self._flatten_content(message.content),
                }
            )

        body: dict[str, Any] = {
            "model": model,
            "messages": wire_messages,
            self._token_param: max_tokens or self.profile.max_tokens,
        }
        if stream:
            body["stream"] = True
            # Without this, streamed responses carry no token accounting at all.
            body["stream_options"] = {"include_usage": True}
        if self.profile.temperature is not None:
            body["temperature"] = self.profile.temperature
        if self.profile.top_p is not None:
            body["top_p"] = self.profile.top_p
        if tools:
            body["tools"] = [self._to_openai_tool(t) for t in tools]
        if schema:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.get("title", "response"),
                    "schema": schema,
                    # `strict` requires every property to be required and
                    # additionalProperties to be false. Platform schemas are not
                    # written to that rule, and a mismatch is a 400 rather than
                    # a downgrade, so it stays off.
                    "strict": False,
                },
            }
        body.update(self.profile.extra_body)
        body.update(extra)
        return body

    @staticmethod
    def _to_openai_tool(tool: dict[str, Any]) -> dict[str, Any]:
        """Translate a registry tool definition into the OpenAI envelope."""
        if tool.get("type") == "function":
            return tool  # already in the target shape
        return {
            "type": "function",
            "function": {
                "name": tool.get("name", ""),
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema") or tool.get("parameters") or {},
            },
        }

    # -- token-parameter negotiation --------------------------------------
    async def complete(self, *args: Any, **kwargs: Any) -> LLMResponse:
        """Complete, negotiating the token parameter name once if rejected."""
        try:
            return await super().complete(*args, **kwargs)
        except ValidationError as exc:
            if not self._is_token_param_rejection(exc):
                raise
            previous = self._token_param
            self._token_param = (
                _LEGACY_TOKEN_PARAM if previous == _MODERN_TOKEN_PARAM else _MODERN_TOKEN_PARAM
            )
            logger.info(
                "endpoint rejected the token parameter; switching for this profile",
                extra={
                    "profile": self.profile.name,
                    "from": previous,
                    "to": self._token_param,
                },
            )
            return await super().complete(*args, **kwargs)

    @staticmethod
    def _is_token_param_rejection(exc: ValidationError) -> bool:
        body = str(exc.details.get("body", "")) if exc.details else ""
        haystack = f"{exc} {body}".lower()
        return _MODERN_TOKEN_PARAM in haystack or "max_tokens" in haystack

    # -- response ----------------------------------------------------------
    def _parse(self, data: dict[str, Any]) -> LLMResponse:
        choices = data.get("choices") or [{}]
        choice = choices[0] if isinstance(choices[0], dict) else {}
        message = choice.get("message") or {}

        refusal = message.get("refusal")
        if refusal:
            return LLMResponse(
                text="",
                stop_reason=StopReason.REFUSAL,
                stop_details={"type": "refusal", "explanation": str(refusal)},
                model=str(data.get("model", "")),
                usage=self._usage(
                    data.get("usage"), input_key="prompt_tokens", output_key="completion_tokens"
                ),
            )

        text = message.get("content") or ""
        tool_calls: list[ToolCall] = []
        blocks: list[dict[str, Any]] = []
        if text:
            blocks.append({"type": "text", "text": text})

        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            tool_calls.append(
                ToolCall(
                    id=str(call.get("id", "")),
                    name=str(function.get("name", "")),
                    arguments=_decode_arguments(function.get("arguments")),
                )
            )
            blocks.append(
                {
                    "type": "tool_use",
                    "id": str(call.get("id", "")),
                    "name": str(function.get("name", "")),
                    "input": tool_calls[-1].arguments,
                }
            )

        return LLMResponse(
            text=text,
            content_blocks=blocks,
            tool_calls=tool_calls,
            stop_reason=self._stop_reason(choice.get("finish_reason"), _STOP_REASONS),
            model=str(data.get("model", "")),
            usage=self._usage(
                data.get("usage"), input_key="prompt_tokens", output_key="completion_tokens"
            ),
        )

    def _delta_text(self, chunk: dict[str, Any]) -> str:
        choices = chunk.get("choices") or []
        if not choices:
            return ""
        return str((choices[0].get("delta") or {}).get("content") or "")


def _decode_arguments(raw: Any) -> dict[str, Any]:
    """Arguments arrive as a JSON string; a malformed one must not kill the turn."""
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("tool call arguments were not valid JSON", extra={"raw": str(raw)[:200]})
        return {}
    return decoded if isinstance(decoded, dict) else {"value": decoded}


__all__ = ["OpenAIProvider"]
