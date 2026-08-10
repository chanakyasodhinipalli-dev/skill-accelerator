"""Shared pytest fixtures.

Every fixture that touches a registry yields an isolated instance, so tests
never depend on discovery order or on what another test registered.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from sa_platform.config import reset_settings
from sa_platform.context import ExecutionContext, Principal, bind_context
from sa_platform.telemetry import metrics


@pytest.fixture(autouse=True)
def _isolate_settings() -> Iterator[None]:
    """Clear the settings cache around every test."""
    reset_settings()
    yield
    reset_settings()


@pytest.fixture(autouse=True)
def _reset_metrics() -> Iterator[None]:
    metrics.reset()
    yield


@pytest.fixture
def principal() -> Principal:
    return Principal(
        subject="test-user",
        kind="service",
        tenant_id="test-tenant",
        permissions=frozenset({"*"}),
    )


@pytest.fixture
def ctx(principal: Principal) -> Iterator[ExecutionContext]:
    context = ExecutionContext(principal=principal, tenant_id="test-tenant")
    with bind_context(context):
        yield context


@pytest.fixture
def restricted_ctx() -> ExecutionContext:
    """A principal holding no permissions — for authorization tests."""
    return ExecutionContext(principal=Principal(subject="restricted", permissions=frozenset()))


@pytest.fixture
def skill_registry() -> Any:
    from sa_skills.registry import SkillRegistry

    return SkillRegistry()


@pytest.fixture
def tool_registry() -> Any:
    from sa_tools.registry import ToolRegistry

    return ToolRegistry()


@pytest.fixture
def skill_runtime(skill_registry: Any) -> Any:
    from sa_skills.policy import SkillPolicy
    from sa_skills.runtime import SkillRuntime

    return SkillRuntime(skill_registry, policy=SkillPolicy(enforce_permissions=False))


@pytest.fixture
def tool_executor(tool_registry: Any) -> Any:
    from sa_tools.executor import ToolExecutor
    from sa_tools.policy import ToolPolicy, allow_all

    return ToolExecutor(
        tool_registry,
        policy=ToolPolicy(enforce_permissions=False, approval_handler=allow_all),
    )


@pytest.fixture
def sample_text() -> str:
    return (
        "The quarterly review covered three areas. Revenue grew twelve percent "
        "year over year, driven mainly by the enterprise segment. Operating costs "
        "rose eight percent, largely from engineering headcount. Management "
        "expects margin expansion in the second half as hiring slows."
    )


@pytest.fixture
def sample_rows() -> list[dict[str, Any]]:
    return [
        {"id": 1, "amount": 120.5, "region": "EMEA", "note": None},
        {"id": 2, "amount": 98.0, "region": "AMER", "note": None},
        {"id": 3, "amount": None, "region": "EMEA", "note": None},
        {"id": 4, "amount": 210.25, "region": "APAC", "note": None},
    ]
