"""Layered configuration.

Precedence, highest first:

1. Explicit constructor arguments
2. Environment variables (``SA_`` prefix, ``__`` nests, e.g. ``SA_LLM__MODEL``)
3. ``.env`` file in the working directory
4. An optional YAML file pointed at by ``SA_CONFIG_FILE``
5. Field defaults
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .errors import ConfigurationError

Environment = Literal["local", "dev", "staging", "prod"]


class LoggingSettings(BaseModel):
    level: str = "INFO"
    format: Literal["json", "text"] = "json"
    include_context: bool = True
    # Field names scrubbed from structured log payloads before emission.
    redact_keys: list[str] = Field(
        default_factory=lambda: [
            "password",
            "secret",
            "token",
            "api_key",
            "apikey",
            "authorization",
            "credential",
            "private_key",
            "session_key",
        ]
    )

    @field_validator("level")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()


class TelemetrySettings(BaseModel):
    enabled: bool = True
    service_name: str = "skill-accelerator"
    otlp_endpoint: str | None = None
    trace_sample_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    metrics_enabled: bool = True


class ResilienceSettings(BaseModel):
    default_timeout_seconds: float = Field(default=30.0, gt=0)
    max_retries: int = Field(default=2, ge=0, le=10)
    retry_base_delay_seconds: float = Field(default=0.25, gt=0)
    retry_max_delay_seconds: float = Field(default=8.0, gt=0)
    circuit_failure_threshold: int = Field(default=5, ge=1)
    circuit_reset_seconds: float = Field(default=30.0, gt=0)
    max_concurrency: int = Field(default=32, ge=1)


class SkillSettings(BaseModel):
    # Directories scanned for `skill.yaml` manifests at startup.
    search_paths: list[Path] = Field(default_factory=lambda: [Path("skills")])
    # Entry point group used for pip-installed skill packages.
    entry_point_group: str = "sa.skills"
    autodiscover: bool = True
    default_timeout_seconds: float = Field(default=60.0, gt=0)
    enforce_permissions: bool = True


class ToolSettings(BaseModel):
    allow: list[str] = Field(default_factory=lambda: ["*"])
    deny: list[str] = Field(default_factory=list)
    # Tools at or above this danger level require an approval decision.
    approval_required_above: Literal["safe", "low", "medium", "high"] = "medium"
    default_timeout_seconds: float = Field(default=30.0, gt=0)
    max_concurrency: int = Field(default=16, ge=1)
    audit_arguments: bool = True


#: Vendors with a first-party implementation in `sa_connectors.llm`.
Vendor = Literal["anthropic", "openai", "gemini", "gateway", "stub"]

#: The wire format an enterprise gateway speaks. Gateways front many vendors but
#: almost always expose one of these three request shapes.
GatewayDialect = Literal["openai", "anthropic", "gemini"]

#: Environment variable each vendor's own SDK/CLI conventionally uses. Consulted
#: after the profile's explicit key and its `api_key_env`, so an existing
#: developer machine works with no extra configuration.
VENDOR_KEY_ENV: dict[str, tuple[str, ...]] = {
    "anthropic": ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"),
    "openai": ("OPENAI_API_KEY", "AZURE_OPENAI_API_KEY"),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "gateway": ("SA_GATEWAY_API_KEY", "LLM_GATEWAY_API_KEY"),
    "stub": (),
}

#: Display names for the built-in default profile, so the console does not show
#: `"Openai"`.
VENDOR_LABEL: dict[str, str] = {
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "gemini": "Gemini",
    "stub": "Deterministic",
}


class LLMProfile(BaseModel):
    """One named, switchable way to reach a model.

    A profile is the unit the UI and the router switch between. Two profiles may
    name the same vendor (prod key vs. sandbox key), and one vendor may be
    reached directly or through a gateway — those are different profiles, not
    different code paths.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Stable identifier used to select this profile")
    vendor: Vendor = "anthropic"
    model: str = Field(description="Vendor model id, e.g. claude-opus-5, gpt-4o, gemini-2.0-flash")
    label: str = Field(default="", description="Display name for the console")
    description: str = ""
    enabled: bool = True

    base_url: str | None = Field(
        default=None,
        description="Override the vendor endpoint. Required for a gateway; also how "
        "Azure OpenAI, a proxy, or a self-hosted OpenAI-compatible server is reached.",
    )
    api_key: SecretStr | None = None
    api_key_env: str | None = Field(
        default=None,
        description="Environment variable holding the credential. Preferred over `api_key` "
        "so secrets stay out of config files.",
    )
    api_version: str | None = Field(
        default=None,
        description="Sent as the `api-version` query parameter. Azure OpenAI requires it; "
        "most other endpoints ignore it.",
    )

    # -- gateway ----------------------------------------------------------
    dialect: GatewayDialect | None = Field(
        default=None,
        description="Wire format for vendor='gateway'. The gateway may route to any "
        "vendor behind it; this is only what *this* side of the call looks like.",
    )
    auth_header: str = Field(
        default="",
        description="Header carrying the credential, when the gateway does not use the "
        "vendor default (e.g. 'api-key' for Azure, 'x-virtual-key' for a broker).",
    )
    auth_scheme: str = Field(
        default="",
        description="Prefix for the credential, e.g. 'Bearer'. Empty sends the raw value.",
    )
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="Extra headers — tenant id, cost centre, routing hints, virtual keys.",
    )

    # -- request shaping ---------------------------------------------------
    max_tokens: int = Field(default=8000, ge=1)
    timeout_seconds: float = Field(default=300.0, gt=0)
    max_retries: int = Field(default=2, ge=0, le=10)
    stream: bool = True
    #: Sampling controls. Deliberately optional and unset by default: Anthropic
    #: current models reject them, while OpenAI and Gemini accept them.
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    #: Anthropic-only depth controls; ignored by other vendors.
    thinking: Literal["adaptive", "disabled"] | None = None
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    enable_prompt_caching: bool = True
    #: Merged into the request body verbatim — the escape hatch for a vendor
    #: feature this model does not know about.
    extra_body: dict[str, Any] = Field(default_factory=dict)

    @property
    def wire_vendor(self) -> str:
        """The request shape to build. A gateway speaks a vendor's dialect."""
        if self.vendor == "gateway":
            return self.dialect or "openai"
        return self.vendor

    @property
    def display_label(self) -> str:
        return self.label or f"{self.vendor}:{self.model}"

    def resolve_api_key(self) -> str | None:
        """Find the credential: explicit value, named env var, then vendor default."""
        if self.api_key is not None:
            return self.api_key.get_secret_value()
        if self.api_key_env:
            value = os.environ.get(self.api_key_env)
            if value:
                return value
        for candidate in VENDOR_KEY_ENV.get(self.vendor, ()):
            value = os.environ.get(candidate)
            if value:
                return value
        return None

    def requires_credential(self) -> bool:
        return self.vendor != "stub"

    @model_validator(mode="after")
    def _validate_shape(self) -> LLMProfile:
        if self.vendor == "gateway":
            if not self.base_url:
                raise ValueError(
                    f"profile '{self.name}': a gateway profile needs base_url — "
                    "there is no default endpoint to fall back to"
                )
            if self.dialect is None:
                raise ValueError(
                    f"profile '{self.name}': a gateway profile needs a dialect "
                    "(openai | anthropic | gemini) so the request body can be built"
                )
        # Sampling parameters are a 400 on current Claude models, not a no-op.
        # Failing here beats failing on every request at runtime.
        if self.wire_vendor == "anthropic" and (
            self.temperature is not None or self.top_p is not None
        ):
            raise ValueError(
                f"profile '{self.name}': Anthropic current models reject temperature/top_p. "
                "Control depth with `effort` instead."
            )
        return self


