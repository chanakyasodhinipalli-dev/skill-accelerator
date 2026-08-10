"""Health check registry backing the liveness and readiness probes."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .logging import get_logger

logger = get_logger(__name__)


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"

    @property
    def rank(self) -> int:
        return {"healthy": 0, "degraded": 1, "unhealthy": 2}[self.value]


@dataclass(slots=True)
class CheckResult:
    status: HealthStatus
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0

    @classmethod
    def healthy(cls, message: str = "ok", **details: Any) -> CheckResult:
        return cls(HealthStatus.HEALTHY, message, details)

    @classmethod
    def degraded(cls, message: str, **details: Any) -> CheckResult:
        return cls(HealthStatus.DEGRADED, message, details)

    @classmethod
    def unhealthy(cls, message: str, **details: Any) -> CheckResult:
        return cls(HealthStatus.UNHEALTHY, message, details)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status.value,
            "duration_ms": round(self.duration_ms, 2),
        }
        if self.message:
            payload["message"] = self.message
        if self.details:
            payload["details"] = self.details
        return payload


#: A check is any callable returning a CheckResult, sync or async. Declared
#: after CheckResult so the alias resolves eagerly at import time.
CheckFn = Callable[[], Awaitable[CheckResult] | CheckResult]


@dataclass(slots=True)
class _Registration:
    name: str
    fn: CheckFn
    critical: bool
    timeout: float


class HealthRegistry:
    """Aggregates component checks into a single readiness verdict.

    Non-critical components can be ``UNHEALTHY`` without failing readiness —
    they downgrade the overall status to ``DEGRADED`` instead. That keeps an
    optional MCP server outage from taking the whole service out of rotation.
    """

    def __init__(self) -> None:
        self._checks: dict[str, _Registration] = {}

    def register(
        self,
        name: str,
        fn: CheckFn,
        *,
        critical: bool = True,
        timeout: float = 5.0,
    ) -> None:
        self._checks[name] = _Registration(name=name, fn=fn, critical=critical, timeout=timeout)

    def unregister(self, name: str) -> None:
        self._checks.pop(name, None)

    def names(self) -> list[str]:
        return sorted(self._checks)

    async def _run_one(self, registration: _Registration) -> CheckResult:
        started = time.perf_counter()
        try:
            outcome = registration.fn()
            result = (
                await asyncio.wait_for(outcome, timeout=registration.timeout)
                if asyncio.iscoroutine(outcome)
                else outcome
            )
        except (TimeoutError, asyncio.TimeoutError):
            result = CheckResult.unhealthy(f"check timed out after {registration.timeout}s")
        except Exception as exc:  # noqa: BLE001 - a failing check is an unhealthy check
            logger.warning(
                "health check raised", extra={"check": registration.name, "error": str(exc)}
            )
            result = CheckResult.unhealthy(f"{type(exc).__name__}: {exc}")
        result.duration_ms = (time.perf_counter() - started) * 1000
        return result

    async def run(self) -> dict[str, Any]:
        """Execute every registered check concurrently."""
        registrations = list(self._checks.values())
        if not registrations:
            return {"status": HealthStatus.HEALTHY.value, "checks": {}}

        results = await asyncio.gather(*(self._run_one(r) for r in registrations))

        overall = HealthStatus.HEALTHY
        checks: dict[str, Any] = {}
        for registration, result in zip(registrations, results, strict=True):
            payload = result.to_dict()
            payload["critical"] = registration.critical
            checks[registration.name] = payload

            effective = result.status
            if not registration.critical and effective is HealthStatus.UNHEALTHY:
                effective = HealthStatus.DEGRADED
            if effective.rank > overall.rank:
                overall = effective

        return {"status": overall.value, "checks": checks}

    async def is_ready(self) -> bool:
        report = await self.run()
        return report["status"] != HealthStatus.UNHEALTHY.value


health_registry = HealthRegistry()

__all__ = ["CheckResult", "HealthRegistry", "HealthStatus", "health_registry"]
