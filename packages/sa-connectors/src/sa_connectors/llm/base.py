"""Provider-neutral LLM contracts.

The orchestrator and skills depend on these types, not on a vendor SDK, so a
provider can be swapped without touching business code. The platform's own
implementation is Anthropic (:mod:`sa_connectors.llm.anthropic_provider`).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Role(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class StopReason(str, Enum):
    END_TURN = "end_turn"
    MAX_TOKENS = "max_tokens"
    STOP_SEQUENCE = "stop_sequence"
    TOOL_USE = "tool_use"
    PAUSE_TURN = "pause_turn"
    REFUSAL = "refusal"
    UNKNOWN = "unknown"


class Message(BaseModel):
    """One conversation turn.

    ``content`` is either plain text or a list of content blocks. Blocks are
    kept as raw dicts so provider-specific block types (thinking, tool_use,
    compaction) survive a round trip unmodified — the API rejects edited
    thinking blocks, so passing them back verbatim matters.
    """

    model_config = ConfigDict(extra="forbid")

    role: Role
    content: str | list[dict[str, Any]]

    @classmethod
    def user(cls, text: str) -> Message:
        return cls(role=Role.USER, content=text)

    @classmethod
    def assistant(cls, content: str | list[dict[str, Any]]) -> Message:
        return cls(role=Role.ASSISTANT, content=content)

    @classmethod
    def system(cls, text: str) -> Message:
        """A mid-conversation system message.

        Supported on Claude Opus 5, Opus 4.8, Fable 5, and Mythos 5 — not
        Sonnet 5. Preferred over rewriting the top-level system prompt because
        it does not invalidate the cached prefix.
        """
        return cls(role=Role.SYSTEM, content=text)

    @classmethod
    def tool_results(cls, results: Sequence[dict[str, Any]]) -> Message:
        """Wrap ``tool_result`` blocks as the user turn that answers a tool call.

        All results for one assistant turn must be in a *single* message —
        splitting them across messages trains the model out of parallel tool
        calls.
        """
        return cls(role=Role.USER, content=list(results))


class Usage(BaseModel):
    """Token accounting for one request."""

    model_config = ConfigDict(extra="allow")

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_input_tokens
            + self.cache_read_input_tokens
        )

    @property
    def cache_hit_ratio(self) -> float:
        """Share of prompt tokens served from cache.

        A ratio near zero across repeated identical-prefix requests means a
        silent cache invalidator — a timestamp, a UUID, or a reordered tool
        list somewhere in the prefix.
        """
        prompt_tokens = (
            self.input_tokens + self.cache_creation_input_tokens + self.cache_read_input_tokens
        )
        return self.cache_read_input_tokens / prompt_tokens if prompt_tokens else 0.0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_creation_input_tokens=(
                self.cache_creation_input_tokens + other.cache_creation_input_tokens
            ),
            cache_read_input_tokens=(self.cache_read_input_tokens + other.cache_read_input_tokens),
        )


class ToolCall(BaseModel):
    """A tool the model asked to run."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    """A single model response."""

    model_config = ConfigDict(extra="forbid")

    text: str = ""
    thinking: str = ""
    content_blocks: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    stop_reason: StopReason = StopReason.UNKNOWN
    stop_details: dict[str, Any] | None = None
    model: str = ""
    usage: Usage = Field(default_factory=Usage)
    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def wants_tools(self) -> bool:
        return self.stop_reason is StopReason.TOOL_USE and bool(self.tool_calls)

    @property
    def was_refused(self) -> bool:
        """True when safety classifiers declined the request.

        Always check this before reading :attr:`text` — a refusal returns
        HTTP 200 with empty or partial content.
        """
        return self.stop_reason is StopReason.REFUSAL

    @property
    def refusal_category(self) -> str | None:
        return (self.stop_details or {}).get("category")


class AgentResult(BaseModel):
    """The outcome of a full agentic loop."""

    model_config = ConfigDict(extra="forbid")

    text: str = ""
    messages: list[Message] = Field(default_factory=list)
    iterations: int = 0
    usage: Usage = Field(default_factory=Usage)
    stop_reason: StopReason = StopReason.UNKNOWN
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    #: Set when the loop halted awaiting human approval of a gated tool.
    pending_approvals: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def needs_approval(self) -> bool:
        return bool(self.pending_approvals)


class LLMProvider(ABC):
    """Contract every model provider implements."""

    @abstractmethod
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
        """One request/response round trip."""

    @abstractmethod
    def stream(
        self,
        messages: Sequence[Message],
        *,
        system: str | list[dict[str, Any]] | None = None,
        tools: Sequence[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Yield text deltas as they arrive."""

    @abstractmethod
    async def count_tokens(
        self,
        messages: Sequence[Message],
        *,
        system: str | None = None,
        tools: Sequence[dict[str, Any]] | None = None,
        model: str | None = None,
    ) -> int:
        """Count prompt tokens using the provider's own tokenizer.

        Never estimate with a third-party tokenizer — counts differ by model
        and a wrong estimate silently breaks context budgeting.
        """


__all__ = [
    "AgentResult",
    "LLMProvider",
    "LLMResponse",
    "Message",
    "Role",
    "StopReason",
    "ToolCall",
    "Usage",
]