class LLMSettings(BaseModel):
    """Model access.

    The top-level fields are the built-in default profile, kept flat because
    they long predate multi-vendor support and are what most deployments set.
    `provider` decides which vendor they describe — the platform default is
    OpenAI. `profiles` adds the other vendors; `active_profile` selects between
    them.
    """

    provider: Vendor = "openai"
    model: str = "gpt-4o"
    max_tokens: int = Field(default=16000, ge=1)
    # Adaptive thinking is the supported mode on current Claude models; depth is
    # controlled by `effort`, not a token budget. Both are Anthropic-only and are
    # not passed to a default profile of any other vendor.
    thinking: Literal["adaptive", "disabled"] = "adaptive"
    thinking_display: Literal["omitted", "summarized"] = "summarized"
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    #: Sampling for the default profile. Unset by default and refused outright
    #: when `provider` is anthropic, matching the per-profile rule.
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    stream: bool = True
    api_key: SecretStr | None = None
    base_url: str | None = None
    timeout_seconds: float = Field(default=600.0, gt=0)
    max_retries: int = Field(default=2, ge=0)
    max_tool_iterations: int = Field(default=12, ge=1)
    enable_prompt_caching: bool = True

    # -- multi-vendor ------------------------------------------------------
    profiles: list[LLMProfile] = Field(
        default_factory=list,
        description="Additional named model routes. The top-level fields are always "
        "available as a profile named after `provider` (default 'openai').",
    )
    active_profile: str | None = Field(
        default=None,
        description="Which profile serves requests. Defaults to the built-in profile "
        "named after `provider` — 'openai' unless that is changed.",
    )
    fallback_profiles: list[str] = Field(
        default_factory=list,
        description="Tried in order when the active profile fails with a retryable error. "
        "A cross-vendor fallback is the point: a vendor outage stops being an outage.",
    )
    allow_runtime_switch: bool = Field(
        default=True,
        description="Permit switching the active profile over the API. Turn off in prod "
        "if the model in use must only change through deployment.",
    )

    @model_validator(mode="after")
    def _validate_default_profile(self) -> LLMSettings:
        if self.provider == "gateway":
            raise ValueError(
                "llm.provider cannot be 'gateway': a gateway needs base_url and dialect, "
                "which only a named entry in llm.profiles carries. Declare the gateway "
                "there and point llm.active_profile at it."
            )
        if self.provider == "anthropic" and self.temperature is not None:
            raise ValueError(
                "llm.temperature is rejected when llm.provider is anthropic — current "
                "Claude models 400 on it. Control depth with llm.effort instead."
            )
        return self

    def default_profile(self) -> LLMProfile:
        """The top-level settings expressed as a profile.

        Named after the vendor it reaches, so `active_profile: openai` in a YAML
        file and the built-in default are the same thing rather than two.
        """
        is_anthropic = self.provider == "anthropic"
        return LLMProfile(
            name=self.provider,
            vendor=self.provider,
            model=self.model,
            label=f"{VENDOR_LABEL.get(self.provider, self.provider)} (default)",
            description="The platform default, configured by the top-level llm settings.",
            api_key=self.api_key,
            base_url=self.base_url,
            max_tokens=self.max_tokens,
            timeout_seconds=self.timeout_seconds,
            max_retries=self.max_retries,
            stream=self.stream,
            # Depth controls are Anthropic-only; sampling is refused there. Each
            # is carried only to the vendor that accepts it.
            thinking=self.thinking if is_anthropic else None,
            effort=self.effort if is_anthropic else None,
            temperature=None if is_anthropic else self.temperature,
            enable_prompt_caching=self.enable_prompt_caching,
        )

    def all_profiles(self) -> list[LLMProfile]:
        """Every profile: the built-in default, whatever is configured, and the stub.

        A configured profile of the same name replaces the built-in rather than
        colliding with it. The stub is always present so a deployment with no
        credential at all still has something selectable — every deterministic
        path in the platform stays exercisable offline.
        """
        configured = {p.name: p for p in self.profiles}
        ordered: list[LLMProfile] = []
        if self.provider not in configured:
            ordered.append(self.default_profile())
        ordered.extend(self.profiles)
        if "stub" not in configured:
            ordered.append(
                LLMProfile(
                    name="stub",
                    vendor="stub",
                    model="deterministic",
                    label="Deterministic (no model)",
                    description=(
                        "Calls no model. Everything the platform decides in code still "
                        "works; only generated wording falls back to fixed phrasing."
                    ),
                )
            )
        return ordered

    def resolved_active_profile(self) -> str:
        return self.active_profile or self.all_profiles()[0].name


