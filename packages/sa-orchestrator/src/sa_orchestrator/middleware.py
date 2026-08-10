"""Step middleware.

A composable pipeline wrapped around every step execution — the extension point
for concerns the engine should not know about (audit sinks, rate limits, PII
scrubbing, cost accounting). Middleware runs outermost-first on the way in and
innermost-first on the way out.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

from sa_platform.context import ExecutionContext
from sa_platform.errors import RateLimitError
from sa_platform.logging import get_logger, redact
from sa_platform.telemetry import metrics

from .models import WorkflowStep

logger = get_logger(__name__)

#: Receives the (already resolved) inputs and returns the step's output.
NextFn = Callable[[dict[str, Any]], Awaitable[Any]]


class Middleware(ABC):
    """Wraps step execution."""

    @abstractmethod
    async def __call__(
        self,
        step: WorkflowStep,
        inputs: dict[str, Any],
        ctx: ExecutionContext,
        call_next: NextFn,
    ) -> Any:
        """Do work, then ``await call_next(inputs)``, then do more work."""


class MiddlewareChain:
    """Composes middleware into a single callable."""

    def __init__(self, middleware: list[Middleware] | None = None) -> None:
        self._middleware = list(middleware or [])

    def add(self, middleware: Middleware) -> MiddlewareChain:
        self._middleware.append(middleware)
        return self

    async def run(
        self,
        step: WorkflowStep,
        inputs: dict[str, Any],
        ctx: ExecutionContext,
        handler: NextFn,
    ) -> Any:
        if not self._middleware:
            return await handler(inputs)

        # Build the chain inside-out so index 0 ends up outermost.
        chain: NextFn = handler
        for middleware in reversed(self._middleware):
            chain = self._bind(middleware, step, ctx, chain)
        return await chain(inputs)

    @staticmethod
    def _bind(
        middleware: Middleware,
        step: WorkflowStep,
        ctx: ExecutionContext,
        call_next: NextFn,
    ) -> NextFn:
        async def invoke(inputs: dict[str, Any]) -> Any:
            return await middleware(step, inputs, ctx, call_next)

        return invoke


class AuditMiddleware(Middleware):
    """Emit a structured audit record for every step, success or failure."""

    def __init__(self, *, log_inputs: bool = True, log_outputs: bool = False) -> None:
        self._log_inputs = log_inputs
        self._log_outputs = log_outputs
        self._redact_keys = frozenset(
            {"password", "secret", "token", "api_key", "authorization", "ssn", "credential"}
        )

    async def __call__(
        self,
        step: WorkflowStep,
        inputs: dict[str, Any],
        ctx: ExecutionContext,
        call_next: NextFn,
    ) -> Any:
        started = time.perf_counter()
        record: dict[str, Any] = {
            "step": step.id,
            "step_type": step.type.value,
            "target": step.target,
            "run_id": ctx.run_id,
            "subject": ctx.principal.subject,
        }
        if self._log_inputs:
            record["inputs"] = redact(inputs, self._redact_keys)

        try:
            output = await call_next(inputs)
        except BaseException as exc:
            record["outcome"] = "failed"
            record["error"] = str(exc)
            record["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
            logger.info("step audit", extra=record)
            raise

        record["outcome"] = "succeeded"
        record["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
        if self._log_outputs:
            record["output"] = redact(output, self._redact_keys)
        logger.info("step audit", extra=record)
        return output


class RateLimitMiddleware(Middleware):
    """Token-bucket rate limit per step target.

    Protects a shared downstream dependency from a wide ``map`` fan-out.
    """

    def __init__(self, *, per_second: float = 10.0, burst: int = 20) -> None:
        self._rate = per_second
        self._burst = burst
        self._tokens: dict[str, float] = {}
        self._last: dict[str, float] = {}

    def _consume(self, key: str) -> bool:
        now = time.monotonic()
        last = self._last.get(key, now)
        tokens = min(
            self._burst, self._tokens.get(key, float(self._burst)) + (now - last) * self._rate
        )
        self._last[key] = now
        if tokens < 1:
            self._tokens[key] = tokens
            return False
        self._tokens[key] = tokens - 1
        return True

    async def __call__(
        self,
        step: WorkflowStep,
        inputs: dict[str, Any],
        ctx: ExecutionContext,
        call_next: NextFn,
    ) -> Any:
        key = step.target or step.id
        if not self._consume(key):
            metrics.increment("workflow.rate_limited", target=key)
            raise RateLimitError(
                f"local rate limit reached for '{key}'",
                retry_after=1.0 / self._rate,
                details={"target": key, "rate_per_second": self._rate},
            )
        return await call_next(inputs)


class DryRunMiddleware(Middleware):
    """Short-circuit side-effecting steps during a dry run.

    Read-only step types still execute so the dry run exercises real bindings
    and surfaces genuine data errors.
    """

    READ_ONLY: ClassVar[set[str]] = {"transform", "noop"}

    async def __call__(
        self,
        step: WorkflowStep,
        inputs: dict[str, Any],
        ctx: ExecutionContext,
        call_next: NextFn,
    ) -> Any:
        if not ctx.dry_run or step.type.value in self.READ_ONLY:
            return await call_next(inputs)
        logger.info("dry run: skipping step", extra={"step": step.id, "target": step.target})
        return {"dry_run": True, "step": step.id, "target": step.target, "inputs": inputs}


__all__ = [
    "AuditMiddleware",
    "DryRunMiddleware",
    "Middleware",
    "MiddlewareChain",
    "NextFn",
    "RateLimitMiddleware",
]
