"""Test harness for skill authors.

Gives every skill a uniform contract test, so a new skill inherits a baseline
of correctness checks without its author writing them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sa_platform.context import ExecutionContext, Principal
from sa_platform.errors import ValidationError
from sa_platform.schema import validate_payload

from .base import Skill
from .models import SkillResult, SkillStatus
from .policy import SkillPolicy
from .registry import SkillRegistry
from .runtime import SkillRuntime


def test_context(
    *,
    permissions: set[str] | None = None,
    tenant_id: str | None = "test-tenant",
    **kwargs: Any,
) -> ExecutionContext:
    """An :class:`ExecutionContext` with full permissions by default."""
    return ExecutionContext(
        principal=Principal(
            subject="test-principal",
            kind="service",
            tenant_id=tenant_id,
            permissions=frozenset(permissions or {"*"}),
        ),
        tenant_id=tenant_id,
        **kwargs,
    )


class SkillHarness:
    """Runs a single skill through the real runtime, in isolation.

    Uses a private registry and a permissive policy so a skill under test is
    unaffected by whatever else the process has registered.
    """

    def __init__(self, skill: Skill, *, policy: SkillPolicy | None = None) -> None:
        self.skill = skill
        self.registry = SkillRegistry()
        self.registry.register(skill)
        self.runtime = SkillRuntime(
            self.registry,
            policy=policy or SkillPolicy(enforce_permissions=False),
        )

    async def invoke(
        self,
        payload: dict[str, Any] | None = None,
        *,
        ctx: ExecutionContext | None = None,
        **kwargs: Any,
    ) -> SkillResult:
        return await self.runtime.invoke(
            self.skill.manifest.name,
            payload or {},
            ctx=ctx or test_context(),
            **kwargs,
        )

    async def expect_success(self, payload: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        result = await self.invoke(payload, **kwargs)
        if not result.ok:
            raise AssertionError(
                f"expected success from '{self.skill.manifest.name}', got "
                f"{result.status.value}: {result.error}"
            )
        return result.output

    async def expect_failure(
        self,
        payload: dict[str, Any] | None = None,
        *,
        code: str | None = None,
        **kwargs: Any,
    ) -> SkillResult:
        result = await self.invoke(payload, **kwargs)
        if result.ok:
            raise AssertionError(f"expected failure from '{self.skill.manifest.name}', got success")
        if code and (result.error or {}).get("code") != code:
            raise AssertionError(
                f"expected error code '{code}', got '{(result.error or {}).get('code')}'"
            )
        return result


@dataclass
class ContractReport:
    """Outcome of :func:`assert_contract`."""

    skill: str
    passed: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures

    def raise_for_failures(self) -> None:
        if self.failures:
            joined = "\n  - ".join(self.failures)
            raise AssertionError(f"skill '{self.skill}' failed its contract:\n  - {joined}")


def assert_manifest_contract(skill: Skill) -> ContractReport:
    """Static checks every skill must satisfy, independent of execution."""
    manifest = skill.manifest
    report = ContractReport(skill=manifest.name)

    def check(condition: bool, label: str, message: str) -> None:
        (report.passed if condition else report.failures).append(
            label if condition else f"{label}: {message}"
        )

    check(
        len(manifest.description) >= 20,
        "description_is_useful",
        "description must be at least 20 characters — it is shown to operators and models",
    )
    check(
        bool(manifest.input_schema),
        "declares_input_schema",
        "input_schema is empty; callers cannot validate payloads",
    )
    check(
        manifest.input_schema.get("type") == "object" if manifest.input_schema else True,
        "input_schema_is_object",
        "input_schema must describe an object",
    )
    check(
        not (manifest.stability.value == "stable" and not manifest.owner),
        "stable_skills_have_owners",
        "a stable skill must declare an owner for incident routing",
    )
    check(
        not (manifest.max_retries > 0 and not manifest.idempotent),
        "retries_imply_idempotence",
        "max_retries > 0 on a non-idempotent skill; retries could duplicate side effects",
    )
    check(
        not (manifest.stability.value == "deprecated" and not manifest.deprecated_reason),
        "deprecation_is_explained",
        "a deprecated skill must set deprecated_reason",
    )
    check(
        not (manifest.cacheable and manifest.cache_ttl_seconds is None),
        "cacheable_declares_ttl",
        "cacheable skills must set cache_ttl_seconds",
    )
    return report


async def assert_contract(
    skill: Skill, *, sample_payload: dict[str, Any] | None = None
) -> ContractReport:
    """Full contract check: manifest rules plus a live invocation.

    ``sample_payload`` is taken from ``manifest.examples[0]["input"]`` when not
    supplied. When neither exists, the execution checks are skipped.
    """
    report = assert_manifest_contract(skill)
    manifest = skill.manifest

    payload = sample_payload
    if payload is None and manifest.examples:
        payload = manifest.examples[0].get("input")

    if payload is None:
        report.passed.append("execution_skipped_no_sample")
        return report

    harness = SkillHarness(skill)
    result = await harness.invoke(payload)

    if result.ok:
        report.passed.append("sample_invocation_succeeds")
        if manifest.output_schema:
            try:
                validate_payload(result.output, manifest.output_schema, label="output")
                report.passed.append("output_matches_schema")
            except ValidationError as exc:
                report.failures.append(f"output_matches_schema: {exc.message}")
    else:
        report.failures.append(f"sample_invocation_succeeds: {result.error}")

    # A skill must reject a payload that violates its own schema.
    if manifest.input_schema.get("required"):
        bad = await harness.invoke({})
        if bad.status in (SkillStatus.FAILED, SkillStatus.DENIED):
            report.passed.append("rejects_invalid_payload")
        else:
            report.failures.append(
                "rejects_invalid_payload: empty payload was accepted despite required fields"
            )

    return report


__all__ = [
    "ContractReport",
    "SkillHarness",
    "assert_contract",
    "assert_manifest_contract",
    "test_context",
]
