"""Skill discovery.

Three sources, all optional and independently usable:

1. **Filesystem** — a directory containing ``skill.yaml`` beside a Python
   module. Manifest values in the YAML override anything the decorator derived.
2. **Entry points** — pip-installed packages advertising ``sa.skills``.
   This is how skills ship as versioned artifacts across teams.
3. **Modules** — explicit ``import`` of a module containing ``@skill``
   functions.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from sa_platform.errors import ConfigurationError
from sa_platform.logging import get_logger

from .base import Skill
from .decorators import drain_pending
from .models import SkillManifest

logger = get_logger(__name__)

MANIFEST_FILENAME = "skill.yaml"


class SkillLoader:
    """Locates skill implementations and returns instantiated :class:`Skill` objects."""

    def __init__(self, *, strict: bool = False) -> None:
        # strict=True surfaces a bad skill as an exception instead of a warning.
        # Use it in CI; leave it off in production so one broken skill package
        # cannot prevent the service from starting.
        self._strict = strict

    # -- filesystem -------------------------------------------------------
    def load_from_directory(self, directory: Path | str) -> list[Skill]:
        """Recursively load every ``skill.yaml`` package under ``directory``."""
        root = Path(directory)
        if not root.is_dir():
            logger.debug("skill search path does not exist", extra={"path": str(root)})
            return []

        discovered: list[Skill] = []
        for manifest_path in sorted(root.rglob(MANIFEST_FILENAME)):
            try:
                discovered.extend(self.load_package(manifest_path.parent))
            except Exception as exc:  # noqa: BLE001 - isolate one bad skill
                self._handle_error(f"failed to load skill at {manifest_path.parent}", exc)
        return discovered

    def load_package(self, package_dir: Path) -> list[Skill]:
        """Load one skill package: ``skill.yaml`` plus its entry module."""
        manifest_path = package_dir / MANIFEST_FILENAME
        if not manifest_path.is_file():
            raise ConfigurationError(f"no {MANIFEST_FILENAME} found in {package_dir}")

        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ConfigurationError(f"{manifest_path} must contain a YAML mapping")

        entrypoint = raw.pop("entrypoint", "skill.py")
        module = self._import_path(package_dir / entrypoint, package_dir.name)

        # Decorated skills registered during import.
        skills = list(drain_pending())

        # An explicitly exported class or instance takes precedence.
        exported = getattr(module, "SKILL", None)
        if exported is not None:
            skills.append(exported() if isinstance(exported, type) else exported)

        if not skills:
            raise ConfigurationError(
                f"{package_dir} declared a manifest but exported no skill "
                f"(use @skill(...) or define a module-level SKILL)"
            )

        # YAML is the source of truth: it is reviewable, diffable, and does not
        # require reading Python to audit a skill's permissions.
        if raw:
            skills = [self._apply_manifest_overrides(s, raw) for s in skills]

        logger.info(
            "loaded skill package",
            extra={"path": str(package_dir), "skills": [s.manifest.qualified_name for s in skills]},
        )
        return skills

    @staticmethod
    def _apply_manifest_overrides(instance: Skill, overrides: dict[str, Any]) -> Skill:
        merged = {**instance.manifest.model_dump(mode="python"), **overrides}
        instance.manifest = SkillManifest(**merged)
        return instance

    @staticmethod
    def _import_path(path: Path, package_name: str) -> Any:
        if not path.is_file():
            raise ConfigurationError(f"skill entrypoint not found: {path}")

        module_name = f"sa_skills._loaded.{package_name}_{path.stem}"
        if module_name in sys.modules:
            return sys.modules[module_name]

        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ConfigurationError(f"could not build an import spec for {path}")

        module = importlib.util.module_from_spec(spec)
        # Register before exec so intra-module relative imports resolve.
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(module_name, None)
            raise
        return module

    # -- entry points -----------------------------------------------------
    def load_from_entry_points(self, group: str = "sa.skills") -> list[Skill]:
        """Load skills advertised by installed distributions.

        A publishing package declares::

            [project.entry-points."sa.skills"]
            finance = "my_pkg.skills.finance"
        """
        from importlib.metadata import entry_points

        discovered: list[Skill] = []
        try:
            found = entry_points(group=group)
        except Exception as exc:  # noqa: BLE001 - metadata errors must not be fatal
            self._handle_error(f"failed to enumerate entry point group '{group}'", exc)
            return discovered

        for entry in found:
            try:
                target = entry.load()
                if isinstance(target, Skill):
                    discovered.append(target)
                elif isinstance(target, type) and issubclass(target, Skill):
                    discovered.append(target())
                else:
                    # A module: its @skill decorators already queued instances.
                    discovered.extend(drain_pending())
            except Exception as exc:  # noqa: BLE001 - isolate one bad distribution
                self._handle_error(f"failed to load entry point '{entry.name}'", exc)

        return discovered

    # -- modules ----------------------------------------------------------
    def load_from_modules(self, module_names: Iterable[str]) -> list[Skill]:
        discovered: list[Skill] = []
        for module_name in module_names:
            try:
                importlib.import_module(module_name)
                discovered.extend(drain_pending())
            except Exception as exc:  # noqa: BLE001 - isolate one bad module
                self._handle_error(f"failed to import skill module '{module_name}'", exc)
        return discovered

    # -- error policy -----------------------------------------------------
    def _handle_error(self, message: str, exc: BaseException) -> None:
        if self._strict:
            raise ConfigurationError(message, cause=exc) from exc
        logger.error(message, extra={"error": str(exc), "error_type": type(exc).__name__})


__all__ = ["MANIFEST_FILENAME", "SkillLoader"]
