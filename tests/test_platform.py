"""Tests for the platform foundation."""

from __future__ import annotations

import asyncio

import pytest

from sa_platform.context import ExecutionContext, Principal, bind_context, current_context
from sa_platform.errors import (
    AcceleratorError,
    ErrorCode,
    NotFoundError,
    RateLimitError,
    TimeoutError_,
    ValidationError,
    wrap,
)
from sa_platform.registry import Registry
from sa_platform.resilience import (
    Bulkhead,
    CircuitBreaker,
    CircuitState,
    RetryPolicy,
    retry_async,
    with_timeout,
)
from sa_platform.schema import schema_from_callable, validate_payload
from sa_platform.security import authorize, constant_time_compare


class TestErrors:
    def test_error_codes_map_to_http_status(self) -> None:
        assert NotFoundError("x").http_status == 404
        assert ValidationError("x").http_status == 422
        assert RateLimitError("x").http_status == 429

    def test_retryability_follows_the_code(self) -> None:
        assert RateLimitError("x").retryable is True
        assert TimeoutError_("x").retryable is True
        assert ValidationError("x").retryable is False
        assert NotFoundError("x").retryable is False

    def test_explicit_retryable_overrides_the_default(self) -> None:
        assert ValidationError("x", retryable=True).retryable is True

    def test_wrap_preserves_platform_errors(self) -> None:
        original = NotFoundError("missing")
        assert wrap(original) is original

    def test_wrap_converts_foreign_exceptions(self) -> None:
        wrapped = wrap(RuntimeError("boom"))
        assert wrapped.code is ErrorCode.EXECUTION
        assert "boom" in wrapped.message

    def test_wrap_maps_builtin_timeout(self) -> None:
        assert isinstance(wrap(TimeoutError("slow")), TimeoutError_)

    def test_to_dict_excludes_traceback(self) -> None:
        payload = ValidationError("bad", details={"field": "x"}).to_dict()
        assert payload == {
            "code": "validation_error",
            "message": "bad",
            "retryable": False,
            "details": {"field": "x"},
        }


class TestPrincipal:
    def test_exact_permission(self) -> None:
        p = Principal(subject="s", permissions=frozenset({"skills:invoke"}))
        assert p.has_permission("skills:invoke")
        assert not p.has_permission("tools:invoke")

    def test_prefix_wildcard(self) -> None:
        p = Principal(subject="s", permissions=frozenset({"skills:*"}))
        assert p.has_permission("skills:invoke")
        assert not p.has_permission("tools:invoke")

    def test_global_wildcard(self) -> None:
        assert Principal.system().has_permission("anything:at:all")

    def test_missing_permissions_lists_the_gap(self) -> None:
        p = Principal(subject="s", permissions=frozenset({"a"}))
        assert p.missing_permissions(["a", "b", "c"]) == ["b", "c"]

    def test_authorize_raises_with_detail(self) -> None:
        p = Principal(subject="s", permissions=frozenset())
        with pytest.raises(AcceleratorError) as caught:
            authorize(p, ["needed:permission"], resource="thing")
        assert caught.value.details["missing"] == ["needed:permission"]


class TestExecutionContext:
    def test_child_merges_attributes(self) -> None:
        parent = ExecutionContext(attributes={"a": 1})
        child = parent.child(attributes={"b": 2})
        assert child.attributes == {"a": 1, "b": 2}
        assert parent.attributes == {"a": 1}  # parent untouched

    def test_deadline_never_extends(self) -> None:
        tight = ExecutionContext().with_deadline_in(1.0)
        loose = tight.with_deadline_in(100.0)
        assert loose.remaining is not None
        assert loose.remaining <= 1.0

    def test_budget_clamps_to_remaining(self) -> None:
        ctx = ExecutionContext().with_deadline_in(2.0)
        budget = ctx.budget(10.0)
        assert budget is not None and budget <= 2.0

    def test_budget_passes_through_without_a_deadline(self) -> None:
        assert ExecutionContext().budget(5.0) == 5.0

    def test_context_binding_is_scoped(self) -> None:
        outer = current_context()
        inner = ExecutionContext(correlation_id="inner")
        with bind_context(inner):
            assert current_context().correlation_id == "inner"
        assert current_context().correlation_id == outer.correlation_id


