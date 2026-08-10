"""Step routing — resolves a step's declared target to something executable.

This is the seam between the declarative workflow model and the concrete
capability registries. The engine never imports the skill runtime, the tool
executor, or an LLM provider directly; it asks the router.
"""

from __future__ import annotations

from typing import Any

from sa_platform.context import ExecutionContext
from sa_platform.errors import ConfigurationError, ExecutionError, ValidationError
from sa_platform.logging import get_logger

from .expressions import resolve
from .models import StepType, WorkflowStep

logger = get_logger(__name__)


class StepRouter:
    """Executes a single step by dispatching on its type."""

    def __init__(
        self,
        *,
        skill_runtime: Any | None = None,
        tool_executor: Any | None = None,
        llm_provider: Any | None = None,
    ) -> None:
        self._skill_runtime = skill_runtime
        self._tool_executor = tool_executor
        self._llm_provider = llm_provider

    # Registries are resolved lazily so a workflow using only skills does not
    # require an LLM credential, and vice versa.
    def _skills(self) -> Any:
        if self._skill_runtime is None:
            from sa_skills.runtime import skill_runtime

            self._skill_runtime = skill_runtime
        return self._skill_runtime

    def _tools(self) -> Any:
        if self._tool_executor is None:
            from sa_tools.executor import tool_executor

            self._tool_executor = tool_executor
        return self._tool_executor

    def _llm(self) -> Any:
        if self._llm_provider is None:
            from sa_connectors.llm import build_provider

            self._llm_provider = build_provider()
        return self._llm_provider

    async def execute(
        self,
        step: WorkflowStep,
        inputs: dict[str, Any],
        ctx: ExecutionContext,
        scope: dict[str, Any],
    ) -> Any:
        """Run one step and return its output."""
        handler = {
            StepType.SKILL: self._run_skill,
            StepType.TOOL: self._run_tool,
            StepType.LLM: self._run_llm,
            StepType.AGENT: self._run_agent,
            StepType.TRANSFORM: self._run_transform,
            StepType.WAIT: self._run_wait,
            StepType.NOOP: self._run_noop,
        }.get(step.type)

        if handler is None:
            raise ConfigurationError(
                f"step type '{step.type.value}' has no handler",
                details={"step": step.id, "type": step.type.value},
            )
        return await handler(step, inputs, ctx, scope)

    # -- handlers ---------------------------------------------------------
    async def _run_skill(
        self,
        step: WorkflowStep,
        inputs: dict[str, Any],
        ctx: ExecutionContext,
        scope: dict[str, Any],
    ) -> Any:
        assert step.target is not None  # - guaranteed by model validation
        result = await self._skills().invoke(
            step.target, inputs, ctx=ctx, timeout_seconds=step.timeout_seconds
        )
        # unwrap() re-raises with the original error code, so the engine's
        # retry decision stays accurate.
        return result.unwrap()

    async def _run_tool(
        self,
        step: WorkflowStep,
        inputs: dict[str, Any],
        ctx: ExecutionContext,
        scope: dict[str, Any],
    ) -> Any:
        from sa_tools.models import ToolStatus

        assert step.target is not None  # - guaranteed by model validation
        result = await self._tools().invoke(
            step.target, inputs, ctx=ctx, timeout_seconds=step.timeout_seconds
        )
        if result.status is ToolStatus.APPROVAL_REQUIRED:
            from sa_platform.errors import ApprovalRequiredError

            raise ApprovalRequiredError(
                f"step '{step.id}' invokes tool '{step.target}', which requires approval",
                details={"step": step.id, "tool": step.target, **(result.error or {})},
            )
        if not result.ok:
            error = result.error or {}
            raise ExecutionError(
                error.get("message", f"tool '{step.target}' failed"),
                details=error.get("details", {}),
            )
        return result.output

    async def _run_llm(
        self,
        step: WorkflowStep,
        inputs: dict[str, Any],
        ctx: ExecutionContext,
        scope: dict[str, Any],
    ) -> Any:
        from sa_connectors.llm.base import Message

        provider = self._llm()
        prompt = resolve(step.prompt, scope)
        system = resolve(step.system, scope) if step.system else None

        if step.output_schema:
            return await provider.complete_structured(
                [Message.user(str(prompt))], step.output_schema, system=system
            )

        response = await provider.complete([Message.user(str(prompt))], system=system)
        if response.was_refused:
            raise ExecutionError(
                f"the model declined step '{step.id}'",
                details={"step": step.id, "category": response.refusal_category},
            )
        return {
            "text": response.text,
            "usage": response.usage.model_dump(),
            "model": response.model,
        }

    async def _run_agent(
        self,
        step: WorkflowStep,
        inputs: dict[str, Any],
        ctx: ExecutionContext,
        scope: dict[str, Any],
    ) -> Any:
        from sa_connectors.llm.base import Message

        provider = self._llm()
        run_agent = getattr(provider, "run_agent", None)
        if run_agent is None:
            raise ConfigurationError(
                f"the configured LLM provider does not support agent steps (step '{step.id}')"
            )

        prompt = resolve(step.prompt, scope)
        system = resolve(step.system, scope) if step.system else None

        result = await run_agent(
            [Message.user(str(prompt))],
            system=system,
            tool_executor=self._tools(),
            tool_names=step.tools,
            ctx=ctx,
        )
        if result.needs_approval:
            from sa_platform.errors import ApprovalRequiredError

            raise ApprovalRequiredError(
                f"agent step '{step.id}' paused awaiting tool approval",
                details={"step": step.id, "pending": result.pending_approvals},
            )
        return {
            "text": result.text,
            "iterations": result.iterations,
            "usage": result.usage.model_dump(),
            "tool_results": result.tool_results,
        }

    async def _run_transform(
        self,
        step: WorkflowStep,
        inputs: dict[str, Any],
        ctx: ExecutionContext,
        scope: dict[str, Any],
    ) -> Any:
        # `inputs` are already expression-resolved by the engine, so a
        # transform step is just its resolved binding — no I/O, no code.
        return inputs

    async def _run_wait(
        self,
        step: WorkflowStep,
        inputs: dict[str, Any],
        ctx: ExecutionContext,
        scope: dict[str, Any],
    ) -> Any:
        import asyncio

        seconds = float(inputs.get("seconds", 0))
        if seconds < 0:
            raise ValidationError(f"wait step '{step.id}' requires a non-negative duration")
        budget = ctx.budget(seconds)
        await asyncio.sleep(min(seconds, budget) if budget is not None else seconds)
        return {"waited_seconds": seconds}

    async def _run_noop(
        self,
        step: WorkflowStep,
        inputs: dict[str, Any],
        ctx: ExecutionContext,
        scope: dict[str, Any],
    ) -> Any:
        return inputs or {}


__all__ = ["StepRouter"]
