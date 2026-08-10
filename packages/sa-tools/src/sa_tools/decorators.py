"""The ``@tool`` decorator."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from sa_platform.schema import description_from_callable, schema_from_callable

from .base import FunctionTool
from .models import DangerLevel, ToolKind, ToolSpec

F = TypeVar("F", bound=Callable[..., Any])

_PENDING: list[FunctionTool] = []


def tool(
    name: str | None = None,
    *,
    description: str | None = None,
    parameters: dict[str, Any] | None = None,
    returns: dict[str, Any] | None = None,
    danger: DangerLevel | str = DangerLevel.SAFE,
    kind: ToolKind | str = ToolKind.NATIVE,
    tags: list[str] | None = None,
    required_permissions: list[str] | None = None,
    timeout_seconds: float | None = None,
    max_retries: int = 0,
    idempotent: bool = True,
    parallel_safe: bool = True,
    requires_approval: bool = False,
    strict: bool = True,
    defer_loading: bool = False,
    examples: list[dict[str, Any]] | None = None,
    register: bool = True,
) -> Callable[[F], F]:
    """Turn a function into a registered tool.

    The description is the highest-leverage field: state *when* to call the
    tool, not only what it does. Parameter descriptions are lifted from a
    Google-style ``Args:`` block.

    Example::

        @tool(danger="medium", required_permissions=["crm:write"])
        async def create_ticket(subject: str, priority: str = "normal") -> dict:
            '''File a support ticket. Call this when the user asks to open,
            raise, or escalate an issue that needs tracking.

            Args:
                subject: One-line summary of the problem.
                priority: One of low, normal, high.
            '''
            ...
    """

    def decorator(fn: F) -> F:
        spec = ToolSpec(
            name=name or fn.__name__,
            description=description or description_from_callable(fn) or fn.__name__,
            parameters=parameters if parameters is not None else schema_from_callable(fn),
            returns=returns or {},
            kind=ToolKind(kind) if isinstance(kind, str) else kind,
            danger=DangerLevel(danger) if isinstance(danger, str) else danger,
            tags=tags or [],
            required_permissions=required_permissions or [],
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            idempotent=idempotent,
            parallel_safe=parallel_safe,
            requires_approval=requires_approval,
            strict=strict,
            defer_loading=defer_loading,
            examples=examples or [],
        )

        instance = FunctionTool(fn, spec)
        fn.__sa_tool__ = instance  # type: ignore[attr-defined]

        if register:
            _PENDING.append(instance)

        return fn

    return decorator


def drain_pending() -> list[FunctionTool]:
    pending = list(_PENDING)
    _PENDING.clear()
    return pending


__all__ = ["drain_pending", "tool"]
