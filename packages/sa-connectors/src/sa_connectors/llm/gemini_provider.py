"""Google Gemini provider.

Implements the Generative Language API (``:generateContent``). Three things
differ enough from the other vendors to be worth stating:

* Roles are ``user`` and ``model`` — not ``assistant`` — and the system prompt
  is a separate ``systemInstruction`` rather than a turn.
* ``responseSchema`` accepts a *subset* of JSON Schema. Unsupported keywords are
  a 400, not an ignored field, so schemas are filtered before they are sent.
* Token counting has a real endpoint (``:countTokens``), so this provider can
  answer :meth:`count_tokens` honestly instead of estimating.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sa_platform.errors import DependencyError
from sa_platform.logging import get_logger

from .base import LLMResponse, Message, Role, StopReason, ToolCall, Usage
from .http_base import HttpLLMProvider

logger = get_logger(__name__)

_STOP_REASONS = {
    "STOP": StopReason.END_TURN,
    "MAX_TOKENS": StopReason.MAX_TOKENS,
    "SAFETY": StopReason.REFUSAL,
    "PROHIBITED_CONTENT": StopReason.REFUSAL,
    "BLOCKLIST": StopReason.REFUSAL,
    "RECITATION": StopReason.REFUSAL,
}

#: JSON Schema keywords `responseSchema` understands. Anything else — notably
#: `additionalProperties`, `$defs`, `$ref`, `oneOf`, `patternProperties` — is
#: rejected, so it is stripped rather than passed through.
_SUPPORTED_SCHEMA_KEYS = frozenset(
    {
        "type",
        "format",
        "description",
        "nullable",
        "enum",
        "items",
        "properties",
        "required",
        "minItems",
        "maxItems",
    }
)


def sanitise_schema(schema: Any) -> Any:
    """Reduce a JSON Schema to the subset Gemini accepts.

    Dropping unsupported keywords loosens validation; keeping them fails the
    request outright. A looser constraint plus the platform's own post-parse
    validation is the better trade.
    """
    if isinstance(schema, list):
        return [sanitise_schema(entry) for entry in schema]
    if not isinstance(schema, dict):
        return schema

    cleaned: dict[str, Any] = {}
    for key, value in schema.items():
        if key not in _SUPPORTED_SCHEMA_KEYS:
            continue
        if key == "properties" and isinstance(value, dict):
            cleaned[key] = {k: sanitise_schema(v) for k, v in value.items()}
        elif key == "items":
            cleaned[key] = sanitise_schema(value)
        else:
            cleaned[key] = value

    # A schema that lost its type entirely would be rejected; objects are the
    # overwhelmingly common case for structured output.
    if "properties" in cleaned and "type" not in cleaned:
        cleaned["type"] = "object"
    return cleaned


class GeminiProvider(HttpLLMProvider):
    """Google Gemini via the Generative Language API."""

    wire = "gemini"
    default_base_url = "https://generativelanguage.googleapis.com/v1beta"
    default_auth_header = "x-goog-api-key"
    default_auth_scheme = ""

    # -- endpoints ---------------------------------------------------------
    def _completion_path(self, model: str, *, stream: bool) -> str:
        name = model if model.startswith("models/") else f"models/{model}"
        if stream:
            return f"/{name}:streamGenerateContent?alt=sse"
        return f"/{name}:generateContent"

    def _models_path(self) -> str | None:
        return "/models"

    def _parse_models(self, data: Any) -> list[str]:
        entries = (data or {}).get("models", []) if isinstance(data, dict) else []
        names = [
            str(e.get("name", "")).removeprefix("models/") for e in entries if isinstance(e, dict)
        ]
        return sorted(n for n in names if n)

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
        contents: list[dict[str, Any]] = []
        # Gemini has no mid-conversation system turn; such a message is folded
        # into the systemInstruction rather than dropped.
        extra_system: list[str] = []
        for message in messages:
            text = self._flatten_content(message.content)
            if not text:
                continue
            if message.role is Role.SYSTEM:
                extra_system.append(text)
                continue
            contents.append(
                {
                    "role": "model" if message.role is Role.ASSISTANT else "user",
                    "parts": [{"text": text}],
                }
            )

        generation: dict[str, Any] = {"maxOutputTokens": max_tokens or self.profile.max_tokens}
        if self.profile.temperature is not None:
            generation["temperature"] = self.profile.temperature
        if self.profile.top_p is not None:
            generation["topP"] = self.profile.top_p
        if schema:
            generation["responseMimeType"] = "application/json"
            generation["responseSchema"] = sanitise_schema(schema)

        body: dict[str, Any] = {"contents": contents, "generationConfig": generation}

        system_text = "\n\n".join(filter(None, [self._system_text(system), *extra_system]))
        if system_text:
            body["systemInstruction"] = {"parts": [{"text": system_text}]}
        if tools:
            body["tools"] = [{"functionDeclarations": [self._to_declaration(t) for t in tools]}]

        body.update(self.profile.extra_body)
        body.update(extra)
        return body

    @staticmethod
    def _to_declaration(tool: dict[str, Any]) -> dict[str, Any]:
        """Translate a registry tool definition into a function declaration."""
        parameters = tool.get("input_schema") or tool.get("parameters") or {}
        return {
            "name": tool.get("name", ""),
            "description": tool.get("description", ""),
            "parameters": sanitise_schema(parameters),
        }

    # -- response ----------------------------------------------------------
    def _parse(self, data: dict[str, Any]) -> LLMResponse:
        candidates = data.get("candidates") or []
        usage_raw = data.get("usageMetadata") or {}
        usage = Usage(
            input_tokens=int(usage_raw.get("promptTokenCount") or 0),
            output_tokens=int(usage_raw.get("candidatesTokenCount") or 0),
        )

        # A prompt blocked before generation returns no candidates at all.
        if not candidates:
            block = (data.get("promptFeedback") or {}).get("blockReason")
            return LLMResponse(
                stop_reason=StopReason.REFUSAL if block else StopReason.UNKNOWN,
                stop_details={"type": "refusal", "category": str(block)} if block else None,
                model=str(data.get("modelVersion", "")),
                usage=usage,
            )

        candidate = candidates[0]
        parts = (candidate.get("content") or {}).get("parts") or []
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        blocks: list[dict[str, Any]] = []

        for index, part in enumerate(parts):
            if "text" in part:
                text_parts.append(str(part["text"]))
                blocks.append({"type": "text", "text": str(part["text"])})
            elif "functionCall" in part:
                call = part["functionCall"] or {}
                # Gemini does not issue call ids; a stable positional id keeps
                # tool results matchable.
                call_id = f"call_{index}"
                tool_calls.append(
                    ToolCall(
                        id=call_id,
                        name=str(call.get("name", "")),
                        arguments=call.get("args") or {},
                    )
                )
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call_id,
                        "name": str(call.get("name", "")),
                        "input": call.get("args") or {},
                    }
                )

        finish = str(candidate.get("finishReason") or "")
        stop_reason = self._stop_reason(finish, _STOP_REASONS)
        if tool_calls and stop_reason is StopReason.END_TURN:
            stop_reason = StopReason.TOOL_USE

        return LLMResponse(
            text="".join(text_parts),
            content_blocks=blocks,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            stop_details=(
                {"type": "refusal", "category": finish}
                if stop_reason is StopReason.REFUSAL
                else None
            ),
            model=str(data.get("modelVersion", "")),
            usage=usage,
        )

    def _delta_text(self, chunk: dict[str, Any]) -> str:
        candidates = chunk.get("candidates") or []
        if not candidates:
            return ""
        parts = (candidates[0].get("content") or {}).get("parts") or []
        return "".join(str(p.get("text", "")) for p in parts)

    # -- token counting ----------------------------------------------------
    async def count_tokens(
        self,
        messages: Sequence[Message],
        *,
        system: str | None = None,
        tools: Sequence[dict[str, Any]] | None = None,
        model: str | None = None,
    ) -> int:
        resolved = model or self.profile.model
        name = resolved if resolved.startswith("models/") else f"models/{resolved}"
        body = {
            "contents": [
                {
                    "role": "model" if m.role is Role.ASSISTANT else "user",
                    "parts": [{"text": self._flatten_content(m.content)}],
                }
                for m in messages
            ]
        }
        data = await self._request("POST", f"/{name}:countTokens", body)
        total = (data or {}).get("totalTokens")
        if total is None:
            raise DependencyError(
                "Gemini countTokens returned no total",
                details={"profile": self.profile.name},
            )
        return int(total)


__all__ = ["GeminiProvider", "sanitise_schema"]
