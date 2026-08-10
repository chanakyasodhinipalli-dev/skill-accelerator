"""Form catalogue: CRUD, versioning, and lifecycle.

The rule the requirement asks for — *always use the latest active version* — is
enforced here in :meth:`FormRegistry.resolve`. Everything downstream (the
conversation engine, the API, the renderers) calls that and cannot accidentally
pick up a draft or a deprecated definition.

Editing never mutates a published version. An update to an ``ACTIVE`` form
creates a new ``DRAFT`` at the next version; activating it deprecates the
previous one. In-progress sessions keep the version they started on, so a
mid-flight edit cannot change the questions under a user.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal

import yaml

from sa_platform.errors import ConflictError, NotFoundError, ValidationError
from sa_platform.logging import get_logger
from sa_platform.registry import Registry

from .models import FormDefinition, FormStatus

logger = get_logger(__name__)

Bump = Literal["major", "minor", "patch"]


def next_version(current: str, bump: Bump = "minor") -> str:
    major, minor, patch = (int(p) for p in current.split("-")[0].split("."))
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


class FormRegistry:
    """Versioned store of form definitions."""

    def __init__(self) -> None:
        self._registry: Registry[FormDefinition] = Registry("form")

    def __len__(self) -> int:
        return len(self._registry)

    def __bool__(self) -> bool:
        return True

    def __contains__(self, name: object) -> bool:
        return name in self._registry

    # -- create -----------------------------------------------------------
    def create(self, definition: FormDefinition, *, activate: bool = False) -> FormDefinition:
        """Register a new form or a new version of an existing one."""
        if self._registry.try_get(definition.name, version=definition.version) is not None:
            raise ConflictError(
                f"form '{definition.name}' version '{definition.version}' already exists",
                details={"form": definition.name, "version": definition.version},
            )
        stored = definition.model_copy(deep=True)
        if activate:
            stored.status = FormStatus.ACTIVE
        self._registry.register(stored.name, stored, version=stored.version)

        if activate:
            self._deprecate_others(stored.name, keep=stored.version)

        logger.info(
            "created form",
            extra={
                "form": stored.name,
                "version": stored.version,
                "status": stored.status.value,
                "fields": stored.field_count(),
            },
        )
        return stored

    # -- read -------------------------------------------------------------
    def get(self, name: str, version: str | None = None) -> FormDefinition:
        """Fetch a specific version, or the newest version of any status."""
        found = self._registry.try_get(name, version=version)
        if found is None:
            raise NotFoundError(
                f"form '{name}'" + (f" version '{version}'" if version else "") + " was not found",
                details={"form": name, "version": version, "available": self.names()},
            )
        return found

    def resolve(self, name: str, version: str | None = None) -> FormDefinition:
        """Resolve the version a *new* session should use.

        Without an explicit version this returns the latest **active** form —
        never a draft, never a deprecated one. That is the guarantee the rest
        of the system relies on.
        """
        if version is not None:
            return self.get(name, version)

        active = self.active_version(name)
        if active is None:
            available = self.versions(name)
            if not available:
                raise NotFoundError(
                    f"form '{name}' was not found",
                    details={"form": name, "available": self.names()},
                )
            raise ValidationError(
                f"form '{name}' has no active version; activate one before starting a session",
                details={
                    "form": name,
                    "versions": {v: self.get(name, v).status.value for v in available},
                },
            )
        return active

    def active_version(self, name: str) -> FormDefinition | None:
        candidates = [self.get(name, v) for v in self.versions(name)]
        active = [c for c in candidates if c.status is FormStatus.ACTIVE]
        return active[-1] if active else None

    def versions(self, name: str) -> list[str]:
        return self._registry.versions(name)

    def names(self) -> list[str]:
        return self._registry.names()

    def list_forms(self, *, include_inactive: bool = False) -> list[FormDefinition]:
        forms: list[FormDefinition] = []
        for name in self.names():
            active = self.active_version(name)
            if active is not None:
                forms.append(active)
            elif include_inactive:
                latest = self._registry.get(name)
                forms.append(latest)
        return forms

    def history(self, name: str) -> list[FormDefinition]:
        """Every version, oldest first — the audit trail for a form."""
        return [self.get(name, v) for v in self.versions(name)]

    def search(
        self, query: str | None = None, tags: Iterable[str] | None = None
    ) -> list[FormDefinition]:
        wanted = set(tags or ())
        needle = query.lower() if query else None

        def matches(form: FormDefinition) -> bool:
            if wanted and not wanted.issubset(set(form.tags)):
                return False
            if needle:
                haystack = f"{form.name} {form.title} {form.description} {' '.join(form.tags)}"
                return needle in haystack.lower()
            return True

        return [f for f in self.list_forms() if matches(f)]

    # -- update -----------------------------------------------------------
    def update(
        self,
        name: str,
        changes: dict[str, Any],
        *,
        version: str | None = None,
        bump: Bump = "minor",
        change_note: str = "",
        editor: str | None = None,
    ) -> FormDefinition:
        """Apply changes to a form.

        A ``DRAFT`` is edited in place. Any published version forks into a new
        draft instead, because a definition someone has already filled against
        must not change beneath them.
        """
        base = self.get(name, version) if version else self._registry.get(name)
        merged = {**base.model_dump(mode="python"), **changes}
        merged["updated_at"] = time.time()
        merged["change_note"] = change_note or merged.get("change_note", "")

        if base.status is FormStatus.DRAFT:
            merged["version"] = base.version
            updated = self._build(merged)
            self._registry.register(name, updated, version=updated.version, replace=True)
            logger.info("updated draft form", extra={"form": name, "version": updated.version})
            return updated

        merged["version"] = next_version(base.version, bump)
        merged["status"] = FormStatus.DRAFT.value
        merged["created_at"] = time.time()
        merged["created_by"] = editor or base.created_by
        updated = self._build(merged)
        self._registry.register(name, updated, version=updated.version)
        logger.info(
            "forked published form into a new draft",
            extra={"form": name, "from": base.version, "to": updated.version},
        )
        return updated

    @staticmethod
    def _build(payload: dict[str, Any]) -> FormDefinition:
        try:
            return FormDefinition(**payload)
        except Exception as exc:  # noqa: BLE001 - pydantic raises its own type
            raise ValidationError(f"invalid form definition: {exc}", cause=exc) from exc

    # -- lifecycle --------------------------------------------------------
    def activate(self, name: str, version: str) -> FormDefinition:
        """Publish a version and deprecate whatever was active before it."""
        form = self.get(name, version)
        if form.status is FormStatus.ARCHIVED:
            raise ValidationError(
                f"form '{name}' version '{version}' is archived and cannot be activated",
                details={"form": name, "version": version},
            )
        form.status = FormStatus.ACTIVE
        form.updated_at = time.time()
        self._registry.register(name, form, version=version, replace=True)
        self._deprecate_others(name, keep=version)
        logger.info("activated form version", extra={"form": name, "version": version})
        return form

    def deprecate(self, name: str, version: str) -> FormDefinition:
        form = self.get(name, version)
        form.status = FormStatus.DEPRECATED
        form.updated_at = time.time()
        self._registry.register(name, form, version=version, replace=True)
        return form

    def archive(self, name: str, version: str) -> FormDefinition:
        """Retire a version permanently. New sessions can never use it."""
        form = self.get(name, version)
        form.status = FormStatus.ARCHIVED
        form.updated_at = time.time()
        self._registry.register(name, form, version=version, replace=True)
        logger.info("archived form version", extra={"form": name, "version": version})
        return form

    def _deprecate_others(self, name: str, *, keep: str) -> None:
        for version in self.versions(name):
            if version == keep:
                continue
            other = self.get(name, version)
            if other.status is FormStatus.ACTIVE:
                other.status = FormStatus.DEPRECATED
                other.updated_at = time.time()
                self._registry.register(name, other, version=version, replace=True)

    # -- delete -----------------------------------------------------------
    def delete(self, name: str, version: str | None = None, *, force: bool = False) -> None:
        """Delete a version, or the whole form.

        Only drafts are deletable without ``force``: a published version may
        already back a baselined artifact, and deleting it would orphan the
        audit trail. Archive instead.
        """
        if version is None:
            if not force:
                published = [
                    v
                    for v in self.versions(name)
                    if self.get(name, v).status is not FormStatus.DRAFT
                ]
                if published:
                    raise ValidationError(
                        f"form '{name}' has published version(s) {published}; "
                        "archive them or pass force=True",
                        details={"form": name, "published": published},
                    )
            self._registry.unregister(name)
            logger.warning("deleted form", extra={"form": name})
            return

        form = self.get(name, version)
        if form.status is not FormStatus.DRAFT and not force:
            raise ValidationError(
                f"form '{name}' version '{version}' is {form.status.value} and cannot be deleted; "
                "archive it instead",
                details={"form": name, "version": version, "status": form.status.value},
            )
        self._registry.unregister(name, version=version)
        logger.warning("deleted form version", extra={"form": name, "version": version})

    def clear(self) -> None:
        self._registry.clear()

    # -- persistence ------------------------------------------------------
    def load_file(self, path: Path | str, *, activate: bool = False) -> FormDefinition:
        file = Path(path)
        if not file.is_file():
            raise NotFoundError(f"form file not found: {file}")
        try:
            raw = yaml.safe_load(file.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise ValidationError(f"invalid YAML in {file}: {exc}", cause=exc) from exc
        if not isinstance(raw, dict):
            raise ValidationError(f"{file} must contain a YAML mapping")

        definition = self._build(raw)
        existing = self._registry.try_get(definition.name, version=definition.version)
        if existing is not None:
            return existing
        return self.create(definition, activate=activate or definition.status is FormStatus.ACTIVE)

    def load_directory(
        self, directory: Path | str, *, strict: bool = False
    ) -> list[FormDefinition]:
        root = Path(directory)
        if not root.is_dir():
            logger.debug("form directory does not exist", extra={"path": str(root)})
            return []

        loaded: list[FormDefinition] = []
        for file in sorted([*root.rglob("*.yaml"), *root.rglob("*.yml")]):
            try:
                loaded.append(self.load_file(file))
            except Exception as exc:  # noqa: BLE001 - one bad file must not block startup
                if strict:
                    raise
                logger.error(
                    "skipping invalid form file", extra={"path": str(file), "error": str(exc)}
                )
        return loaded

    def export(self, name: str, version: str | None = None) -> str:
        """Serialise a definition to YAML for checking into version control."""
        form = self.get(name, version)
        return yaml.safe_dump(
            form.model_dump(mode="json", exclude_none=True), sort_keys=False, allow_unicode=True
        )


form_registry = FormRegistry()

__all__ = ["FormRegistry", "form_registry", "next_version"]
