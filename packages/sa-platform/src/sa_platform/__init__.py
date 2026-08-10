"""sa-platform — cross-cutting foundation for the Skill Accelerator.

Every other package depends on this one; this one depends on nothing internal.
That acyclic rule is what keeps the monorepo composable.

Layers::

    sa_api / sa_cli          entry points
    sa_orchestrator          workflow execution
    sa_skills / sa_tools     capability units and their invocation surface
    sa_connectors            outbound integrations (HTTP, MCP, OpenAPI, LLM)
    sa_platform             <- you are here
"""

from __future__ import annotations

from .config import Settings, get_settings, load_settings, reset_settings
from .context import (
    ExecutionContext,
    Principal,
    bind_context,
    current_context,
    new_context,
)
from .errors import (
    AcceleratorError,
    ApprovalRequiredError,
    AuthenticationError,
    AuthorizationError,
    CircuitOpenError,
    ConfigurationError,
    ConflictError,
    DependencyError,
    ErrorCode,
    ExecutionError,
    NotFoundError,
    PolicyViolationError,
    RateLimitError,
    TimeoutError_,
    UnavailableError,
    ValidationError,
    wrap,
)
from .events import Event, EventBus, Events, event_bus
from .health import CheckResult, HealthStatus, health_registry
from .logging import configure_logging, get_logger
from .registry import Registry
from .resilience import (
    Bulkhead,
    CircuitBreaker,
    RetryPolicy,
    gather_bounded,
    retry_async,
    with_retry,
    with_timeout,
)
from .schema import (
    description_from_callable,
    schema_from_callable,
    validate_payload,
)
from .security import (
    SecretProvider,
    authorize,
    get_secret_provider,
    resolve_secret,
    set_secret_provider,
)
from .telemetry import Span, Tracer, get_tracer, metrics

__version__ = "0.1.0"

__all__ = [
    "AcceleratorError",
    "ApprovalRequiredError",
    "AuthenticationError",
    "AuthorizationError",
    "Bulkhead",
    "CheckResult",
    "CircuitBreaker",
    "CircuitOpenError",
    "ConfigurationError",
    "ConflictError",
    "DependencyError",
    "ErrorCode",
    "Event",
    "EventBus",
    "Events",
    "ExecutionContext",
    "ExecutionError",
    "HealthStatus",
    "NotFoundError",
    "PolicyViolationError",
    "Principal",
    "RateLimitError",
    "Registry",
    "RetryPolicy",
    "SecretProvider",
    "Settings",
    "Span",
    "TimeoutError_",
    "Tracer",
    "UnavailableError",
    "ValidationError",
    "__version__",
    "authorize",
    "bind_context",
    "configure_logging",
    "current_context",
    "description_from_callable",
    "event_bus",
    "gather_bounded",
    "get_logger",
    "get_secret_provider",
    "get_settings",
    "get_tracer",
    "health_registry",
    "load_settings",
    "metrics",
    "new_context",
    "reset_settings",
    "resolve_secret",
    "retry_async",
    "schema_from_callable",
    "set_secret_provider",
    "validate_payload",
    "with_retry",
    "with_timeout",
    "wrap",
]
