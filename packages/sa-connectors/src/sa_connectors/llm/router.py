"""Provider routing: many vendors behind one contract.

The router *is* an :class:`~sa_connectors.llm.base.LLMProvider`. That is the
whole design. Every caller in the platform — form extraction, question phrasing,
form authoring, the workflow planner — already depends on the provider
interface, so making the router implement it means switching vendors changes a
setting and touches no business code.

Three ways to choose a profile, narrowest first:

1. ``complete(..., profile="openai")`` — one call.
2. :func:`use_profile` — a scope, e.g. one HTTP request pinned by a header. The
   selection rides on a context variable, so it survives into nested awaits
   without being threaded through every signature.
3. :meth:`LLMRouter.use` — the process default, switchable at runtime.

Fallback is cross-vendor on purpose. A configured fallback chain means a vendor
outage or a rate-limit wall degrades to a different vendor rather than to an
error, which is the main thing a gateway is bought for and the main thing a
direct integration lacks.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from sa_platform.config import LLMProfile, LLMSettings, get_settings
from sa_platform.errors import AcceleratorError, ConfigurationError, NotFoundError
from sa_platform.health import CheckResult
from sa_platform.logging import get_logger

from ..base import Connector, ConnectorState
from .base import LLMProvider, LLMResponse, Message

logger = get_logger(__name__)

#: Per-scope profile override. Set by :func:`use_profile`.
_selected_profile: ContextVar[str | None] = ContextVar("sa_llm_profile", default=None)


@contextmanager
def use_profile(name: str | None) -> Iterator[None]:
    """Pin the profile for everything inside this scope."""
    token = _selected_profile.set(name)
    try:
        yield
    finally:
        _selected_profile.reset(token)


def current_profile() -> str | None:
    """The profile pinned for this scope, if any."""
    return _selected_profile.get()


@dataclass
class ProfileStats:
    """Live counters per profile. What the console's provider page shows."""

    calls: int = 0
    failures: int = 0
    fallbacks_served: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_latency_ms: float = 0.0
    last_used_at: float | None = None
    last_error: str = ""

    @property
    def average_latency_ms(self) -> float:
        return self.total_latency_ms / self.calls if self.calls else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "failures": self.failures,
            "fallbacks_served": self.fallbacks_served,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "average_latency_ms": round(self.average_latency_ms, 1),
            "last_used_at": self.last_used_at,
            "last_error": self.last_error,
        }


@dataclass
class RoutingDecision:
    """Which profile actually served a call, and what was tried first."""

    profile: str
    attempted: list[str] = field(default_factory=list)
    fell_back: bool = False


def build_provider_for(profile: LLMProfile) -> LLMProvider:
    """Construct the provider implementing one profile.

    Imports are local so a deployment that uses only one vendor does not pay for
    the others — most relevantly, the Anthropic SDK stays optional.
    """
    wire = profile.wire_vendor

    if profile.vendor == "stub":
        from .stub_provider import StubProvider

        return StubProvider(profile)

    if profile.vendor == "anthropic":
        # Direct Anthropic access uses the official SDK. A gateway carrying the
        # Anthropic dialect does not — see the note in anthropic_http.
        from sa_platform.config import LLMSettings as _LLMSettings

        from .anthropic_provider import AnthropicProvider

        settings = _LLMSettings(
            model=profile.model,
            max_tokens=profile.max_tokens,
            thinking=profile.thinking or "adaptive",
            effort=profile.effort or "high",
            stream=profile.stream,
            api_key=profile.api_key,
            base_url=profile.base_url,
            timeout_seconds=profile.timeout_seconds,
            max_retries=profile.max_retries,
            enable_prompt_caching=profile.enable_prompt_caching,
        )
        return AnthropicProvider(settings, name=profile.name)

    if wire == "openai":
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(profile)
    if wire == "gemini":
        from .gemini_provider import GeminiProvider

        return GeminiProvider(profile)
    if wire == "anthropic":
        from .anthropic_http import AnthropicHttpProvider

        return AnthropicHttpProvider(profile)

    raise ConfigurationError(
        f"profile '{profile.name}': no implementation for vendor '{profile.vendor}'",
        details={
            "vendor": profile.vendor,
            "supported": ["anthropic", "openai", "gemini", "gateway", "stub"],
        },
    )


