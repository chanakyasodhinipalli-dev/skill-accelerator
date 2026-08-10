"""The tool executor.

Applies policy, deadlines, retries, concurrency limits, and audit to every tool
call — including calls originating from an LLM's tool-use blocks. Failures are
returned as :class:`ToolResult` objects rather than raised, because a model
loop must be able to see an error and adapt.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

from sa_platform.config import get_settings
from sa_platform.context import ExecutionContext, current_context
from sa_platform.errors import (
    AcceleratorError,
    ApprovalRequiredError,
    AuthorizationError,
    PolicyViolationError,
    TimeoutError_,
    wrap,
)
from sa_platform.events import Events, event_bus
from sa_platform.logging import get_logger, redact
from sa_platform.resilience import Bulkhead, RetryPolicy, gather_bounded, retry_async, with_timeout
from sa_platform.telemetry import get_tracer, metrics

from .models import ToolInvocation, ToolResult, ToolStatus
from .policy import ToolPolicy
from .registry import ToolRegistry, tool_registry

logger = get_logger(__name__)
tracer = get_tracer("sa.tools")

_AUDIT_REDACT_KEYS = frozenset(
    {"password", "secret", "token", "api_key", "authorization", "credential"}
)


class ToolExecutor:
    """Executes tool invocations under the platform's guarantees."""

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        *,
        policy: ToolPolicy | None = None,
        bulkhead: Bulkhead | None = None,
    ) -> None:
        self._registry = registry if registry is not None else tool_registry
        self._policy = policy or ToolPolicy.from_settings()
        settings = get_settings().tools
        self._bulkhead = bulkhead or Bulkhead("tools", settings.max_concurrency)
        self._default_timeout = settings.default_timeout_seconds
        self._audit_arguments = settings.audit_arguments

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    @property
    def policy(self) -> ToolPolicy:
        return self._policy

    def with_policy(self, policy: ToolPolicy) -> ToolExecutor:
        """Derive an executor with a narrower policy (per-skill or per-agent scope)."""
        return ToolExecutor(self._registry, policy=policy, bulkhead=self._bulkhead)

    # -- single invocation ------------------------------------------------
    async def invoke(
        self,
        tool: str,
        arguments: dict[str, Any] | None = None,
        *,
        ctx: ExecutionContext | None = None,
        invocation_id: str | None = None,
        approved: bool | None = None,
        timeout_seconds: float | None = None,
    ) -> ToolResult:
        return await self.execute(
            ToolInvocation(
                tool=tool,
                arguments=arguments or {},
                invocation_id=invocation_id,
                approved=approved,
                timeout_seconds=timeout_seconds,
            ),
            ctx=ctx,
        )

    async def execute(
        self,
        invocation: ToolInvocation,
        *,
        ctx: ExecutionContext | None = None,
    ) -> ToolResult:
        ctx = ctx or current_context()
        started = time.perf_counter()
        started_at = time.time()

        try:
            instance = self._registry.require(invocation.tool)
        except AcceleratorError as exc:
            return self._failure(invocation, exc, started, started_at, 0)

        spec = instance.spec
        timeout = invocation.timeout_seconds or spec.timeout_seconds or self._default_timeout
        call_ctx = ctx.with_deadline_in(timeout)

        with tracer.span(
            "tool.invoke",
            tool=spec.name,
            kind=spec.kind.value,
            danger=spec.danger.value,
        ) as span:
            # -- governance ---------------------------------------------
            try:
                await self._policy.check(
                    spec, invocation.arguments, call_ctx, preapproved=invocation.approved
                )
            except ApprovalRequiredError as exc:
                span.record_exception(exc)
                metrics.increment("tool.approval_required", tool=spec.name)
                return self._failure(
                    invocation,
                    exc,
                    started,
                    started_at,
                    0,
                    status=ToolStatus.APPROVAL_REQUIRED,
                )
            except (AuthorizationError, PolicyViolationError) as exc:
                span.record_exception(exc)
                metrics.increment("tool.denied", tool=spec.name)
                return self._failure(
                    invocation, exc, started, started_at, 0, status=ToolStatus.DENIED
                )

            await event_bus.emit(
                Events.TOOL_INVOKED,
                tool=spec.name,
                danger=spec.danger.value,
                arguments=(
                    redact(invocation.arguments, _AUDIT_REDACT_KEYS)
                    if self._audit_arguments
                    else None
                ),
                subject=call_ctx.principal.subject,
                correlation_id=call_ctx.correlation_id,
            )

            # -- execution ------------------------------------------------
            attempts = 0

            async def attempt() -> Any:
                nonlocal attempts
                attempts += 1
                validated = await instance.validate_arguments(dict(invocation.arguments))
                if call_ctx.dry_run:
                    return {"dry_run": True, "tool": spec.name, "arguments": validated}
                return await instance.invoke(call_ctx, validated)

            retry_policy = RetryPolicy.from_settings(
                max_attempts=spec.max_retries + 1 if spec.idempotent else 1
            )

            try:
                output = await self._bulkhead.run(
                    lambda: with_timeout(
                        retry_async(attempt, policy=retry_policy, operation=f"tool:{spec.name}"),
                        timeout,
                        operation=f"tool:{spec.name}",
                    )
                )
            except BaseException as exc:  # noqa: BLE001 - normalised into a result
                error = wrap(exc, message=f"tool '{spec.name}' failed: {exc}")
                span.record_exception(error)
                metrics.increment("tool.failed", tool=spec.name)
                logger.warning(
                    "tool failed",
                    extra={
                        "tool": spec.name,
                        "attempts": attempts,
                        "error": error.message,
                        "error_code": error.code.value,
                    },
                )
                await event_bus.emit(
                    Events.TOOL_FAILED,
                    tool=spec.name,
                    error=error.to_dict(),
                    attempts=attempts,
                )
                status = (
                    ToolStatus.TIMED_OUT if isinstance(error, TimeoutError_) else ToolStatus.FAILED
                )
                return self._failure(
                    invocation, error, started, started_at, attempts, status=status
                )

            duration_ms = (time.perf_counter() - started) * 1000
            metrics.increment("tool.succeeded", tool=spec.name)
            metrics.observe("tool.duration_ms", duration_ms, tool=spec.name)
            await event_bus.emit(
                Events.TOOL_COMPLETED,
                tool=spec.name,
                duration_ms=duration_ms,
                attempts=attempts,
            )

            return ToolResult(
                tool=spec.name,
                status=ToolStatus.SUCCEEDED,
                output=output,
                invocation_id=invocation.invocation_id,
                duration_ms=duration_ms,
                attempts=attempts,
                started_at=started_at,
            )

    # -- batch ------------------------------------------------------------
    async def execute_many(
        self,
        invocations: Sequence[ToolInvocation],
        *,
        ctx: ExecutionContext | None = None,
    ) -> list[ToolResult]:
        """Run a batch of invocations, parallelising where it is safe.

        A model turn may contain several ``tool_use`` blocks. Tools flagged
        ``parallel_safe`` run concurrently; the rest are serialised, in the
        order the model requested them, to preserve causality between
        state-mutating calls.
        """
        if not invocations:
            return []

        ctx = ctx or current_context()
        results: dict[int, ToolResult] = {}

        parallel: list[tuple[int, ToolInvocation]] = []
        serial: list[tuple[int, ToolInvocation]] = []

        for index, invocation in enumerate(invocations):
            instance = self._registry.try_get(invocation.tool)
            # Unknown tools go through the normal path so the caller gets a
            # proper not-found result rather than a KeyError.
            if instance is None or instance.spec.parallel_safe:
                parallel.append((index, invocation))
            else:
                serial.append((index, invocation))

        if parallel:
            limit = min(len(parallel), get_settings().tools.max_concurrency)
            completed = await gather_bounded(
                [self.execute(inv, ctx=ctx) for _, inv in parallel],
                limit=limit,
                return_exceptions=True,
            )
            for (index, invocation), outcome in zip(parallel, completed, strict=True):
                results[index] = (
                    outcome
                    if isinstance(outcome, ToolResult)
                    else self._failure(
                        invocation, wrap(outcome), time.perf_counter(), time.time(), 1
                    )
                )

        for index, invocation in serial:
            results[index] = await self.execute(invocation, ctx=ctx)

        return [results[i] for i in range(len(invocations))]

    # -- LLM bridge -------------------------------------------------------
    async def execute_tool_use_blocks(
        self,
        blocks: Sequence[Any],
        *,
        ctx: ExecutionContext | None = None,
        approvals: dict[str, bool] | None = None,
    ) -> list[dict[str, Any]]:
        """Run the ``tool_use`` blocks from a model response.

        Returns ``tool_result`` content blocks in the same order. Every block
        gets exactly one result — including failures, which are returned with
        ``is_error: true`` rather than dropped, because an unmatched
        ``tool_use`` id makes the follow-up request invalid.
        """
        approvals = approvals or {}
        invocations = [
            ToolInvocation(
                tool=self._block_field(block, "name"),
                arguments=self._block_field(block, "input") or {},
                invocation_id=self._block_field(block, "id"),
                approved=approvals.get(self._block_field(block, "id")),
            )
            for block in blocks
        ]
        results = await self.execute_many(invocations, ctx=ctx)
        return [r.to_anthropic_tool_result() for r in results]

    @staticmethod
    def _block_field(block: Any, field: str) -> Any:
        """Read a field from either an SDK block object or a plain dict."""
        if isinstance(block, dict):
            return block.get(field)
        return getattr(block, field, None)

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def _failure(
        invocation: ToolInvocation,
        exc: AcceleratorError,
        started: float,
        started_at: float,
        attempts: int,
        *,
        status: ToolStatus = ToolStatus.FAILED,
    ) -> ToolResult:
        return ToolResult(
            tool=invocation.tool,
            status=status,
            error=exc.to_dict(),
            invocation_id=invocation.invocation_id,
            duration_ms=(time.perf_counter() - started) * 1000,
            attempts=max(attempts, 1),
            started_at=started_at,
        )


tool_executor = ToolExecutor()

__all__ = ["ToolExecutor", "tool_executor"]
