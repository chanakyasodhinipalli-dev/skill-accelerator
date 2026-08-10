"""Tests for the Anthropic provider's request construction.

These encode API contract rules that are easy to regress and expensive to
discover in production — a rejected parameter fails *every* call, and a silently
dropped one changes cost or behaviour without any error.
"""

from __future__ import annotations

from typing import Any

import pytest

from sa_connectors.llm.anthropic_provider import AnthropicProvider
from sa_connectors.llm.base import Message, StopReason
from sa_platform.config import LLMSettings

pytest.importorskip("anthropic")


def anthropic_settings(**overrides: Any) -> LLMSettings:
    """Settings for the Anthropic provider specifically.

    Stated rather than inherited: the platform default is OpenAI, so these tests
    would otherwise assert an Anthropic request shape built from a `gpt-4o`
    default and drift the moment either default moves.
    """
    base: dict[str, Any] = {"provider": "anthropic", "model": "claude-opus-5", "api_key": None}
    return LLMSettings(**{**base, **overrides})


@pytest.fixture
def provider() -> AnthropicProvider:
    return AnthropicProvider(anthropic_settings())


class TestRequestShape:
    def _params(self, provider: AnthropicProvider, **overrides: Any) -> dict[str, Any]:
        base: dict[str, Any] = {
            "system": None,
            "tools": None,
            "max_tokens": None,
            "model": None,
            "effort": None,
            "extra": {},
        }
        return provider._build_params([Message.user("hi")], **{**base, **overrides})

    def test_sampling_parameters_are_never_sent(self, provider: AnthropicProvider) -> None:
        """temperature / top_p / top_k are rejected with a 400 on current models."""
        params = self._params(provider)
        assert not {"temperature", "top_p", "top_k"} & params.keys()

    def test_budget_tokens_is_never_sent(self, provider: AnthropicProvider) -> None:
        """The fixed thinking-budget concept was replaced by `effort`."""
        assert "budget_tokens" not in params_of(self._params(provider))

    def test_adaptive_thinking_is_the_default(self, provider: AnthropicProvider) -> None:
        params = self._params(provider)
        assert params["thinking"]["type"] == "adaptive"
        assert params["output_config"]["effort"] == "high"

    def test_disabled_thinking_is_capped_at_high_effort(self) -> None:
        """Disabling thinking above `high` effort is a 400; clamp instead."""
        provider = AnthropicProvider(anthropic_settings(thinking="disabled", effort="max"))
        params = provider._build_params(
            [Message.user("hi")],
            system=None,
            tools=None,
            max_tokens=None,
            model=None,
            effort=None,
            extra={},
        )
        assert params["thinking"]["type"] == "disabled"
        assert params["output_config"]["effort"] == "high"

    def test_caller_output_config_merges_rather_than_replaces(
        self, provider: AnthropicProvider
    ) -> None:
        """Structured outputs must not silently drop the configured effort."""
        params = self._params(
            provider,
            extra={"output_config": {"format": {"type": "json_schema", "schema": {}}}},
        )
        assert params["output_config"]["effort"] == "high"
        assert params["output_config"]["format"]["type"] == "json_schema"

    def test_prompt_cache_breakpoint_goes_on_the_last_system_block(
        self, provider: AnthropicProvider
    ) -> None:
        params = self._params(provider, system="a long stable system prompt")
        assert params["system"][-1]["cache_control"] == {"type": "ephemeral"}

    def test_caching_can_be_disabled(self) -> None:
        provider = AnthropicProvider(anthropic_settings(enable_prompt_caching=False))
        params = provider._build_params(
            [Message.user("hi")],
            system="plain",
            tools=None,
            max_tokens=None,
            model=None,
            effort=None,
            extra={},
        )
        assert params["system"] == "plain"

    def test_default_model_is_current(self, provider: AnthropicProvider) -> None:
        assert self._params(provider)["model"] == "claude-opus-5"


def params_of(params: dict[str, Any]) -> dict[str, Any]:
    """Flatten nested config so absence assertions cover the whole request."""
    flat = dict(params)
    for key in ("thinking", "output_config"):
        if isinstance(params.get(key), dict):
            flat.update(params[key])
    return flat


