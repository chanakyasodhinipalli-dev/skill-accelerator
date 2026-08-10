"""FastAPI dependencies: authentication, context binding, and registry access."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, Request

from sa_connectors.llm import use_profile
from sa_connectors.registry import ConnectorRegistry, connector_registry
from sa_orchestrator.engine import OrchestrationEngine, engine
from sa_orchestrator.registry import WorkflowRegistry, workflow_registry
from sa_platform.config import Settings, get_settings
from sa_platform.context import ExecutionContext, Principal
from sa_platform.errors import AuthenticationError
from sa_platform.security import constant_time_compare
from sa_skills.registry import SkillRegistry, skill_registry
from sa_skills.runtime import SkillRuntime, skill_runtime
from sa_tools.executor import ToolExecutor, tool_executor
from sa_tools.registry import ToolRegistry, tool_registry


def get_app_settings() -> Settings:
    return get_settings()


async def get_principal(
    settings: Annotated[Settings, Depends(get_app_settings)],
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None,
) -> Principal:
    """Resolve the caller's identity.

    Ships with static API-key auth, which is adequate for service-to-service
    calls inside a trusted network. Replace this dependency with an OIDC token
    verifier for user-facing deployments — that is the only change required,
    since everything downstream consumes :class:`Principal`.
    """
    if not settings.api.require_auth:
        return Principal(
            subject="anonymous",
            kind="service",
            permissions=frozenset({"*"}),
        )

    token = x_api_key
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:]

    if not token:
        raise AuthenticationError("a credential is required (X-API-Key or Bearer token)")

    for subject, configured in settings.api.api_keys.items():
        if constant_time_compare(token, configured):
            return Principal(
                subject=subject,
                kind="service",
                permissions=frozenset({"*"}),
            )

    raise AuthenticationError("the supplied credential was not recognised")


async def get_context(
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    x_correlation_id: Annotated[str | None, Header()] = None,
    x_tenant_id: Annotated[str | None, Header()] = None,
) -> ExecutionContext:
    """Build the per-request execution context.

    An inbound ``X-Correlation-Id`` is honoured so a trace spans the caller and
    this service; otherwise the middleware-generated id is used.
    """
    return ExecutionContext(
        correlation_id=x_correlation_id or getattr(request.state, "correlation_id", None) or "",
        principal=principal,
        tenant_id=x_tenant_id or principal.tenant_id,
        request_id=getattr(request.state, "request_id", None),
    )


async def bind_llm_profile(
    x_llm_profile: Annotated[str | None, Header()] = None,
) -> AsyncIterator[None]:
    """Pin the model profile for the duration of one request.

    Applied globally, so *any* endpoint that ends up calling a model — form
    extraction, question phrasing, form inference — honours the header without
    threading a parameter through its signature. An unknown name falls back to
    the active profile rather than failing the request: choosing a model is not
    the caller's business to get right.
    """
    if not x_llm_profile:
        yield
        return
    with use_profile(x_llm_profile):
        yield


# Registry accessors. Declared as dependencies rather than imported directly so
# tests can override them with isolated instances.
def get_skill_registry() -> SkillRegistry:
    return skill_registry


def get_skill_runtime() -> SkillRuntime:
    return skill_runtime


def get_tool_registry() -> ToolRegistry:
    return tool_registry


def get_tool_executor() -> ToolExecutor:
    return tool_executor


def get_workflow_registry() -> WorkflowRegistry:
    return workflow_registry


def get_engine() -> OrchestrationEngine:
    return engine


def get_connector_registry() -> ConnectorRegistry:
    return connector_registry


ContextDep = Annotated[ExecutionContext, Depends(get_context)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
SkillRegistryDep = Annotated[SkillRegistry, Depends(get_skill_registry)]
SkillRuntimeDep = Annotated[SkillRuntime, Depends(get_skill_runtime)]
ToolRegistryDep = Annotated[ToolRegistry, Depends(get_tool_registry)]
ToolExecutorDep = Annotated[ToolExecutor, Depends(get_tool_executor)]
WorkflowRegistryDep = Annotated[WorkflowRegistry, Depends(get_workflow_registry)]
EngineDep = Annotated[OrchestrationEngine, Depends(get_engine)]
ConnectorRegistryDep = Annotated[ConnectorRegistry, Depends(get_connector_registry)]

__all__ = [
    "ConnectorRegistryDep",
    "ContextDep",
    "EngineDep",
    "SettingsDep",
    "SkillRegistryDep",
    "SkillRuntimeDep",
    "ToolExecutorDep",
    "ToolRegistryDep",
    "WorkflowRegistryDep",
    "bind_llm_profile",
    "get_context",
    "get_principal",
]
