"""Tests for multi-vendor routing.

Two things are worth protecting here. The first is *selection*: which profile
serves a call, given a per-call argument, a scoped override, and a process
default. The second is the vendor request shapes — a parameter sent to the wrong
vendor is a 400 on every request, and the failure looks like a broken feature
rather than a wrong body.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from sa_connectors.llm.anthropic_http import AnthropicHttpProvider
from sa_connectors.llm.base import Message, StopReason
from sa_connectors.llm.gemini_provider import GeminiProvider, sanitise_schema
from sa_connectors.llm.openai_provider import OpenAIProvider
from sa_connectors.llm.router import LLMRouter, build_provider_for, use_profile
from sa_connectors.llm.stub_provider import StubProvider, empty_for_schema
from sa_platform.config import LLMProfile, LLMSettings
from sa_platform.errors import (
    ConfigurationError,
    DependencyError,
    NotFoundError,
    RateLimitError,
    ValidationError,
)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "title": "extraction",
    "properties": {
        "found": {"type": "boolean"},
        "items": {"type": "array", "items": {"type": "string"}},
        "note": {"type": "string"},
    },
    "required": ["found"],
    "additionalProperties": False,
}


def profile(**overrides: Any) -> LLMProfile:
    base: dict[str, Any] = {"name": "p", "vendor": "openai", "model": "gpt-4o"}
    return LLMProfile(**{**base, **overrides})


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class TestProfileConfiguration:
    def test_sampling_parameters_are_rejected_for_anthropic_profiles(self) -> None:
        """A 400 on every request is a worse failure than one at startup."""
        with pytest.raises(ValueError, match="reject temperature"):
            profile(vendor="anthropic", model="claude-opus-5", temperature=0.7)

    def test_a_gateway_profile_needs_an_endpoint_and_a_dialect(self) -> None:
        with pytest.raises(ValueError, match="base_url"):
            profile(vendor="gateway", dialect="openai", base_url=None)
        with pytest.raises(ValueError, match="dialect"):
            profile(vendor="gateway", base_url="https://gw.internal/v1")

    def test_a_gateway_reports_the_dialect_as_its_wire_format(self) -> None:
        gateway = profile(vendor="gateway", dialect="anthropic", base_url="https://gw/v1")
        assert gateway.wire_vendor == "anthropic"
        assert build_provider_for(gateway).wire == "anthropic"

    def test_credentials_resolve_explicit_then_named_then_vendor_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert profile().resolve_api_key() is None

        monkeypatch.setenv("OPENAI_API_KEY", "vendor-default")
        assert profile().resolve_api_key() == "vendor-default"

        monkeypatch.setenv("MY_KEY", "named")
        assert profile(api_key_env="MY_KEY").resolve_api_key() == "named"
        assert profile(api_key="explicit", api_key_env="MY_KEY").resolve_api_key() == "explicit"

    def test_the_stub_profile_is_always_available(self) -> None:
        """A deployment with no credential still has something selectable."""
        names = [p.name for p in LLMSettings().all_profiles()]
        assert "stub" in names
        assert names[0] == "openai"

    def test_the_builtin_default_profile_is_openai(self) -> None:
        """Out of the box, with no config file, a call reaches OpenAI."""
        settings = LLMSettings()
        assert settings.resolved_active_profile() == "openai"

        default = settings.default_profile()
        assert (default.vendor, default.model) == ("openai", "gpt-4o")
        # Anthropic-only depth controls are not carried to another vendor.
        assert default.thinking is None
        assert default.effort is None

    def test_the_default_profile_follows_the_provider_setting(self) -> None:
        settings = LLMSettings(provider="anthropic", model="claude-opus-5")
        default = settings.default_profile()
        assert (default.name, default.vendor) == ("anthropic", "anthropic")
        assert default.effort == "high"
        assert default.temperature is None
        assert settings.resolved_active_profile() == "anthropic"

    def test_sampling_is_rejected_on_an_anthropic_default_profile(self) -> None:
        with pytest.raises(ValueError, match="temperature"):
            LLMSettings(provider="anthropic", model="claude-opus-5", temperature=0.7)

    def test_a_gateway_cannot_be_the_toplevel_provider(self) -> None:
        """It has nowhere to carry base_url and dialect; a named profile does."""
        with pytest.raises(ValueError, match="gateway"):
            LLMSettings(provider="gateway")

    def test_a_configured_profile_replaces_the_builtin_of_the_same_name(self) -> None:
        settings = LLMSettings(profiles=[LLMProfile(name="stub", vendor="stub", model="custom")])
        stubs = [p for p in settings.all_profiles() if p.name == "stub"]
        assert len(stubs) == 1
        assert stubs[0].model == "custom"

        settings = LLMSettings(
            profiles=[LLMProfile(name="openai", vendor="openai", model="gpt-4o-mini")]
        )
        defaults = [p for p in settings.all_profiles() if p.name == "openai"]
        assert len(defaults) == 1
        assert defaults[0].model == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def router(**settings: Any) -> LLMRouter:
    return LLMRouter(
        LLMSettings(
            profiles=[
                LLMProfile(name="primary", vendor="stub", model="a"),
                LLMProfile(name="secondary", vendor="stub", model="b"),
            ],
            active_profile="primary",
            **settings,
        )
    )


class TestSelection:
    def test_the_active_profile_serves_by_default(self) -> None:
        assert router().resolve_name() == "primary"

    def test_an_explicit_argument_wins_over_everything(self) -> None:
        # "openai" here is the built-in default profile, which is always present
        # alongside the two configured ones.
        with use_profile("secondary"):
            assert router().resolve_name("openai") == "openai"

    def test_a_scoped_override_wins_over_the_process_default(self) -> None:
        instance = router()
        with use_profile("secondary"):
            assert instance.resolve_name() == "secondary"
        assert instance.resolve_name() == "primary"

    def test_an_unknown_scoped_profile_falls_back_rather_than_failing(self) -> None:
        """A caller's header naming a retired profile must not break the request."""
        instance = router()
        with use_profile("does-not-exist"):
            assert instance.resolve_name() == "primary"

    def test_an_unknown_explicit_profile_is_an_error(self) -> None:
        with pytest.raises(NotFoundError):
            router().resolve_name("does-not-exist")

    def test_switching_is_refused_when_configuration_forbids_it(self) -> None:
        instance = router(allow_runtime_switch=False)
        with pytest.raises(ConfigurationError, match="switching is disabled"):
            instance.use("secondary")

    def test_a_bad_active_profile_does_not_take_the_platform_down(self) -> None:
        instance = LLMRouter(
            LLMSettings(
                profiles=[LLMProfile(name="only", vendor="stub", model="a")],
                active_profile="typo",
            )
        )
        assert instance.active in instance.names()

    def test_registering_a_profile_drops_the_cached_provider(self) -> None:
        """Otherwise a rotated credential keeps using the old client."""
        instance = router()
        first = instance.provider("primary")
        instance.register(LLMProfile(name="primary", vendor="stub", model="rebuilt"))
        assert instance.provider("primary") is not first

    def test_describe_never_exposes_the_credential(self) -> None:
        instance = LLMRouter(
            LLMSettings(
                profiles=[
                    LLMProfile(name="p", vendor="openai", model="gpt-4o", api_key="super-secret")
                ]
            )
        )
        assert "super-secret" not in str(instance.describe("p"))
        assert instance.describe("p")["credential_present"] is True


