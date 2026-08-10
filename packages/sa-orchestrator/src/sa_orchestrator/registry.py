"""Workflow catalogue and YAML loading."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from sa_platform.errors import AcceleratorError, ConfigurationError, NotFoundError
from sa_platform.logging import get_logger
from sa_platform.registry import Registry

from .graph import build_graph
from .models import WorkflowSpec

logger = get_logger(__name__)


class WorkflowRegistry:
    """Holds validated workflow definitions.

    Every registration builds the graph, so a cyclic or mis-bound workflow is
    rejected at load time rather than mid-run.
    """

    def __init__(self) -> None:
        self._registry: Registry[WorkflowSpec] = Registry("workflow")

    def register(self, spec: WorkflowSpec, *, replace: bool = False) -> WorkflowSpec:
        build_graph(spec)  # validation side effect
        self._registry.register(spec.name, spec, version=spec.version, replace=replace)
        logger.info(
            "registered workflow",
            extra={"workflow": spec.name, "version": spec.version, "steps": len(spec.steps)},
        )
        return spec

    def register_many(self, specs: Iterable[WorkflowSpec], *, replace: bool = False) -> None:
        for spec in specs:
            self.register(spec, replace=replace)

    def get(self, name: str, *, version: str | None = None) -> WorkflowSpec:
        return self._registry.get(name, version=version)

    def require(self, name: str, *, version: str | None = None) -> WorkflowSpec:
        found = self._registry.try_get(name, version=version)
        if found is None:
            raise NotFoundError(
                f"workflow '{name}' is not registered",
                details={"workflow": name, "available": self.names()},
            )
        return found

    def names(self) -> list[str]:
        return self._registry.names()

    def all(self) -> list[WorkflowSpec]:
        return self._registry.all()

    def unregister(self, name: str, *, version: str | None = None) -> None:
        self._registry.unregister(name, version=version)

    def clear(self) -> None:
        self._registry.clear()

    # -- loading ----------------------------------------------------------
    def load_file(self, path: Path | str, *, replace: bool = False) -> WorkflowSpec:
        file = Path(path)
        if not file.is_file():
            raise ConfigurationError(f"workflow file not found: {file}")
        try:
            raw: Any = yaml.safe_load(file.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise ConfigurationError(f"invalid YAML in {file}: {exc}", cause=exc) from exc
        if not isinstance(raw, dict):
            raise ConfigurationError(f"{file} must contain a YAML mapping")

        try:
            spec = WorkflowSpec(**raw)
        except Exception as exc:  # noqa: BLE001 - pydantic raises its own type
            raise ConfigurationError(
                f"invalid workflow definition in {file}: {exc}", cause=exc
            ) from exc
        return self.register(spec, replace=replace)

    def load_directory(
        self, directory: Path | str, *, replace: bool = False, strict: bool = False
    ) -> list[WorkflowSpec]:
        """Load every ``*.yaml`` / ``*.yml`` workflow under ``directory``."""
        root = Path(directory)
        if not root.is_dir():
            logger.debug("workflow directory does not exist", extra={"path": str(root)})
            return []

        loaded: list[WorkflowSpec] = []
        for file in sorted([*root.rglob("*.yaml"), *root.rglob("*.yml")]):
            try:
                loaded.append(self.load_file(file, replace=replace))
            except AcceleratorError as exc:
                # Catches graph ValidationError as well as parse/shape errors:
                # one malformed workflow must not prevent the service starting.
                if strict:
                    raise
                logger.error(
                    "skipping invalid workflow file",
                    extra={"path": str(file), "error": exc.message},
                )
        return loaded


workflow_registry = WorkflowRegistry()

__all__ = ["WorkflowRegistry", "workflow_registry"]
