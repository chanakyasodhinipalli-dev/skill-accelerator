"""Generic, thread-safe, version-aware registry.

Skills, tools, and connectors all need the same thing: register named items,
resolve them by name (optionally pinned to a version), and enumerate them.
This is that, once.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from threading import RLock
from typing import Generic, TypeVar

from .errors import ConflictError, NotFoundError

T = TypeVar("T")


def _version_key(version: str) -> tuple[int | str, ...]:
    """Sort key for semantic-ish versions.

    Numeric segments compare numerically so ``0.10.0`` sorts above ``0.9.0``.
    Non-numeric segments (pre-release tags) fall back to string comparison and
    sort below any numeric segment at the same position.
    """
    parts: list[int | str] = []
    for segment in version.replace("-", ".").split("."):
        parts.append(int(segment) if segment.isdigit() else segment)
    return tuple(parts)


class Registry(Generic[T]):
    """Name → {version → item}, with a resolvable "latest"."""

    def __init__(self, kind: str) -> None:
        self._kind = kind
        self._items: dict[str, dict[str, T]] = {}
        self._lock = RLock()

    # -- mutation ---------------------------------------------------------
    def register(self, name: str, item: T, *, version: str = "0.0.0", replace: bool = False) -> T:
        with self._lock:
            versions = self._items.setdefault(name, {})
            if version in versions and not replace:
                raise ConflictError(
                    f"{self._kind} '{name}' version '{version}' is already registered",
                    details={"kind": self._kind, "name": name, "version": version},
                )
            versions[version] = item
            return item

    def unregister(self, name: str, *, version: str | None = None) -> None:
        with self._lock:
            versions = self._items.get(name)
            if versions is None:
                return
            if version is None:
                del self._items[name]
                return
            versions.pop(version, None)
            if not versions:
                del self._items[name]

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    # -- lookup -----------------------------------------------------------
    def get(self, name: str, *, version: str | None = None) -> T:
        with self._lock:
            versions = self._items.get(name)
            if not versions:
                raise NotFoundError(
                    f"{self._kind} '{name}' is not registered",
                    details={"kind": self._kind, "name": name, "available": self.names()},
                )
            if version is None:
                latest = max(versions, key=_version_key)
                return versions[latest]
            item = versions.get(version)
            if item is None:
                raise NotFoundError(
                    f"{self._kind} '{name}' has no version '{version}'",
                    details={
                        "kind": self._kind,
                        "name": name,
                        "version": version,
                        "available_versions": sorted(versions, key=_version_key),
                    },
                )
            return item

    def try_get(self, name: str, *, version: str | None = None) -> T | None:
        try:
            return self.get(name, version=version)
        except NotFoundError:
            return None

    def __contains__(self, name: object) -> bool:
        with self._lock:
            return name in self._items

    def __len__(self) -> int:
        with self._lock:
            return sum(len(v) for v in self._items.values())

    def __bool__(self) -> bool:
        # Without this, `__len__` makes an *empty* registry falsy, and the
        # `registry or default_registry` idiom silently discards a caller's
        # empty registry in favour of the global one. A registry object always
        # exists; emptiness is not absence.
        return True

    def __iter__(self) -> Iterator[T]:
        return iter(self.all())

    # -- enumeration ------------------------------------------------------
    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._items)

    def versions(self, name: str) -> list[str]:
        with self._lock:
            return sorted(self._items.get(name, {}), key=_version_key)

    def all(self, *, latest_only: bool = True) -> list[T]:
        with self._lock:
            if latest_only:
                return [
                    versions[max(versions, key=_version_key)]
                    for versions in self._items.values()
                    if versions
                ]
            return [item for versions in self._items.values() for item in versions.values()]

    def filter(self, predicate: Callable[[T], bool], *, latest_only: bool = True) -> list[T]:
        return [item for item in self.all(latest_only=latest_only) if predicate(item)]


__all__ = ["Registry"]
