"""Tests for expressions, graph construction, and the workflow engine."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from sa_orchestrator.engine import OrchestrationEngine
from sa_orchestrator.expressions import (
    build_scope,
    evaluate_condition,
    referenced_steps,
    resolve,
)
from sa_orchestrator.graph import build_graph
from sa_orchestrator.models import RunStatus, StepStatus, WorkflowSpec
from sa_orchestrator.router import StepRouter
from sa_orchestrator.state import InMemoryStateStore
from sa_platform.context import ExecutionContext
from sa_platform.errors import ValidationError
from sa_skills import skill
from sa_skills.policy import SkillPolicy
from sa_skills.runtime import SkillRuntime


class TestExpressions:
    def test_whole_expression_preserves_type(self) -> None:
        scope = build_scope({"n": 42, "d": {"a": 1}}, {})
        assert resolve("${inputs.n}", scope) == 42
        assert resolve("${inputs.d}", scope) == {"a": 1}

    def test_interpolation_renders_to_text(self) -> None:
        scope = build_scope({"name": "Ada"}, {})
        assert resolve("Hello ${inputs.name}!", scope) == "Hello Ada!"

    def test_step_output_lookup(self) -> None:
        scope = build_scope({}, {"fetch": {"email": "a@b.c"}})
        assert resolve("${steps.fetch.output.email}", scope) == "a@b.c"

    def test_missing_path_resolves_to_none(self) -> None:
        assert resolve("${inputs.absent.deeply.nested}", build_scope({}, {})) is None

    def test_list_indexing(self) -> None:
        scope = build_scope({"items": ["a", "b", "c"]}, {})
        assert resolve("${inputs.items.1}", scope) == "b"

    def test_nested_structures_are_resolved(self) -> None:
        scope = build_scope({"x": 1, "y": 2}, {})
        assert resolve({"a": "${inputs.x}", "b": ["${inputs.y}"]}, scope) == {"a": 1, "b": [2]}

    def test_comparisons(self) -> None:
        scope = build_scope({"score": 0.9, "mode": "strict"}, {})
        assert evaluate_condition("${inputs.score > 0.8}", scope) is True
        assert evaluate_condition("${inputs.score > 0.95}", scope) is False
        assert evaluate_condition('${inputs.mode == "strict"}', scope) is True

    def test_boolean_composition(self) -> None:
        scope = build_scope({"a": True, "b": False}, {})
        assert evaluate_condition("${inputs.a and inputs.b}", scope) is False
        assert evaluate_condition("${inputs.a or inputs.b}", scope) is True
        assert evaluate_condition("${not inputs.b}", scope) is True

    def test_absent_condition_means_always_run(self) -> None:
        assert evaluate_condition(None, {}) is True

    def test_expressions_cannot_reach_python_internals(self) -> None:
        """Path lookup only walks dicts and lists — never attributes."""
        scope = build_scope({"x": "text"}, {})
        assert resolve("${inputs.x.__class__}", scope) is None

    def test_referenced_steps_extraction(self) -> None:
        found = referenced_steps({"a": "${steps.one.output.x}", "b": ["${steps.two.output}"]})
        assert found == {"one", "two"}


class TestGraph:
    def _spec(self, steps: list[dict[str, Any]]) -> WorkflowSpec:
        return WorkflowSpec(name="t", description="test", steps=steps)  # type: ignore[arg-type]

    def test_levels_group_independent_steps(self) -> None:
        spec = self._spec(
            [
                {"id": "a", "type": "noop"},
                {"id": "b", "type": "noop"},
                {"id": "c", "type": "noop", "depends_on": ["a", "b"]},
            ]
        )
        graph = build_graph(spec)
        assert graph.levels == [["a", "b"], ["c"]]
        assert graph.max_width == 2

    def test_cycle_is_rejected_with_the_path(self) -> None:
        # Self-dependency is caught by the model; a two-node cycle passes model
        # validation (both ids exist) and must be caught by the graph builder.
        spec = self._spec(
            [
                {"id": "a", "type": "noop", "depends_on": ["b"]},
                {"id": "b", "type": "noop", "depends_on": ["a"]},
            ]
        )
        with pytest.raises(ValidationError, match="cycle"):
            build_graph(spec)

    def test_unknown_dependency_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown step"):
            self._spec([{"id": "a", "type": "noop", "depends_on": ["ghost"]}])

    def test_undeclared_binding_is_rejected(self) -> None:
        """Reading a step's output without depending on it is a race."""
        spec = self._spec(
            [
                {"id": "a", "type": "noop"},
                {"id": "b", "type": "noop", "inputs": {"x": "${steps.a.output}"}},
            ]
        )
        with pytest.raises(ValidationError, match="depends_on"):
            build_graph(spec)

    def test_descendants(self) -> None:
        spec = self._spec(
            [
                {"id": "a", "type": "noop"},
                {"id": "b", "type": "noop", "depends_on": ["a"]},
                {"id": "c", "type": "noop", "depends_on": ["b"]},
                {"id": "d", "type": "noop"},
            ]
        )
        assert build_graph(spec).descendants("a") == {"b", "c"}


