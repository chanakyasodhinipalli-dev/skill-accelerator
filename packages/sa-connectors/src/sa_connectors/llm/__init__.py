"""LLM provider abstraction, vendor implementations, and the routing layer.

:func:`build_provider` returns the shared :class:`~sa_connectors.llm.router.LLMRouter`.
Callers keep depending on the :class:`~sa_connectors.llm.base.LLMProvider`
interface and get vendor switching for free — the router *is* a provider.
"""

from __future__ import annotations

from typing import Any

from .base import (
    AgentResult,
    LLMProvider,
    LLMResponse,
    Message,
    Role,
    StopReason,
    ToolCall,
    Usage,
)
from .router import (
    LLMRouter,
    ProfileStats,
    build_provider_for,
    current_profile,
    use_profile,
)

#: Process-wide router. Shared so that switching the active profile takes effect
#: everywhere at once — a per-caller router would make "switch the model" mean
#: "switch it for whichever component happened to build this one".
_router: LLMRouter | None = None


def get_router(*, refresh: bool = False) -> LLMRouter:
    """The shared router, built on first use."""
    global _router
    if _router is None or refresh:
        _router = LLMRouter()
    return _router


def reset_router() -> None:
    """Drop the shared router. Call after changing settings, and in tests."""
    global _router
    _router = None


def build_provider(settings: Any | None = None, **kwargs: Any) -> LLMProvider:
    """Return a provider.

    With no arguments this is the shared router, which is what every component
    in the platform uses. Passing explicit ``settings`` builds a single
    Anthropic provider directly — the pre-routing behaviour, kept for callers
    that deliberately want one isolated client.
    """
    if settings is None and not kwargs:
        return get_router()

    from sa_platform.config import get_settings

    from .anthropic_provider import AnthropicProvider

    return AnthropicProvider(settings or get_settings().llm, **kwargs)


__all__ = [
    "AgentResult",
    "LLMProvider",
    "LLMResponse",
    "LLMRouter",
    "Message",
    "ProfileStats",
    "Role",
    "StopReason",
    "ToolCall",
    "Usage",
    "build_provider",
    "build_provider_for",
    "current_profile",
    "get_router",
    "reset_router",
    "use_profile",
]