class LLMRouter(Connector, LLMProvider):
    """Selects a provider per call, per scope, or per process."""

    def __init__(self, settings: LLMSettings | None = None, *, name: str = "llm-router") -> None:
        Connector.__init__(self, name)
        self._settings = settings or get_settings().llm
        self._profiles: dict[str, LLMProfile] = {p.name: p for p in self._settings.all_profiles()}
        if not self._profiles:  # pragma: no cover - all_profiles always yields one
            raise ConfigurationError("no LLM profiles are configured")
        self._providers: dict[str, LLMProvider] = {}
        self._stats: dict[str, ProfileStats] = {n: ProfileStats() for n in self._profiles}
        self._active = self._resolve_initial_active()
        self._last_decision: RoutingDecision | None = None

    def _resolve_initial_active(self) -> str:
        requested = self._settings.resolved_active_profile()
        if requested in self._profiles:
            return requested
        # A typo in `active_profile` must not take the platform down; log loudly
        # and serve the first profile instead.
        fallback = next(iter(self._profiles))
        logger.error(
            "configured active LLM profile does not exist; using another",
            extra={"requested": requested, "using": fallback, "known": list(self._profiles)},
        )
        return fallback

    # -- catalogue ---------------------------------------------------------
    @property
    def active(self) -> str:
        return self._active

    @property
    def profiles(self) -> dict[str, LLMProfile]:
        return dict(self._profiles)

    def names(self) -> list[str]:
        return list(self._profiles)

    def profile(self, name: str) -> LLMProfile:
        try:
            return self._profiles[name]
        except KeyError as exc:
            raise NotFoundError(
                f"unknown LLM profile '{name}'",
                details={"profile": name, "known": list(self._profiles)},
            ) from exc

    def provider(self, name: str | None = None) -> LLMProvider:
        """The provider for a profile, built on first use."""
        resolved = self.resolve_name(name)
        if resolved not in self._providers:
            self._providers[resolved] = build_provider_for(self.profile(resolved))
        return self._providers[resolved]

    def resolve_name(self, name: str | None = None) -> str:
        """Apply the selection precedence: explicit, then scope, then process."""
        if name:
            self.profile(name)  # validate
            return name
        scoped = current_profile()
        if scoped and scoped in self._profiles:
            return scoped
        return self._active

    def use(self, name: str) -> LLMProfile:
        """Change the process-wide active profile."""
        if not self._settings.allow_runtime_switch:
            raise ConfigurationError(
                "runtime profile switching is disabled (llm.allow_runtime_switch=false)",
                details={"requested": name, "active": self._active},
            )
        profile = self.profile(name)
        if not profile.enabled:
            raise ConfigurationError(
                f"profile '{name}' is disabled",
                details={"profile": name},
            )
        previous, self._active = self._active, name
        logger.info(
            "active LLM profile changed",
            extra={"from": previous, "to": name, "vendor": profile.vendor},
        )
        return profile

    def register(self, profile: LLMProfile, *, activate: bool = False) -> LLMProfile:
        """Add or replace a profile at runtime.

        Replacing one drops its cached provider so the next call picks up the
        new endpoint or credential instead of quietly using the old client.
        """
        self._profiles[profile.name] = profile
        self._providers.pop(profile.name, None)
        self._stats.setdefault(profile.name, ProfileStats())
        if activate:
            self.use(profile.name)
        return profile

    def describe(self, name: str) -> dict[str, Any]:
        """Everything the console needs about one profile. Never the credential."""
        profile = self.profile(name)
        described: dict[str, Any]
        if name in self._providers:
            provider = self._providers[name]
            describe = getattr(provider, "describe", None)
            described = describe() if callable(describe) else {}
        else:
            described = {}

        return {
            "name": profile.name,
            "label": profile.display_label,
            "description": profile.description,
            "vendor": profile.vendor,
            "wire": profile.wire_vendor,
            "model": profile.model,
            "base_url": profile.base_url or described.get("base_url", ""),
            "via_gateway": profile.vendor == "gateway",
            "enabled": profile.enabled,
            "active": name == self._active,
            "credential_present": profile.resolve_api_key() is not None
            or not profile.requires_credential(),
            "instantiated": name in self._providers,
            "state": described.get("state", ConnectorState.CREATED.value),
            "max_tokens": profile.max_tokens,
            "temperature": profile.temperature,
            "effort": profile.effort,
            "stats": self._stats[name].to_dict(),
        }

    def describe_all(self) -> list[dict[str, Any]]:
        return [self.describe(name) for name in self._profiles]

    @property
    def last_decision(self) -> RoutingDecision | None:
        return self._last_decision

    # -- lifecycle ---------------------------------------------------------
    async def connect(self) -> None:
        await self.provider().connect()  # type: ignore[attr-defined]
        self._set_state(ConnectorState.READY)

    async def close(self) -> None:
        for provider in self._providers.values():
            close = getattr(provider, "close", None)
            if callable(close):
                await close()
        self._providers.clear()
        self._set_state(ConnectorState.CLOSED)

    async def health(self) -> CheckResult:
        provider = self.provider()
        probe = getattr(provider, "health", None)
        if probe is None:  # pragma: no cover - every provider has one
            return CheckResult.healthy(f"active profile '{self._active}'")
        result = await probe()
        return result

    async def health_all(self) -> dict[str, dict[str, Any]]:
        """Probe every enabled profile. Used by the console's provider page."""
        report: dict[str, dict[str, Any]] = {}
        for name, profile in self._profiles.items():
            if not profile.enabled:
                report[name] = {"status": "skipped", "message": "profile is disabled"}
                continue
            try:
                result = await self.provider(name).health()  # type: ignore[attr-defined]
                report[name] = result.to_dict()
            except Exception as exc:  # noqa: BLE001 - a probe reports, never raises
                report[name] = {"status": "unhealthy", "message": str(exc)}
        return report

    # -- routed calls ------------------------------------------------------
    def _chain(self, name: str) -> list[str]:
        chain = [name]
        for candidate in self._settings.fallback_profiles:
            if candidate != name and candidate in self._profiles:
                chain.append(candidate)
        return chain

    async def _route(self, operation: str, name: str | None, call: Any) -> Any:
        """Run ``call(provider)`` against the chosen profile, then the fallbacks."""
        chain = self._chain(self.resolve_name(name))
        attempted: list[str] = []
        last_error: BaseException | None = None

        for index, candidate in enumerate(chain):
            profile = self._profiles[candidate]
            if not profile.enabled:
                continue
            attempted.append(candidate)
            stats = self._stats[candidate]
            started = time.perf_counter()
            try:
                result = await call(self.provider(candidate))
            except Exception as exc:  # noqa: BLE001 - classified below
                stats.failures += 1
                stats.last_error = str(exc)[:300]
                last_error = exc
                # Only a retryable failure is worth another vendor. A rejected
                # request or a bad schema fails identically everywhere, and
                # re-sending it just doubles the cost of the same error.
                retryable = isinstance(exc, AcceleratorError) and exc.retryable
                if not retryable or index == len(chain) - 1:
                    raise
                logger.warning(
                    "llm call failed; falling back to the next profile",
                    extra={
                        "operation": operation,
                        "failed_profile": candidate,
                        "next_profile": chain[index + 1],
                        "error": str(exc),
                    },
                )
                continue

            stats.calls += 1
            stats.total_latency_ms += (time.perf_counter() - started) * 1000
            stats.last_used_at = time.time()
            if index > 0:
                stats.fallbacks_served += 1
            if isinstance(result, LLMResponse):
                stats.input_tokens += result.usage.input_tokens
                stats.output_tokens += result.usage.output_tokens
            self._last_decision = RoutingDecision(
                profile=candidate, attempted=attempted, fell_back=index > 0
            )
            return result

        if last_error is not None:  # pragma: no cover - loop raises first
            raise last_error
        raise ConfigurationError(
            "no enabled LLM profile could serve the request",
            details={"chain": chain},
        )

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        system: str | list[dict[str, Any]] | None = None,
        tools: Sequence[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
        profile: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        return await self._route(
            "complete",
            profile,
            lambda p: p.complete(
                messages,
                system=system,
                tools=tools,
                max_tokens=max_tokens,
                model=model,
                **kwargs,
            ),
        )

    async def complete_structured(
        self,
        messages: Sequence[Message],
        schema: dict[str, Any],
        *,
        system: str | list[dict[str, Any]] | None = None,
        profile: str | None = None,
        **kwargs: Any,
    ) -> Any:
        async def call(provider: LLMProvider) -> Any:
            structured = getattr(provider, "complete_structured", None)
            if structured is None:  # pragma: no cover - every provider has one
                raise ConfigurationError(
                    f"provider '{type(provider).__name__}' does not support structured output"
                )
            return await structured(messages, schema, system=system, **kwargs)

        return await self._route("complete_structured", profile, call)

    async def stream(  # type: ignore[override]
        self,
        messages: Sequence[Message],
        *,
        system: str | list[dict[str, Any]] | None = None,
        tools: Sequence[dict[str, Any]] | None = None,
        profile: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream from the chosen profile.

        Not routed through the fallback chain: a stream that fails part-way has
        already delivered tokens to the caller, and restarting on another vendor
        would repeat them.
        """
        provider = self.provider(profile)
        async for chunk in provider.stream(messages, system=system, tools=tools, **kwargs):
            yield chunk

    async def count_tokens(
        self,
        messages: Sequence[Message],
        *,
        system: str | None = None,
        tools: Sequence[dict[str, Any]] | None = None,
        model: str | None = None,
        profile: str | None = None,
    ) -> int:
        return await self.provider(profile).count_tokens(
            messages, system=system, tools=tools, model=model
        )

    async def list_models(self, profile: str | None = None) -> list[str]:
        provider = self.provider(profile)
        lister = getattr(provider, "list_models", None)
        if lister is None:
            return [self.profile(self.resolve_name(profile)).model]
        return await lister()

    async def run_agent(self, *args: Any, profile: str | None = None, **kwargs: Any) -> Any:
        """Delegate the tool-use loop to the selected provider.

        Only the Anthropic provider implements the governed agent loop today.
        This raises with the reason rather than silently dropping the tools,
        which would look like a model that simply chose not to call them.
        """
        provider = self.provider(profile)
        loop = getattr(provider, "run_agent", None)
        if loop is None:
            resolved = self.resolve_name(profile)
            raise ConfigurationError(
                f"profile '{resolved}' ({self.profile(resolved).vendor}) does not implement the "
                "governed agent loop; switch to an Anthropic profile for tool use",
                details={"profile": resolved},
            )
        return await loop(*args, **kwargs)


__all__ = [
    "LLMRouter",
    "ProfileStats",
    "RoutingDecision",
    "build_provider_for",
    "current_profile",
    "use_profile",
]
