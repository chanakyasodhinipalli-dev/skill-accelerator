"""The skill registry — the catalogue every other layer reads from."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from pathlib import Path

from sa_platform.config import get_settings
from sa_platform.errors import NotFoundError
from sa_platform.logging import get_logger
from sa_platform.registry import Registry

from .base import Skill
from .decorators import drain_pending
from .loader import SkillLoader
from .models import SkillCategory, SkillManifest, SkillStability

logger = get_logger(__name__)


class SkillRegistry:
    """Registers, discovers, and resolves skills.

    Wraps the generic :class:`~sa_platform.registry.Registry` with skill-aware
    discovery and lifecycle management.
    """

    def __init__(self, *, loader: SkillLoader | None = None) -> None:
        self._registry: Registry[Skill] = Registry("skill")
        self._loader = loader or SkillLoader()
        self._loaded = False

    # -- registration -----------------------------------------------------
    def register(self, skill: Skill, *, replace: bool = False) -> Skill:
        manifest = skill.manifest
        self._registry.register(manifest.name, skill, version=manifest.version, replace=replace)
        logger.debug(
            "registered skill",
            extra={
                "skill": manifest.name,
                "version": manifest.version,
                "category": manifest.category.value,
                "stability": manifest.stability.value,
            },
        )
        return skill

    def register_many(self, skills: Iterable[Skill], *, replace: bool = False) -> list[Skill]:
        return [self.register(s, replace=replace) for s in skills]

    def unregister(self, name: str, *, version: str | None = None) -> None:
        self._registry.unregister(name, version=version)

    def clear(self) -> None:
        self._registry.clear()
        self._loaded = False

    # -- lookup -----------------------------------------------------------
    def get(self, name: str, *, version: str | None = None) -> Skill:
        return self._registry.get(name, version=version)

    def try_get(self, name: str, *, version: str | None = None) -> Skill | None:
        return self._registry.try_get(name, version=version)

    def require(self, name: str, *, version: str | None = None) -> Skill:
        skill = self.try_get(name, version=version)
        if skill is None:
            raise NotFoundError(
                f"skill '{name}' is not registered",
                details={"skill": name, "version": version, "available": self.names()},
            )
        return skill

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

    def versions(self, name: str) -> list[str]:
        return self._registry.versions(name)

    def all(self, *, latest_only: bool = True) -> list[Skill]:
        return self._registry.all(latest_only=latest_only)

    def manifests(self, *, latest_only: bool = True) -> list[SkillManifest]:
        return [s.manifest for s in self.all(latest_only=latest_only)]

    def search(
        self,
        *,
        query: str | None = None,
        category: SkillCategory | str | None = None,
        tags: Iterable[str] | None = None,
        stability: SkillStability | str | None = None,
        exposed_as_tool: bool | None = None,
    ) -> list[Skill]:
        """Filter the catalogue. All criteria are ANDed; ``None`` means "any"."""
        wanted_tags = set(tags or ())
        needle = query.lower() if query else None

        def matches(skill: Skill) -> bool:
            m = skill.manifest
            if category is not None and m.category != SkillCategory(category):
                return False
            if stability is not None and m.stability != SkillStability(stability):
                return False
            if wanted_tags and not wanted_tags.issubset(set(m.tags)):
                return False
            if exposed_as_tool is not None and m.expose_as_tool != exposed_as_tool:
                return False
            if needle and needle not in f"{m.name} {m.description} {' '.join(m.tags)}".lower():
                return False
            return True

        return self._registry.filter(matches)

    # -- discovery --------------------------------------------------------
    async def discover(self, *, force: bool = False) -> int:
        """Populate the registry from every configured source.

        Returns the number of newly registered skills. Idempotent unless
        ``force`` is set.
        """
        if self._loaded and not force:
            return 0

        settings = get_settings().skills
        found: list[Skill] = list(drain_pending())

        if settings.autodiscover:
            for raw_path in settings.search_paths:
                found.extend(self._loader.load_from_directory(Path(raw_path)))
            found.extend(self._loader.load_from_entry_points(settings.entry_point_group))

        registered = 0
        for skill in found:
            existing = self.try_get(skill.manifest.name, version=skill.manifest.version)
            if existing is not None:
                continue
            self.register(skill)
            registered += 1

        await self._run_load_hooks(found)
        self._loaded = True

        logger.info(
            "skill discovery complete",
            extra={"registered": registered, "total": len(self._registry)},
        )
        return registered

    async def _run_load_hooks(self, skills: Iterable[Skill]) -> None:
        async def safe_load(skill: Skill) -> None:
            try:
                await skill.on_load()
            except Exception as exc:  # noqa: BLE001 - a bad hook must not abort startup
                logger.error(
                    "skill on_load hook failed",
                    extra={"skill": skill.manifest.name, "error": str(exc)},
                )

        await asyncio.gather(*(safe_load(s) for s in skills))

    async def shutdown(self) -> None:
        """Run every ``on_unload`` hook. Call during application shutdown."""

        async def safe_unload(skill: Skill) -> None:
            try:
                await skill.on_unload()
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "skill on_unload hook failed",
                    extra={"skill": skill.manifest.name, "error": str(exc)},
                )

        await asyncio.gather(*(safe_unload(s) for s in self.all(latest_only=False)))


#: Process-wide registry. Applications may construct their own for isolation.
skill_registry = SkillRegistry()

__all__ = ["SkillRegistry", "skill_registry"]
