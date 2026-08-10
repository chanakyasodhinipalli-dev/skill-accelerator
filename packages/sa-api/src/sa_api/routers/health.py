"""Health, readiness, and metrics endpoints.

Liveness and readiness are deliberately distinct: liveness answers "should the
orchestrator restart this process", readiness answers "should it receive
traffic". Conflating them causes restart loops when a dependency is briefly
unavailable.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response

from sa_platform.config import get_settings
from sa_platform.health import health_registry
from sa_platform.telemetry import metrics

router = APIRouter(tags=["health"])


@router.get("/health/live", summary="Liveness probe")
async def live() -> dict[str, str]:
    """Always 200 while the process can serve. Never probes dependencies."""
    return {"status": "alive"}


@router.get("/health/ready", summary="Readiness probe")
async def ready(response: Response) -> dict[str, Any]:
    """Aggregate every registered check.

    Non-critical components that are down produce ``degraded`` and still
    return 200 — a missing optional MCP server should not pull the pod out of
    rotation.
    """
    report = await health_registry.run()
    if report["status"] == "unhealthy":
        response.status_code = 503
    return report


@router.get("/health", summary="Service information")
async def info() -> dict[str, Any]:
    settings = get_settings()
    return {
        "service": settings.service_name,
        "version": settings.version,
        "environment": settings.environment,
        "model": settings.llm.model,
    }


@router.get("/metrics", summary="In-process metrics snapshot")
async def metrics_snapshot() -> dict[str, Any]:
    """Return the in-process counters and histograms.

    A debugging and smoke-test surface, not a substitute for a metrics
    backend — configure the OTLP exporter for that.
    """
    return metrics.snapshot().summary()