class TestRegistry:
    def test_latest_version_wins_numerically(self) -> None:
        registry: Registry[str] = Registry("thing")
        registry.register("a", "v0.9", version="0.9.0")
        registry.register("a", "v0.10", version="0.10.0")
        # 0.10.0 > 0.9.0 numerically, not lexically.
        assert registry.get("a") == "v0.10"

    def test_pinned_version(self) -> None:
        registry: Registry[str] = Registry("thing")
        registry.register("a", "old", version="1.0.0")
        registry.register("a", "new", version="2.0.0")
        assert registry.get("a", version="1.0.0") == "old"

    def test_duplicate_registration_conflicts(self) -> None:
        registry: Registry[str] = Registry("thing")
        registry.register("a", "x", version="1.0.0")
        with pytest.raises(AcceleratorError) as caught:
            registry.register("a", "y", version="1.0.0")
        assert caught.value.code is ErrorCode.CONFLICT

    def test_replace_allows_overwrite(self) -> None:
        registry: Registry[str] = Registry("thing")
        registry.register("a", "x", version="1.0.0")
        registry.register("a", "y", version="1.0.0", replace=True)
        assert registry.get("a") == "y"

    def test_missing_raises_not_found(self) -> None:
        registry: Registry[str] = Registry("thing")
        with pytest.raises(NotFoundError):
            registry.get("nope")


class TestResilience:
    async def test_retries_until_success(self) -> None:
        attempts = 0

        async def flaky() -> str:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise RateLimitError("slow down")
            return "ok"

        result = await retry_async(flaky, policy=RetryPolicy(max_attempts=5, base_delay=0.001))
        assert result == "ok"
        assert attempts == 3

    async def test_does_not_retry_non_retryable_errors(self) -> None:
        attempts = 0

        async def bad_request() -> None:
            nonlocal attempts
            attempts += 1
            raise ValidationError("malformed")

        with pytest.raises(ValidationError):
            await retry_async(bad_request, policy=RetryPolicy(max_attempts=5, base_delay=0.001))
        assert attempts == 1

    async def test_retry_honours_server_retry_after(self) -> None:
        policy = RetryPolicy(max_delay=30.0)
        delay = policy.delay_for(1, RateLimitError("x", retry_after=2.5))
        assert delay == 2.5

    async def test_timeout_raises_platform_error(self) -> None:
        async def slow() -> None:
            await asyncio.sleep(1.0)

        with pytest.raises(TimeoutError_):
            await with_timeout(slow(), 0.01, operation="test")

    async def test_circuit_opens_after_threshold(self) -> None:
        breaker = CircuitBreaker(name="test", failure_threshold=2, reset_timeout=60.0)

        async def failing() -> None:
            raise ValidationError("nope")

        for _ in range(2):
            with pytest.raises(ValidationError):
                await breaker.call(failing)

        assert breaker.state is CircuitState.OPEN
        # Subsequent calls are rejected without touching the dependency.
        with pytest.raises(AcceleratorError) as caught:
            await breaker.call(failing)
        assert caught.value.code is ErrorCode.CIRCUIT_OPEN

    async def test_bulkhead_bounds_concurrency(self) -> None:
        bulkhead = Bulkhead("test", limit=2)
        peak = 0
        active = 0

        async def work() -> None:
            nonlocal peak, active
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1

        await asyncio.gather(*(bulkhead.run(work) for _ in range(10)))
        assert peak <= 2


class TestSchema:
    def test_schema_derived_from_signature(self) -> None:
        def sample(name: str, count: int = 5, ratio: float | None = None) -> dict:
            """Do a thing.

            Args:
                name: The name to use.
                count: How many.
            """
            return {}

        schema = schema_from_callable(sample)
        assert schema["properties"]["name"] == {
            "type": "string",
            "description": "The name to use.",
        }
        assert schema["properties"]["count"]["default"] == 5
        assert schema["required"] == ["name"]
        assert schema["additionalProperties"] is False

    def test_context_parameters_are_excluded(self) -> None:
        def sample(ctx: object, value: str) -> dict:
            return {}

        assert "ctx" not in schema_from_callable(sample)["properties"]

    def test_optional_becomes_nullable(self) -> None:
        def sample(value: str | None = None) -> dict:
            return {}

        assert schema_from_callable(sample)["properties"]["value"]["type"] == [
            "string",
            "null",
        ]

    def test_validation_rejects_missing_required(self) -> None:
        schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
        with pytest.raises(ValidationError):
            validate_payload({}, schema)

    def test_validation_accepts_valid_payload(self) -> None:
        schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
        validate_payload({"a": "x"}, schema)  # must not raise


def test_constant_time_compare() -> None:
    assert constant_time_compare("secret", "secret")
    assert not constant_time_compare("secret", "secrez")