class OrchestratorSettings(BaseModel):
    max_parallel_steps: int = Field(default=8, ge=1)
    default_step_timeout_seconds: float = Field(default=120.0, gt=0)
    default_run_timeout_seconds: float = Field(default=900.0, gt=0)
    state_backend: Literal["memory"] = "memory"
    checkpoint_every_step: bool = True
    compensate_on_failure: bool = True


class ApiSettings(BaseModel):
    host: str = "0.0.0.0"  # noqa: S104 - containers bind all interfaces by design
    port: int = Field(default=8000, ge=1, le=65535)
    root_path: str = ""
    cors_origins: list[str] = Field(default_factory=list)
    docs_enabled: bool = True
    # Static bearer tokens for service-to-service auth. Production deployments
    # should replace this with the OIDC verifier in sa_api.security.
    api_keys: dict[str, str] = Field(default_factory=dict)
    require_auth: bool = False


class MCPServerConfig(BaseModel):
    """One MCP server the orchestration layer may connect to."""

    name: str
    transport: Literal["stdio", "http"] = "http"
    url: str | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    timeout_seconds: float = Field(default=30.0, gt=0)
    # Only expose these tool names to the model; empty means "all".
    tool_allowlist: list[str] = Field(default_factory=list)

    @field_validator("url")
    @classmethod
    def _require_url_for_http(cls, v: str | None, info: Any) -> str | None:
        if info.data.get("transport") == "http" and not v:
            raise ValueError("MCP servers with transport='http' require a url")
        return v