class _Flaky:
    """A provider that fails a set number of times before succeeding."""

    def __init__(self, error: BaseException, failures: int = 99) -> None:
        self.error = error
        self.remaining = failures
        self.calls = 0

    async def complete(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        if self.remaining > 0:
            self.remaining -= 1
            raise self.error
        from sa_connectors.llm.base import LLMResponse

        return LLMResponse(text="served")


class TestFallback:
    async def test_a_retryable_failure_falls_through_to_the_next_vendor(self) -> None:
        instance = router(fallback_profiles=["secondary"])
        broken = _Flaky(RateLimitError("slow down"))
        instance._providers["primary"] = broken  # type: ignore[assignment]

        response = await instance.complete([Message.user("hi")])
        assert response.stop_reason is StopReason.END_TURN
        assert instance.last_decision is not None
        assert instance.last_decision.fell_back is True
        assert instance.last_decision.profile == "secondary"

    async def test_a_non_retryable_failure_is_not_retried_elsewhere(self) -> None:
        """A rejected request fails identically everywhere; re-sending doubles the cost."""
        instance = router(fallback_profiles=["secondary"])
        broken = _Flaky(ValidationError("bad schema"))
        instance._providers["primary"] = broken  # type: ignore[assignment]
        second = _Flaky(DependencyError("never reached"))
        instance._providers["secondary"] = second  # type: ignore[assignment]

        with pytest.raises(ValidationError):
            await instance.complete([Message.user("hi")])
        assert second.calls == 0

    async def test_failures_are_counted_per_profile(self) -> None:
        instance = router(fallback_profiles=["secondary"])
        instance._providers["primary"] = _Flaky(RateLimitError("x"))  # type: ignore[assignment]
        await instance.complete([Message.user("hi")])

        assert instance.describe("primary")["stats"]["failures"] == 1
        assert instance.describe("secondary")["stats"]["calls"] == 1
        assert instance.describe("secondary")["stats"]["fallbacks_served"] == 1

    async def test_tool_use_on_a_provider_without_the_agent_loop_says_why(self) -> None:
        instance = router()
        with pytest.raises(ConfigurationError, match="governed agent loop"):
            await instance.run_agent([Message.user("hi")])


# ---------------------------------------------------------------------------
# Vendor request shapes
# ---------------------------------------------------------------------------


def build(provider: Any, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "system": "be brief",
        "tools": None,
        "max_tokens": 100,
        "model": provider.profile.model,
        "stream": False,
        "schema": None,
        "extra": {},
    }
    return provider._build_body([Message.user("hello")], **{**base, **overrides})


TOOLS = [
    {
        "name": "search",
        "description": "Find something",
        "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}},
    }
]


class TestOpenAIDialect:
    @pytest.fixture
    def provider(self) -> OpenAIProvider:
        return OpenAIProvider(profile(temperature=0.2))

    def test_the_system_prompt_becomes_the_first_message(self, provider: OpenAIProvider) -> None:
        body = build(provider)
        assert body["messages"][0] == {"role": "system", "content": "be brief"}
        assert body["temperature"] == 0.2

    def test_registry_tools_are_translated_to_the_function_envelope(
        self, provider: OpenAIProvider
    ) -> None:
        """Tools are authored once, Anthropic-shaped, and translated per vendor."""
        body = build(provider, tools=TOOLS)
        assert body["tools"][0]["type"] == "function"
        assert body["tools"][0]["function"]["name"] == "search"
        assert body["tools"][0]["function"]["parameters"]["properties"] == {"q": {"type": "string"}}

    def test_structured_output_is_not_sent_in_strict_mode(self, provider: OpenAIProvider) -> None:
        """Strict mode requires every property to be required; a mismatch is a 400."""
        body = build(provider, schema=SCHEMA)
        assert body["response_format"]["json_schema"]["strict"] is False
        assert body["response_format"]["json_schema"]["schema"] == SCHEMA

    def test_streaming_asks_for_usage(self, provider: OpenAIProvider) -> None:
        """Without this a streamed response carries no token accounting at all."""
        assert build(provider, stream=True)["stream_options"] == {"include_usage": True}

    def test_the_token_parameter_flips_once_when_rejected(self, provider: OpenAIProvider) -> None:
        assert "max_completion_tokens" in build(provider)
        provider._token_param = "max_tokens"
        assert "max_tokens" in build(provider)
        assert provider._is_token_param_rejection(
            ValidationError("Unsupported parameter: 'max_completion_tokens'")
        )

    def test_tool_calls_are_decoded_from_their_json_string(self, provider: OpenAIProvider) -> None:
        response = provider._parse(
            {
                "model": "gpt-4o",
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "function": {"name": "search", "arguments": '{"q": "x"}'},
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            }
        )
        assert response.wants_tools
        assert response.tool_calls[0].arguments == {"q": "x"}
        assert response.usage.input_tokens == 12

    def test_malformed_tool_arguments_do_not_kill_the_turn(self, provider: OpenAIProvider) -> None:
        response = provider._parse(
            {
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "tool_calls": [
                                {"id": "c", "function": {"name": "s", "arguments": "{oops"}}
                            ]
                        },
                    }
                ]
            }
        )
        assert response.tool_calls[0].arguments == {}

    def test_a_refusal_is_recognised(self, provider: OpenAIProvider) -> None:
        response = provider._parse(
            {"choices": [{"finish_reason": "stop", "message": {"refusal": "I can't help"}}]}
        )
        assert response.was_refused
        assert response.text == ""

    def test_stream_deltas_are_read(self, provider: OpenAIProvider) -> None:
        assert provider._delta_text({"choices": [{"delta": {"content": "he"}}]}) == "he"
        assert provider._delta_text({"choices": []}) == ""


