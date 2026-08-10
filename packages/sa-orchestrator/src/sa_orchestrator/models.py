"""Workflow definition and run-state models.

A workflow is a declarative DAG. Steps name a target (a skill, tool, connector
operation, or LLM call) and bind their inputs from workflow inputs or upstream
step outputs via ``${...}`` expressions. Nothing in a workflow definition is
executable code, so definitions are reviewable, diffable, and safe to store.
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StepType(str, Enum):
    SKILL = "skill"  # invoke a registered skill
    TOOL = "tool"  # invoke a registered tool
    LLM = "llm"  # a model call, optionally with tools
    AGENT = "agent"  # an autonomous tool-use loop
    MAP = "map"  # fan out a sub-step over a collection
    TRANSFORM = "transform"  # pure data reshaping, no I/O
    WAIT = "wait"  # delay or external signal
    NOOP = "noop"  # placeholder / join point


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"
    AWAITING_APPROVAL = "awaiting_approval"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    COMPENSATED = "compensated"
    AWAITING_APPROVAL = "awaiting_approval"


class ErrorPolicy(str, Enum):
    """What the engine does when a step fails."""

    FAIL = "fail"  # abort the run (and compensate)
    CONTINUE = "continue"  # record the failure, keep going
    SKIP_BRANCH = "skip_branch"  # mark this step and its dependents skipped


class RetrySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_attempts: int = Field(default=1, ge=1, le=10)
    base_delay_seconds: float = Field(default=0.5, gt=0)
    max_delay_seconds: float = Field(default=30.0, gt=0)


class WorkflowStep(BaseModel):
    """One node in the workflow DAG."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Unique within the workflow; referenced by depends_on")
    type: StepType = StepType.SKILL
    target: str | None = Field(
        default=None, description="Skill name, tool name, or sub-workflow id"
    )
    description: str = ""

    #: Inputs, with ``${...}`` expressions resolved against the run context.
    inputs: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)

    #: Truthiness expression; a falsy result skips the step (and its branch).
    when: str | None = None

    retry: RetrySpec | None = None
    timeout_seconds: float | None = Field(default=None, gt=0)
    on_error: ErrorPolicy = ErrorPolicy.FAIL
    #: Step id to run if this step succeeded but the run later fails (saga).
    compensate_with: str | None = None

    # MAP-specific
    over: str | None = Field(default=None, description="MAP: expression yielding a list")
    as_: str = Field(default="item", alias="as", description="MAP: loop variable name")
    max_parallel: int = Field(default=4, ge=1, description="MAP: concurrency ceiling")

    # LLM/AGENT-specific
    prompt: str | None = None
    system: str | None = None
    tools: list[str] | None = Field(
        default=None, description="Tool allowlist for LLM/AGENT steps; None means all"
    )
    output_schema: dict[str, Any] | None = None

    #: Store the output under this name instead of the step id.
    output_key: str | None = None

    @field_validator("id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        if not v or not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError(f"step id '{v}' must be alphanumeric with - or _")
        return v

    @model_validator(mode="after")
    def _validate_shape(self) -> WorkflowStep:
        if self.type in (StepType.SKILL, StepType.TOOL) and not self.target:
            raise ValueError(f"step '{self.id}' of type '{self.type.value}' requires a target")
        if self.type is StepType.MAP and not self.over:
            raise ValueError(f"map step '{self.id}' requires an 'over' expression")
        if self.type in (StepType.LLM, StepType.AGENT) and not self.prompt:
            raise ValueError(f"step '{self.id}' of type '{self.type.value}' requires a prompt")
        if self.id in self.depends_on:
            raise ValueError(f"step '{self.id}' cannot depend on itself")
        return self

    @property
    def result_key(self) -> str:
        return self.output_key or self.id


class WorkflowSpec(BaseModel):
    """A complete, versioned workflow definition."""

    model_config = ConfigDict(extra="forbid")

    name: str
    version: str = "0.1.0"
    description: str = ""
    owner: str | None = None

    inputs_schema: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(
        default_factory=dict,
        description="Expression map projecting the final run output",
    )
    steps: list[WorkflowStep] = Field(min_length=1)

    timeout_seconds: float | None = Field(default=None, gt=0)
    max_parallel: int = Field(default=8, ge=1)
    required_permissions: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    compensate_on_failure: bool = True

    @model_validator(mode="after")
    def _validate_graph(self) -> WorkflowSpec:
        ids = [s.id for s in self.steps]
        duplicates = {i for i in ids if ids.count(i) > 1}
        if duplicates:
            raise ValueError(f"duplicate step id(s): {', '.join(sorted(duplicates))}")

        known = set(ids)
        for step in self.steps:
            unknown = [d for d in step.depends_on if d not in known]
            if unknown:
                raise ValueError(
                    f"step '{step.id}' depends on unknown step(s): {', '.join(unknown)}"
                )
            if step.compensate_with and step.compensate_with not in known:
                raise ValueError(
                    f"step '{step.id}' names an unknown compensation step "
                    f"'{step.compensate_with}'"
                )
        return self

    @property
    def qualified_name(self) -> str:
        return f"{self.name}@{self.version}"

    def step(self, step_id: str) -> WorkflowStep:
        for step in self.steps:
            if step.id == step_id:
                return step
        raise KeyError(step_id)


class StepResult(BaseModel):
    """Outcome of one step execution."""

    model_config = ConfigDict(extra="forbid")

    step_id: str
    status: StepStatus
    output: Any = None
    error: dict[str, Any] | None = None
    started_at: float | None = None
    duration_ms: float = 0.0
    attempts: int = 0
    skipped_reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is StepStatus.SUCCEEDED


class RunState(BaseModel):
    """The full, checkpointable state of a workflow run.

    Serialisable end to end, so a run can be persisted between steps and
    resumed after a restart or an approval pause.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    workflow: str = ""
    workflow_version: str = ""
    status: RunStatus = RunStatus.PENDING

    inputs: dict[str, Any] = Field(default_factory=dict)
    steps: dict[str, StepResult] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None

    started_at: float = Field(default_factory=time.time)
    completed_at: float | None = None
    correlation_id: str | None = None
    #: Steps that succeeded, newest last — the saga rollback order.
    completed_order: list[str] = Field(default_factory=list)
    pending_approvals: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        end = self.completed_at or time.time()
        return (end - self.started_at) * 1000

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.COMPENSATED,
        )

    def outputs_by_step(self) -> dict[str, Any]:
        """Successful step outputs, keyed for expression resolution."""
        return {sid: r.output for sid, r in self.steps.items() if r.ok}

    def record(self, result: StepResult) -> None:
        self.steps[result.step_id] = result
        if result.ok and result.step_id not in self.completed_order:
            self.completed_order.append(result.step_id)


__all__ = [
    "ErrorPolicy",
    "RetrySpec",
    "RunState",
    "RunStatus",
    "StepResult",
    "StepStatus",
    "StepType",
    "WorkflowSpec",
    "WorkflowStep",
]
