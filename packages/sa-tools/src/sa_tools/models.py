"""Tool contracts.

A *tool* is a callable action with a JSON Schema. Tools are the surface an LLM
(or an orchestrator, or a human operator) uses to act. The spec is designed to
translate directly into the Anthropic Messages API ``tools`` array.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# The API accepts ^[a-zA-Z0-9_-]{1,128}$ for tool names.
_TOOL_NAME_PATTERN = r"^[a-zA-Z0-9_-]{1,128}$"


class DangerLevel(str, Enum):
    """How much damage a mistaken call could do.

    Drives the approval gate: anything at or above the configured threshold
    requires an explicit decision before it runs.
    """

    SAFE = "safe"  # read-only, no side effects
    LOW = "low"  # writes to scratch space, easily reversed
    MEDIUM = "medium"  # mutates business state, reversible with effort
    HIGH = "high"  # irreversible, external, or financially material

    @property
    def rank(self) -> int:
        return {"safe": 0, "low": 1, "medium": 2, "high": 3}[self.value]


class ToolKind(str, Enum):
    NATIVE = "native"  # implemented in-process
    SKILL = "skill"  # bridges to a registered skill
    MCP = "mcp"  # proxied to an MCP server
    OPENAPI = "openapi"  # generated from an OpenAPI operation
    SERVER = "server"  # executed by the model provider (web search, etc.)


class ToolSpec(BaseModel):
    """The declarative contract for a tool."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(description="Unique identifier; must match ^[a-zA-Z0-9_-]{1,128}$")
    description: str = Field(
        description=(
            "What the tool does AND when to call it. Prescriptive trigger "
            "conditions materially improve model tool selection."
        )
    )
    parameters: dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "properties": {}},
        description="JSON Schema for the tool's arguments",
    )
    returns: dict[str, Any] = Field(default_factory=dict, description="JSON Schema for the result")

    kind: ToolKind = ToolKind.NATIVE
    danger: DangerLevel = DangerLevel.SAFE
    tags: list[str] = Field(default_factory=list)
    # Permissions the calling principal must hold.
    required_permissions: list[str] = Field(default_factory=list)

    timeout_seconds: float | None = Field(default=None, gt=0)
    max_retries: int = Field(default=0, ge=0, le=5)
    idempotent: bool = True
    # Safe to run alongside other tools in the same model turn.
    parallel_safe: bool = True
    # Force human approval regardless of the danger threshold.
    requires_approval: bool = False
    # Ask the API to guarantee the arguments validate against `parameters`.
    strict: bool = True
    # Defer schema loading until tool search surfaces it (large tool catalogues).
    defer_loading: bool = False

    source: str | None = Field(default=None, description="Origin, e.g. 'mcp:github'")
    examples: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        import re

        if not re.match(_TOOL_NAME_PATTERN, v):
            raise ValueError(
                f"tool name '{v}' must match {_TOOL_NAME_PATTERN} "
                "(letters, digits, underscore, hyphen; dots are not allowed)"
            )
        return v

    def to_anthropic(self) -> dict[str, Any]:
        """Render as an Anthropic Messages API tool definition.

        ``strict`` is a top-level field on the tool — not on ``tool_choice`` —
        and requires ``additionalProperties: false`` plus ``required`` in the
        schema, so it is only emitted when the schema actually satisfies that.
        """
        definition: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }
        schema_is_strict_ready = (
            self.parameters.get("additionalProperties") is False and "required" in self.parameters
        )
        if self.strict and schema_is_strict_ready:
            definition["strict"] = True
        if self.defer_loading:
            definition["defer_loading"] = True
        return definition

    def to_openai(self) -> dict[str, Any]:
        """Render in OpenAI function-calling shape.

        Present so a downstream consumer can adapt; the platform's own LLM
        provider is Anthropic.
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolInvocation(BaseModel):
    """A single request to run a tool."""

    model_config = ConfigDict(extra="forbid")

    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    # Correlates with the model's tool_use block id when driven by an LLM.
    invocation_id: str | None = None
    timeout_seconds: float | None = Field(default=None, gt=0)
    approved: bool | None = Field(
        default=None,
        description="Pre-supplied approval decision for gated tools. None means undecided.",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"
    TIMED_OUT = "timed_out"
    APPROVAL_REQUIRED = "approval_required"


class ToolResult(BaseModel):
    """The outcome of a tool invocation."""

    model_config = ConfigDict(extra="forbid")

    tool: str
    status: ToolStatus
    output: Any = None
    error: dict[str, Any] | None = None
    invocation_id: str | None = None
    duration_ms: float = 0.0
    attempts: int = 1
    started_at: float = Field(default_factory=time.time)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status is ToolStatus.SUCCEEDED

    @property
    def is_error(self) -> bool:
        return not self.ok

    def to_content(self) -> str:
        """Render for a ``tool_result`` content block.

        Errors are rendered as readable text rather than a stack trace so the
        model can adapt its next step instead of parsing internals.
        """
        import json

        if self.ok:
            if isinstance(self.output, str):
                return self.output
            return json.dumps(self.output, default=str, ensure_ascii=False)

        error = self.error or {}
        message = error.get("message", "the tool failed")
        if self.status is ToolStatus.APPROVAL_REQUIRED:
            return f"This action requires human approval before it can run: {message}"
        if self.status is ToolStatus.DENIED:
            return f"Permission denied: {message}"
        return f"Error: {message}"

    def to_anthropic_tool_result(self) -> dict[str, Any]:
        """Render as a ``tool_result`` content block for the Messages API.

        A failed tool must still return a ``tool_result`` (with ``is_error``)
        — dropping it leaves an unmatched ``tool_use`` id and the API rejects
        the follow-up request.
        """
        return {
            "type": "tool_result",
            "tool_use_id": self.invocation_id or "",
            "content": self.to_content(),
            "is_error": self.is_error,
        }


__all__ = [
    "DangerLevel",
    "ToolInvocation",
    "ToolKind",
    "ToolResult",
    "ToolSpec",
    "ToolStatus",
]