class TestGeminiDialect:
    @pytest.fixture
    def provider(self) -> GeminiProvider:
        return GeminiProvider(profile(vendor="gemini", model="gemini-2.0-flash"))

    def test_the_system_prompt_is_a_separate_instruction(self, provider: GeminiProvider) -> None:
        body = build(provider)
        assert body["systemInstruction"]["parts"][0]["text"] == "be brief"
        assert body["contents"][0]["role"] == "user"

    def test_assistant_turns_are_relabelled_model(self, provider: GeminiProvider) -> None:
        body = provider._build_body(
            [Message.user("a"), Message.assistant("b")],
            system=None,
            tools=None,
            max_tokens=10,
            model="gemini-2.0-flash",
            stream=False,
            schema=None,
            extra={},
        )
        assert [c["role"] for c in body["contents"]] == ["user", "model"]

    def test_unsupported_schema_keywords_are_stripped(self) -> None:
        """`additionalProperties` and friends are a 400 here, not an ignored field."""
        cleaned = sanitise_schema(SCHEMA)
        assert "additionalProperties" not in cleaned
        assert cleaned["properties"]["items"] == {"type": "array", "items": {"type": "string"}}
        assert cleaned["required"] == ["found"]

    def test_a_schema_that_lost_its_type_still_declares_object(self) -> None:
        assert sanitise_schema({"properties": {"a": {"type": "string"}}})["type"] == "object"

    def test_the_streaming_path_uses_the_sse_endpoint(self, provider: GeminiProvider) -> None:
        assert provider._completion_path("gemini-2.0-flash", stream=True).endswith("alt=sse")
        assert provider._completion_path("models/x", stream=False) == "/models/x:generateContent"

    def test_a_blocked_prompt_returns_no_candidates_and_reads_as_a_refusal(
        self, provider: GeminiProvider
    ) -> None:
        response = provider._parse({"promptFeedback": {"blockReason": "SAFETY"}})
        assert response.was_refused
        assert response.refusal_category == "SAFETY"

    def test_function_calls_get_a_stable_id(self, provider: GeminiProvider) -> None:
        """Gemini issues no call ids, and tool results must stay matchable."""
        response = provider._parse(
            {
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"functionCall": {"name": "s", "args": {"q": 1}}}]},
                    }
                ],
                "usageMetadata": {"promptTokenCount": 4, "candidatesTokenCount": 2},
            }
        )
        assert response.wants_tools
        assert response.tool_calls[0].id
        assert response.stop_reason is StopReason.TOOL_USE


