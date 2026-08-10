"""sa-orchestrator — declarative workflow execution.

Workflows are data: a DAG of steps that bind inputs from workflow inputs and
upstream outputs via ``${...}`` expressions. Independent steps run in parallel,
state is checkpointed after every step, and failed runs roll back through
declared compensations.

    from sa_orchestrator import WorkflowSpec, engine

    spec = WorkflowSpec(
        name="onboard_counterparty",
        steps=[
            {"id": "fetch", "type": "skill", "target": "crm.fetch_entity",
             "inputs": {"entity_id": "${inputs.entity_id}"}},
            {"id": "score", "type": "skill", "target": "risk.score",
             "depends_on": ["fetch"],
             "inputs": {"profile": "${steps.fetch.output}"}},
        ],
        outputs={"risk": "${steps.score.output}"},
    )

    state = await engine.run(spec, {"entity_id": "C-1"})
"""

from __future__ import annotations

from .engine import OrchestrationEngine, engine
from .expressions import build_scope, evaluate_condition, resolve
from .graph import ExecutionGraph, build_graph
from .middleware import (
    AuditMiddleware,
    DryRunMiddleware,
    Middleware,
    MiddlewareChain,
    RateLimitMiddleware,
)
from .models import (
    ErrorPolicy,
    RetrySpec,
    RunState,
    RunStatus,
    StepResult,
    StepStatus,
    StepType,
    WorkflowSpec,
    WorkflowStep,
)
from .planner import WorkflowPlanner
from .registry import WorkflowRegistry, workflow_registry
from .router import StepRouter
from .state import InMemoryStateStore, StateStore, build_state_store

__version__ = "0.1.0"

__all__ = [
    "AuditMiddleware",
    "DryRunMiddleware",
    "ErrorPolicy",
    "ExecutionGraph",
    "InMemoryStateStore",
    "Middleware",
    "MiddlewareChain",
    "OrchestrationEngine",
    "RateLimitMiddleware",
    "RetrySpec",
    "RunState",
    "RunStatus",
    "StateStore",
    "StepResult",
    "StepRouter",
    "StepStatus",
    "StepType",
    "WorkflowPlanner",
    "WorkflowRegistry",
    "WorkflowSpec",
    "WorkflowStep",
    "__version__",
    "build_graph",
    "build_scope",
    "build_state_store",
    "engine",
    "evaluate_condition",
    "resolve",
    "workflow_registry",
]