class Settings(BaseSettings):
    """Root settings object. Resolve once via :func:`get_settings`."""

    model_config = SettingsConfigDict(
        env_prefix="SA_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Environment = "local"
    service_name: str = "skill-accelerator"
    version: str = "0.1.0"
    debug: bool = False

    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    telemetry: TelemetrySettings = Field(default_factory=TelemetrySettings)
    resilience: ResilienceSettings = Field(default_factory=ResilienceSettings)
    skills: SkillSettings = Field(default_factory=SkillSettings)
    tools: ToolSettings = Field(default_factory=ToolSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    orchestrator: OrchestratorSettings = Field(default_factory=OrchestratorSettings)
    api: ApiSettings = Field(default_factory=ApiSettings)
    mcp_servers: list[MCPServerConfig] = Field(default_factory=list)

    @property
    def is_production(self) -> bool:
        return self.environment in ("staging", "prod")

    def require_llm_api_key(self) -> str:
        """Resolve the credential for the default profile's vendor.

        Settings first, then the variables that vendor's own SDK/CLI reads — so a
        machine that already has `OPENAI_API_KEY` needs no extra configuration.
        """
        if self.llm.api_key is not None:
            return self.llm.api_key.get_secret_value()
        candidates = VENDOR_KEY_ENV.get(self.llm.provider, ())
        for candidate in candidates:
            key = os.environ.get(candidate)
            if key:
                return key
        expected = " or ".join(candidates) or "a vendor credential"
        raise ConfigurationError(
            f"No {self.llm.provider} credential found. Set SA_LLM__API_KEY or {expected}.",
            details={"provider": self.llm.provider, "checked": list(candidates)},
        )


def _load_yaml_overrides() -> dict[str, Any]:
    path = os.environ.get("SA_CONFIG_FILE")
    if not path:
        return {}
    file = Path(path)
    if not file.is_file():
        raise ConfigurationError(f"SA_CONFIG_FILE points at a missing file: {file}")
    try:
        data = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"invalid YAML in {file}: {exc}", cause=exc) from exc
    if not isinstance(data, dict):
        raise ConfigurationError(f"{file} must contain a YAML mapping at the top level")
    return data


def load_settings(**overrides: Any) -> Settings:
    """Build a fresh Settings instance. Prefer :func:`get_settings` at runtime."""
    merged: dict[str, Any] = {**_load_yaml_overrides(), **overrides}
    try:
        return Settings(**merged)
    except Exception as exc:  # noqa: BLE001 - pydantic raises its own type
        raise ConfigurationError(f"invalid configuration: {exc}", cause=exc) from exc


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide singleton. Call :func:`reset_settings` in tests."""
    return load_settings()


def reset_settings() -> None:
    get_settings.cache_clear()


__all__ = [
    "VENDOR_KEY_ENV",
    "VENDOR_LABEL",
    "ApiSettings",
    "Environment",
    "GatewayDialect",
    "LLMProfile",
    "LLMSettings",
    "LoggingSettings",
    "MCPServerConfig",
    "OrchestratorSettings",
    "ResilienceSettings",
    "Settings",
    "SkillSettings",
    "TelemetrySettings",
    "ToolSettings",
    "Vendor",
    "get_settings",
    "load_settings",
    "reset_settings",
]