class TestAnthropicDialect:
    @pytest.fixture
    def provider(self) -> AnthropicHttpProvider:
        return AnthropicHttpProvider(
            profile(
                vendor="gateway",
                dialect="anthropic",
                model="claude-opus-5",
                base_url="https://gw/v1",
            )
        )

    def test_sampling_parameters_are_never_sent(self, provider: AnthropicHttpProvider) -> None:
        assert not {"temperature", "top_p", "top_k"} & build(provider).keys()

    def test_budget_tokens_is_never_sent(self, provider: AnthropicHttpProvider) -> None:
        body = build(provider)
        assert "budget_tokens" not in body
        assert "budget_tokens" not in body["thinking"]

    def test_adaptive_thinking_and_effort_are_the_depth_controls(
        self, provider: AnthropicHttpProvider
    ) -> None:
        body = build(provider)
        assert body["thinking"] == {"type": "adaptive"}
        assert body["output_config"]["effort"] == "high"

    def test_disabled_thinking_is_clamped_to_high_effort(self) -> None:
        provider = AnthropicHttpProvider(
            profile(
                vendor="gateway",
                dialect="anthropic",
                model="claude-opus-5",
                base_url="https://gw/v1",
                thinking="disabled",
                effort="max",
            )
        )
        body = build(provider)
        assert body["thinking"]["type"] == "disabled"
        assert body["output_config"]["effort"] == "high"

    def test_the_api_version_header_is_required_without_an_sdk(
        self, provider: AnthropicHttpProvider
    ) -> None:
        assert provider._headers()["anthropic-version"]

    def test_structured_output_uses_output_config_format(
        self, provider: AnthropicHttpProvider
    ) -> None:
        body = build(provider, schema=SCHEMA)
        assert body["output_config"]["format"] == {"type": "json_schema", "schema": SCHEMA}


