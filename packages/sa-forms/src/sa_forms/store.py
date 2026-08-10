"""Session and artifact persistence.

Both are narrow interfaces with in-memory and filesystem implementations. The
requirement that a user "can come back later" is entirely a property of the
session store, so it is the first thing to swap for a database in a real
deployment.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from pathlib import Path

from sa_platform.errors import NotFoundError, ValidationError
from sa_platform.logging import get_logger

from .models import ArtifactRecord, FormSession, SessionStatus

logger = get_logger(__name__)

_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


class SessionStore(ABC):
    """Persists in-progress form sessions."""

    @abstractmethod
    async def save(self, session: FormSession) -> None:
        ...

    @abstractmethod
    async def load(self, session_id: str) -> FormSession:
        ...

    @abstractmethod
    async def delete(self, session_id: str) -> None:
        ...

    @abstractmethod
    async def list_sessions(
        self,
        *,
        form_name: str | None = None,
        status: SessionStatus | None = None,
        participant: str | None = None,
        limit: int = 100,
    ) -> list[FormSession]:
        ...

    async def try_load(self, session_id: str) -> FormSession | None:
        try:
            return await self.load(session_id)
        except NotFoundError:
            return None

    async def find_resumable(self, form_name: str, participant: str) -> FormSession | None:
        """Find a session this person can pick back up.

        Used to answer "continue where I left off" without the user having to
        remember a session id.
        """
        candidates = await self.list_sessions(form_name=form_name, participant=participant)
        editable = [s for s in candidates if s.status.is_editable]
        return max(editable, key=lambda s: s.updated_at) if editable else None


class InMemorySessionStore(SessionStore):
    """Bounded in-process store.

    Correct for a single process and for tests. Sessions are deep-copied on
    write so a later mutation of the live object cannot rewrite history.
    """

    def __init__(self, *, max_sessions: int = 5000) -> None:
        self._sessions: OrderedDict[str, FormSession] = OrderedDict()
        self._max = max_sessions
        self._lock = asyncio.Lock()

    async def save(self, session: FormSession) -> None:
        async with self._lock:
            session.touch()
            self._sessions[session.id] = session.model_copy(deep=True)
            self._sessions.move_to_end(session.id)
            while len(self._sessions) > self._max:
                evicted, _ = self._sessions.popitem(last=False)
                logger.warning("evicted session from memory store", extra={"session": evicted})

    async def load(self, session_id: str) -> FormSession:
        async with self._lock:
            found = self._sessions.get(session_id)
            if found is None:
                raise NotFoundError(
                    f"form session '{session_id}' was not found",
                    details={"session_id": session_id},
                )
            return found.model_copy(deep=True)

    async def delete(self, session_id: str) -> None:
        async with self._lock:
            self._sessions.pop(session_id, None)

    async def list_sessions(
        self,
        *,
        form_name: str | None = None,
        status: SessionStatus | None = None,
        participant: str | None = None,
        limit: int = 100,
    ) -> list[FormSession]:
        async with self._lock:
            found = [
                s.model_copy(deep=True)
                for s in reversed(self._sessions.values())
                if (form_name is None or s.form_name == form_name)
                and (status is None or s.status is status)
                and (participant is None or participant in s.participants)
            ]
            return found[:limit]


class FileSessionStore(SessionStore):
    """JSON-on-disk store.

    Enough to survive a restart in a single-node deployment, and a useful
    reference for what a database implementation has to provide.
    """

    def __init__(self, root: Path | str = ".sa/sessions") -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    def _path(self, session_id: str) -> Path:
        safe = _UNSAFE_FILENAME.sub("_", session_id)
        return self._root / f"{safe}.json"

    async def save(self, session: FormSession) -> None:
        async with self._lock:
            session.touch()
            path = self._path(session.id)
            # Write-then-rename so a crash mid-write cannot truncate a session.
            temporary = path.with_suffix(".tmp")
            temporary.write_text(session.model_dump_json(indent=2), encoding="utf-8")
            temporary.replace(path)

    async def load(self, session_id: str) -> FormSession:
        path = self._path(session_id)
        if not path.is_file():
            raise NotFoundError(
                f"form session '{session_id}' was not found", details={"session_id": session_id}
            )
        try:
            return FormSession(**json.loads(path.read_text(encoding="utf-8")))
        except Exception as exc:  # noqa: BLE001 - corrupt file surfaces as a platform error
            raise ValidationError(
                f"session '{session_id}' could not be read: {exc}", cause=exc
            ) from exc

    async def delete(self, session_id: str) -> None:
        self._path(session_id).unlink(missing_ok=True)

    async def list_sessions(
        self,
        *,
        form_name: str | None = None,
        status: SessionStatus | None = None,
        participant: str | None = None,
        limit: int = 100,
    ) -> list[FormSession]:
        sessions: list[FormSession] = []
        for path in sorted(
            self._root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
        ):
            try:
                session = FormSession(**json.loads(path.read_text(encoding="utf-8")))
            except Exception as exc:  # noqa: BLE001 - one bad file must not hide the rest
                logger.warning(
                    "skipping unreadable session file",
                    extra={"path": str(path), "error": str(exc)},
                )
                continue
            if form_name is not None and session.form_name != form_name:
                continue
            if status is not None and session.status is not status:
                continue
            if participant is not None and participant not in session.participants:
                continue
            sessions.append(session)
            if len(sessions) >= limit:
                break
        return sessions


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------


class ArtifactStore(ABC):
    """Stores rendered documents and their metadata."""

    @abstractmethod
    async def put(self, record: ArtifactRecord, content: bytes) -> ArtifactRecord:
        ...

    @abstractmethod
    async def get(self, artifact_id: str) -> ArtifactRecord:
        ...

    @abstractmethod
    async def read(self, artifact_id: str) -> bytes:
        ...

    @abstractmethod
    async def update(self, record: ArtifactRecord) -> ArtifactRecord:
        ...

    @abstractmethod
    async def list_artifacts(
        self, *, session_id: str | None = None, limit: int = 100
    ) -> list[ArtifactRecord]:
        ...

    @staticmethod
    def checksum(content: bytes) -> str:
        """SHA-256 of the bytes.

        Recorded at baseline time: an artifact whose bytes no longer hash to
        the recorded value has been altered since approval.
        """
        return hashlib.sha256(content).hexdigest()


class InMemoryArtifactStore(ArtifactStore):
    def __init__(self) -> None:
        self._records: dict[str, ArtifactRecord] = {}
        self._blobs: dict[str, bytes] = {}
        self._lock = asyncio.Lock()

    async def put(self, record: ArtifactRecord, content: bytes) -> ArtifactRecord:
        async with self._lock:
            record.size_bytes = len(content)
            record.checksum = self.checksum(content)
            record.location = f"memory://{record.id}"
            self._records[record.id] = record.model_copy(deep=True)
            self._blobs[record.id] = content
            return record

    async def get(self, artifact_id: str) -> ArtifactRecord:
        async with self._lock:
            found = self._records.get(artifact_id)
            if found is None:
                raise NotFoundError(
                    f"artifact '{artifact_id}' was not found", details={"artifact_id": artifact_id}
                )
            return found.model_copy(deep=True)

    async def read(self, artifact_id: str) -> bytes:
        async with self._lock:
            blob = self._blobs.get(artifact_id)
            if blob is None:
                raise NotFoundError(
                    f"artifact '{artifact_id}' has no stored content",
                    details={"artifact_id": artifact_id},
                )
            return blob

    async def update(self, record: ArtifactRecord) -> ArtifactRecord:
        async with self._lock:
            if record.id not in self._records:
                raise NotFoundError(
                    f"artifact '{record.id}' was not found", details={"artifact_id": record.id}
                )
            self._records[record.id] = record.model_copy(deep=True)
            return record

    async def list_artifacts(
        self, *, session_id: str | None = None, limit: int = 100
    ) -> list[ArtifactRecord]:
        async with self._lock:
            found = [
                r.model_copy(deep=True)
                for r in sorted(self._records.values(), key=lambda r: r.created_at, reverse=True)
                if session_id is None or r.session_id == session_id
            ]
            return found[:limit]


class FileArtifactStore(ArtifactStore):
    """Filesystem artifact store: bytes beside a JSON sidecar."""

    def __init__(self, root: Path | str = ".sa/artifacts") -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    def _blob_path(self, record: ArtifactRecord) -> Path:
        safe = _UNSAFE_FILENAME.sub("_", record.filename or f"{record.id}.{record.format}")
        return self._root / record.id / safe

    def _meta_path(self, artifact_id: str) -> Path:
        safe = _UNSAFE_FILENAME.sub("_", artifact_id)
        return self._root / safe / "metadata.json"

    async def put(self, record: ArtifactRecord, content: bytes) -> ArtifactRecord:
        async with self._lock:
            record.size_bytes = len(content)
            record.checksum = self.checksum(content)
            blob = self._blob_path(record)
            blob.parent.mkdir(parents=True, exist_ok=True)
            blob.write_bytes(content)
            record.location = str(blob)
            self._meta_path(record.id).write_text(
                record.model_dump_json(indent=2), encoding="utf-8"
            )
            return record

    async def get(self, artifact_id: str) -> ArtifactRecord:
        path = self._meta_path(artifact_id)
        if not path.is_file():
            raise NotFoundError(
                f"artifact '{artifact_id}' was not found", details={"artifact_id": artifact_id}
            )
        return ArtifactRecord(**json.loads(path.read_text(encoding="utf-8")))

    async def read(self, artifact_id: str) -> bytes:
        record = await self.get(artifact_id)
        blob = Path(record.location)
        if not blob.is_file():
            raise NotFoundError(
                f"artifact '{artifact_id}' content is missing from {blob}",
                details={"artifact_id": artifact_id},
            )
        return blob.read_bytes()

    async def update(self, record: ArtifactRecord) -> ArtifactRecord:
        async with self._lock:
            path = self._meta_path(record.id)
            if not path.is_file():
                raise NotFoundError(
                    f"artifact '{record.id}' was not found", details={"artifact_id": record.id}
                )
            path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
            return record

    async def list_artifacts(
        self, *, session_id: str | None = None, limit: int = 100
    ) -> list[ArtifactRecord]:
        records: list[ArtifactRecord] = []
        for meta in sorted(
            self._root.glob("*/metadata.json"), key=lambda p: p.stat().st_mtime, reverse=True
        ):
            try:
                record = ArtifactRecord(**json.loads(meta.read_text(encoding="utf-8")))
            except Exception as exc:  # noqa: BLE001 - one bad file must not hide the rest
                logger.warning(
                    "skipping unreadable artifact sidecar",
                    extra={"path": str(meta), "error": str(exc)},
                )
                continue
            if session_id is not None and record.session_id != session_id:
                continue
            records.append(record)
            if len(records) >= limit:
                break
        return records


def build_session_store(backend: str = "memory", **kwargs: object) -> SessionStore:
    if backend == "memory":
        return InMemorySessionStore(**kwargs)  # type: ignore[arg-type]
    if backend == "file":
        return FileSessionStore(**kwargs)  # type: ignore[arg-type]
    from sa_platform.errors import ConfigurationError

    raise ConfigurationError(
        f"unsupported session store backend '{backend}'",
        details={"backend": backend, "supported": ["memory", "file"]},
    )


def build_artifact_store(backend: str = "memory", **kwargs: object) -> ArtifactStore:
    if backend == "memory":
        return InMemoryArtifactStore()
    if backend == "file":
        return FileArtifactStore(**kwargs)  # type: ignore[arg-type]
    from sa_platform.errors import ConfigurationError

    raise ConfigurationError(
        f"unsupported artifact store backend '{backend}'",
        details={"backend": backend, "supported": ["memory", "file"]},
    )


def utc_stamp() -> str:
    """Filename-safe timestamp used when naming artifacts."""
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


__all__ = [
    "ArtifactStore",
    "FileArtifactStore",
    "FileSessionStore",
    "InMemoryArtifactStore",
    "InMemorySessionStore",
    "SessionStore",
    "build_artifact_store",
    "build_session_store",
    "utc_stamp",
]
