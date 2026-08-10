"""Error taxonomy shared by every package in the platform.

Every failure that crosses a package boundary is expressed as an
:class:`AcceleratorError`. That gives the API layer a single place to translate
failures into HTTP responses, and gives the orchestrator a single place to
decide whether a step is worth retrying.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    """Stable, machine-readable error identifiers.

    These are part of the platform's public contract — clients branch on them.
    Never renumber or repurpose an existing member; add a new one instead.
    """

    CONFIGURATION = "configuration_error"
    VALIDATION = "validation_error"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    AUTHENTICATION = "authentication_error"
    AUTHORIZATION = "authorization_error"
    POLICY_VIOLATION = "policy_violation"
    APPROVAL_REQUIRED = "approval_required"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    CIRCUIT_OPEN = "circuit_open"
    DEPENDENCY = "dependency_error"
    EXECUTION = "execution_error"
    CANCELLED = "cancelled"
    UNAVAILABLE = "unavailable"
    INTERNAL = "internal_error"


_HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.CONFIGURATION: 500,
    ErrorCode.VALIDATION: 422,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.AUTHENTICATION: 401,
    ErrorCode.AUTHORIZATION: 403,
    ErrorCode.POLICY_VIOLATION: 403,
    ErrorCode.APPROVAL_REQUIRED: 428,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.TIMEOUT: 504,
    ErrorCode.CIRCUIT_OPEN: 503,
    ErrorCode.DEPENDENCY: 502,
    ErrorCode.EXECUTION: 500,
    ErrorCode.CANCELLED: 499,
    ErrorCode.UNAVAILABLE: 503,
    ErrorCode.INTERNAL: 500,
}

# Codes whose failures are transient by nature. The orchestrator and the retry
# helper both consult this set rather than inspecting exception types.
_RETRYABLE: frozenset[ErrorCode] = frozenset(
    {
        ErrorCode.RATE_LIMITED,
        ErrorCode.TIMEOUT,
        ErrorCode.DEPENDENCY,
        ErrorCode.UNAVAILABLE,
    }
)


class AcceleratorError(Exception):
    """Base class for every platform failure."""

    code: ErrorCode = ErrorCode.INTERNAL

    def __init__(
        self,
        message: str,
        *,
        code: ErrorCode | None = None,
        details: dict[str, Any] | None = None,
        retryable: bool | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        self.details: dict[str, Any] = details or {}
        self._retryable = retryable
        if cause is not None:
            self.__cause__ = cause

    @property
    def retryable(self) -> bool:
        if self._retryable is not None:
            return self._retryable
        return self.code in _RETRYABLE

    @property
    def http_status(self) -> int:
        return _HTTP_STATUS.get(self.code, 500)

    def to_dict(self) -> dict[str, Any]:
        """Wire representation. Deliberately excludes tracebacks."""
        payload: dict[str, Any] = {
            "code": self.code.value,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.details:
            payload["details"] = self.details
        return payload

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"{type(self).__name__}(code={self.code.value!r}, message={self.message!r})"


class ConfigurationError(AcceleratorError):
    code = ErrorCode.CONFIGURATION


class ValidationError(AcceleratorError):
    code = ErrorCode.VALIDATION


class NotFoundError(AcceleratorError):
    code = ErrorCode.NOT_FOUND


class ConflictError(AcceleratorError):
    code = ErrorCode.CONFLICT


class AuthenticationError(AcceleratorError):
    code = ErrorCode.AUTHENTICATION


class AuthorizationError(AcceleratorError):
    code = ErrorCode.AUTHORIZATION


class PolicyViolationError(AcceleratorError):
    code = ErrorCode.POLICY_VIOLATION


class ApprovalRequiredError(AcceleratorError):
    """Raised when a tool call is gated behind human approval."""

    code = ErrorCode.APPROVAL_REQUIRED


class RateLimitError(AcceleratorError):
    code = ErrorCode.RATE_LIMITED

    def __init__(self, message: str, *, retry_after: float | None = None, **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        self.retry_after = retry_after
        if retry_after is not None:
            self.details.setdefault("retry_after", retry_after)


class TimeoutError_(AcceleratorError):  # noqa: N801, N818 - avoids shadowing the builtin
    """Platform timeout. Named with a trailing underscore to avoid shadowing the builtin."""

    code = ErrorCode.TIMEOUT


class CircuitOpenError(AcceleratorError):
    code = ErrorCode.CIRCUIT_OPEN


class DependencyError(AcceleratorError):
    """An upstream service (API, MCP server, database) failed."""

    code = ErrorCode.DEPENDENCY


class ExecutionError(AcceleratorError):
    """A skill, tool, or workflow step raised while running."""

    code = ErrorCode.EXECUTION


class CancelledError_(AcceleratorError):  # noqa: N801, N818 - avoids shadowing the builtin
    code = ErrorCode.CANCELLED


class UnavailableError(AcceleratorError):
    code = ErrorCode.UNAVAILABLE


def wrap(exc: BaseException, *, message: str | None = None) -> AcceleratorError:
    """Coerce an arbitrary exception into an :class:`AcceleratorError`.

    Already-typed platform errors pass through untouched so their code and
    retryability survive the round trip.
    """
    if isinstance(exc, AcceleratorError):
        return exc
    if isinstance(exc, TimeoutError):
        return TimeoutError_(message or str(exc) or "operation timed out", cause=exc)
    return ExecutionError(message or f"{type(exc).__name__}: {exc}", cause=exc)


__all__ = [
    "AcceleratorError",
    "ApprovalRequiredError",
    "AuthenticationError",
    "AuthorizationError",
    "CancelledError_",
    "CircuitOpenError",
    "ConfigurationError",
    "ConflictError",
    "DependencyError",
    "ErrorCode",
    "ExecutionError",
    "NotFoundError",
    "PolicyViolationError",
    "RateLimitError",
    "TimeoutError_",
    "UnavailableError",
    "ValidationError",
    "wrap",
]
