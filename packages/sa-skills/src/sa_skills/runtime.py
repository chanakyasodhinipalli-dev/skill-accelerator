"""The skill runtime.

Everything cross-cutting about invoking a skill lives here — policy, schema
validation, deadlines, retries, telemetry, audit events, and error shaping — so
that skill implementations contain only business logic.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from sa_platform.config import get_settings
from sa_platform.context import ExecutionContext, current_context
from sa_platform.errors import (
    AcceleratorError,
    AuthorizationError,
    PolicyViolationError,
    TimeoutError_,
    wrap,
)
from sa_platform.events import Events, event_bus
from sa_platform.logging import get_logger
from sa_platform.resilience import Bulkhead, RetryPolicy, retry_async, with_timeout
from sa_platform.telemetry import get_tracer, metrics

from .models import SkillRequest, SkillResult, SkillStatus
from .policy import SkillPolicy
from .registry import SkillRegistry, skill_registry

logger = get_logger(__name__)
tracer = get_tracer("sa.skills")


class SkillRuntime:
    """Invokes skills with the platform's guarantees applied uniformly."""

    def __init__(
        self,
        registry: SkillRegistry | None = None,
        *,
        policy: SkillPolicy | None = None,
        bulkhead: Bulkhead | None = None,
    ) -> None:
        self._registry = registry if registry is not None else skill_registry
        self._policy = policy or SkillPolicy.from_settings()
        settings = get_settings()
        self._bulkhead = bulkhead or Bulkhead("skills", settings.resilience.max_concurrency)
        self._default_timeout = settings.skills.default_timeout_seconds

    @property
    def registry(self) -> SkillRegistry:
        return self._registry

    # -- public API -------------------------------------------------------
    async def invoke(
        self,
        skill: str,
        payload: dict[str, Any] | None = None,
        *,
        ctx: ExecutionContext | None = None,
        version: str | None = None,
        timeout_seconds: float | None = None,
    ) -> SkillResult:
        """Invoke a skill by name. Never raises for business failures.

        Failures are returned as a :class:`SkillResult` with a non-success
        status; call :meth:`SkillResult.unwrap` to convert one back into an
        exception.
        """
        request = SkillRequest(
            skill=skill,
            version=version,
            payload=payload or {},
            timeout_seconds=timeout_seconds,
        )
        return await self.execute(request, ctx=ctx)

    async def invoke_or_raise(
        self,
        skill: str,
        payload: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Invoke and return the raw output, raising on failure."""
        result = await self.invoke(skill, payload, **kwargs)
        return result.unwrap()

    async def execute(
        self,
        request: SkillRequest,
        *,
        ctx: ExecutionContext | None = None,
    ) -> SkillResult:
        ctx = ctx or current_context()
        started = time.perf_counter()
        started_at = time.time()

        try:
            instance = self._registry.require(request.skill, version=request.version)
        except AcceleratorError as exc:
            return self._failure(request, request.version or "unknown", exc, started, started_at, 0)

        manifest = instance.manifest
        step_ctx = ctx.child(step_id=ctx.step_id or f"skill-{uuid.uuid4().hex[:8]}")

        # Deadline: explicit request > manifest > global default, always clamped
        # to whatever the caller's deadline still allows.
        timeout = request.timeout_seconds or manifest.timeout_seconds or self._default_timeout
        step_ctx = step_ctx.with_deadline_in(timeout)

        with tracer.span(
            "skill.invoke",
            skill=manifest.name,
            skill_version=manifest.version,
            category=manifest.category.value,
        ) as span:
            try:
                self._policy.check(manifest, step_ctx)
            except (AuthorizationError, PolicyViolationError) as exc:
                span.record_exception(exc)
                metrics.increment("skill.denied", skill=manifest.name)
                await event_bus.emit(
                    Events.SKILL_FAILED,
                    skill=manifest.name,
                    reason="policy",
                    error=exc.to_dict(),
                )
                return self._failure(
                    request,
                    manifest.version,
                    exc,
                    started,
                    started_at,
                    0,
                    status=SkillStatus.DENIED,
                )

            await event_bus.emit(
                Events.SKILL_STARTED,
                skill=manifest.name,
                version=manifest.version,
                correlation_id=step_ctx.correlation_id,
            )

            attempts = 0

            async def attempt() -> Any:
                nonlocal attempts
                attempts += 1
                validated = await instance.validate_input(dict(request.payload))
                if request.dry_run or step_ctx.dry_run:
                    # Validation and policy have run; stop before side effects.
                    return {"dry_run": True, "validated_payload": validated}
                output = await instance.run(step_ctx, validated)
                return await instance.validate_output(output)

            retry_policy = RetryPolicy.from_settings(
                max_attempts=manifest.max_retries + 1 if manifest.is_retryable else 1
            )

            try:
                output = await self._bulkhead.run(
                    lambda: with_timeout(
                        retry_async(
                            attempt, policy=retry_policy, operation=f"skill:{manifest.name}"
                        ),
                        timeout,
                        operation=f"skill:{manifest.name}",
                    )
                )
            except BaseException as exc:  # noqa: BLE001 - normalised into a result below
                error = wrap(exc, message=f"skill '{manifest.name}' failed: {exc}")
                span.record_exception(error)
                metrics.increment("skill.failed", skill=manifest.name)
                # A bad payload is the caller's problem, and a stack trace adds
                # nothing: log it at WARNING without one. Reserve ERROR and a
                # traceback for failures inside the skill, which are ours.
                caller_error = error.http_status < 500
                logger.log(
                    logging.WARNING if caller_error else logging.ERROR,
                    "skill failed",
                    exc_info=None if caller_error else exc,
                    extra={
                        "skill": manifest.name,
                        "version": manifest.version,
                        "attempts": attempts,
                        "error": error.message,
                        "error_code": error.code.value,
                    },
                )
                await event_bus.emit(
                    Events.SKILL_FAILED,
                    skill=manifest.name,
                    version=manifest.version,
                    error=error.to_dict(),
                    attempts=attempts,
                )
                status = (
                    SkillStatus.TIMED_OUT
                    if isinstance(error, TimeoutError_)
                    else SkillStatus.FAILED
                )
                return self._failure(
                    request, manifest.version, error, started, started_at, attempts, status=status
                )

            duration_ms = (time.perf_counter() - started) * 1000
            span.set_attribute("attempts", attempts)
            metrics.increment("skill.succeeded", skill=manifest.name)
            metrics.observe("skill.duration_ms", duration_ms, skill=manifest.name)

            await event_bus.emit(
                Events.SKILL_COMPLETED,
                skill=manifest.name,
                version=manifest.version,
                duration_ms=duration_ms,
                attempts=attempts,
            )

            return SkillResult(
                skill=manifest.name,
                version=manifest.version,
                status=SkillStatus.SUCCEEDED,
                output=output,
                started_at=started_at,
                duration_ms=duration_ms,
                attempts=attempts,
                correlation_id=step_ctx.correlation_id,
            )

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def _failure(
        request: SkillRequest,
        version: str,
        exc: AcceleratorError,
        started: float,
        started_at: float,
        attempts: int,
        *,
        status: SkillStatus = SkillStatus.FAILED,
    ) -> SkillResult:
        return SkillResult(
            skill=request.skill,
            version=version,
            status=status,
            error=exc.to_dict(),
            started_at=started_at,
            duration_ms=(time.perf_counter() - started) * 1000,
            attempts=max(attempts, 1),
            correlation_id=current_context().correlation_id,
        )

    async def health(self) -> dict[str, bool]:
        """Poll every registered skill's health hook."""
        report: dict[str, bool] = {}
        for instance in self._registry.all():
            try:
                report[instance.manifest.name] = await instance.health()
            except Exception:  # noqa: BLE001 - a raising probe is an unhealthy probe
                report[instance.manifest.name] = False
        return report


#: Default runtime bound to the process-wide registry.
skill_runtime = SkillRuntime()

__all__ = ["SkillRuntime", "skill_runtime"]
