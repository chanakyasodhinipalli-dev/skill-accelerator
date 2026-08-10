"""HTTP error handling.

Translates the platform error taxonomy into RFC 7807-shaped responses so every
failure the service emits has the same envelope, whatever raised it.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from sa_platform.errors import AcceleratorError, ErrorCode
from sa_platform.logging import get_logger
from sa_platform.telemetry import metrics

logger = get_logger(__name__)


def _problem(
    status: int,
    code: str,
    message: str,
    *,
    correlation_id: str | None = None,
    details: dict[str, Any] | None = None,
    retryable: bool = False,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"https://errors.aimed.ai/{code}",
        "title": code.replace("_", " ").title(),
        "status": status,
        "detail": message,
        "code": code,
        "retryable": retryable,
    }
    if correlation_id:
        body["correlation_id"] = correlation_id
    if details:
        body["details"] = details

    headers = {"X-Error-Code": code}
    if correlation_id:
        headers["X-Correlation-Id"] = correlation_id
    # Give clients an explicit backoff hint rather than making them guess.
    if retryable and (retry_after := (details or {}).get("retry_after")):
        headers["Retry-After"] = str(int(float(retry_after)) or 1)

    return JSONResponse(status_code=status, content=body, headers=headers)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AcceleratorError)
    async def handle_platform_error(request: Request, exc: AcceleratorError) -> JSONResponse:
        correlation_id = getattr(request.state, "correlation_id", None)
        metrics.increment("api.errors", code=exc.code.value)

        # 5xx means we broke; log with a stack trace. 4xx is the caller's
        # problem and does not warrant one.
        if exc.http_status >= 500:
            logger.error(
                "request failed",
                exc_info=exc,
                extra={"path": request.url.path, "code": exc.code.value},
            )
        else:
            logger.info(
                "request rejected",
                extra={
                    "path": request.url.path,
                    "code": exc.code.value,
                    # Not "message": `logging` reserves that name on a
                    # LogRecord and raises rather than overwriting it — which
                    # would turn every 4xx into a 500 raised from the handler
                    # that was meant to report it.
                    "reason": exc.message,
                },
            )

        return _problem(
            exc.http_status,
            exc.code.value,
            exc.message,
            correlation_id=correlation_id,
            details=exc.details or None,
            retryable=exc.retryable,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _problem(
            422,
            ErrorCode.VALIDATION.value,
            "the request body or parameters failed validation",
            correlation_id=getattr(request.state, "correlation_id", None),
            details={"errors": exc.errors()},
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {
            401: ErrorCode.AUTHENTICATION,
            403: ErrorCode.AUTHORIZATION,
            404: ErrorCode.NOT_FOUND,
            409: ErrorCode.CONFLICT,
            429: ErrorCode.RATE_LIMITED,
        }.get(exc.status_code, ErrorCode.INTERNAL)
        return _problem(
            exc.status_code,
            code.value,
            str(exc.detail),
            correlation_id=getattr(request.state, "correlation_id", None),
            retryable=exc.status_code in (429, 503),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        correlation_id = getattr(request.state, "correlation_id", None)
        logger.error("unhandled exception", exc_info=exc, extra={"path": request.url.path})
        metrics.increment("api.errors", code="unhandled")
        # Never leak internals to the caller; the correlation id is how support
        # ties the response back to the logged stack trace.
        return _problem(
            500,
            ErrorCode.INTERNAL.value,
            "an internal error occurred",
            correlation_id=correlation_id,
        )


__all__ = ["register_error_handlers"]