class TestGatewayShape:
    def test_the_auth_header_and_extra_headers_are_applied(self) -> None:
        provider = build_provider_for(
            profile(
                name="corp",
                vendor="gateway",
                dialect="openai",
                base_url="https://gw.internal/v1",
                api_key="k",
                auth_header="x-virtual-key",
                headers={"x-cost-centre": "risk"},
            )
        )
        headers = provider._headers()  # type: ignore[attr-defined]
        # A custom auth header carries the raw value: a gateway that wanted a
        # scheme would be asking for the vendor default header anyway.
        assert headers["x-virtual-key"] == "k"
        assert headers["x-cost-centre"] == "risk"
        assert "Authorization" not in headers

    def test_azure_style_versioning_lands_on_the_query_string(self) -> None:
        provider = OpenAIProvider(
            profile(
                base_url="https://x.openai.azure.com/openai/deployments/gpt4o",
                api_version="2024-10-21",
            )
        )
        assert provider._completion_path("gpt-4o", stream=False).endswith("?api-version=2024-10-21")


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


def mounted(provider: Any, handler: Any) -> Any:
    """Give a provider a client that answers locally.

    ``httpx.MockTransport`` rather than a mocking library: it exercises the
    provider's real request construction, headers, and response handling, and
    adds no dependency.
    """
    provider._client = httpx.AsyncClient(
        base_url=provider.base_url, transport=httpx.MockTransport(handler)
    )
    return provider


