"""The ``@skill`` decorator — the lowest-friction way to author a skill."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from sa_platform.schema import description_from_callable, schema_from_callable

from .base import FunctionSkill
from .models import SkillCategory, SkillManifest, SkillStability

F = TypeVar("F", bound=Callable[..., Any])

# Functions decorated at import time land here; `SkillRegistry.load_decorated()`
# drains this list. This lets a skill module be a plain import with no
# registry object threaded through it.
_PENDING: list[FunctionSkill] = []


def skill(
    name: str | None = None,
    *,
    version: str = "0.1.0",
    description: str | None = None,
    category: SkillCategory | str = SkillCategory.UTILITY,
    stability: SkillStability | str = SkillStability.EXPERIMENTAL,
    owner: str | None = None,
    tags: list[str] | None = None,
    input_schema: dict[str, Any] | None = None,
    output_schema: dict[str, Any] | None = None,
    required_permissions: list[str] | None = None,
    allowed_tools: list[str] | None = None,
    timeout_seconds: float | None = None,
    max_retries: int = 0,
    idempotent: bool = True,
    cacheable: bool = False,
    expose_as_tool: bool = True,
    examples: list[dict[str, Any]] | None = None,
    register: bool = True,
) -> Callable[[F], F]:
    """Turn a function into a registered skill.

    The input schema, description, and name are derived from the function when
    not given explicitly, so the common case is a bare ``@skill()``.

    Example::

        @skill(category="analysis", required_permissions=["skills:analysis:run"])
        async def summarize_document(text: str, max_words: int = 200) -> dict:
            '''Summarize a document into a short abstract.

            Args:
                text: Full document text.
                max_words: Upper bound on the summary length.
            '''
            ...

    The decorated function is returned unchanged, so it remains directly
    callable and unit-testable without the runtime.
    """

    def decorator(fn: F) -> F:
        manifest = SkillManifest(
            name=name or fn.__name__.lower(),
            version=version,
            description=description or description_from_callable(fn) or fn.__name__,
            category=SkillCategory(category) if isinstance(category, str) else category,
            stability=SkillStability(stability) if isinstance(stability, str) else stability,
            owner=owner,
            tags=tags or [],
            input_schema=input_schema if input_schema is not None else schema_from_callable(fn),
            output_schema=output_schema or {},
            required_permissions=required_permissions or [],
            allowed_tools=allowed_tools or [],
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            idempotent=idempotent,
            cacheable=cacheable,
            expose_as_tool=expose_as_tool,
            examples=examples or [],
        )

        instance = FunctionSkill(fn, manifest)
        # Attached so callers can reach the skill from the function object.
        fn.__sa_skill__ = instance  # type: ignore[attr-defined]

        if register:
            _PENDING.append(instance)

        return fn

    return decorator


def drain_pending() -> list[FunctionSkill]:
    """Return and clear skills queued by the decorator at import time."""
    pending = list(_PENDING)
    _PENDING.clear()
    return pending


def peek_pending() -> list[FunctionSkill]:
    return list(_PENDING)


__all__ = ["drain_pending", "peek_pending", "skill"]
