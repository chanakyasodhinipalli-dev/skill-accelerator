"""Tests for the skill runtime, tool executor, and the bridge between them."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from sa_platform.context import ExecutionContext, Principal
from sa_platform.errors import AcceleratorError, ErrorCode
from sa_skills import Skill, SkillManifest, SkillStatus, skill
from sa_skills.policy import SkillPolicy
from sa_skills.runtime import SkillRuntime
from sa_skills.testing import assert_manifest_contract
from sa_tools import DangerLevel, ToolPolicy, ToolStatus, tool
from sa_tools.base import FunctionTool, SkillTool
from sa_tools.decorators import drain_pending as drain_tools
from sa_tools.executor import ToolExecutor
from sa_tools.policy import ApprovalDecision, allow_all

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def echo_skill() -> Skill:
    @skill(name="test.echo", description="Echo the payload back for testing.", register=False)
    async def echo(value: str, repeat: int = 1) -> dict:
        """Echo a value.

        Args:
            value: The value to echo.
            repeat: How many times.
        """
        return {"echoed": value * repeat}

    return echo.__sa_skill__  # type: ignore[attr-defined]


@pytest.fixture
def failing_skill() -> Skill:
    @skill(name="test.fail", description="Always fails, for error-path testing.", register=False)
    async def always_fails(reason: str = "expected") -> dict:
        """Raise on purpose.

        Args:
            reason: The failure message.
        """
        raise RuntimeError(reason)

    return always_fails.__sa_skill__  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# skills
# ---------------------------------------------------------------------------


class TestSkillManifest:
    def test_rejects_invalid_names(self) -> None:
        with pytest.raises(ValueError, match="lowercase dotted"):
            SkillManifest(name="Bad Name", description="x" * 25)

    def test_rejects_invalid_versions(self) -> None:
        with pytest.raises(ValueError, match="MAJOR.MINOR.PATCH"):
            SkillManifest(name="a.b", version="1.0", description="x" * 25)

    def test_tool_name_flattens_dots(self) -> None:
        manifest = SkillManifest(name="finance.score", description="x" * 25)
        assert manifest.tool_name() == "skill_finance_score"

    def test_retryable_requires_idempotence(self) -> None:
        manifest = SkillManifest(name="a.b", description="x" * 25, max_retries=3, idempotent=False)
        assert manifest.is_retryable is False


class TestSkillRuntime:
    async def test_successful_invocation(
        self, skill_runtime: SkillRuntime, echo_skill: Skill, ctx: ExecutionContext
    ) -> None:
        skill_runtime.registry.register(echo_skill)
        result = await skill_runtime.invoke("test.echo", {"value": "ab", "repeat": 2}, ctx=ctx)
        assert result.ok
        assert result.output == {"echoed": "abab"}
        assert result.attempts == 1

    async def test_failure_is_returned_not_raised(
        self, skill_runtime: SkillRuntime, failing_skill: Skill, ctx: ExecutionContext
    ) -> None:
        skill_runtime.registry.register(failing_skill)
        result = await skill_runtime.invoke("test.fail", {"reason": "boom"}, ctx=ctx)
        assert result.status is SkillStatus.FAILED
        assert result.error is not None
        assert "boom" in result.error["message"]

    async def test_unwrap_converts_failure_to_exception(
        self, skill_runtime: SkillRuntime, failing_skill: Skill, ctx: ExecutionContext
    ) -> None:
        skill_runtime.registry.register(failing_skill)
        result = await skill_runtime.invoke("test.fail", {}, ctx=ctx)
        with pytest.raises(AcceleratorError):
            result.unwrap()

    async def test_unknown_skill_returns_not_found(
        self, skill_runtime: SkillRuntime, ctx: ExecutionContext
    ) -> None:
        result = await skill_runtime.invoke("does.not.exist", {}, ctx=ctx)
        assert not result.ok
        assert result.error is not None
        assert result.error["code"] == ErrorCode.NOT_FOUND.value

    async def test_input_schema_is_enforced(
        self, skill_runtime: SkillRuntime, echo_skill: Skill, ctx: ExecutionContext
    ) -> None:
        skill_runtime.registry.register(echo_skill)
        result = await skill_runtime.invoke("test.echo", {}, ctx=ctx)  # 'value' is required
        assert not result.ok
        assert result.error is not None
        assert result.error["code"] == ErrorCode.VALIDATION.value

    async def test_permissions_are_enforced(self, skill_registry: Any, echo_skill: Skill) -> None:
        echo_skill.manifest = echo_skill.manifest.model_copy(
            update={"required_permissions": ["skills:test:run"]}
        )
        skill_registry.register(echo_skill)
        runtime = SkillRuntime(skill_registry, policy=SkillPolicy(enforce_permissions=True))

        denied = ExecutionContext(principal=Principal(subject="nobody", permissions=frozenset()))
        result = await runtime.invoke("test.echo", {"value": "x"}, ctx=denied)
        assert result.status is SkillStatus.DENIED

        allowed = ExecutionContext(
            principal=Principal(subject="ops", permissions=frozenset({"skills:test:run"}))
        )
        assert (await runtime.invoke("test.echo", {"value": "x"}, ctx=allowed)).ok

    async def test_dry_run_skips_execution(
        self, skill_runtime: SkillRuntime, failing_skill: Skill, ctx: ExecutionContext
    ) -> None:
        # The skill always raises, so success proves the body never ran.
        skill_runtime.registry.register(failing_skill)
        result = await skill_runtime.invoke("test.fail", {}, ctx=ctx.child(dry_run=True))
        assert result.ok
        assert result.output["dry_run"] is True

    async def test_timeout_produces_timed_out_status(
        self, skill_registry: Any, ctx: ExecutionContext
    ) -> None:
        @skill(name="test.slow", description="Sleeps forever, for timeout testing.", register=False)
        async def slow() -> dict:
            """Sleep."""
            await asyncio.sleep(10)
            return {}

        skill_registry.register(slow.__sa_skill__)  # type: ignore[attr-defined]
        runtime = SkillRuntime(skill_registry, policy=SkillPolicy(enforce_permissions=False))
        result = await runtime.invoke("test.slow", {}, ctx=ctx, timeout_seconds=0.05)
        assert result.status is SkillStatus.TIMED_OUT


class TestSkillContract:
    def test_contract_flags_a_thin_manifest(self, echo_skill: Skill) -> None:
        echo_skill.manifest = echo_skill.manifest.model_copy(update={"description": "short"})
        report = assert_manifest_contract(echo_skill)
        assert not report.ok
        assert any("description" in f for f in report.failures)

    def test_contract_flags_retries_without_idempotence(self, echo_skill: Skill) -> None:
        echo_skill.manifest = echo_skill.manifest.model_copy(
            update={"max_retries": 2, "idempotent": False}
        )
        report = assert_manifest_contract(echo_skill)
        assert any("retries_imply_idempotence" in f for f in report.failures)


# ---------------------------------------------------------------------------
# tools
# ---------------------------------------------------------------------------


class TestToolSpec:
    def test_rejects_dots_in_names(self) -> None:
        from sa_tools.models import ToolSpec

        with pytest.raises(ValueError, match="must match"):
            ToolSpec(name="bad.name", description="x")

    def test_anthropic_rendering_includes_strict_only_when_valid(self) -> None:
        from sa_tools.models import ToolSpec

        strict_ready = ToolSpec(
            name="ok",
            description="x",
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        )
        assert strict_ready.to_anthropic()["strict"] is True

        # additionalProperties is absent, so strict would be rejected by the API.
        not_ready = ToolSpec(
            name="ok2", description="x", parameters={"type": "object", "properties": {}}
        )
        assert "strict" not in not_ready.to_anthropic()


class TestToolExecutor:
    @pytest.fixture
    def adder(self) -> FunctionTool:
        @tool(name="add", description="Add two numbers together.", register=False)
        async def add(a: int, b: int) -> int:
            """Add two numbers.

            Args:
                a: First addend.
                b: Second addend.
            """
            return a + b

        return add.__sa_tool__  # type: ignore[attr-defined]

    async def test_invocation(
        self, tool_executor: ToolExecutor, adder: FunctionTool, ctx: ExecutionContext
    ) -> None:
        tool_executor.registry.register(adder)
        result = await tool_executor.invoke("add", {"a": 2, "b": 3}, ctx=ctx)
        assert result.ok
        assert result.output == 5

    async def test_failure_returns_error_result(
        self, tool_executor: ToolExecutor, ctx: ExecutionContext
    ) -> None:
        result = await tool_executor.invoke("nonexistent", {}, ctx=ctx)
        assert result.status is ToolStatus.FAILED
        assert result.error is not None
        assert result.error["code"] == ErrorCode.NOT_FOUND.value

    async def test_high_danger_tool_defers_to_approval(
        self, tool_registry: Any, ctx: ExecutionContext
    ) -> None:
        @tool(name="delete_all", description="Destroy things.", danger="high", register=False)
        async def destroy() -> dict:
            """Destroy."""
            return {"destroyed": True}

        tool_registry.register(destroy.__sa_tool__)  # type: ignore[attr-defined]
        # Default handler defers, so nothing dangerous runs unattended.
        executor = ToolExecutor(tool_registry, policy=ToolPolicy(enforce_permissions=False))
        result = await executor.invoke("delete_all", {}, ctx=ctx)
        assert result.status is ToolStatus.APPROVAL_REQUIRED

    async def test_preapproval_lets_a_gated_tool_run(
        self, tool_registry: Any, ctx: ExecutionContext
    ) -> None:
        @tool(name="risky", description="Mutates state.", danger="high", register=False)
        async def risky() -> dict:
            """Mutate."""
            return {"ok": True}

        tool_registry.register(risky.__sa_tool__)  # type: ignore[attr-defined]
        executor = ToolExecutor(tool_registry, policy=ToolPolicy(enforce_permissions=False))
        result = await executor.invoke("risky", {}, ctx=ctx, approved=True)
        assert result.ok

    async def test_deny_list_blocks_a_tool(
        self, tool_registry: Any, adder: FunctionTool, ctx: ExecutionContext
    ) -> None:
        tool_registry.register(adder)
        executor = ToolExecutor(
            tool_registry,
            policy=ToolPolicy(deny=["add"], enforce_permissions=False, approval_handler=allow_all),
        )
        result = await executor.invoke("add", {"a": 1, "b": 1}, ctx=ctx)
        assert result.status is ToolStatus.DENIED

    async def test_scope_restricts_to_declared_tools(
        self, tool_registry: Any, adder: FunctionTool, ctx: ExecutionContext
    ) -> None:
        tool_registry.register(adder)
        base = ToolPolicy(enforce_permissions=False, approval_handler=allow_all)
        executor = ToolExecutor(tool_registry, policy=base.scoped_to(["other_tool"]))
        result = await executor.invoke("add", {"a": 1, "b": 1}, ctx=ctx)
        assert result.status is ToolStatus.DENIED

    async def test_batch_preserves_input_order(
        self, tool_executor: ToolExecutor, adder: FunctionTool, ctx: ExecutionContext
    ) -> None:
        from sa_tools.models import ToolInvocation

        tool_executor.registry.register(adder)
        invocations = [
            ToolInvocation(tool="add", arguments={"a": i, "b": 0}, invocation_id=f"t{i}")
            for i in range(5)
        ]
        results = await tool_executor.execute_many(invocations, ctx=ctx)
        assert [r.output for r in results] == [0, 1, 2, 3, 4]
        assert [r.invocation_id for r in results] == ["t0", "t1", "t2", "t3", "t4"]

    async def test_tool_use_blocks_always_get_a_result(
        self, tool_executor: ToolExecutor, adder: FunctionTool, ctx: ExecutionContext
    ) -> None:
        """Every tool_use id must be answered — an unmatched id invalidates the
        follow-up request to the API."""
        tool_executor.registry.register(adder)
        blocks = [
            {"type": "tool_use", "id": "tu_1", "name": "add", "input": {"a": 1, "b": 2}},
            {"type": "tool_use", "id": "tu_2", "name": "missing", "input": {}},
        ]
        results = await tool_executor.execute_tool_use_blocks(blocks, ctx=ctx)
        assert len(results) == 2
        assert {r["tool_use_id"] for r in results} == {"tu_1", "tu_2"}
        assert results[0]["is_error"] is False
        assert results[1]["is_error"] is True


class TestSkillToolBridge:
    async def test_skill_is_callable_as_a_tool(
        self, skill_registry: Any, tool_registry: Any, ctx: ExecutionContext
    ) -> None:
        @skill(name="bridge.test", description="A skill exposed as a tool.", register=False)
        async def bridged(value: str) -> dict:
            """Bridge test.

            Args:
                value: Anything.
            """
            return {"got": value}

        instance = bridged.__sa_skill__  # type: ignore[attr-defined]
        skill_registry.register(instance)
        runtime = SkillRuntime(skill_registry, policy=SkillPolicy(enforce_permissions=False))
        tool_registry.register(SkillTool(instance, runtime))

        executor = ToolExecutor(
            tool_registry,
            policy=ToolPolicy(enforce_permissions=False, approval_handler=allow_all),
        )
        result = await executor.invoke("skill_bridge_test", {"value": "x"}, ctx=ctx)
        assert result.ok
        assert result.output == {"got": "x"}

    def test_bridged_spec_inherits_the_manifest_contract(self, echo_skill: Skill) -> None:
        bridged = SkillTool(echo_skill)
        assert bridged.spec.name == "skill_test_echo"
        assert bridged.spec.parameters == echo_skill.manifest.input_schema
        assert bridged.spec.danger is DangerLevel.SAFE


def test_anthropic_definitions_are_sorted_for_cache_stability(
    tool_registry: Any,
) -> None:
    """Tool order is part of the cached prompt prefix; unstable ordering would
    invalidate the cache on every request."""

    for name in ("zebra", "alpha", "mike"):

        @tool(name=name, description=f"Tool {name}.", register=False)
        async def noop() -> dict:
            """Noop."""
            return {}

        tool_registry.register(noop.__sa_tool__)  # type: ignore[attr-defined]

    drain_tools()  # keep the module-level pending list clean for other tests
    definitions = tool_registry.to_anthropic_tools()
    assert [d["name"] for d in definitions] == sorted(d["name"] for d in definitions)


async def test_approval_handler_can_deny(ctx: ExecutionContext, tool_registry: Any) -> None:
    async def always_deny(spec: Any, arguments: Any, context: Any) -> ApprovalDecision:
        return ApprovalDecision.DENY

    @tool(name="gated", description="Needs approval.", danger="high", register=False)
    async def gated() -> dict:
        """Gated."""
        return {}

    tool_registry.register(gated.__sa_tool__)  # type: ignore[attr-defined]
    executor = ToolExecutor(
        tool_registry,
        policy=ToolPolicy(enforce_permissions=False, approval_handler=always_deny),
    )
    result = await executor.invoke("gated", {}, ctx=ctx)
    assert result.status is ToolStatus.DENIED
