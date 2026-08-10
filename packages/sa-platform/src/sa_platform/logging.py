"""Structured logging with automatic context enrichment and secret redaction.

Log records carry the ambient :class:`~sa_platform.context.ExecutionContext`
fields (correlation id, principal, run/step ids) without callers passing them,
so a single correlation id ties an API request to every skill, tool, and
upstream call it triggered.
"""

from __future__ import annotations

import json
import logging
import logging.config
import sys
import traceback
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from .config import LoggingSettings, get_settings
from .context import current_context

# Attributes present on every LogRecord; anything else the caller attached via
# `extra=` is treated as structured payload.
_RESERVED = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "stacklevel",
        "thread",
        "threadName",
        "taskName",
    }
)

_REDACTED = "***REDACTED***"


class PlatformLogger(logging.Logger):
    """A logger where a reserved field name degrades instead of raising.

    ``Logger.makeRecord`` raises ``KeyError`` if ``extra`` carries a key that
    already exists on a ``LogRecord`` — ``message``, ``name``, ``filename``,
    ``module``, and a dozen others. Structured logging positively invites those
    words: an attachment has a filename, a rejected request has a message.

    The failure mode is the problem. The exception is raised *at the log call*,
    so it propagates out of whatever was being reported — an error handler
    logging a 404 raises a 500 instead of returning the 404. Renaming the key
    keeps the field, keeps the log line, and keeps the original outcome.
    """

    def makeRecord(  # - signature fixed by the stdlib
        self,
        name: str,
        level: int,
        fn: str,
        lno: int,
        msg: object,
        args: Any,
        exc_info: Any,
        func: str | None = None,
        extra: Mapping[str, Any] | None = None,
        sinfo: str | None = None,
    ) -> logging.LogRecord:
        if extra:
            collisions = _RESERVED & set(extra)
            if collisions:
                extra = {(f"{k}_" if k in collisions else k): v for k, v in extra.items()}
        return super().makeRecord(name, level, fn, lno, msg, args, exc_info, func, extra, sinfo)


# Installed at import so every `get_logger` call gets the safe class. Loggers
# third-party libraries created before this point keep the stdlib behaviour,
# which is correct — their fields are their business.
logging.setLoggerClass(PlatformLogger)


def redact(value: Any, keys: frozenset[str], _depth: int = 0) -> Any:
    """Recursively mask values whose key looks sensitive.

    Matching is substring-based and case-insensitive, so ``customerApiKey``
    is caught by the ``api_key`` rule after normalisation.
    """
    if _depth > 6:
        return value
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for k, v in value.items():
            normalised = str(k).lower().replace("-", "_")
            if any(sensitive in normalised for sensitive in keys):
                out[str(k)] = _REDACTED
            else:
                out[str(k)] = redact(v, keys, _depth + 1)
        return out
    if isinstance(value, (list, tuple, set)):
        return [redact(v, keys, _depth + 1) for v in value]
    return value


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per line — the shape log shippers expect."""

    def __init__(self, settings: LoggingSettings, service: str, environment: str) -> None:
        super().__init__()
        self._settings = settings
        self._service = service
        self._environment = environment
        self._redact_keys = frozenset(k.lower() for k in settings.redact_keys)

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            # Built from the record's epoch value rather than strftime: the
            # millisecond field has no portable strftime directive.
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self._service,
            "environment": self._environment,
        }

        if self._settings.include_context:
            payload.update(current_context().log_fields())

        extras = {k: v for k, v in record.__dict__.items() if k not in _RESERVED}
        if extras:
            payload["data"] = redact(extras, self._redact_keys)

        if record.exc_info:
            exc_type, exc_value, exc_tb = record.exc_info
            payload["error"] = {
                "type": getattr(exc_type, "__name__", str(exc_type)),
                "message": str(exc_value),
                "stack": "".join(traceback.format_exception(exc_type, exc_value, exc_tb))[-8000:],
            }
            # Surface the platform error code so log-based alerting can filter on it.
            code = getattr(exc_value, "code", None)
            if code is not None:
                payload["error"]["code"] = getattr(code, "value", str(code))

        return json.dumps(payload, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Human-readable format for local development."""

    def __init__(self, settings: LoggingSettings) -> None:
        super().__init__("%(asctime)s %(levelname)-7s %(name)s | %(message)s")
        self._settings = settings

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        if self._settings.include_context:
            ctx = current_context()
            base = f"{base} [cid={ctx.correlation_id[:8]}]"
        extras = {k: v for k, v in record.__dict__.items() if k not in _RESERVED}
        if extras:
            keys = frozenset(k.lower() for k in self._settings.redact_keys)
            base = f"{base} {json.dumps(redact(extras, keys), default=str)}"
        return base


_configured = False


def configure_logging(*, force: bool = False) -> None:
    """Install the platform handler on the root logger. Idempotent."""
    global _configured
    if _configured and not force:
        return

    settings = get_settings()
    formatter: logging.Formatter
    if settings.logging.format == "json":
        formatter = JsonFormatter(settings.logging, settings.service_name, settings.environment)
    else:
        formatter = TextFormatter(settings.logging)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(settings.logging.level)

    # These libraries are chatty at INFO and add nothing at our altitude.
    for noisy in ("httpx", "httpcore", "urllib3", "asyncio", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger. Safe to call at import time."""
    configure_logging()
    return logging.getLogger(name)


__all__ = [
    "JsonFormatter",
    "PlatformLogger",
    "TextFormatter",
    "configure_logging",
    "get_logger",
    "redact",
]
