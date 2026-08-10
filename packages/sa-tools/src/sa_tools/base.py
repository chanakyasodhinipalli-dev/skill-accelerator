"""Tool base classes and the skill→tool bridge."""

from __future__ import annotations

import asyncio
import functools
import inspect
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from sa_platform.context import ExecutionContext
from sa_platform.errors import ExecutionError
from sa_platform.schema import (
    description_from_callable,
    schema_from_callable,
    validate_payload,
)

from .models import DangerLevel, ToolKind, ToolSpec


class Tool(ABC):
    """Base class for every tool.

    Cross-cutting behaviour (policy, approval, timeout, retry, audit) lives in
    :class:`~sa_tools.executor.ToolExecutor`, not here.
    """

    spec: ToolSpec

    def __init__(self, spec: ToolSpec | None = None) -> None:
        if spec is not None:
            self.spec = spec
        if not hasattr(self, "spec"):
            raise ExecutionError(
                f"{type(self).__name__} must define a `spec` attribute or pass one to __init__"
            )

    @abstractmethod
    async def invoke(self, ctx: ExecutionContext, arguments: dict[str, Any]) -> Any:
        """Execute the tool. Raise on failure."""

    async def validate_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        validate_payload(arguments, self.spec.parameters, label=f"{self.spec.name} arguments")
        return arguments

    async def on_load(self) -> None:
        """Called when the tool is registered."""

    async def on_unload(self) -> None:
        """Called during shutdown."""

    @property
    def name(self) -> str:
        return self.spec.name

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Tool {self.spec.name} ({self.spec.kind.value})>"


class FunctionTool(Tool):
    """Wraps a plain function as a tool.

    Sync functions run in the default executor so they cannot block the loop.
    """

    def __init__(self, fn: Callable[..., Any], spec: ToolSpec) -> None:
        super().__init__(spec)
        self._fn = fn
        self._is_async = inspect.iscoroutinefunction(fn)
        parameters = inspect.signature(fn).parameters
        self._context_param = next((p for p in ("ctx", "context") if p in parameters), None)

    async def invoke(self, ctx: ExecutionContext, arguments: dict[str, Any]) -> Any:
        kwargs = dict(arguments)
        if self._context_param:
            kwargs[self._context_param] = ctx

        if self._is_async:
            return await self._fn(**kwargs)

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, functools.partial(self._fn, **kwargs))

    @classmethod
    def from_function(cls, fn: Callable[..., Any], **spec_fields: Any) -> FunctionTool:
        spec_fields.setdefault("name", fn.__name__)
        spec_fields.setdefault("description", description_from_callable(fn) or fn.__name__)
        spec_fields.setdefault("parameters", schema_from_callable(fn))
        return cls(fn, ToolSpec(**spec_fields))


class SkillTool(Tool):
    """Exposes a registered skill as an LLM-callable tool.

    This is the seam that makes skills usable by a model without skill authors
    knowing anything about tool calling. The skill manifest supplies the schema,
    permissions, and timeout; the danger level is inferred from the skill's
    category and idempotence.
    """

    def __init__(self, skill: Any, runtime: Any | None = None) -> None:
        from sa_skills.runtime import skill_runtime

        manifest = skill.manifest
        super().__init__(
            ToolSpec(
                name=manifest.tool_name(),
                description=self._build_description(manifest),
                parameters=manifest.input_schema
                or {"type": "object", "properties": {}, "additionalProperties": False},
                returns=manifest.output_schema,
                kind=ToolKind.SKILL,
                danger=self._infer_danger(manifest),
                tags=manifest.tags,
                required_permissions=manifest.required_permissions,
                timeout_seconds=manifest.timeout_seconds,
                max_retries=manifest.max_retries,
                idempotent=manifest.idempotent,
                parallel_safe=manifest.idempotent,
                source=f"skill:{manifest.name}",
                examples=manifest.examples,
            )
        )
        self._skill_name = manifest.name
        self._skill_version = manifest.version
        self._runtime = runtime if runtime is not None else skill_runtime

    @staticmethod
    def _build_description(manifest: Any) -> str:
        """Compose a description that tells the model *when* to call, not just what it does."""
        parts = [manifest.description]
        if manifest.tags:
            parts.append(f"Relevant topics: {', '.join(manifest.tags)}.")
        if manifest.stability.value == "deprecated" and manifest.replaced_by:
            parts.append(f"Deprecated — prefer '{manifest.replaced_by}'.")
        return " ".join(parts)

    @staticmethod
    def _infer_danger(manifest: Any) -> DangerLevel:
        if not manifest.idempotent:
            return DangerLevel.HIGH
        if manifest.category.value in ("integration", "orchestration"):
            return DangerLevel.MEDIUM
        if manifest.category.value in ("transformation", "generation"):
            return DangerLevel.LOW
        return DangerLevel.SAFE

    async def invoke(self, ctx: ExecutionContext, arguments: dict[str, Any]) -> Any:
        result = await self._runtime.invoke(
            self._skill_name,
            arguments,
            ctx=ctx,
            version=self._skill_version,
        )
        # Surface the skill's failure as an exception so the executor records
        # it as a failed tool call with the original error code intact.
        return result.unwrap()


__all__ = ["FunctionTool", "SkillTool", "Tool"]
