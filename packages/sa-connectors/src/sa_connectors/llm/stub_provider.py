"""A deterministic provider that calls no model.

Not a mock for tests — a real, selectable profile. Two things make it worth
shipping:

* **The console is fully exercisable with no credential.** Every screen, every
  flow, and every artifact works offline; only the *wording* of generated
  questions degrades to the deterministic fallback.
* **It shows what the platform does without a model.** Field selection, gap
  analysis, coercion, validation, approval, and rendering are all deterministic
  by design. Switching to this profile makes that claim checkable rather than
  something written in a README.

Structured calls return a schema-shaped object with empty values, which is
exactly what the callers treat as "the model contributed nothing" — so they take
their own deterministic path rather than failing.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

from sa_platform.config import LLMProfile
from sa_platform.health import CheckResult

from ..base import Connector, ConnectorState
from .base import LLMProvider, LLMResponse, Message, StopReason, Usage

#: Roughly four characters per token. Used only to report a plausible figure for
#: a call that never leaves the process — never for real context budgeting.
_CHARS_PER_TOKEN = 4


class StubProvider(Connector, LLMProvider):
    """Deterministic, offline, zero-cost. Selectable like any other profile."""

    wire = "stub"

    def __init__(self, profile: LLMProfile | None = None, *, name: str | None = None) -> None:
        self.profile = profile or LLMProfile(name="stub", vendor="stub", model="deterministic")
        Connector.__init__(self, name or self.profile.name)

    async def connect(self) -> None:
        self._set_state(ConnectorState.READY)

    async def close(self) -> None:
        self._set_state(ConnectorState.CLOSED)

    async def health(self) -> CheckResult:
        return CheckResult.healthy("deterministic provider needs no upstream")

    @property
    def base_url(self) -> str:
        return ""

    @property
    def via_gateway(self) -> bool:
        return False

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.profile.name,
            "label": self.profile.label or "Deterministic (no model)",
            "vendor": "stub",
            "wire": "stub",
            "model": self.profile.model,
            "base_url": "",
            "via_gateway": False,
            "state": self.state.value,
            "credential_present": True,
            "streaming": False,
        }

    async def list_models(self) -> list[str]:
        return [self.profile.model]

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        system: str | list[dict[str, Any]] | None = None,
        tools: Sequence[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        last = messages[-1].content if messages else ""
        text = last if isinstance(last, str) else ""
        return LLMResponse(
            text="",
            stop_reason=StopReason.END_TURN,
            model=self.profile.model,
            usage=Usage(input_tokens=len(text) // _CHARS_PER_TOKEN, output_tokens=0),
        )

    async def stream(  # type: ignore[override]
        self,
        messages: Sequence[Message],
        *,
        system: str | list[dict[str, Any]] | None = None,
        tools: Sequence[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        response = await self.complete(messages, system=system, tools=tools)
        if response.text:
            yield response.text

    async def count_tokens(
        self,
        messages: Sequence[Message],
        *,
        system: str | None = None,
        tools: Sequence[dict[str, Any]] | None = None,
        model: str | None = None,
    ) -> int:
        characters = sum(
            len(m.content) if isinstance(m.content, str) else 0 for m in messages
        ) + len(system or "")
        return characters // _CHARS_PER_TOKEN

    async def complete_structured(
        self,
        messages: Sequence[Message],
        schema: dict[str, Any],
        *,
        system: str | list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> Any:
        return empty_for_schema(schema)


def empty_for_schema(schema: Any) -> Any:
    """Build the emptiest value a schema allows.

    Callers read this as "nothing was extracted / nothing was phrased" and fall
    back to their deterministic path, which is the intended behaviour.
    """
    if not isinstance(schema, dict):
        return None
    kind = schema.get("type")
    if kind == "object":
        properties = schema.get("properties") or {}
        return {key: empty_for_schema(value) for key, value in properties.items()}
    if kind == "array":
        return []
    if kind == "string":
        options = schema.get("enum")
        return options[0] if options else ""
    if kind == "integer":
        return 0
    if kind == "number":
        return 0.0
    if kind == "boolean":
        return False
    return None


__all__ = ["StubProvider", "empty_for_schema"]
