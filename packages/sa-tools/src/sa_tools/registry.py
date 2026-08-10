"""Tool registry and the Anthropic tool-definition renderer."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any

from sa_platform.errors import NotFoundError
from sa_platform.logging import get_logger
from sa_platform.registry import Registry

from .base import SkillTool, Tool
from .decorators import drain_pending
from .models import DangerLevel, ToolKind, ToolSpec

logger = get_logger(__name__)


class ToolRegistry:
    """The catalogue of callable actions available to models and workflows."""

    def __init__(self) -> None:
        self._registry: Registry[Tool] = Registry("tool")

    # -- registration -----------------------------------------------------
    def register(self, tool: Tool, *, replace: bool = False) -> Tool:
        self._registry.register(tool.spec.name, tool, replace=replace)
        logger.debug(
            "registered tool",
            extra={
                "tool": tool.spec.name,
                "kind": tool.spec.kind.value,
                "danger": tool.spec.danger.value,
            },
        )
        return tool

    def register_many(self, tools: Iterable[Tool], *, replace: bool = False) -> list[Tool]:
        return [self.register(t, replace=replace) for t in tools]

    def register_decorated(self, *, replace: bool = False) -> list[Tool]:
        """Register tools queued by ``@tool`` at import time."""
        return self.register_many(drain_pending(), replace=replace)

    def register_skills(
        self,
        skill_registry: Any | None = None,
        *,
        replace: bool = True,
    ) -> list[Tool]:
        """Expose every tool-eligible skill as a tool.

        Called at startup after skill discovery. ``replace=True`` by default so
        a re-discovery refreshes the bridged specs rather than conflicting.
        """
        from sa_skills.registry import skill_registry as default_registry

        registry = skill_registry if skill_registry is not None else default_registry
        bridged: list[Tool] = []
        for skill in registry.all():
            if not skill.manifest.expose_as_tool:
                continue
            try:
                bridged.append(self.register(SkillTool(skill), replace=replace))
            except Exception as exc:  # noqa: BLE001 - isolate one bad skill
                logger.error(
                    "failed to bridge skill to tool",
                    extra={"skill": skill.manifest.name, "error": str(exc)},
                )

        logger.info("bridged skills to tools", extra={"count": len(bridged)})
        return bridged

    def unregister(self, name: str) -> None:
        self._registry.unregister(name)

    def clear(self) -> None:
        self._registry.clear()

    # -- lookup -----------------------------------------------------------
    def get(self, name: str) -> Tool:
        return self._registry.get(name)

    def try_get(self, name: str) -> Tool | None:
        return self._registry.try_get(name)

    def require(self, name: str) -> Tool:
        found = self.try_get(name)
        if found is None:
            raise NotFoundError(
                f"tool '{name}' is not registered",
                details={"tool": name, "available": self.names()},
            )
        return found

    def __contains__(self, name: object) -> bool:
        return name in self._registry

    def __len__(self) -> int:
        return len(self._registry)

    def __bool__(self) -> bool:
        # An empty registry is still a registry — see Registry.__bool__.
        return True

    # -- enumeration ------------------------------------------------------
    def names(self) -> list[str]:
        return self._registry.names()

    def all(self) -> list[Tool]:
        return self._registry.all()

    def specs(self) -> list[ToolSpec]:
        return [t.spec for t in self.all()]

    def search(
        self,
        *,
        query: str | None = None,
        kind: ToolKind | str | None = None,
        tags: Iterable[str] | None = None,
        max_danger: DangerLevel | str | None = None,
    ) -> list[Tool]:
        wanted_tags = set(tags or ())
        needle = query.lower() if query else None
        ceiling = DangerLevel(max_danger).rank if max_danger is not None else None

        def matches(tool: Tool) -> bool:
            spec = tool.spec
            if kind is not None and spec.kind != ToolKind(kind):
                return False
            if ceiling is not None and spec.danger.rank > ceiling:
                return False
            if wanted_tags and not wanted_tags.issubset(set(spec.tags)):
                return False
            if needle and needle not in f"{spec.name} {spec.description}".lower():
                return False
            return True

        return self._registry.filter(matches)

    # -- provider rendering -----------------------------------------------
    def to_anthropic_tools(
        self,
        *,
        names: Iterable[str] | None = None,
        max_danger: DangerLevel | str | None = None,
        include_server_tools: bool = False,
    ) -> list[dict[str, Any]]:
        """Render the catalogue as an Anthropic ``tools`` array.

        Filtering the surface down to what a given agent actually needs matters:
        a smaller, better-bounded tool set improves selection accuracy and
        costs fewer tokens on every request.
        """
        selected = self.all() if names is None else [self.require(n) for n in names]

        ceiling = DangerLevel(max_danger).rank if max_danger is not None else None
        definitions: list[dict[str, Any]] = []

        for tool in selected:
            spec = tool.spec
            if ceiling is not None and spec.danger.rank > ceiling:
                continue
            if spec.kind is ToolKind.SERVER and not include_server_tools:
                continue
            definitions.append(spec.to_anthropic())

        # Stable ordering keeps the prompt prefix byte-identical across
        # requests, which is what makes prompt caching actually hit.
        definitions.sort(key=lambda d: d["name"])
        return definitions

    # -- lifecycle --------------------------------------------------------
    async def load(self) -> None:
        async def safe(tool: Tool) -> None:
            try:
                await tool.on_load()
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "tool on_load failed", extra={"tool": tool.spec.name, "error": str(exc)}
                )

        await asyncio.gather(*(safe(t) for t in self.all()))

    async def shutdown(self) -> None:
        async def safe(tool: Tool) -> None:
            try:
                await tool.on_unload()
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "tool on_unload failed", extra={"tool": tool.spec.name, "error": str(exc)}
                )

        await asyncio.gather(*(safe(t) for t in self.all()))


tool_registry = ToolRegistry()

__all__ = ["ToolRegistry", "tool_registry"]
