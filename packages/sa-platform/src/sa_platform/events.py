"""In-process asynchronous event bus.

Used for audit trails, progress streaming, and side effects that must not
block the critical path. Handler failures are logged and swallowed: an audit
sink going down must never fail the business operation it was observing.

The interface is intentionally narrow so it can be backed by Kafka, SNS, or a
database outbox later without touching call sites.
"""

from __future__ import annotations

import asyncio
import fnmatch
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from .context import current_context
from .logging import get_logger
from .telemetry import metrics

logger = get_logger(__name__)

EventHandler = Callable[["Event"], Awaitable[None] | None]


@dataclass(frozen=True, slots=True)
class Event:
    """A domain occurrence. ``name`` is dotted, e.g. ``skill.completed``."""

    name: str
    payload: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)
    correlation_id: str = field(default_factory=lambda: current_context().correlation_id)
    source: str = "platform"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "timestamp": self.timestamp,
            "correlation_id": self.correlation_id,
            "source": self.source,
            "payload": self.payload,
        }


class EventBus:
    """Topic-based pub/sub with glob subscriptions (``skill.*``, ``*``)."""

    def __init__(self, *, max_concurrent_handlers: int = 32) -> None:
        self._subscribers: dict[str, list[EventHandler]] = {}
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(max_concurrent_handlers)
        self._background: set[asyncio.Task[None]] = set()

    def subscribe(self, pattern: str, handler: EventHandler) -> Callable[[], None]:
        """Register a handler. Returns a callable that unsubscribes it."""
        self._subscribers.setdefault(pattern, []).append(handler)

        def unsubscribe() -> None:
            handlers = self._subscribers.get(pattern, [])
            if handler in handlers:
                handlers.remove(handler)

        return unsubscribe

    def _matching(self, name: str) -> list[EventHandler]:
        matched: list[EventHandler] = []
        for pattern, handlers in self._subscribers.items():
            if pattern == name or fnmatch.fnmatchcase(name, pattern):
                matched.extend(handlers)
        return matched

    async def publish(self, event: Event) -> None:
        """Deliver to all matching handlers, awaiting completion.

        Handler exceptions are logged and isolated — one bad subscriber cannot
        break delivery to the others or to the publisher.
        """
        handlers = self._matching(event.name)
        if not handlers:
            return

        metrics.increment("events.published", event=event.name)

        async def invoke(handler: EventHandler) -> None:
            async with self._semaphore:
                try:
                    result = handler(event)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    metrics.increment("events.handler_errors", event=event.name)
                    logger.exception(
                        "event handler failed",
                        extra={"event": event.name, "handler": getattr(handler, "__name__", "?")},
                    )

        await asyncio.gather(*(invoke(h) for h in handlers))

    async def emit(self, name: str, **payload: Any) -> None:
        """Convenience wrapper around :meth:`publish`."""
        await self.publish(Event(name=name, payload=payload))

    def emit_nowait(self, name: str, **payload: Any) -> None:
        """Fire-and-forget from a running loop; a no-op outside one.

        Task references are retained until completion so the garbage collector
        cannot cancel an in-flight handler.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(self.emit(name, **payload))
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def drain(self) -> None:
        """Await any fire-and-forget deliveries. Call before shutdown."""
        if self._background:
            await asyncio.gather(*list(self._background), return_exceptions=True)


event_bus = EventBus()


# Canonical event names. Referencing these constants keeps subscribers and
# publishers from drifting apart on string literals.
class Events:
    SKILL_STARTED = "skill.started"
    SKILL_COMPLETED = "skill.completed"
    SKILL_FAILED = "skill.failed"

    TOOL_INVOKED = "tool.invoked"
    TOOL_COMPLETED = "tool.completed"
    TOOL_FAILED = "tool.failed"
    TOOL_APPROVAL_REQUIRED = "tool.approval_required"
    TOOL_DENIED = "tool.denied"

    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_COMPLETED = "workflow.completed"
    WORKFLOW_FAILED = "workflow.failed"
    STEP_STARTED = "workflow.step.started"
    STEP_COMPLETED = "workflow.step.completed"
    STEP_FAILED = "workflow.step.failed"
    STEP_SKIPPED = "workflow.step.skipped"
    COMPENSATION_RAN = "workflow.compensation.ran"

    CONNECTOR_CONNECTED = "connector.connected"
    CONNECTOR_FAILED = "connector.failed"

    LLM_REQUEST = "llm.request"
    LLM_RESPONSE = "llm.response"


__all__ = ["Event", "EventBus", "EventHandler", "Events", "event_bus"]