@pytest.fixture
def workflow_engine(skill_registry: Any) -> OrchestrationEngine:
    """An engine backed by isolated registries and an in-memory store."""

    @skill(name="test.double", description="Double a number for testing.", register=False)
    async def double(value: int) -> dict:
        """Double a value.

        Args:
            value: The number to double.
        """
        return {"result": value * 2}

    @skill(name="test.boom", description="Always raises, for failure testing.", register=False)
    async def boom() -> dict:
        """Fail."""
        raise RuntimeError("intentional failure")

    @skill(name="test.slow", description="Sleeps, for concurrency testing.", register=False)
    async def slow(seconds: float = 0.05) -> dict:
        """Sleep.

        Args:
            seconds: How long to sleep.
        """
        await asyncio.sleep(seconds)
        return {"slept": seconds}

    for fn in (double, boom, slow):
        skill_registry.register(fn.__sa_skill__)  # type: ignore[attr-defined]

    runtime = SkillRuntime(skill_registry, policy=SkillPolicy(enforce_permissions=False))
    return OrchestrationEngine(
        router=StepRouter(skill_runtime=runtime),
        state_store=InMemoryStateStore(),
    )


class TestEngine:
    async def test_linear_workflow(
        self, workflow_engine: OrchestrationEngine, ctx: ExecutionContext
    ) -> None:
        spec = WorkflowSpec(
            name="linear",
            description="Two chained steps.",
            steps=[
                {
                    "id": "first",
                    "type": "skill",
                    "target": "test.double",
                    "inputs": {"value": "${inputs.n}"},
                },
                {
                    "id": "second",
                    "type": "skill",
                    "target": "test.double",
                    "depends_on": ["first"],
                    "inputs": {"value": "${steps.first.output.result}"},
                },
            ],
            outputs={"total": "${steps.second.output.result}"},
        )
        state = await workflow_engine.run(spec, {"n": 3}, ctx=ctx)
        assert state.status is RunStatus.SUCCEEDED
        assert state.outputs == {"total": 12}

    async def test_independent_steps_run_concurrently(
        self, workflow_engine: OrchestrationEngine, ctx: ExecutionContext
    ) -> None:
        spec = WorkflowSpec(
            name="parallel",
            description="Three independent sleeps.",
            steps=[
                {"id": f"s{i}", "type": "skill", "target": "test.slow", "inputs": {"seconds": 0.1}}
                for i in range(3)
            ],
        )
        started = asyncio.get_running_loop().time()
        state = await workflow_engine.run(spec, {}, ctx=ctx)
        elapsed = asyncio.get_running_loop().time() - started

        assert state.status is RunStatus.SUCCEEDED
        # Serial would be ~0.3s; concurrent should land well under that.
        assert elapsed < 0.25

    async def test_condition_skips_a_step(
        self, workflow_engine: OrchestrationEngine, ctx: ExecutionContext
    ) -> None:
        spec = WorkflowSpec(
            name="conditional",
            description="Skip on a false guard.",
            steps=[
                {"id": "always", "type": "skill", "target": "test.double", "inputs": {"value": 1}},
                {
                    "id": "maybe",
                    "type": "skill",
                    "target": "test.double",
                    "depends_on": ["always"],
                    "when": "${inputs.enabled}",
                    "inputs": {"value": 1},
                },
            ],
        )
        state = await workflow_engine.run(spec, {"enabled": False}, ctx=ctx)
        assert state.status is RunStatus.SUCCEEDED
        assert state.steps["maybe"].status is StepStatus.SKIPPED

    async def test_failure_aborts_the_run_by_default(
        self, workflow_engine: OrchestrationEngine, ctx: ExecutionContext
    ) -> None:
        spec = WorkflowSpec(
            name="failing",
            description="A step that raises.",
            steps=[
                {"id": "explode", "type": "skill", "target": "test.boom"},
                {
                    "id": "after",
                    "type": "skill",
                    "target": "test.double",
                    "depends_on": ["explode"],
                    "inputs": {"value": 1},
                },
            ],
        )
        state = await workflow_engine.run(spec, {}, ctx=ctx)
        assert state.status is RunStatus.FAILED
        assert state.steps["explode"].status is StepStatus.FAILED
        assert "after" not in state.steps  # never scheduled

    async def test_continue_policy_keeps_going(
        self, workflow_engine: OrchestrationEngine, ctx: ExecutionContext
    ) -> None:
        spec = WorkflowSpec(
            name="tolerant",
            description="A non-critical step fails.",
            steps=[
                {"id": "optional", "type": "skill", "target": "test.boom", "on_error": "continue"},
                {
                    "id": "required",
                    "type": "skill",
                    "target": "test.double",
                    "inputs": {"value": 5},
                },
            ],
        )
        state = await workflow_engine.run(spec, {}, ctx=ctx)
        assert state.status is RunStatus.SUCCEEDED
        assert state.steps["optional"].status is StepStatus.FAILED
        assert state.steps["required"].ok

    async def test_dependents_of_a_failed_step_are_skipped(
        self, workflow_engine: OrchestrationEngine, ctx: ExecutionContext
    ) -> None:
        spec = WorkflowSpec(
            name="cascade",
            description="A CONTINUE failure must not silently feed downstream steps.",
            steps=[
                {"id": "bad", "type": "skill", "target": "test.boom", "on_error": "continue"},
                {
                    "id": "downstream",
                    "type": "transform",
                    "depends_on": ["bad"],
                    "inputs": {"x": "${steps.bad.output.result}"},
                },
            ],
        )
        state = await workflow_engine.run(spec, {}, ctx=ctx)
        assert state.steps["downstream"].status is StepStatus.SKIPPED

    async def test_retry_recovers_a_flaky_step(
        self, skill_registry: Any, ctx: ExecutionContext
    ) -> None:
        attempts = 0

        @skill(name="test.flaky", description="Fails twice, then succeeds.", register=False)
        async def flaky() -> dict:
            """Flaky."""
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                from sa_platform.errors import DependencyError

                raise DependencyError("upstream hiccup")
            return {"ok": True}

        skill_registry.register(flaky.__sa_skill__)  # type: ignore[attr-defined]
        engine = OrchestrationEngine(
            router=StepRouter(
                skill_runtime=SkillRuntime(
                    skill_registry, policy=SkillPolicy(enforce_permissions=False)
                )
            ),
            state_store=InMemoryStateStore(),
        )
        spec = WorkflowSpec(
            name="retrying",
            description="Retry a transient failure.",
            steps=[
                {
                    "id": "flaky",
                    "type": "skill",
                    "target": "test.flaky",
                    "retry": {"max_attempts": 4, "base_delay_seconds": 0.01},
                }
            ],
        )
        state = await engine.run(spec, {}, ctx=ctx)
        assert state.status is RunStatus.SUCCEEDED
        assert state.steps["flaky"].attempts == 3

    async def test_run_state_is_checkpointed(
        self, workflow_engine: OrchestrationEngine, ctx: ExecutionContext
    ) -> None:
        spec = WorkflowSpec(
            name="checkpointed",
            description="State survives to the store.",
            steps=[{"id": "s", "type": "skill", "target": "test.double", "inputs": {"value": 2}}],
        )
        state = await workflow_engine.run(spec, {}, ctx=ctx)
        stored = await workflow_engine.state_store.load(state.run_id)
        assert stored.status is RunStatus.SUCCEEDED
        assert stored.steps["s"].output == {"result": 4}

    async def test_dry_run_does_not_execute_side_effects(
        self, workflow_engine: OrchestrationEngine, ctx: ExecutionContext
    ) -> None:
        spec = WorkflowSpec(
            name="dry",
            description="A failing step must not run under dry_run.",
            steps=[{"id": "explode", "type": "skill", "target": "test.boom"}],
        )
        state = await workflow_engine.run(spec, {}, ctx=ctx.child(dry_run=True))
        assert state.status is RunStatus.SUCCEEDED

    async def test_input_schema_is_enforced(
        self, workflow_engine: OrchestrationEngine, ctx: ExecutionContext
    ) -> None:
        spec = WorkflowSpec(
            name="strict_inputs",
            description="Reject a bad payload before running anything.",
            inputs_schema={
                "type": "object",
                "properties": {"n": {"type": "integer"}},
                "required": ["n"],
            },
            steps=[{"id": "s", "type": "noop"}],
        )
        with pytest.raises(ValidationError):
            await workflow_engine.run(spec, {}, ctx=ctx)
