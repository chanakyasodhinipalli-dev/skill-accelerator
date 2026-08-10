"""LLM-assisted workflow planning.

Turns a natural-language goal into a :class:`WorkflowSpec` drafted from the
skills and tools that actually exist. The output is *always* validated before
it is returned, and is never executed automatically — a generated plan is a
proposal for a human to review, which is what keeps this safe.
"""

from __future__ import annotations

from typing import Any

from sa_platform.context import ExecutionContext, current_context
from sa_platform.errors import ValidationError
from sa_platform.logging import get_logger

from .graph import build_graph
from .models import WorkflowSpec

logger = get_logger(__name__)

_PLANNER_SYSTEM = """\
You design workflow definitions for an enterprise orchestration engine.

A workflow is a DAG of steps. Each step names a target from the available \
capabilities and binds its inputs, either to workflow inputs or to an upstream \
step's output.

Rules you must follow:
- Use only the skills and tools listed in the catalogue. Do not invent targets.
- Every value a step reads from elsewhere uses an expression: ${inputs.x} or \
${steps.step_id.output.field}.
- Any step referenced in an expression MUST also appear in that step's \
depends_on list. Steps with no dependency between them run in parallel, so an \
undeclared dependency is a race condition.
- Prefer parallelism: only add a dependency when the data genuinely flows.
- Set on_error to "continue" only for steps whose output later steps do not need.
- For any step that mutates external state, set compensate_with to a step that \
undoes it.

Return only the workflow object matching the provided schema.\
"""

# The shape the model must produce. Constrained deliberately: a narrower schema
# yields plans that validate on the first attempt far more often.
PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "snake_case workflow name"},
        "description": {"type": "string"},
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": ["skill", "tool", "llm", "transform", "noop"],
                    },
                    "target": {"type": ["string", "null"]},
                    "description": {"type": "string"},
                    "inputs": {"type": "object", "additionalProperties": True},
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                    "when": {"type": ["string", "null"]},
                    "prompt": {"type": ["string", "null"]},
                    "on_error": {
                        "type": "string",
                        "enum": ["fail", "continue", "skip_branch"],
                    },
                },
                "required": ["id", "type", "depends_on"],
                "additionalProperties": False,
            },
        },
        "outputs": {"type": "object", "additionalProperties": True},
    },
    "required": ["name", "description", "steps"],
    "additionalProperties": False,
}


class WorkflowPlanner:
    """Drafts workflows from a goal statement."""

    def __init__(
        self,
        *,
        llm_provider: Any | None = None,
        skill_registry: Any | None = None,
        tool_registry: Any | None = None,
    ) -> None:
        self._llm = llm_provider
        self._skills = skill_registry
        self._tools = tool_registry

    def _provider(self) -> Any:
        if self._llm is None:
            from sa_connectors.llm import build_provider

            self._llm = build_provider()
        return self._llm

    def _catalogue(self) -> str:
        """Render the available capabilities for the prompt."""
        from sa_skills.registry import skill_registry as default_skills
        from sa_tools.registry import tool_registry as default_tools

        skills = self._skills if self._skills is not None else default_skills
        tools = self._tools if self._tools is not None else default_tools

        lines: list[str] = ["## Available skills"]
        for manifest in skills.manifests():
            required = ", ".join(manifest.input_schema.get("required", [])) or "none"
            lines.append(
                f"- {manifest.name}: {manifest.description} " f"(required inputs: {required})"
            )
        if len(lines) == 1:
            lines.append("- (none registered)")

        lines.append("")
        lines.append("## Available tools")
        for spec in tools.specs():
            required = ", ".join(spec.parameters.get("required", [])) or "none"
            lines.append(
                f"- {spec.name}: {spec.description} "
                f"(danger: {spec.danger.value}; required args: {required})"
            )
        if lines[-1] == "## Available tools":
            lines.append("- (none registered)")

        return "\n".join(lines)

    async def plan(
        self,
        goal: str,
        *,
        inputs_schema: dict[str, Any] | None = None,
        ctx: ExecutionContext | None = None,
        max_repair_attempts: int = 2,
    ) -> WorkflowSpec:
        """Draft and validate a workflow for ``goal``.

        Validation failures are fed back to the model so it can repair its own
        plan, up to ``max_repair_attempts`` times.
        """
        from sa_connectors.llm.base import Message

        ctx = ctx or current_context()
        provider = self._provider()

        prompt_parts = [
            f"Goal: {goal}",
            "",
            self._catalogue(),
        ]
        if inputs_schema:
            import json

            prompt_parts.extend(
                ["", "## Workflow input schema", json.dumps(inputs_schema, indent=2)]
            )

        messages = [Message.user("\n".join(prompt_parts))]
        last_error: str | None = None

        for attempt in range(max_repair_attempts + 1):
            if last_error:
                messages.append(
                    Message.user(
                        f"That plan failed validation: {last_error}\n"
                        "Return a corrected workflow that fixes exactly this problem."
                    )
                )

            draft = await provider.complete_structured(
                messages, PLAN_SCHEMA, system=_PLANNER_SYSTEM
            )

            try:
                spec = WorkflowSpec(
                    **{
                        **draft,
                        "inputs_schema": inputs_schema or {},
                        "version": "0.1.0",
                    }
                )
                build_graph(spec)  # cycle + binding validation
            except Exception as exc:  # noqa: BLE001 - fed back to the model
                last_error = str(exc)
                logger.info(
                    "generated plan failed validation; requesting a repair",
                    extra={"attempt": attempt + 1, "error": last_error},
                )
                messages.append(Message.assistant(str(draft)))
                continue

            logger.info(
                "generated workflow plan",
                extra={"workflow": spec.name, "steps": len(spec.steps), "attempts": attempt + 1},
            )
            return spec

        raise ValidationError(
            f"the planner could not produce a valid workflow after "
            f"{max_repair_attempts + 1} attempts",
            details={"goal": goal, "last_error": last_error},
        )


__all__ = ["PLAN_SCHEMA", "WorkflowPlanner"]
