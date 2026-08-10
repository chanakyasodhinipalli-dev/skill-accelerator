"""Sandboxed filesystem tools.

Paths supplied by a model are untrusted input. Every path is resolved to its
canonical form and verified to stay inside the configured root before any I/O
happens — that check is the entire security boundary here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sa_platform.context import ExecutionContext
from sa_platform.errors import ExecutionError, ValidationError

from ..base import Tool
from ..models import DangerLevel, ToolSpec

DEFAULT_MAX_BYTES = 512_000


def _resolve_within(root: Path, candidate: str) -> Path:
    """Resolve ``candidate`` against ``root``, rejecting anything that escapes.

    Catches ``..`` traversal, absolute paths outside the root, and symlinks
    pointing elsewhere (``resolve()`` follows links before the containment
    check).
    """
    if not candidate or candidate.strip() in (".", ".."):
        raise ValidationError("path must be a non-empty relative path inside the sandbox")

    resolved_root = root.resolve()
    target = (resolved_root / candidate).resolve()

    if not target.is_relative_to(resolved_root):
        raise ValidationError(
            "path escapes the sandbox root",
            details={"path": candidate, "root": str(resolved_root)},
        )
    return target


class ReadFileTool(Tool):
    """Read a UTF-8 text file from the sandbox."""

    def __init__(self, root: Path | str = ".", max_bytes: int = DEFAULT_MAX_BYTES) -> None:
        self._root = Path(root)
        self._max_bytes = max_bytes
        super().__init__(
            ToolSpec(
                name="read_file",
                description=(
                    "Read the contents of a UTF-8 text file. Call this when you need the "
                    "actual contents of a file to answer a question or make an edit. "
                    "Paths are relative to the workspace root; paths outside it are rejected."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Workspace-relative path, e.g. 'reports/q3.md'",
                        },
                        "max_bytes": {
                            "type": "integer",
                            "description": f"Truncate after this many bytes (default {max_bytes}).",
                        },
                    },
                    "required": ["path"],
                    "additionalProperties": False,
                },
                danger=DangerLevel.SAFE,
                tags=["filesystem", "read"],
                required_permissions=["files:read"],
            )
        )

    async def invoke(self, ctx: ExecutionContext, arguments: dict[str, Any]) -> Any:
        target = _resolve_within(self._root, arguments["path"])
        if not target.is_file():
            raise ExecutionError(f"file not found: {arguments['path']}")

        limit = min(int(arguments.get("max_bytes") or self._max_bytes), self._max_bytes)
        raw = target.read_bytes()
        truncated = len(raw) > limit
        text = raw[:limit].decode("utf-8", errors="replace")

        return {
            "path": arguments["path"],
            "content": text,
            "bytes": len(raw),
            "truncated": truncated,
        }


class WriteFileTool(Tool):
    """Write a UTF-8 text file into the sandbox."""

    def __init__(self, root: Path | str = ".", max_bytes: int = DEFAULT_MAX_BYTES) -> None:
        self._root = Path(root)
        self._max_bytes = max_bytes
        super().__init__(
            ToolSpec(
                name="write_file",
                description=(
                    "Create or overwrite a UTF-8 text file. Call this only when the user has "
                    "asked for a file to be produced or changed. Overwrites without warning; "
                    "read the file first if you need to preserve existing content."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Workspace-relative path."},
                        "content": {"type": "string", "description": "Full file contents."},
                        "create_parents": {
                            "type": "boolean",
                            "description": "Create missing parent directories (default true).",
                        },
                    },
                    "required": ["path", "content"],
                    "additionalProperties": False,
                },
                danger=DangerLevel.MEDIUM,
                tags=["filesystem", "write"],
                required_permissions=["files:write"],
                idempotent=True,
                parallel_safe=False,
            )
        )

    async def invoke(self, ctx: ExecutionContext, arguments: dict[str, Any]) -> Any:
        content: str = arguments["content"]
        encoded = content.encode("utf-8")
        if len(encoded) > self._max_bytes:
            raise ValidationError(
                f"content exceeds the {self._max_bytes} byte limit",
                details={"bytes": len(encoded), "limit": self._max_bytes},
            )

        target = _resolve_within(self._root, arguments["path"])
        if arguments.get("create_parents", True):
            target.parent.mkdir(parents=True, exist_ok=True)

        existed = target.exists()
        target.write_text(content, encoding="utf-8")

        return {
            "path": arguments["path"],
            "bytes_written": len(encoded),
            "overwrote_existing": existed,
        }


__all__ = ["ReadFileTool", "WriteFileTool"]
