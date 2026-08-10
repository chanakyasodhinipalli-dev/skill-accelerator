"""Skill base classes.

Two authoring styles are supported and behave identically at runtime:

* subclass :class:`Skill` when you need lifecycle hooks or injected dependencies
* decorate a function with :func:`~sa_skills.decorators.skill` for simple cases
"""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any

from sa_platform.context import ExecutionContext
from sa_platform.errors import ExecutionError
from sa_platform.schema import (
    description_from_callable,
    schema_from_callable,
    validate_payload,
)

from .models import SkillManifest


class Skill(ABC):
    """Base class for all skills.

    Implementations must expose a :attr:`manifest` and an async :meth:`run`.
    The runtime — not the skill — owns validation, policy, retries, timeouts,
    and telemetry, so implementations stay focused on business logic.
    """

    #: Set by subclasses, or built by the decorator.
    manifest: SkillManifest

    def __init__(self, manifest: SkillManifest | None = None) -> None:
        if manifest is not None:
            self.manifest = manifest
        if not hasattr(self, "manifest"):
            raise ExecutionError(
                f"{type(self).__name__} must define a `manifest` attribute or pass one to __init__"
            )

    # -- contract ---------------------------------------------------------
    @abstractmethod
    async def run(self, ctx: ExecutionContext, payload: dict[str, Any]) -> Any:
        """Execute the skill. Raise on failure; the runtime converts it to a result."""

    # -- lifecycle hooks (optional) ---------------------------------------
    async def on_load(self) -> None:
        """Called once when the skill is registered. Warm caches, open pools."""

    async def on_unload(self) -> None:
        """Called during shutdown. Release resources."""

    async def validate_input(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate and optionally normalise the payload.

        The default enforces ``manifest.input_schema``. Override to coerce
        values, but always return the payload the skill should receive.
        """
        validate_payload(payload, self.manifest.input_schema, label=f"{self.manifest.name} input")
        return payload

    async def validate_output(self, output: Any) -> Any:
        validate_payload(output, self.manifest.output_schema, label=f"{self.manifest.name} output")
        return output

    async def health(self) -> bool:
        """Report whether the skill's dependencies are usable."""
        return True

    # -- helpers ----------------------------------------------------------
    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def version(self) -> str:
        return self.manifest.version

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Skill {self.manifest.qualified_name}>"


class FunctionSkill(Skill):
    """Adapts a plain (async or sync) function into a :class:`Skill`.

    A sync function is executed in the default thread pool so a blocking
    implementation cannot stall the event loop.
    """

    def __init__(self, fn: Callable[..., Any], manifest: SkillManifest) -> None:
        super().__init__(manifest)
        self._fn = fn
        self._is_async = inspect.iscoroutinefunction(fn)
        signature = inspect.signature(fn)
        self._wants_context = any(name in signature.parameters for name in ("ctx", "context"))
        self._context_param = "ctx" if "ctx" in signature.parameters else "context"
        # A single `payload` parameter means "hand me the whole dict"; otherwise
        # the payload keys are mapped onto named parameters.
        self._takes_payload_dict = "payload" in signature.parameters

    async def run(self, ctx: ExecutionContext, payload: dict[str, Any]) -> Any:
        kwargs: dict[str, Any] = {}
        if self._wants_context:
            kwargs[self._context_param] = ctx
        if self._takes_payload_dict:
            kwargs["payload"] = payload
        else:
            kwargs.update(payload)

        if self._is_async:
            return await self._fn(**kwargs)

        import asyncio
        import functools

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, functools.partial(self._fn, **kwargs))

    @classmethod
    def from_function(
        cls,
        fn: Callable[..., Any],
        **manifest_fields: Any,
    ) -> FunctionSkill:
        """Build a skill from a function, deriving anything not supplied."""
        manifest_fields.setdefault("name", fn.__name__.lower())
        manifest_fields.setdefault("description", description_from_callable(fn) or fn.__name__)
        if "input_schema" not in manifest_fields:
            manifest_fields["input_schema"] = schema_from_callable(fn)
        return cls(fn, SkillManifest(**manifest_fields))


CompositeStep = tuple[str, Callable[[Any], dict[str, Any]] | None]


class CompositeSkill(Skill):
    """A skill that sequences other skills.

    Useful for stable, linear macros. Anything with branching, parallelism, or
    compensation belongs in a workflow (``sa_orchestrator``) instead.
    """

    def __init__(
        self,
        manifest: SkillManifest,
        steps: list[CompositeStep],
        invoke: Callable[[str, dict[str, Any], ExecutionContext], Awaitable[Any]],
    ) -> None:
        super().__init__(manifest)
        self._steps = steps
        self._invoke = invoke

    async def run(self, ctx: ExecutionContext, payload: dict[str, Any]) -> Any:
        current: Any = payload
        for skill_name, adapter in self._steps:
            ctx.check_deadline()
            step_payload = adapter(current) if adapter else current
            if not isinstance(step_payload, dict):
                raise ExecutionError(
                    f"composite step '{skill_name}' received a non-dict payload "
                    f"({type(step_payload).__name__}); add an adapter to reshape it"
                )
            current = await self._invoke(skill_name, step_payload, ctx)
        return current


__all__ = ["CompositeSkill", "FunctionSkill", "Skill"]
