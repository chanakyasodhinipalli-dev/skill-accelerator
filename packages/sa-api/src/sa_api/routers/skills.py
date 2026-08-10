"""Skill catalogue and invocation endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from sa_skills.models import SkillManifest, SkillResult

from ..dependencies import ContextDep, SkillRegistryDep, SkillRuntimeDep

router = APIRouter(prefix="/skills", tags=["skills"])


class SkillListResponse(BaseModel):
    count: int
    skills: list[SkillManifest]


class InvokeRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)
    version: str | None = None
    timeout_seconds: float | None = Field(default=None, gt=0)
    dry_run: bool = False


@router.get("", response_model=SkillListResponse, summary="List registered skills")
async def list_skills(
    registry: SkillRegistryDep,
    query: str | None = Query(default=None, description="Substring filter"),
    category: str | None = Query(default=None),
    stability: str | None = Query(default=None),
) -> SkillListResponse:
    found = registry.search(query=query, category=category, stability=stability)
    return SkillListResponse(count=len(found), skills=[s.manifest for s in found])


@router.get("/{name}", response_model=SkillManifest, summary="Describe one skill")
async def get_skill(
    name: str,
    registry: SkillRegistryDep,
    version: str | None = Query(default=None),
) -> SkillManifest:
    return registry.require(name, version=version).manifest


@router.get("/{name}/versions", summary="List a skill's versions")
async def list_versions(name: str, registry: SkillRegistryDep) -> dict[str, Any]:
    registry.require(name)  # 404s if unknown
    return {"skill": name, "versions": registry.versions(name)}


@router.post("/{name}/invoke", response_model=SkillResult, summary="Invoke a skill")
async def invoke_skill(
    name: str,
    request: InvokeRequest,
    runtime: SkillRuntimeDep,
    ctx: ContextDep,
) -> SkillResult:
    """Invoke a skill synchronously.

    Returns HTTP 200 with a non-success ``status`` for business failures — the
    call itself succeeded, the work did not. Reserve non-2xx for problems with
    the request or the caller's authorization.
    """
    invocation_ctx = ctx.child(dry_run=request.dry_run) if request.dry_run else ctx
    return await runtime.invoke(
        name,
        request.payload,
        ctx=invocation_ctx,
        version=request.version,
        timeout_seconds=request.timeout_seconds,
    )


@router.post("/discover", summary="Re-run skill discovery")
async def rediscover(registry: SkillRegistryDep) -> dict[str, Any]:
    """Re-scan skill sources. Useful after deploying a new skill package."""
    registered = await registry.discover(force=True)
    return {"newly_registered": registered, "total": len(registry)}
