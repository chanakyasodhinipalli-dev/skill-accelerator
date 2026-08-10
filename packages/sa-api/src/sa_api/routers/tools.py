"""Tool catalogue and invocation endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from sa_tools.models import ToolResult, ToolSpec

from ..dependencies import ContextDep, ToolExecutorDep, ToolRegistryDep

router = APIRouter(prefix="/tools", tags=["tools"])


class ToolListResponse(BaseModel):
    count: int
    tools: list[ToolSpec]


class InvokeToolRequest(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float | None = Field(default=None, gt=0)
    approved: bool | None = Field(
        default=None,
        description="Approval decision for a gated tool. Omit to trigger the approval flow.",
    )


class BatchInvokeRequest(BaseModel):
    invocations: list[dict[str, Any]] = Field(
        description="Each entry: {tool, arguments, invocation_id?, approved?}"
    )


@router.get("", response_model=ToolListResponse, summary="List registered tools")
async def list_tools(
    registry: ToolRegistryDep,
    query: str | None = Query(default=None),
    kind: str | None = Query(default=None, description="native | skill | mcp | openapi"),
    max_danger: str | None = Query(default=None, description="safe | low | medium | high"),
) -> ToolListResponse:
    found = registry.search(query=query, kind=kind, max_danger=max_danger)
    return ToolListResponse(count=len(found), tools=[t.spec for t in found])


@router.get("/{name}", response_model=ToolSpec, summary="Describe one tool")
async def get_tool(name: str, registry: ToolRegistryDep) -> ToolSpec:
    return registry.require(name).spec


@router.get(
    "/definitions/anthropic",
    summary="Render the catalogue as Anthropic tool definitions",
)
async def anthropic_definitions(
    registry: ToolRegistryDep,
    max_danger: str | None = Query(default=None),
    names: list[str] | None = Query(default=None),
) -> dict[str, Any]:
    """Return the ``tools`` array to send with a Messages API request.

    Filter it down to what the calling agent actually needs — a narrower tool
    surface improves selection accuracy and costs fewer tokens per request.
    """
    definitions = registry.to_anthropic_tools(names=names, max_danger=max_danger)
    return {"count": len(definitions), "tools": definitions}


@router.post("/{name}/invoke", response_model=ToolResult, summary="Invoke a tool")
async def invoke_tool(
    name: str,
    request: InvokeToolRequest,
    executor: ToolExecutorDep,
    ctx: ContextDep,
) -> ToolResult:
    """Invoke a tool directly.

    A tool gated behind approval returns ``status: approval_required``; resend
    with ``approved: true`` once a human has decided.
    """
    return await executor.invoke(
        name,
        request.arguments,
        ctx=ctx,
        approved=request.approved,
        timeout_seconds=request.timeout_seconds,
    )


@router.post("/invoke/batch", summary="Invoke several tools")
async def invoke_batch(
    request: BatchInvokeRequest,
    executor: ToolExecutorDep,
    ctx: ContextDep,
) -> dict[str, Any]:
    """Run a batch, parallelising the tools that declare themselves safe to."""
    from sa_tools.models import ToolInvocation

    invocations = [ToolInvocation(**entry) for entry in request.invocations]
    results = await executor.execute_many(invocations, ctx=ctx)
    return {"count": len(results), "results": [r.model_dump(mode="json") for r in results]}
