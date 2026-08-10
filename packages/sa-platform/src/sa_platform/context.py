"""Ambient execution context propagated through every layer.

The context carries identity, tenancy, and correlation across skill, tool,
connector, and orchestration boundaries without threading parameters through
every signature. It is stored in a :mod:`contextvars` variable so it survives
``await`` boundaries and is isolated per-task.
"""

from __future__ import annotations

import contextvars
import time
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from typing import Any

from .errors import TimeoutError_


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated actor on whose behalf work is performed."""

    subject: str
    kind: str = "user"  # user | service | system
    tenant_id: str | None = None
    roles: frozenset[str] = field(default_factory=frozenset)
    permissions: frozenset[str] = field(default_factory=frozenset)
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def has_permission(self, permission: str) -> bool:
        """Check a permission, honouring ``*`` and ``prefix:*`` wildcards."""
        if "*" in self.permissions or permission in self.permissions:
            return True
        # `skills:*` grants `skills:invoke`
        head, _, _ = permission.partition(":")
        return f"{head}:*" in self.permissions

    def missing_permissions(self, required: Sequence[str]) -> list[str]:
        return [p for p in required if not self.has_permission(p)]

    @classmethod
    def system(cls) -> Principal:
        """The in-process identity used for background and bootstrap work."""
        return cls(subject="system", kind="system", permissions=frozenset({"*"}))

    @classmethod
    def anonymous(cls) -> Principal:
        return cls(subject="anonymous", kind="user", permissions=frozenset())


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """Immutable per-request context.

    Mutating helpers return a copy, so a child step can add attributes without
    affecting its siblings.
    """

    correlation_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    principal: Principal = field(default_factory=Principal.anonymous)
    tenant_id: str | None = None
    request_id: str | None = None
    run_id: str | None = None
    step_id: str | None = None
    deadline: float | None = None  # monotonic clock reading
    attributes: Mapping[str, Any] = field(default_factory=dict)
    dry_run: bool = False

    # -- derivation -------------------------------------------------------
    def child(self, **overrides: Any) -> ExecutionContext:
        """Derive a context for a nested unit of work."""
        attributes = overrides.pop("attributes", None)
        if attributes is not None:
            overrides["attributes"] = {**self.attributes, **attributes}
        return replace(self, **overrides)

    def with_deadline_in(self, seconds: float) -> ExecutionContext:
        """Set a deadline, never extending one that is already tighter."""
        candidate = time.monotonic() + seconds
        if self.deadline is not None:
            candidate = min(candidate, self.deadline)
        return replace(self, deadline=candidate)

    # -- deadline ---------------------------------------------------------
    @property
    def remaining(self) -> float | None:
        """Seconds left before the deadline, or ``None`` when unbounded."""
        if self.deadline is None:
            return None
        return self.deadline - time.monotonic()

    def check_deadline(self) -> None:
        """Raise if the context's deadline has already passed."""
        remaining = self.remaining
        if remaining is not None and remaining <= 0:
            raise TimeoutError_(
                "execution deadline exceeded",
                details={"correlation_id": self.correlation_id},
            )

    def budget(self, requested: float | None) -> float | None:
        """Clamp a requested timeout to whatever the deadline still allows."""
        remaining = self.remaining
        if remaining is None:
            return requested
        if remaining <= 0:
            self.check_deadline()
        return remaining if requested is None else min(requested, remaining)

    # -- logging ----------------------------------------------------------
    def log_fields(self) -> dict[str, Any]:
        fields: dict[str, Any] = {
            "correlation_id": self.correlation_id,
            "principal": self.principal.subject,
        }
        for key in ("tenant_id", "request_id", "run_id", "step_id"):
            value = getattr(self, key)
            if value:
                fields[key] = value
        return fields


_current: contextvars.ContextVar[ExecutionContext] = contextvars.ContextVar("sa_execution_context")


def current_context() -> ExecutionContext:
    """Return the active context, creating an anonymous one on first access."""
    try:
        return _current.get()
    except LookupError:
        ctx = ExecutionContext()
        _current.set(ctx)
        return ctx


def set_context(ctx: ExecutionContext) -> contextvars.Token[ExecutionContext]:
    return _current.set(ctx)


def reset_context(token: contextvars.Token[ExecutionContext]) -> None:
    _current.reset(token)


@contextmanager
def bind_context(ctx: ExecutionContext) -> Iterator[ExecutionContext]:
    """Scope a context to a block, restoring the previous one on exit."""
    token = _current.set(ctx)
    try:
        yield ctx
    finally:
        _current.reset(token)


@contextmanager
def new_context(**kwargs: Any) -> Iterator[ExecutionContext]:
    """Create and bind a fresh context in one step."""
    with bind_context(ExecutionContext(**kwargs)) as ctx:
        yield ctx


__all__ = [
    "ExecutionContext",
    "Principal",
    "bind_context",
    "current_context",
    "new_context",
    "reset_context",
    "set_context",
]
