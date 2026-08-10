"""Run-state persistence.

The in-memory store is the default and is correct for a single process. The
:class:`StateStore` interface is deliberately small so a Redis, Postgres, or
DynamoDB backend can be dropped in without touching the engine.
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from collections import OrderedDict

from sa_platform.errors import NotFoundError
from sa_platform.logging import get_logger

from .models import RunState

logger = get_logger(__name__)


class StateStore(ABC):
    """Persists workflow run state between steps."""

    @abstractmethod
    async def save(self, state: RunState) -> None:
        """Create or replace the stored state for ``state.run_id``."""

    @abstractmethod
    async def load(self, run_id: str) -> RunState:
        """Load state, raising :class:`NotFoundError` when absent."""

    @abstractmethod
    async def delete(self, run_id: str) -> None:
        ...

    @abstractmethod
    async def list_runs(self, *, workflow: str | None = None, limit: int = 100) -> list[RunState]:
        ...

    async def try_load(self, run_id: str) -> RunState | None:
        try:
            return await self.load(run_id)
        except NotFoundError:
            return None


class InMemoryStateStore(StateStore):
    """Bounded, thread-safe in-process store.

    Evicts oldest-first past ``max_runs`` so a long-lived process cannot leak
    memory through completed run history.
    """

    def __init__(self, *, max_runs: int = 1000, ttl_seconds: float | None = 3600.0) -> None:
        self._runs: OrderedDict[str, RunState] = OrderedDict()
        self._written_at: dict[str, float] = {}
        self._max_runs = max_runs
        self._ttl = ttl_seconds
        self._lock = asyncio.Lock()

    async def save(self, state: RunState) -> None:
        async with self._lock:
            # model_copy(deep=True) so later mutation of the live object does
            # not retroactively rewrite the checkpoint.
            self._runs[state.run_id] = state.model_copy(deep=True)
            self._runs.move_to_end(state.run_id)
            self._written_at[state.run_id] = time.monotonic()
            self._evict()

    def _evict(self) -> None:
        if self._ttl is not None:
            cutoff = time.monotonic() - self._ttl
            expired = [rid for rid, at in self._written_at.items() if at < cutoff]
            for run_id in expired:
                self._runs.pop(run_id, None)
                self._written_at.pop(run_id, None)

        while len(self._runs) > self._max_runs:
            run_id, _ = self._runs.popitem(last=False)
            self._written_at.pop(run_id, None)

    async def load(self, run_id: str) -> RunState:
        async with self._lock:
            state = self._runs.get(run_id)
            if state is None:
                raise NotFoundError(f"run '{run_id}' was not found", details={"run_id": run_id})
            return state.model_copy(deep=True)

    async def delete(self, run_id: str) -> None:
        async with self._lock:
            self._runs.pop(run_id, None)
            self._written_at.pop(run_id, None)

    async def list_runs(self, *, workflow: str | None = None, limit: int = 100) -> list[RunState]:
        async with self._lock:
            # Newest first.
            found = [
                state.model_copy(deep=True)
                for state in reversed(self._runs.values())
                if workflow is None or state.workflow == workflow
            ]
            return found[:limit]


class NullStateStore(StateStore):
    """Discards all state. For fire-and-forget runs that never resume."""

    async def save(self, state: RunState) -> None:
        return None

    async def load(self, run_id: str) -> RunState:
        raise NotFoundError("the null state store does not retain runs", details={"run_id": run_id})

    async def delete(self, run_id: str) -> None:
        return None

    async def list_runs(self, *, workflow: str | None = None, limit: int = 100) -> list[RunState]:
        return []


def build_state_store(backend: str = "memory", **kwargs: object) -> StateStore:
    if backend == "memory":
        return InMemoryStateStore(**kwargs)  # type: ignore[arg-type]
    if backend == "null":
        return NullStateStore()
    from sa_platform.errors import ConfigurationError

    raise ConfigurationError(
        f"unsupported state backend '{backend}'",
        details={"backend": backend, "supported": ["memory", "null"]},
    )


__all__ = ["InMemoryStateStore", "NullStateStore", "StateStore", "build_state_store"]
