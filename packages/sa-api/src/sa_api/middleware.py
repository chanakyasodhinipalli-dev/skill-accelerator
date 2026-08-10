"""HTTP middleware: correlation, context binding, and access logging."""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from sa_platform.context import ExecutionContext, bind_context
from sa_platform.logging import get_logger
from sa_platform.telemetry import metrics

logger = get_logger(__name__)

NextCall = Callable[[Request], Awaitable[Response]]


class CorrelationMiddleware(BaseHTTPMiddleware):
    """Assign a correlation id and bind a context for the request's lifetime.

    Binding here (rather than in each route) means every log line, span, and
    outbound call made while handling the request carries the same id without
    the handler doing anything.
    """

    async def dispatch(self, request: Request, call_next: NextCall) -> Response:
        correlation_id = request.headers.get("x-correlation-id") or uuid.uuid4().hex
        request_id = uuid.uuid4().hex

        request.state.correlation_id = correlation_id
        request.state.request_id = request_id

        ctx = ExecutionContext(correlation_id=correlation_id, request_id=request_id)
        with bind_context(ctx):
            response = await call_next(request)

        response.headers["X-Correlation-Id"] = correlation_id
        response.headers["X-Request-Id"] = request_id
        return response


class AccessLogMiddleware(BaseHTTPMiddleware):
    """Structured access logging with latency and status metrics."""

    # Probe endpoints fire constantly and would drown the log.
    QUIET_PATHS = frozenset({"/health/live", "/health/ready", "/metrics"})

    async def dispatch(self, request: Request, call_next: NextCall) -> Response:
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - started) * 1000
            logger.warning(
                "request raised",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round(duration_ms, 2),
                },
            )
            raise

        duration_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Response-Time-Ms"] = f"{duration_ms:.2f}"

        route = request.scope.get("route")
        # Label metrics with the route template, not the concrete path, or the
        # cardinality explodes with one series per id.
        path_label = getattr(route, "path", request.url.path)
        metrics.increment(
            "api.requests", method=request.method, path=path_label, status=response.status_code
        )
        metrics.observe("api.duration_ms", duration_ms, path=path_label)

        if request.url.path not in self.QUIET_PATHS:
            logger.info(
                "request completed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round(duration_ms, 2),
                },
            )
        return response


__all__ = ["AccessLogMiddleware", "CorrelationMiddleware"]
