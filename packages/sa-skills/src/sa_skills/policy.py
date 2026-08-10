"""Authorization and governance checks applied before a skill runs."""

from __future__ import annotations

from dataclasses import dataclass, field

from sa_platform.config import get_settings
from sa_platform.context import ExecutionContext
from sa_platform.errors import AuthorizationError, PolicyViolationError
from sa_platform.logging import get_logger

from .models import SkillManifest, SkillStability

logger = get_logger(__name__)


@dataclass(slots=True)
class SkillPolicy:
    """Decides whether a principal may invoke a given skill.

    Checks run in ascending order of cost: cheap deny-list matching first,
    then permission evaluation.
    """

    #: When set, only these skill names (glob-matched) may run.
    allow: list[str] = field(default_factory=lambda: ["*"])
    #: Always wins over ``allow``.
    deny: list[str] = field(default_factory=list)
    #: Block skills marked deprecated. On in production by default.
    block_deprecated: bool = False
    #: Refuse experimental skills — appropriate for production tenants.
    block_experimental: bool = False
    enforce_permissions: bool = True

    @classmethod
    def from_settings(cls) -> SkillPolicy:
        settings = get_settings()
        return cls(
            enforce_permissions=settings.skills.enforce_permissions,
            block_deprecated=settings.is_production,
            block_experimental=settings.environment == "prod",
        )

    @staticmethod
    def _matches(name: str, patterns: list[str]) -> bool:
        import fnmatch

        return any(fnmatch.fnmatchcase(name, p) for p in patterns)

    def check(self, manifest: SkillManifest, ctx: ExecutionContext) -> None:
        """Raise if the invocation is not permitted."""
        name = manifest.name

        if self.deny and self._matches(name, self.deny):
            raise PolicyViolationError(
                f"skill '{name}' is denied by policy",
                details={"skill": name, "rule": "deny_list"},
            )

        if self.allow and not self._matches(name, self.allow):
            raise PolicyViolationError(
                f"skill '{name}' is not in the allow list",
                details={"skill": name, "rule": "allow_list"},
            )

        if self.block_deprecated and manifest.stability is SkillStability.DEPRECATED:
            raise PolicyViolationError(
                f"skill '{name}' is deprecated and blocked in this environment",
                details={
                    "skill": name,
                    "reason": manifest.deprecated_reason,
                    "replaced_by": manifest.replaced_by,
                },
            )

        if self.block_experimental and manifest.stability is SkillStability.EXPERIMENTAL:
            raise PolicyViolationError(
                f"skill '{name}' is experimental and blocked in this environment",
                details={"skill": name, "stability": manifest.stability.value},
            )

        if self.enforce_permissions and manifest.required_permissions:
            missing = ctx.principal.missing_permissions(manifest.required_permissions)
            if missing:
                raise AuthorizationError(
                    f"principal '{ctx.principal.subject}' may not invoke skill '{name}'",
                    details={
                        "skill": name,
                        "subject": ctx.principal.subject,
                        "required": manifest.required_permissions,
                        "missing": missing,
                    },
                )

        # A deprecated skill that is still allowed should be loud in the logs so
        # migration work gets scheduled before it is removed.
        if manifest.stability is SkillStability.DEPRECATED:
            logger.warning(
                "invoking deprecated skill",
                extra={
                    "skill": name,
                    "reason": manifest.deprecated_reason,
                    "replaced_by": manifest.replaced_by,
                },
            )

    def is_allowed(self, manifest: SkillManifest, ctx: ExecutionContext) -> bool:
        try:
            self.check(manifest, ctx)
        except (AuthorizationError, PolicyViolationError):
            return False
        return True


__all__ = ["SkillPolicy"]
