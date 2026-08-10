"""Resilient HTTP connector.

Wraps ``httpx`` with the platform's retry policy, circuit breaker, deadline
propagation, and error taxonomy. Every outbound API integration should go
through this rather than instantiating its own client, so failures are
classified consistently and one flaky dependency cannot exhaust the pool.
"""

from __future__ import annotations

from typing import Any

import httpx

from sa_platform.config import get_settings
from sa_platform.context import current_context
from sa_platform.errors import (
    AuthenticationError,
    AuthorizationError,
    DependencyError,
    NotFoundError,
    RateLimitError,
    TimeoutError_,
    ValidationError,
)
from sa_platform.health import CheckResult
from sa_platform.logging import get_logger
from sa_platform.resilience import CircuitBreaker, RetryPolicy, retry_async
from sa_platform.telemetry import get_tracer, metrics

from .auth import AuthStrategy, NoAuth
from .base import Connector, ConnectorState

logger = get_logger(__name__)
tracer = get_tracer("sa.connectors.http")


def _classify(response: httpx.Response, url: str) -> None:
    """Translate an HTTP status into the platform error taxonomy.

    This is what makes retry decisions correct downstream: a 429 or 503 is
    marked retryable, a 400 or 404 is not.
    """
    status = response.status_code
    if status < 400:
        return

    body = response.text[:1000]
    details = {"url": url, "status_code": status, "body": body}

    if status == 401:
        raise AuthenticationError(f"upstream rejected credentials ({status})", details=details)
    if status == 403:
        raise AuthorizationError(f"upstream denied access ({status})", details=details)
    if status == 404:
        raise NotFoundError(f"upstream resource not found ({status})", details=details)
    if status == 408 or status == 504:
        raise TimeoutError_(f"upstream timed out ({status})", details=details)
    if status == 429:
        retry_after = response.headers.get("retry-after")
        raise RateLimitError(
            f"upstream rate limited the request ({status})",
            retry_after=float(retry_after) if retry_after and retry_after.isdigit() else None,
            details=details,
        )
    if 400 <= status < 500:
        raise ValidationError(f"upstream rejected the request ({status})", details=details)

    raise DependencyError(f"upstream returned {status}", details=details)


class HttpConnector(Connector):
    """A configured, resilient client for one upstream HTTP service."""

    def __init__(
        self,
        name: str,
        base_url: str,
        *,
        auth: AuthStrategy | None = None,
        default_headers: dict[str, str] | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
        verify_tls: bool = True,
        max_connections: int = 100,
    ) -> None:
        super().__init__(name)
        settings = get_settings().resilience
        self._base_url = base_url.rstrip("/")
        self._auth = auth or NoAuth()
        self._default_headers = default_headers or {}
        self._timeout = timeout_seconds or settings.default_timeout_seconds
        self._verify_tls = verify_tls
        self._max_connections = max_connections
        self._client: httpx.AsyncClient | None = None
        self._breaker = CircuitBreaker.from_settings(f"http:{name}")
        self._retry_policy = RetryPolicy.from_settings(
            **({"max_attempts": max_retries + 1} if max_retries is not None else {})
        )

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def circuit_state(self) -> str:
        return self._breaker.state.value

    # -- lifecycle --------------------------------------------------------
    async def connect(self) -> None:
        if self._client is not None:
            return
        self._set_state(ConnectorState.CONNECTING)
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            verify=self._verify_tls,
            limits=httpx.Limits(
                max_connections=self._max_connections,
                max_keepalive_connections=min(20, self._max_connections),
            ),
            follow_redirects=False,
        )
        self._set_state(ConnectorState.READY)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._set_state(ConnectorState.CLOSED)

    async def health(self) -> CheckResult:
        if self._client is None:
            return CheckResult.unhealthy(f"connector '{self.name}' is not connected")
        if self._breaker.state.value == "open":
            return CheckResult.degraded(
                f"circuit for '{self.name}' is open", circuit=self._breaker.state.value
            )
        return CheckResult.healthy(f"connector '{self.name}' is ready", base_url=self._base_url)

    # -- requests ---------------------------------------------------------
    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        data: Any = None,
        headers: dict[str, str] | None = None,
        timeout_seconds: float | None = None,
        retry: bool = True,
    ) -> httpx.Response:
        """Issue a request with retry, circuit breaking, and error classification."""
        if self._client is None:
            await self.connect()
        assert self._client is not None  # - guaranteed by connect()

        url = path if path.startswith("http") else f"/{path.lstrip('/')}"
        ctx = current_context()
        timeout = ctx.budget(timeout_seconds or self._timeout)

        async def send() -> httpx.Response:
            merged = await self._auth.apply({**self._default_headers, **(headers or {})})
            # Propagate correlation so upstream logs join with ours.
            merged.setdefault("X-Correlation-Id", ctx.correlation_id)
            try:
                response = await self._client.request(  # type: ignore[union-attr]
                    method.upper(),
                    url,
                    params=params,
                    json=json,
                    data=data,
                    headers=merged,
                    timeout=timeout,
                )
            except httpx.TimeoutException as exc:
                raise TimeoutError_(
                    f"request to {self.name}{url} timed out",
                    details={"connector": self.name, "url": url},
                    cause=exc,
                ) from exc
            except httpx.HTTPError as exc:
                raise DependencyError(
                    f"request to {self.name}{url} failed: {exc}",
                    details={"connector": self.name, "url": url},
                    cause=exc,
                ) from exc

            _classify(response, url)
            return response

        async def guarded() -> httpx.Response:
            return await self._breaker.call(send)

        with tracer.span(
            "http.request", connector=self.name, method=method.upper(), path=url
        ) as span:
            response = (
                await retry_async(guarded, policy=self._retry_policy, operation=f"http:{self.name}")
                if retry
                else await guarded()
            )
            span.set_attribute("status_code", response.status_code)
            metrics.increment(
                "http.responses", connector=self.name, status=response.status_code // 100
            )
            return response

    async def get_json(self, path: str, **kwargs: Any) -> Any:
        response = await self.request("GET", path, **kwargs)
        return response.json()

    async def post_json(self, path: str, json: Any = None, **kwargs: Any) -> Any:
        response = await self.request("POST", path, json=json, **kwargs)
        if not response.content:
            return None
        return response.json()


__all__ = ["HttpConnector"]
