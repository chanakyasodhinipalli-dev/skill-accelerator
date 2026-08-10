"""Outbound authentication strategies.

Credentials are supplied as secret *references* and resolved at request time
through the platform's secret provider, so a rotated secret takes effect
without a redeploy and no plaintext credential is held in a config object.
"""

from __future__ import annotations

import base64
import time
from abc import ABC, abstractmethod
from typing import Any

import httpx

from sa_platform.errors import AuthenticationError, ConfigurationError
from sa_platform.logging import get_logger
from sa_platform.security import resolve_secret

logger = get_logger(__name__)


class AuthStrategy(ABC):
    """Mutates an outgoing request to carry credentials."""

    @abstractmethod
    async def apply(self, headers: dict[str, str]) -> dict[str, str]:
        """Return headers with authentication applied."""

    async def refresh(self) -> None:
        """Force credential renewal. No-op for static strategies."""


class NoAuth(AuthStrategy):
    async def apply(self, headers: dict[str, str]) -> dict[str, str]:
        return headers


class ApiKeyAuth(AuthStrategy):
    """API key in a header (default ``X-API-Key``)."""

    def __init__(self, key_ref: str, *, header: str = "X-API-Key", prefix: str = "") -> None:
        self._key_ref = key_ref
        self._header = header
        self._prefix = prefix

    async def apply(self, headers: dict[str, str]) -> dict[str, str]:
        key = resolve_secret(self._key_ref, required=True)
        return {**headers, self._header: f"{self._prefix}{key}"}


class BearerAuth(AuthStrategy):
    """Static bearer token."""

    def __init__(self, token_ref: str) -> None:
        self._token_ref = token_ref

    async def apply(self, headers: dict[str, str]) -> dict[str, str]:
        token = resolve_secret(self._token_ref, required=True)
        return {**headers, "Authorization": f"Bearer {token}"}


class BasicAuth(AuthStrategy):
    def __init__(self, username_ref: str, password_ref: str) -> None:
        self._username_ref = username_ref
        self._password_ref = password_ref

    async def apply(self, headers: dict[str, str]) -> dict[str, str]:
        username = resolve_secret(self._username_ref, required=True)
        password = resolve_secret(self._password_ref, required=True)
        encoded = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
        return {**headers, "Authorization": f"Basic {encoded}"}


class OAuth2ClientCredentials(AuthStrategy):
    """OAuth2 client-credentials grant with token caching and pre-emptive refresh.

    Tokens are refreshed ``leeway`` seconds before nominal expiry so an
    in-flight request never races the expiry boundary.
    """

    def __init__(
        self,
        *,
        token_url: str,
        client_id_ref: str,
        client_secret_ref: str,
        scope: str | None = None,
        audience: str | None = None,
        leeway_seconds: float = 60.0,
    ) -> None:
        self._token_url = token_url
        self._client_id_ref = client_id_ref
        self._client_secret_ref = client_secret_ref
        self._scope = scope
        self._audience = audience
        self._leeway = leeway_seconds
        self._token: str | None = None
        self._expires_at: float = 0.0

    def _is_valid(self) -> bool:
        return self._token is not None and time.monotonic() < (self._expires_at - self._leeway)

    async def apply(self, headers: dict[str, str]) -> dict[str, str]:
        if not self._is_valid():
            await self.refresh()
        return {**headers, "Authorization": f"Bearer {self._token}"}

    async def refresh(self) -> None:
        client_id = resolve_secret(self._client_id_ref, required=True)
        client_secret = resolve_secret(self._client_secret_ref, required=True)

        form: dict[str, str] = {
            "grant_type": "client_credentials",
            "client_id": client_id or "",
            "client_secret": client_secret or "",
        }
        if self._scope:
            form["scope"] = self._scope
        if self._audience:
            form["audience"] = self._audience

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(self._token_url, data=form)
                response.raise_for_status()
                payload: dict[str, Any] = response.json()
        except httpx.HTTPStatusError as exc:
            raise AuthenticationError(
                f"OAuth2 token request failed with HTTP {exc.response.status_code}",
                details={"token_url": self._token_url},
                cause=exc,
            ) from exc
        except httpx.HTTPError as exc:
            raise AuthenticationError(
                f"OAuth2 token request to {self._token_url} failed: {exc}", cause=exc
            ) from exc

        token = payload.get("access_token")
        if not token:
            raise AuthenticationError(
                "OAuth2 token response contained no access_token",
                details={"token_url": self._token_url},
            )

        self._token = token
        self._expires_at = time.monotonic() + float(payload.get("expires_in", 3600))
        logger.info(
            "refreshed OAuth2 token",
            extra={"token_url": self._token_url, "expires_in": payload.get("expires_in")},
        )


def build_auth(config: dict[str, Any] | None) -> AuthStrategy:
    """Construct a strategy from a declarative config block.

    Example::

        {"type": "oauth2_client_credentials",
         "token_url": "https://id.example.com/oauth/token",
         "client_id_ref": "env:PARTNER_CLIENT_ID",
         "client_secret_ref": "env:PARTNER_CLIENT_SECRET"}
    """
    if not config:
        return NoAuth()

    kind = config.get("type", "none")
    try:
        if kind == "none":
            return NoAuth()
        if kind == "api_key":
            return ApiKeyAuth(
                config["key_ref"],
                header=config.get("header", "X-API-Key"),
                prefix=config.get("prefix", ""),
            )
        if kind == "bearer":
            return BearerAuth(config["token_ref"])
        if kind == "basic":
            return BasicAuth(config["username_ref"], config["password_ref"])
        if kind == "oauth2_client_credentials":
            return OAuth2ClientCredentials(
                token_url=config["token_url"],
                client_id_ref=config["client_id_ref"],
                client_secret_ref=config["client_secret_ref"],
                scope=config.get("scope"),
                audience=config.get("audience"),
            )
    except KeyError as exc:
        raise ConfigurationError(
            f"auth config of type '{kind}' is missing required field {exc}",
            details={"type": kind},
        ) from exc

    raise ConfigurationError(f"unknown auth type '{kind}'", details={"type": kind})


__all__ = [
    "ApiKeyAuth",
    "AuthStrategy",
    "BasicAuth",
    "BearerAuth",
    "NoAuth",
    "OAuth2ClientCredentials",
    "build_auth",
]