class TestTransport:
    async def test_a_request_carries_the_credential_and_the_built_body(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["auth"] = request.headers.get("authorization")
            seen["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "model": "gpt-4o",
                    "choices": [{"finish_reason": "stop", "message": {"content": "hi there"}}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 2},
                },
            )

        provider = mounted(OpenAIProvider(profile(api_key="sk-test")), handler)
        response = await provider.complete([Message.user("hello")], system="be brief")

        assert response.text == "hi there"
        assert response.usage.input_tokens == 5
        assert seen["auth"] == "Bearer sk-test"
        assert seen["url"].endswith("/chat/completions")
        assert seen["body"]["messages"][0]["role"] == "system"

    async def test_a_rate_limit_is_classified_and_therefore_retryable(self) -> None:
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            if attempts["n"] == 1:
                return httpx.Response(429, headers={"retry-after": "0"}, json={"error": "slow"})
            return httpx.Response(
                200,
                json={"choices": [{"finish_reason": "stop", "message": {"content": "ok"}}]},
            )

        provider = mounted(OpenAIProvider(profile(max_retries=2)), handler)
        response = await provider.complete([Message.user("hi")])

        assert response.text == "ok"
        assert attempts["n"] == 2

    async def test_a_rejected_request_is_not_retried(self) -> None:
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            return httpx.Response(400, json={"error": "bad model"})

        provider = mounted(OpenAIProvider(profile(max_retries=2)), handler)
        with pytest.raises(ValidationError):
            await provider.complete([Message.user("hi")])
        assert attempts["n"] == 1

    async def test_an_unreachable_endpoint_becomes_a_dependency_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route to host")

        provider = mounted(OpenAIProvider(profile()), handler)
        with pytest.raises(DependencyError, match="could not reach"):
            await provider.complete([Message.user("hi")])

    async def test_structured_output_survives_a_fenced_response(self) -> None:
        """A gateway that silently drops schema support returns fenced JSON."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": '```json\n{"found": true}\n```'},
                        }
                    ]
                },
            )

        provider = mounted(OpenAIProvider(profile()), handler)
        assert await provider.complete_structured([Message.user("x")], SCHEMA) == {"found": True}

    async def test_gemini_counts_tokens_with_its_own_endpoint(self) -> None:
        """Estimating with a foreign tokenizer silently mis-budgets context."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path.endswith(":countTokens")
            assert request.headers.get("x-goog-api-key") == "gk"
            return httpx.Response(200, json={"totalTokens": 42})

        provider = mounted(
            GeminiProvider(profile(vendor="gemini", model="gemini-2.0-flash", api_key="gk")),
            handler,
        )
        assert await provider.count_tokens([Message.user("hi")]) == 42

    async def test_openai_has_no_token_counting_endpoint_and_says_so(self) -> None:
        provider = OpenAIProvider(profile())
        with pytest.raises(ConfigurationError, match="no token-counting endpoint"):
            await provider.count_tokens([Message.user("hi")])

    async def test_the_model_list_comes_from_the_endpoint(self) -> None:
        """Pointed at a gateway this is the organisation's approved model list."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [{"id": "gpt-4o"}, {"id": "o3"}]})

        provider = mounted(OpenAIProvider(profile()), handler)
        assert await provider.list_models() == ["gpt-4o", "o3"]

    async def test_listing_models_degrades_rather_than_raising(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "not supported here"})

        provider = mounted(OpenAIProvider(profile(model="gpt-4o")), handler)
        assert await provider.list_models() == ["gpt-4o"]


# ---------------------------------------------------------------------------
# Deterministic provider
# ---------------------------------------------------------------------------


class TestStubProvider:
    async def test_structured_calls_return_the_emptiest_valid_shape(self) -> None:
        """Callers read this as 'the model contributed nothing' and use their own path."""
        result = await StubProvider().complete_structured([Message.user("x")], SCHEMA)
        assert result == {"found": False, "items": [], "note": ""}

    def test_enums_take_their_first_option(self) -> None:
        assert empty_for_schema({"type": "string", "enum": ["a", "b"]}) == "a"

    async def test_it_needs_no_credential_and_reports_healthy(self) -> None:
        provider = StubProvider()
        await provider.connect()
        assert (await provider.health()).status == "healthy"
        assert provider.describe()["credential_present"] is True