class TestFallbackCapability:
    """`fallbacks` is newer than the minimum supported SDK.

    Sending it to an SDK that does not accept it fails every request, so support
    is detected by signature and the feature degrades when it is absent.
    """

    async def test_detection_disables_the_beta_path_when_unsupported(
        self, provider: AnthropicProvider
    ) -> None:
        class OldMessages:
            def stream(self, *, model: str, messages: list[Any]) -> None:
                ...

            def create(self, *, model: str, messages: list[Any]) -> None:
                ...

        class OldClient:
            beta = type("Beta", (), {"messages": OldMessages()})()

        assert provider._detect_fallback_support(OldClient()) is False

    async def test_detection_enables_the_beta_path_when_supported(
        self, provider: AnthropicProvider
    ) -> None:
        class NewMessages:
            def stream(self, *, model: str, fallbacks: Any = None, betas: Any = None) -> None:
                ...

            def create(self, *, model: str, fallbacks: Any = None, betas: Any = None) -> None:
                ...

        class NewClient:
            beta = type("Beta", (), {"messages": NewMessages()})()

        assert provider._detect_fallback_support(NewClient()) is True

    async def test_unsupported_sdk_omits_the_parameter_entirely(
        self, provider: AnthropicProvider
    ) -> None:
        provider._supports_fallbacks = False
        assert provider._beta_kwargs() == {}
        assert provider._use_beta_endpoint() is False

    async def test_supported_sdk_opts_in_by_default(self, provider: AnthropicProvider) -> None:
        provider._supports_fallbacks = True
        kwargs = provider._beta_kwargs()
        assert kwargs["fallbacks"] == "default"
        assert kwargs["betas"] == ["server-side-fallback-2026-07-01"]

    async def test_a_missing_beta_namespace_is_handled(self, provider: AnthropicProvider) -> None:
        assert provider._detect_fallback_support(object()) is False


class TestResponseParsing:
    def test_refusal_is_detected_before_content_is_read(self, provider: AnthropicProvider) -> None:
        """A refusal is HTTP 200 with empty content; reading content[0] would break."""

        class Raw:
            content: list[Any] = []
            stop_reason = "refusal"
            stop_details = type(
                "D", (), {"type": "refusal", "category": "cyber", "explanation": ""}
            )()
            model = "claude-opus-5"
            usage = type("U", (), {"input_tokens": 10, "output_tokens": 0})()

        response = provider._parse(Raw())
        assert response.was_refused
        assert response.refusal_category == "cyber"
        assert response.text == ""

    def test_tool_use_blocks_are_surfaced(self, provider: AnthropicProvider) -> None:
        class Raw:
            content = [
                {"type": "text", "text": "let me check"},
                {"type": "tool_use", "id": "tu_1", "name": "search", "input": {"q": "x"}},
            ]
            stop_reason = "tool_use"
            stop_details = None
            model = "claude-opus-5"
            usage = type("U", (), {"input_tokens": 5, "output_tokens": 7})()

        response = provider._parse(Raw())
        assert response.wants_tools
        assert response.tool_calls[0].name == "search"
        assert response.tool_calls[0].arguments == {"q": "x"}
        # Blocks are preserved verbatim: thinking blocks must echo back unedited.
        assert len(response.content_blocks) == 2

    def test_an_unknown_stop_reason_does_not_raise(self, provider: AnthropicProvider) -> None:
        class Raw:
            content: list[Any] = []
            stop_reason = "something_new"
            stop_details = None
            model = "m"
            usage = type("U", (), {"input_tokens": 0, "output_tokens": 0})()

        assert provider._parse(Raw()).stop_reason is StopReason.UNKNOWN

    def test_cache_hit_ratio_is_computed(self, provider: AnthropicProvider) -> None:
        class Raw:
            content: list[Any] = []
            stop_reason = "end_turn"
            stop_details = None
            model = "m"
            usage = type(
                "U",
                (),
                {
                    "input_tokens": 100,
                    "output_tokens": 10,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 900,
                },
            )()

        assert provider._parse(Raw()).usage.cache_hit_ratio == pytest.approx(0.9)


class TestErrorTranslation:
    def test_sdk_errors_map_onto_the_platform_taxonomy(self, provider: AnthropicProvider) -> None:
        import anthropic
        import httpx

        from sa_platform.errors import (
            AuthenticationError,
            ConfigurationError,
            RateLimitError,
            ValidationError,
        )

        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")

        def response(status: int) -> httpx.Response:
            return httpx.Response(status, request=request)

        cases = [
            (
                anthropic.AuthenticationError("bad key", response=response(401), body=None),
                AuthenticationError,
            ),
            (
                anthropic.NotFoundError("no model", response=response(404), body=None),
                ConfigurationError,
            ),
            (
                anthropic.RateLimitError("slow down", response=response(429), body=None),
                RateLimitError,
            ),
            (anthropic.BadRequestError("bad", response=response(400), body=None), ValidationError),
        ]
        for sdk_error, expected in cases:
            assert isinstance(provider._translate(sdk_error), expected)

    def test_unknown_exceptions_become_dependency_errors(self, provider: AnthropicProvider) -> None:
        from sa_platform.errors import DependencyError

        assert isinstance(provider._translate(RuntimeError("boom")), DependencyError)
