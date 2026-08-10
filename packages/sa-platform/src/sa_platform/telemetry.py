"""Tracing and metrics with a no-op fallback.

OpenTelemetry is an optional dependency. When it is absent (or telemetry is
disabled) the facade degrades to in-process counters and a span object that
does nothing, so instrumentation calls are always safe to write.
"""

from __future__ import annotations

import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from .config import get_settings
from .context import current_context

try:  # pragma: no cover - import-time capability probe
    from opentelemetry import trace as _otel_trace

    _OTEL_AVAILABLE = True
except ImportError:  # pragma: no cover
    _otel_trace = None  # type: ignore[assignment]
    _OTEL_AVAILABLE = False


class Span:
    """Minimal span facade. Wraps an OTel span when one is available."""

    __slots__ = ("_otel", "_attributes")

    def __init__(self, otel_span: Any = None) -> None:
        self._otel = otel_span
        self._attributes: dict[str, Any] = {}

    def set_attribute(self, key: str, value: Any) -> None:
        self._attributes[key] = value
        if self._otel is not None:  # pragma: no cover - requires otel
            self._otel.set_attribute(key, value)

    def set_attributes(self, attributes: Mapping[str, Any]) -> None:
        for key, value in attributes.items():
            self.set_attribute(key, value)

    def add_event(self, name: str, attributes: Mapping[str, Any] | None = None) -> None:
        if self._otel is not None:  # pragma: no cover - requires otel
            self._otel.add_event(name, dict(attributes or {}))

    def record_exception(self, exc: BaseException) -> None:
        self.set_attribute("error", True)
        self.set_attribute("error.type", type(exc).__name__)
        code = getattr(exc, "code", None)
        if code is not None:
            self.set_attribute("error.code", getattr(code, "value", str(code)))
        if self._otel is not None:  # pragma: no cover - requires otel
            self._otel.record_exception(exc)

    @property
    def attributes(self) -> dict[str, Any]:
        return dict(self._attributes)


@dataclass
class MetricSnapshot:
    """Point-in-time read of the in-process metric registry."""

    counters: dict[str, float] = field(default_factory=dict)
    histograms: dict[str, list[float]] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        out: dict[str, Any] = {"counters": dict(self.counters), "histograms": {}}
        for name, values in self.histograms.items():
            if not values:
                continue
            ordered = sorted(values)
            out["histograms"][name] = {
                "count": len(ordered),
                "min": ordered[0],
                "max": ordered[-1],
                "mean": sum(ordered) / len(ordered),
                "p50": ordered[len(ordered) // 2],
                "p95": ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))],
            }
        return out


class Metrics:
    """Thread-safe in-process metrics.

    Deliberately simple: this is a health/debug surface and a test seam, not a
    replacement for a real metrics backend. Wire the OTLP exporter for that.
    """

    def __init__(self, *, max_samples: int = 2048) -> None:
        self._lock = Lock()
        self._counters: dict[str, float] = {}
        self._histograms: dict[str, list[float]] = {}
        self._max_samples = max_samples

    @staticmethod
    def _key(name: str, labels: Mapping[str, Any] | None) -> str:
        if not labels:
            return name
        rendered = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{rendered}}}"

    def increment(self, name: str, value: float = 1.0, **labels: Any) -> None:
        key = self._key(name, labels)
        with self._lock:
            self._counters[key] = self._counters.get(key, 0.0) + value

    def observe(self, name: str, value: float, **labels: Any) -> None:
        key = self._key(name, labels)
        with self._lock:
            samples = self._histograms.setdefault(key, [])
            samples.append(value)
            if len(samples) > self._max_samples:
                # Keep the most recent window; older samples stop being useful.
                del samples[: len(samples) - self._max_samples]

    def snapshot(self) -> MetricSnapshot:
        with self._lock:
            return MetricSnapshot(
                counters=dict(self._counters),
                histograms={k: list(v) for k, v in self._histograms.items()},
            )

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._histograms.clear()


metrics = Metrics()


class Tracer:
    """Span factory. Falls back to no-op spans without OpenTelemetry."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._otel = None
        settings = get_settings()
        if _OTEL_AVAILABLE and settings.telemetry.enabled:  # pragma: no cover
            self._otel = _otel_trace.get_tracer(name)

    @contextmanager
    def span(self, name: str, **attributes: Any) -> Iterator[Span]:
        """Time a block, record failures, and emit duration/error metrics."""
        ctx = current_context()
        started = time.perf_counter()

        if self._otel is not None:  # pragma: no cover - requires otel
            with self._otel.start_as_current_span(name) as otel_span:
                span = Span(otel_span)
                yield from self._run(span, name, attributes, ctx, started)
        else:
            span = Span()
            yield from self._run(span, name, attributes, ctx, started)

    def _run(
        self,
        span: Span,
        name: str,
        attributes: Mapping[str, Any],
        ctx: Any,
        started: float,
    ) -> Iterator[Span]:
        span.set_attribute("correlation_id", ctx.correlation_id)
        if ctx.tenant_id:
            span.set_attribute("tenant_id", ctx.tenant_id)
        span.set_attributes(attributes)
        try:
            yield span
        except BaseException as exc:
            span.record_exception(exc)
            metrics.increment(f"{name}.errors", error=type(exc).__name__)
            raise
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            span.set_attribute("duration_ms", round(elapsed_ms, 3))
            metrics.observe(f"{name}.duration_ms", elapsed_ms)
            metrics.increment(f"{name}.calls")


_tracers: dict[str, Tracer] = {}
_tracer_lock = Lock()


def get_tracer(name: str) -> Tracer:
    with _tracer_lock:
        tracer = _tracers.get(name)
        if tracer is None:
            tracer = Tracer(name)
            _tracers[name] = tracer
        return tracer


def otel_available() -> bool:
    return _OTEL_AVAILABLE


__all__ = ["MetricSnapshot", "Metrics", "Span", "Tracer", "get_tracer", "metrics", "otel_available"]
