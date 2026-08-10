"""Resilience primitives: retry, timeout, circuit breaker, bulkhead.

All helpers are async-native and cooperate with
:class:`~sa_platform.context.ExecutionContext` deadlines — a retry will never
push work past the caller's deadline.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Any, TypeVar

from .config import get_settings
from .context import current_context
from .errors import AcceleratorError, CircuitOpenError, RateLimitError, TimeoutError_, wrap
from .logging import get_logger
from .telemetry import metrics

T = TypeVar("T")

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RetryPolicy:
    """Exponential backoff with full jitter.

    Full jitter (``delay = random(0, capped_backoff)``) is used rather than
    equal jitter because it de-synchronises retry storms most effectively when
    many workers fail against the same dependency at once.
    """

    max_attempts: int = 3
    base_delay: float = 0.25
    max_delay: float = 8.0
    multiplier: float = 2.0
    jitter: bool = True
    retry_on: tuple[type[BaseException], ...] = (AcceleratorError,)

    @classmethod
    def from_settings(cls, **overrides: Any) -> RetryPolicy:
        cfg = get_settings().resilience
        params: dict[str, Any] = {
            "max_attempts": cfg.max_retries + 1,
            "base_delay": cfg.retry_base_delay_seconds,
            "max_delay": cfg.retry_max_delay_seconds,
        }
        params.update(overrides)
        return cls(**params)

    def should_retry(self, exc: BaseException, attempt: int) -> bool:
        if attempt >= self.max_attempts:
            return False
        if not isinstance(exc, self.retry_on):
            return False
        # Platform errors self-describe whether another attempt can help.
        if isinstance(exc, AcceleratorError):
            return exc.retryable
        return True

    def delay_for(self, attempt: int, exc: BaseException | None = None) -> float:
        # Honour a server-supplied Retry-After over our own backoff curve.
        if isinstance(exc, RateLimitError) and exc.retry_after is not None:
            return min(exc.retry_after, self.max_delay)
        backoff = min(self.base_delay * (self.multiplier ** (attempt - 1)), self.max_delay)
        return random.uniform(0, backoff) if self.jitter else backoff  # noqa: S311


async def retry_async(
    fn: Callable[[], Awaitable[T]],
    *,
    policy: RetryPolicy | None = None,
    operation: str = "operation",
) -> T:
    """Run ``fn`` under a retry policy, respecting the context deadline."""
    policy = policy or RetryPolicy.from_settings()
    ctx = current_context()
    attempt = 0
    last: BaseException

    while True:
        attempt += 1
        try:
            return await fn()
        except BaseException as exc:  # noqa: BLE001 - re-raised below
            last = exc
            if isinstance(exc, asyncio.CancelledError):
                raise
            if not policy.should_retry(exc, attempt):
                raise

            delay = policy.delay_for(attempt, exc)

            # Never sleep past the caller's deadline — fail fast instead.
            remaining = ctx.remaining
            if remaining is not None and remaining <= delay:
                raise TimeoutError_(
                    f"{operation} exhausted its deadline after {attempt} attempt(s)",
                    details={"operation": operation, "attempts": attempt},
                    cause=exc,
                ) from exc

            metrics.increment("resilience.retry", operation=operation)
            logger.warning(
                "retrying %s after failure",
                operation,
                extra={
                    "operation": operation,
                    "attempt": attempt,
                    "max_attempts": policy.max_attempts,
                    "delay_seconds": round(delay, 3),
                    "error": str(exc),
                },
            )
            await asyncio.sleep(delay)

    raise wrap(last)  # pragma: no cover - unreachable, satisfies type checkers


def with_retry(
    *, policy: RetryPolicy | None = None, operation: str | None = None
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorator form of :func:`retry_async`."""

    def decorator(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        name = operation or getattr(fn, "__qualname__", "operation")

        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            return await retry_async(lambda: fn(*args, **kwargs), policy=policy, operation=name)

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------


async def with_timeout(
    awaitable: Awaitable[T],
    seconds: float | None,
    *,
    operation: str = "operation",
) -> T:
    """Await with a timeout clamped to the context deadline."""
    budget = current_context().budget(seconds)
    if budget is None:
        return await awaitable
    try:
        return await asyncio.wait_for(awaitable, timeout=budget)
    except (TimeoutError, asyncio.TimeoutError) as exc:
        metrics.increment("resilience.timeout", operation=operation)
        raise TimeoutError_(
            f"{operation} timed out after {budget:.1f}s",
            details={"operation": operation, "timeout_seconds": budget},
            cause=exc,
        ) from exc


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    """Per-dependency breaker.

    ``CLOSED`` → ``OPEN`` after ``failure_threshold`` consecutive failures.
    ``OPEN`` → ``HALF_OPEN`` after ``reset_timeout`` seconds, admitting a single
    probe. A successful probe closes the circuit; a failed one re-opens it.
    """

    name: str
    failure_threshold: int = 5
    reset_timeout: float = 30.0
    success_threshold: int = 1

    state: CircuitState = CircuitState.CLOSED
    _failures: int = field(default=0, repr=False)
    _successes: int = field(default=0, repr=False)
    _opened_at: float = field(default=0.0, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    @classmethod
    def from_settings(cls, name: str) -> CircuitBreaker:
        cfg = get_settings().resilience
        return cls(
            name=name,
            failure_threshold=cfg.circuit_failure_threshold,
            reset_timeout=cfg.circuit_reset_seconds,
        )

    async def _before(self) -> None:
        async with self._lock:
            if self.state is CircuitState.OPEN:
                if time.monotonic() - self._opened_at < self.reset_timeout:
                    metrics.increment("resilience.circuit_rejected", circuit=self.name)
                    raise CircuitOpenError(
                        f"circuit '{self.name}' is open",
                        details={
                            "circuit": self.name,
                            "retry_after": round(
                                self.reset_timeout - (time.monotonic() - self._opened_at), 2
                            ),
                        },
                    )
                self.state = CircuitState.HALF_OPEN
                self._successes = 0
                logger.info("circuit half-open", extra={"circuit": self.name})

    async def _on_success(self) -> None:
        async with self._lock:
            if self.state is CircuitState.HALF_OPEN:
                self._successes += 1
                if self._successes >= self.success_threshold:
                    self._close()
            else:
                self._failures = 0

    async def _on_failure(self) -> None:
        async with self._lock:
            self._failures += 1
            if self.state is CircuitState.HALF_OPEN or self._failures >= self.failure_threshold:
                self._open()

    def _open(self) -> None:
        self.state = CircuitState.OPEN
        self._opened_at = time.monotonic()
        metrics.increment("resilience.circuit_opened", circuit=self.name)
        logger.error("circuit opened", extra={"circuit": self.name, "failures": self._failures})

    def _close(self) -> None:
        self.state = CircuitState.CLOSED
        self._failures = 0
        self._successes = 0
        logger.info("circuit closed", extra={"circuit": self.name})

    async def call(self, fn: Callable[[], Awaitable[T]]) -> T:
        await self._before()
        try:
            result = await fn()
        except CircuitOpenError:
            raise
        except BaseException:
            await self._on_failure()
            raise
        else:
            await self._on_success()
            return result

    def reset(self) -> None:
        self._close()


# ---------------------------------------------------------------------------
# Bulkhead
# ---------------------------------------------------------------------------


class Bulkhead:
    """Bound concurrency for a class of work so one dependency cannot starve others."""

    def __init__(self, name: str, limit: int, *, acquire_timeout: float | None = None) -> None:
        self.name = name
        self.limit = limit
        self._semaphore = asyncio.Semaphore(limit)
        self._acquire_timeout = acquire_timeout
        self._in_flight = 0

    @property
    def in_flight(self) -> int:
        return self._in_flight

    async def run(self, fn: Callable[[], Awaitable[T]]) -> T:
        try:
            if self._acquire_timeout is None:
                await self._semaphore.acquire()
            else:
                await asyncio.wait_for(self._semaphore.acquire(), self._acquire_timeout)
        except (TimeoutError, asyncio.TimeoutError) as exc:
            metrics.increment("resilience.bulkhead_rejected", bulkhead=self.name)
            raise TimeoutError_(
                f"bulkhead '{self.name}' saturated ({self.limit} slots)",
                details={"bulkhead": self.name, "limit": self.limit},
                cause=exc,
            ) from exc

        self._in_flight += 1
        metrics.observe("resilience.bulkhead_in_flight", self._in_flight, bulkhead=self.name)
        try:
            return await fn()
        finally:
            self._in_flight -= 1
            self._semaphore.release()


async def gather_bounded(
    awaitables: Iterable[Awaitable[T]],
    *,
    limit: int,
    return_exceptions: bool = False,
) -> list[T]:
    """``asyncio.gather`` with a concurrency ceiling, preserving input order."""
    semaphore = asyncio.Semaphore(limit)

    async def guarded(aw: Awaitable[T]) -> T:
        async with semaphore:
            return await aw

    return await asyncio.gather(
        *(guarded(aw) for aw in awaitables), return_exceptions=return_exceptions
    )  # type: ignore[return-value]


__all__ = [
    "Bulkhead",
    "CircuitBreaker",
    "CircuitState",
    "RetryPolicy",
    "gather_bounded",
    "retry_async",
    "with_retry",
    "with_timeout",
]
