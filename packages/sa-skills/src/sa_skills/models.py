"""Skill contracts.

A *skill* is a versioned, self-describing unit of business capability. The
manifest is the contract: it declares the input/output schema, the permissions
required to run it, and its operational envelope (timeout, retries). Everything
else in the platform — the API, the tool bridge, the orchestrator — reads the
manifest rather than introspecting the implementation.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

_NAME_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$"


class SkillCategory(str, Enum):
    """Coarse grouping used for discovery and access policy."""

    ANALYSIS = "analysis"
    GENERATION = "generation"
    EXTRACTION = "extraction"
    TRANSFORMATION = "transformation"
    VALIDATION = "validation"
    INTEGRATION = "integration"
    ORCHESTRATION = "orchestration"
    UTILITY = "utility"


class SkillStability(str, Enum):
    EXPERIMENTAL = "experimental"
    BETA = "beta"
    STABLE = "stable"
    DEPRECATED = "deprecated"


class SkillManifest(BaseModel):
    """The declarative contract for a skill."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(description="Dotted lowercase identifier, e.g. 'finance.summarize_filing'")
    version: str = Field(default="0.1.0", description="Semantic version of this implementation")
    description: str = Field(
        description="What the skill does. Surfaced to operators and to the model."
    )

    category: SkillCategory = SkillCategory.UTILITY
    stability: SkillStability = SkillStability.EXPERIMENTAL
    owner: str | None = Field(default=None, description="Owning team; used for routing incidents")
    tags: list[str] = Field(default_factory=list)

    input_schema: dict[str, Any] = Field(
        default_factory=dict, description="JSON Schema for the payload"
    )
    output_schema: dict[str, Any] = Field(
        default_factory=dict, description="JSON Schema for the result"
    )

    required_permissions: list[str] = Field(
        default_factory=list,
        description="Permissions the calling principal must hold, e.g. ['skills:finance:read']",
    )
    # Skills declare which tools they may reach for. The tool executor enforces
    # this, so a skill cannot quietly widen its own blast radius.
    allowed_tools: list[str] = Field(default_factory=list)

    timeout_seconds: float | None = Field(default=None, gt=0)
    max_retries: int = Field(default=0, ge=0, le=5)
    idempotent: bool = Field(
        default=True,
        description="False disables automatic retries — the orchestrator will not re-run it.",
    )
    cacheable: bool = False
    cache_ttl_seconds: float | None = Field(default=None, gt=0)

    # Set when this skill should also be exposed as an LLM-callable tool.
    expose_as_tool: bool = True
    examples: list[dict[str, Any]] = Field(default_factory=list)
    documentation_url: str | None = None
    deprecated_reason: str | None = None
    replaced_by: str | None = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        import re

        if not re.match(_NAME_PATTERN, v):
            raise ValueError(
                f"skill name '{v}' must be lowercase dotted snake_case (e.g. 'domain.action')"
            )
        return v

    @field_validator("version")
    @classmethod
    def _validate_version(cls, v: str) -> str:
        head = v.split("-")[0]
        parts = head.split(".")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            raise ValueError(f"version '{v}' must be MAJOR.MINOR.PATCH")
        return v

    @property
    def qualified_name(self) -> str:
        return f"{self.name}@{self.version}"

    @property
    def is_retryable(self) -> bool:
        return self.idempotent and self.max_retries > 0

    def tool_name(self) -> str:
        """Flat identifier used when the skill is surfaced as an LLM tool.

        Dots are illegal in tool names, so `finance.summarize` becomes
        `skill_finance_summarize`.
        """
        return "skill_" + self.name.replace(".", "_")


class SkillStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    TIMED_OUT = "timed_out"
    DENIED = "denied"


class SkillRequest(BaseModel):
    """One invocation of a skill."""

    model_config = ConfigDict(extra="forbid")

    skill: str
    version: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float | None = Field(default=None, gt=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = False


class SkillResult(BaseModel):
    """The outcome of an invocation, successful or not.

    Failures are returned as data, not raised, so a workflow engine can record
    a partial failure and decide what to do rather than unwinding the stack.
    """

    model_config = ConfigDict(extra="forbid")

    skill: str
    version: str
    status: SkillStatus
    output: Any = None
    error: dict[str, Any] | None = None
    started_at: float = Field(default_factory=time.time)
    duration_ms: float = 0.0
    attempts: int = 1
    correlation_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status is SkillStatus.SUCCEEDED

    def unwrap(self) -> Any:
        """Return the output, raising the recorded error when the call failed."""
        if self.ok:
            return self.output
        from sa_platform.errors import AcceleratorError, ErrorCode

        error = self.error or {}
        raise AcceleratorError(
            error.get("message", f"skill '{self.skill}' failed"),
            code=ErrorCode(error.get("code", ErrorCode.EXECUTION.value)),
            details=error.get("details", {}),
        )


__all__ = [
    "SkillCategory",
    "SkillManifest",
    "SkillRequest",
    "SkillResult",
    "SkillStability",
    "SkillStatus",
]
