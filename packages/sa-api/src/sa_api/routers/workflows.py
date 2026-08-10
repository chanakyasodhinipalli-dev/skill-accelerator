"""Workflow definition, execution, and run-inspection endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Query
from pydantic import BaseModel, Field

from sa_orchestrator.models import RunState, WorkflowSpec

from ..dependencies import ContextDep, EngineDep, WorkflowRegistryDep

router = APIRouter(prefix="/workflows", tags=["workflows"])


class WorkflowSummary(BaseModel):
    name: str
    version: str
    description: str
    owner: str | None = None
    steps: int
    tags: list[str] = Field(default_factory=list)


class RunRequest(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    version: str | None = None
    run_id: str | None = None
    dry_run: bool = False
    #: Return immediately with a run id and execute in the background.
    asynchronous: bool = False


class ResumeRequest(BaseModel):
    approvals: dict[str, bool] = Field(
        default_factory=dict, description="invocation_id -> allow/deny"
    )
    version: str | None = None


@router.get("", response_model=list[WorkflowSummary], summary="List workflows")
async def list_workflows(registry: WorkflowRegistryDep) -> list[WorkflowSummary]:
    return [
        WorkflowSummary(
            name=spec.name,
            version=spec.version,
            description=spec.description,
            owner=spec.owner,
            steps=len(spec.steps),
            tags=spec.tags,
        )
        for spec in registry.all()
    ]


@router.get("/{name}", response_model=WorkflowSpec, summary="Get a workflow definition")
async def get_workflow(
    name: str,
    registry: WorkflowRegistryDep,
    version: str | None = Query(default=None),
) -> WorkflowSpec:
    return registry.require(name, version=version)


@router.get("/{name}/graph", summary="Inspect a workflow's execution plan")
async def get_graph(
    name: str,
    registry: WorkflowRegistryDep,
    version: str | None = Query(default=None),
) -> dict[str, Any]:
    """Return the computed DAG levels — what runs in parallel, and when."""
    from sa_orchestrator.graph import build_graph

    spec = registry.require(name, version=version)
    graph = build_graph(spec)
    return {
        "workflow": spec.qualified_name,
        "steps": graph.size,
        "levels": graph.levels,
        "max_parallelism": graph.max_width,
        "roots": graph.roots(),
        "leaves": graph.leaves(),
    }


@router.post("", response_model=WorkflowSpec, status_code=201, summary="Register a workflow")
async def register_workflow(
    spec: WorkflowSpec,
    registry: WorkflowRegistryDep,
    replace: bool = Query(default=False),
) -> WorkflowSpec:
    """Register a definition. The DAG is validated before it is accepted."""
    return registry.register(spec, replace=replace)


@router.post("/{name}/run", response_model=RunState, summary="Execute a workflow")
async def run_workflow(
    name: str,
    request: RunRequest,
    registry: WorkflowRegistryDep,
    engine: EngineDep,
    ctx: ContextDep,
    background: BackgroundTasks,
) -> RunState:
    """Run a workflow.

    Synchronous by default. Set ``asynchronous`` for long workflows: the
    response returns immediately with a run id, and the run continues in the
    background — poll ``/workflows/runs/{run_id}`` for progress.
    """
    spec = registry.require(name, version=request.version)
    run_ctx = ctx.child(dry_run=request.dry_run) if request.dry_run else ctx

    if not request.asynchronous:
        return await engine.run(spec, request.inputs, ctx=run_ctx, run_id=request.run_id)

    state = RunState(
        workflow=spec.name,
        workflow_version=spec.version,
        inputs=request.inputs,
        correlation_id=run_ctx.correlation_id,
    )
    if request.run_id:
        state.run_id = request.run_id
    # Persist before returning so the caller's poll never 404s on a valid id.
    await engine.state_store.save(state)

    background.add_task(engine.run, spec, request.inputs, ctx=run_ctx, run_id=state.run_id)
    return state


@router.post("/{name}/resume/{run_id}", response_model=RunState, summary="Resume a paused run")
async def resume_run(
    name: str,
    run_id: str,
    request: ResumeRequest,
    registry: WorkflowRegistryDep,
    engine: EngineDep,
    ctx: ContextDep,
) -> RunState:
    """Resume a run paused for approval. Steps that already succeeded are not re-run."""
    spec = registry.require(name, version=request.version)
    return await engine.resume(spec, run_id, approvals=request.approvals, ctx=ctx)


@router.get("/runs/{run_id}", response_model=RunState, summary="Get a run's state")
async def get_run(run_id: str, engine: EngineDep) -> RunState:
    return await engine.state_store.load(run_id)


@router.get("/runs", summary="List recent runs")
async def list_runs(
    engine: EngineDep,
    workflow: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    runs = await engine.state_store.list_runs(workflow=workflow, limit=limit)
    return {
        "count": len(runs),
        "runs": [
            {
                "run_id": r.run_id,
                "workflow": r.workflow,
                "status": r.status.value,
                "started_at": r.started_at,
                "duration_ms": r.duration_ms,
            }
            for r in runs
        ],
    }
