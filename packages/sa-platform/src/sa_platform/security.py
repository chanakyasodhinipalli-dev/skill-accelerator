"""Secret resolution and authorization helpers.

Secrets are never held in configuration objects as plain strings. Components
declare a secret *reference* (``env:MY_KEY``, ``file:/run/secrets/token``) and
resolve it through a :class:`SecretProvider` at the point of use.
"""

from __future__ import annotations

import hmac
import os
from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path
from threading import RLock

from .context import Principal
from .errors import AuthorizationError, ConfigurationError


class SecretProvider(ABC):
    """Resolves a secret reference to its value."""

    @abstractmethod
    def get(self, reference: str) -> str | None:
        """Return the secret, or ``None`` when the reference is unresolvable."""

    def require(self, reference: str) -> str:
        value = self.get(reference)
        if value is None:
            raise ConfigurationError(
                f"secret '{reference}' could not be resolved",
                details={"reference": reference, "provider": type(self).__name__},
            )
        return value


class EnvSecretProvider(SecretProvider):
    """Reads ``env:NAME`` references (and bare names) from the process environment."""

    def __init__(self, prefix: str = "") -> None:
        self._prefix = prefix

    def get(self, reference: str) -> str | None:
        name = reference.removeprefix("env:")
        return os.environ.get(f"{self._prefix}{name}") or os.environ.get(name)


class FileSecretProvider(SecretProvider):
    """Reads ``file:/path`` references — the mounted-secret pattern used by
    Kubernetes and Docker secrets."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base = base_dir

    def get(self, reference: str) -> str | None:
        raw = reference.removeprefix("file:")
        path = Path(raw)
        if not path.is_absolute() and self._base is not None:
            path = self._base / path
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return None


class StaticSecretProvider(SecretProvider):
    """In-memory provider. Intended for tests and local development."""

    def __init__(self, secrets: dict[str, str] | None = None) -> None:
        self._secrets = dict(secrets or {})

    def set(self, reference: str, value: str) -> None:
        self._secrets[reference] = value

    def get(self, reference: str) -> str | None:
        return self._secrets.get(reference)


class ChainedSecretProvider(SecretProvider):
    """Tries each provider in order and returns the first hit.

    Route by scheme where one is present so a ``file:`` reference never falls
    through to the environment.
    """

    def __init__(self, providers: Sequence[SecretProvider]) -> None:
        if not providers:
            raise ConfigurationError("ChainedSecretProvider requires at least one provider")
        self._providers = list(providers)

    def get(self, reference: str) -> str | None:
        for provider in self._providers:
            if reference.startswith("file:") and not isinstance(provider, FileSecretProvider):
                continue
            value = provider.get(reference)
            if value is not None:
                return value
        return None


_provider: SecretProvider = ChainedSecretProvider([EnvSecretProvider(), FileSecretProvider()])
_provider_lock = RLock()


def get_secret_provider() -> SecretProvider:
    with _provider_lock:
        return _provider


def set_secret_provider(provider: SecretProvider) -> None:
    """Swap the process-wide provider (vault client, cloud secret manager, ...)."""
    global _provider
    with _provider_lock:
        _provider = provider


def resolve_secret(reference: str | None, *, required: bool = False) -> str | None:
    """Resolve a reference, or pass a literal through unchanged.

    A value with no recognised scheme is treated as a literal so that plain
    strings still work in local development.
    """
    if reference is None:
        if required:
            raise ConfigurationError("a required secret reference was not provided")
        return None
    if reference.startswith(("env:", "file:")):
        provider = get_secret_provider()
        return provider.require(reference) if required else provider.get(reference)
    return reference


def constant_time_compare(a: str, b: str) -> bool:
    """Timing-attack-resistant comparison for tokens and signatures."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def authorize(principal: Principal, required: Sequence[str], *, resource: str = "") -> None:
    """Raise :class:`AuthorizationError` unless every permission is held."""
    if not required:
        return
    missing = principal.missing_permissions(required)
    if missing:
        raise AuthorizationError(
            f"principal '{principal.subject}' lacks required permission(s): {', '.join(missing)}",
            details={
                "subject": principal.subject,
                "resource": resource,
                "required": list(required),
                "missing": missing,
            },
        )


__all__ = [
    "ChainedSecretProvider",
    "EnvSecretProvider",
    "FileSecretProvider",
    "SecretProvider",
    "StaticSecretProvider",
    "authorize",
    "constant_time_compare",
    "get_secret_provider",
    "resolve_secret",
    "set_secret_provider",
]
