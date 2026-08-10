"""Tool governance: allow/deny lists, permissions, and the approval gate.

The approval gate is the important part. An LLM decides *which* tool to call;
this module decides whether that call is allowed to happen. Keeping the two
separate is what makes an autonomous agent safe to run against real systems.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from sa_platform.config import get_settings
from sa_platform.context import ExecutionContext
from sa_platform.errors import ApprovalRequiredError, AuthorizationError, PolicyViolationError
from sa_platform.events import Events, event_bus
from sa_platform.logging import get_logger

from .models import DangerLevel, ToolSpec

logger = get_logger(__name__)


class ApprovalDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    DEFER = "defer"  # no decision available; caller must surface the request


#: Receives the spec, the arguments, and the context; returns a decision.
ApprovalHandler = Callable[
    [ToolSpec, dict[str, Any], ExecutionContext], Awaitable[ApprovalDecision]
]


async def deny_by_default(
    spec: ToolSpec, arguments: dict[str, Any], ctx: ExecutionContext
) -> ApprovalDecision:
    """Default handler: defer, so nothing dangerous runs unattended.

    Deferring (rather than denying) lets the API layer return a 428 and let a
    human decide, instead of silently failing the agent's plan.
    """
    return ApprovalDecision.DEFER


async def allow_all(
    spec: ToolSpec, arguments: dict[str, Any], ctx: ExecutionContext
) -> ApprovalDecision:
    """Auto-approve everything. Development and trusted-batch use only."""
    return ApprovalDecision.ALLOW


@dataclass
class ToolPolicy:
    """Decides whether a tool invocation may proceed."""

    allow: list[str] = field(default_factory=lambda: ["*"])
    deny: list[str] = field(default_factory=list)
    approval_required_above: DangerLevel = DangerLevel.MEDIUM
    enforce_permissions: bool = True
    approval_handler: ApprovalHandler = deny_by_default
    #: Restricts a skill to the tools its manifest declared, when set.
    scoped_tools: list[str] | None = None

    @classmethod
    def from_settings(cls, **overrides: Any) -> ToolPolicy:
        cfg = get_settings().tools
        params: dict[str, Any] = {
            "allow": list(cfg.allow),
            "deny": list(cfg.deny),
            "approval_required_above": DangerLevel(cfg.approval_required_above),
        }
        params.update(overrides)
        return cls(**params)

    def scoped_to(self, tools: list[str] | None) -> ToolPolicy:
        """Derive a narrower policy for a specific skill or agent."""
        return ToolPolicy(
            allow=self.allow,
            deny=self.deny,
            approval_required_above=self.approval_required_above,
            enforce_permissions=self.enforce_permissions,
            approval_handler=self.approval_handler,
            scoped_tools=tools,
        )

    @staticmethod
    def _matches(name: str, patterns: list[str]) -> bool:
        return any(fnmatch.fnmatchcase(name, p) for p in patterns)

    def needs_approval(self, spec: ToolSpec) -> bool:
        return spec.requires_approval or spec.danger.rank >= self.approval_required_above.rank

    async def check(
        self,
        spec: ToolSpec,
        arguments: dict[str, Any],
        ctx: ExecutionContext,
        *,
        preapproved: bool | None = None,
    ) -> None:
        """Raise unless the invocation is permitted.

        Order matters: deny-list, allow-list, and scope are cheap and
        deterministic, so they run before permissions and long before the
        approval handler (which may block on a human).
        """
        name = spec.name

        if self.deny and self._matches(name, self.deny):
            await self._audit_denied(spec, ctx, "deny_list")
            raise PolicyViolationError(
                f"tool '{name}' is denied by policy",
                details={"tool": name, "rule": "deny_list"},
            )

        if self.allow and not self._matches(name, self.allow):
            await self._audit_denied(spec, ctx, "allow_list")
            raise PolicyViolationError(
                f"tool '{name}' is not in the allow list",
                details={"tool": name, "rule": "allow_list"},
            )

        if self.scoped_tools is not None and not self._matches(name, self.scoped_tools):
            await self._audit_denied(spec, ctx, "scope")
            raise PolicyViolationError(
                f"tool '{name}' is outside the caller's declared tool scope",
                details={"tool": name, "rule": "scope", "scope": self.scoped_tools},
            )

        if self.enforce_permissions and spec.required_permissions:
            missing = ctx.principal.missing_permissions(spec.required_permissions)
            if missing:
                await self._audit_denied(spec, ctx, "permissions")
                raise AuthorizationError(
                    f"principal '{ctx.principal.subject}' may not invoke tool '{name}'",
                    details={
                        "tool": name,
                        "subject": ctx.principal.subject,
                        "required": spec.required_permissions,
                        "missing": missing,
                    },
                )

        if not self.needs_approval(spec):
            return

        # A dry run has no side effects, so the gate does not apply.
        if ctx.dry_run:
            return

        if preapproved is True:
            logger.info(
                "tool invocation pre-approved",
                extra={"tool": name, "subject": ctx.principal.subject},
            )
            return
        if preapproved is False:
            await self._audit_denied(spec, ctx, "approval_denied")
            raise PolicyViolationError(
                f"invocation of '{name}' was explicitly denied by the approver",
                details={"tool": name, "rule": "approval_denied"},
            )

        await event_bus.emit(
            Events.TOOL_APPROVAL_REQUIRED,
            tool=name,
            danger=spec.danger.value,
            subject=ctx.principal.subject,
            correlation_id=ctx.correlation_id,
        )

        decision = await self.approval_handler(spec, arguments, ctx)

        if decision is ApprovalDecision.ALLOW:
            logger.info("tool invocation approved", extra={"tool": name})
            return
        if decision is ApprovalDecision.DENY:
            await self._audit_denied(spec, ctx, "approval_denied")
            raise PolicyViolationError(
                f"invocation of '{name}' was denied by the approver",
                details={"tool": name, "rule": "approval_denied"},
            )

        raise ApprovalRequiredError(
            f"tool '{name}' is classified '{spec.danger.value}' and requires approval before running",
            details={
                "tool": name,
                "danger": spec.danger.value,
                "arguments": arguments,
                "correlation_id": ctx.correlation_id,
            },
        )

    @staticmethod
    async def _audit_denied(spec: ToolSpec, ctx: ExecutionContext, rule: str) -> None:
        logger.warning(
            "tool invocation denied",
            extra={"tool": spec.name, "rule": rule, "subject": ctx.principal.subject},
        )
        await event_bus.emit(
            Events.TOOL_DENIED,
            tool=spec.name,
            rule=rule,
            subject=ctx.principal.subject,
            correlation_id=ctx.correlation_id,
        )


__all__ = [
    "ApprovalDecision",
    "ApprovalHandler",
    "ToolPolicy",
    "allow_all",
    "deny_by_default",
]
