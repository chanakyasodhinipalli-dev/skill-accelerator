"""Console settings.

Separate from the platform's own settings because the console is a separate
deployable: it can run beside the API in one process for a demo, or as its own
container pointed at a remote API in an environment where the two are scaled and
secured independently.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConsoleSettings(BaseSettings):
    """Configuration for the operator console."""

    model_config = SettingsConfigDict(
        env_prefix="SA_CONSOLE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    title: str = "Skill Accelerator Console"
    host: str = "127.0.0.1"
    port: int = Field(default=8100, ge=1, le=65535)

    api_base_url: str | None = Field(
        default=None,
        description="Remote API to proxy to. Unset mounts the API in this process, "
        "which is what makes a single-command demo possible.",
    )
    api_key: SecretStr | None = Field(
        default=None,
        description="Credential forwarded upstream in remote mode. Held server-side so "
        "it never reaches the browser.",
    )
    request_timeout_seconds: float = Field(default=120.0, gt=0)

    #: Shown in the header so nobody demos against production by accident.
    environment_banner: str = ""
    default_participant: str = "operator"
    theme: Literal["auto", "light", "dark"] = "auto"

    @property
    def mode(self) -> Literal["embedded", "remote"]:
        return "remote" if self.api_base_url else "embedded"

    def public_config(self) -> dict[str, object]:
        """What the browser is told. Deliberately excludes every credential."""
        return {
            "title": self.title,
            "mode": self.mode,
            "environment_banner": self.environment_banner,
            "default_participant": self.default_participant,
            "theme": self.theme,
        }


__all__ = ["ConsoleSettings"]
