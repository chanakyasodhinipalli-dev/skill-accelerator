"""Introspection tools.

These let an agent discover the platform's own capabilities at runtime instead
of carrying every schema in its context window — the same idea as tool search,
scoped to this catalogue.
"""

from __future__ import annotations

from typing import Any

from sa_platform.context import ExecutionContext

from ..base import Tool
from ..models import DangerLevel, ToolSpec


class ListToolsTool(Tool):
    """Enumerate the tools available to the caller."""

    def __init__(self, registry: Any | None = None) -> None:
        self._registry = registry
        super().__init__(
            ToolSpec(
                name="list_tools",
                description=(
                    "List the tools currently available, with a one-line description of each. "
                    "Call this when you are unsure whether a capability exists before "
                    "concluding a task cannot be done."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Filter by substring match on name or description.",
                        },
                        "tag": {"type": "string", "description": "Filter by tag."},
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                danger=DangerLevel.SAFE,
                tags=["introspection"],
            )
        )

    def _resolve_registry(self) -> Any:
        if self._registry is not None:
            return self._registry
        from ..registry import tool_registry

        return tool_registry

    async def invoke(self, ctx: ExecutionContext, arguments: dict[str, Any]) -> Any:
        registry = self._resolve_registry()
        tag = arguments.get("tag")
        found = registry.search(
            query=arguments.get("query"),
            tags=[tag] if tag else None,
        )
        return {
            "count": len(found),
            "tools": [
                {
                    "name": t.spec.name,
                    "description": t.spec.description,
                    "danger": t.spec.danger.value,
                    "tags": t.spec.tags,
                }
                for t in found
                # Hide tools the caller could not run anyway — listing them
                # only invites the model to plan around capabilities it lacks.
                if not t.spec.required_permissions
                or not ctx.principal.missing_permissions(t.spec.required_permissions)
            ],
        }


class ListSkillsTool(Tool):
    """Enumerate registered business skills."""

    def __init__(self, registry: Any | None = None) -> None:
        self._registry = registry
        super().__init__(
            ToolSpec(
                name="list_skills",
                description=(
                    "List the business skills registered on this platform, optionally "
                    "filtered by category or search term. Call this to discover domain "
                    "capabilities before planning multi-step work."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Substring filter."},
                        "category": {
                            "type": "string",
                            "enum": [
                                "analysis",
                                "generation",
                                "extraction",
                                "transformation",
                                "validation",
                                "integration",
                                "orchestration",
                                "utility",
                            ],
                        },
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                danger=DangerLevel.SAFE,
                tags=["introspection"],
            )
        )

    def _resolve_registry(self) -> Any:
        if self._registry is not None:
            return self._registry
        from sa_skills.registry import skill_registry

        return skill_registry

    async def invoke(self, ctx: ExecutionContext, arguments: dict[str, Any]) -> Any:
        registry = self._resolve_registry()
        found = registry.search(
            query=arguments.get("query"),
            category=arguments.get("category"),
        )
        return {
            "count": len(found),
            "skills": [
                {
                    "name": s.manifest.name,
                    "version": s.manifest.version,
                    "description": s.manifest.description,
                    "category": s.manifest.category.value,
                    "stability": s.manifest.stability.value,
                }
                for s in found
            ],
        }


class DescribeSkillTool(Tool):
    """Return the full manifest for one skill."""

    def __init__(self, registry: Any | None = None) -> None:
        self._registry = registry
        super().__init__(
            ToolSpec(
                name="describe_skill",
                description=(
                    "Return the full contract for a named skill: its input schema, output "
                    "schema, required permissions, and examples. Call this after list_skills "
                    "when you need to know exactly what arguments a skill takes."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Skill name, e.g. 'finance.score'.",
                        },
                        "version": {"type": "string", "description": "Optional pinned version."},
                    },
                    "required": ["name"],
                    "additionalProperties": False,
                },
                danger=DangerLevel.SAFE,
                tags=["introspection"],
            )
        )

    async def invoke(self, ctx: ExecutionContext, arguments: dict[str, Any]) -> Any:
        registry = self._registry
        if registry is None:
            from sa_skills.registry import skill_registry

            registry = skill_registry

        skill = registry.require(arguments["name"], version=arguments.get("version"))
        return skill.manifest.model_dump(mode="json")


__all__ = ["DescribeSkillTool", "ListSkillsTool", "ListToolsTool"]
