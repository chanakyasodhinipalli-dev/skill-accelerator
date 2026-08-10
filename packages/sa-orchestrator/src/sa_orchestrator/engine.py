"""The workflow execution engine.

Executes a validated DAG level by level, running independent steps
concurrently. Responsibilities:

* resolve each step's input bindings and ``when`` guard
* enforce per-step and per-run deadlines and retries
* checkpoint run state after every step so a run can resume
* pause cleanly when a step needs human approval
* run compensations in reverse completion order when a run fails (saga)
"""

from __future__ import annotations

import time
from typing import Any

from sa_platform.config import get_settings
from sa_platform.context import ExecutionContext, current_context
from sa_platform.errors import (
    AcceleratorError,
    ApprovalRequiredError,
    ValidationError,
    wrap,
)
from sa_platform.events import Events, event_bus
from sa_platform.logging import get_logger
from sa_platform.resilience import RetryPolicy, gather_bounded, retry_async, with_timeout
from sa_platform.schema import validate_payload
from sa_platform.security import authorize
from sa_platform.telemetry import get_tracer, metrics

from .expressions import build_scope, evaluate_condition, resolve
from .graph import ExecutionGraph, build_graph
from .middleware import Middleware, MiddlewareChain
from .models import (
    ErrorPolicy,
    RunState,
    RunStatus,
    StepResult,
    StepStatus,
    StepType,
    WorkflowSpec,
    WorkflowStep,
)
from .router import StepRouter
from .state import StateStore, build_state_store

logger = get_logger(__name__)
tracer = get_tracer("sa.orchestrator")


class OrchestrationEngine:
    """Runs workflows."""

    def __init__(
        self,
        *,
        router: StepRouter | None = None,
        state_store: StateStore | None = None,
        middleware: list[Middleware] | None = None,
    ) -> None:
        settings = get_settings().orchestrator
        self._router = router or StepRouter()
        self._state = state_store or build_state_store(settings.state_backend)
        self._middleware = MiddlewareChain(middleware or [])
        self._settings = settings

    @property
    def state_store(self) -> StateStore:
        return self._state

    # -- public API -------------------------------------------------------
    async def run(
        self,
        spec: WorkflowSpec,
        inputs: dict[str, Any] | None = None,
        *,
        ctx: ExecutionContext | None = None,
        run_id: str | None = None,
    ) -> RunState:
        """Execute a workflow to completion (or to a pause/failure).

        Never raises for business failures — inspect ``state.status``.
        Configuration and authorization problems do raise, because they mean
        the run should never have started.
        """
        ctx = ctx or current_context()
        inputs = inputs or {}

        graph = build_graph(spec)

        if spec.required_permissions:
            authorize(ctx.principal, spec.required_permissions, resource=f"workflow:{spec.name}")
        if spec.inputs_schema:
            validate_payload(inputs, spec.inputs_schema, label=f"{spec.name} inputs")

        state = RunState(
            workflow=spec.name,
            workflow_version=spec.version,
            inputs=inputs,
            status=RunStatus.RUNNING,
            correlation_id=ctx.correlation_id,
        )
        if run_id:
            state.run_id = run_id

        run_timeout = spec.timeout_seconds or self._settings.default_run_timeout_seconds
        run_ctx = ctx.child(run_id=state.run_id).with_deadline_in(run_timeout)

        with tracer.span(
            "workflow.run",
            workflow=spec.name,
            workflow_version=spec.version,
            run_id=state.run_id,
            steps=graph.size,
        ) as span:
            await self._state.save(state)
            await event_bus.emit(
                Events.WORKFLOW_STARTED,
                workflow=spec.name,
                run_id=state.run_id,
                correlation_id=run_ctx.correlation_id,
            )

            try:
                await self._execute_levels(spec, graph, state, run_ctx)
            except ApprovalRequiredError as exc:
                state.status = RunStatus.AWAITING_APPROVAL
                state.pending_approvals.append(exc.to_dict())
                logger.info(
                    "workflow paused for approval",
                    extra={"workflow": spec.name, "run_id": state.run_id},
                )
            except BaseException as exc:  # noqa: BLE001 - recorded on the run
                error = wrap(exc, message=f"workflow '{spec.name}' failed: {exc}")
                state.status = RunStatus.FAILED
                state.error = error.to_dict()
                span.record_exception(error)
                logger.error(
                    "workflow failed",
                    exc_info=exc,
                    extra={"workflow": spec.name, "run_id": state.run_id},
                )

            # -- terminal handling --------------------------------------
            if state.status is RunStatus.RUNNING:
                state.status = RunStatus.SUCCEEDED
                state.outputs = self._project_outputs(spec, state)

            if state.status is RunStatus.FAILED and (
                spec.compensate_on_failure and self._settings.compensate_on_failure
            ):
                await self._compensate(spec, state, run_ctx)

            state.completed_at = time.time()
            await self._state.save(state)

            span.set_attributes({"status": state.status.value, "duration_ms": state.duration_ms})
            metrics.increment("workflow.runs", workflow=spec.name, status=state.status.value)
            metrics.observe("workflow.duration_ms", state.duration_ms, workflow=spec.name)

            await event_bus.emit(
                Events.WORKFLOW_COMPLETED
                if state.status is RunStatus.SUCCEEDED
                else Events.WORKFLOW_FAILED,
                workflow=spec.name,
                run_id=state.run_id,
                status=state.status.value,
                duration_ms=state.duration_ms,
            )
            return state

    async def resume(
        self,
        spec: WorkflowSpec,
        run_id: str,
        *,
        approvals: dict[str, bool] | None = None,
        ctx: ExecutionContext | None = None,
    ) -> RunState:
        """Resume a paused run, replaying only the steps that have not succeeded."""
        state = await self._state.load(run_id)
        if state.is_terminal:
            raise ValidationError(
                f"run '{run_id}' is already {state.status.value} and cannot be resumed",
                details={"run_id": run_id, "status": state.status.value},
            )

        ctx = ctx or current_context()
        state.status = RunStatus.RUNNING
        state.pending_approvals.clear()
        if approvals:
            state.metadata["approvals"] = {**state.metadata.get("approvals", {}), **approvals}

        graph = build_graph(spec)
        run_timeout = spec.timeout_seconds or self._settings.default_run_timeout_seconds
        run_ctx = ctx.child(run_id=state.run_id).with_deadline_in(run_timeout)

        try:
            await self._execute_levels(spec, graph, state, run_ctx)
        except ApprovalRequiredError as exc:
            state.status = RunStatus.AWAITING_APPROVAL
            state.pending_approvals.append(exc.to_dict())
        except BaseException as exc:  # noqa: BLE001
            error = wrap(exc)
            state.status = RunStatus.FAILED
            state.error = error.to_dict()

        if state.status is RunStatus.RUNNING:
            state.status = RunStatus.SUCCEEDED
            state.outputs = self._project_outputs(spec, state)
            state.completed_at = time.time()

        await self._state.save(state)
        return state

    # -- execution --------------------------------------------------------
    async def _execute_levels(
        self,
        spec: WorkflowSpec,
        graph: ExecutionGraph,
        state: RunState,
        ctx: ExecutionContext,
    ) -> None:
        skipped: set[str] = set()
        parallelism = min(spec.max_parallel, self._settings.max_parallel_steps)

        for level in graph.levels:
            ctx.check_deadline()

            runnable: list[WorkflowStep] = []
            for step_id in level:
                step = graph.steps[step_id]

                # Already succeeded on a previous attempt — do not re-run.
                existing = state.steps.get(step_id)
                if existing is not None and existing.ok:
                    continue

                # An upstream step was skipped, so this branch is dead.
                if skipped & set(step.depends_on):
                    self._mark_skipped(state, step, "an upstream step was skipped")
                    skipped.add(step_id)
                    continue

                # A dependency failed under CONTINUE — the data it should have
                # produced is missing, so downstream work cannot be trusted.
                failed_deps = [
                    d
                    for d in step.depends_on
                    if (r := state.steps.get(d)) is not None and r.status is StepStatus.FAILED
                ]
                if failed_deps:
                    self._mark_skipped(state, step, f"dependency failed: {', '.join(failed_deps)}")
                    skipped.add(step_id)
                    continue

                scope = build_scope(state.inputs, state.outputs_by_step())
                if not evaluate_condition(step.when, scope):
                    self._mark_skipped(state, step, f"condition '{step.when}' evaluated false")
                    skipped.add(step_id)
                    continue

                runnable.append(step)

            if not runnable:
                continue

            results = await gather_bounded(
                [self._execute_step(spec, step, state, ctx) for step in runnable],
                limit=parallelism,
                return_exceptions=True,
            )

            for step, outcome in zip(runnable, results, strict=True):
                if isinstance(outcome, ApprovalRequiredError):
                    state.record(
                        StepResult(
                            step_id=step.id,
                            status=StepStatus.AWAITING_APPROVAL,
                            error=outcome.to_dict(),
                        )
                    )
                    await self._checkpoint(state)
                    raise outcome
                if isinstance(outcome, BaseException):
                    raise outcome

                state.record(outcome)
                if outcome.status is StepStatus.FAILED:
                    if step.on_error is ErrorPolicy.FAIL:
                        error = outcome.error or {}
                        raise AcceleratorError(
                            f"step '{step.id}' failed: {error.get('message', 'unknown error')}",
                            details={"step": step.id, **error},
                        )
                    if step.on_error is ErrorPolicy.SKIP_BRANCH:
                        skipped.update(graph.descendants(step.id))

            await self._checkpoint(state)

    async def _execute_step(
        self,
        spec: WorkflowSpec,
        step: WorkflowStep,
        state: RunState,
        ctx: ExecutionContext,
    ) -> StepResult:
        started = time.perf_counter()
        started_at = time.time()
        attempts = 0

        step_ctx = ctx.child(step_id=step.id)
        timeout = step.timeout_seconds or self._settings.default_step_timeout_seconds
        step_ctx = step_ctx.with_deadline_in(timeout)

        scope = build_scope(state.inputs, state.outputs_by_step())

        with tracer.span(
            "workflow.step", workflow=spec.name, step=step.id, step_type=step.type.value
        ) as span:
            await event_bus.emit(
                Events.STEP_STARTED,
                workflow=spec.name,
                run_id=state.run_id,
                step=step.id,
                type=step.type.value,
            )

            async def attempt() -> Any:
                nonlocal attempts
                attempts += 1
                if step.type is StepType.MAP:
                    return await self._execute_map(step, state, step_ctx, scope)
                inputs = resolve(step.inputs, scope)
                if not isinstance(inputs, dict):
                    raise ValidationError(
                        f"step '{step.id}' inputs must resolve to an object, "
                        f"got {type(inputs).__name__}"
                    )
                return await self._middleware.run(
                    step,
                    inputs,
                    step_ctx,
                    lambda resolved: self._router.execute(step, resolved, step_ctx, scope),
                )

            retry_policy = RetryPolicy(
                max_attempts=step.retry.max_attempts if step.retry else 1,
                base_delay=step.retry.base_delay_seconds if step.retry else 0.5,
                max_delay=step.retry.max_delay_seconds if step.retry else 30.0,
            )

            try:
                output = await with_timeout(
                    retry_async(attempt, policy=retry_policy, operation=f"step:{step.id}"),
                    timeout,
                    operation=f"step:{step.id}",
                )
            except ApprovalRequiredError:
                raise
            except BaseException as exc:  # noqa: BLE001 - normalised into a result
                error = wrap(exc, message=f"step '{step.id}' failed: {exc}")
                span.record_exception(error)
                metrics.increment("workflow.step_failed", workflow=spec.name, step=step.id)
                await event_bus.emit(
                    Events.STEP_FAILED,
                    workflow=spec.name,
                    run_id=state.run_id,
                    step=step.id,
                    error=error.to_dict(),
                )
                logger.warning(
                    "workflow step failed",
                    extra={
                        "workflow": spec.name,
                        "run_id": state.run_id,
                        "step": step.id,
                        "attempts": attempts,
                        "error": error.message,
                    },
                )
                return StepResult(
                    step_id=step.id,
                    status=StepStatus.FAILED,
                    error=error.to_dict(),
                    started_at=started_at,
                    duration_ms=(time.perf_counter() - started) * 1000,
                    attempts=attempts,
                )

            duration_ms = (time.perf_counter() - started) * 1000
            span.set_attribute("attempts", attempts)
            metrics.observe("workflow.step_duration_ms", duration_ms, step=step.id)
            await event_bus.emit(
                Events.STEP_COMPLETED,
                workflow=spec.name,
                run_id=state.run_id,
                step=step.id,
                duration_ms=duration_ms,
            )
            return StepResult(
                step_id=step.result_key,
                status=StepStatus.SUCCEEDED,
                output=output,
                started_at=started_at,
                duration_ms=duration_ms,
                attempts=attempts,
            )

    async def _execute_map(
        self,
        step: WorkflowStep,
        state: RunState,
        ctx: ExecutionContext,
        scope: dict[str, Any],
    ) -> list[Any]:
        """Fan the step's target out over a collection."""
        collection = resolve(step.over, scope)
        if collection is None:
            return []
        if not isinstance(collection, (list, tuple)):
            raise ValidationError(
                f"map step '{step.id}' expected a list from '{step.over}', "
                f"got {type(collection).__name__}",
                details={"step": step.id, "over": step.over},
            )

        async def run_one(index: int, item: Any) -> Any:
            item_scope = {**scope, step.as_: item, "index": index}
            inputs = resolve(step.inputs, item_scope)
            if not isinstance(inputs, dict):
                inputs = {step.as_: item}
            # A map iteration is a plain step of the same target type.
            iteration = step.model_copy(
                update={"type": StepType.SKILL if step.target else StepType.NOOP}
            )
            return await self._router.execute(iteration, inputs, ctx, item_scope)

        outcomes = await gather_bounded(
            [run_one(i, item) for i, item in enumerate(collection)],
            limit=step.max_parallel,
            return_exceptions=True,
        )

        # Report per-item outcomes rather than failing the whole fan-out: a
        # caller usually wants the 98 successes plus a list of the 2 failures.
        return [
            {"index": index, "ok": False, "error": str(outcome)}
            if isinstance(outcome, BaseException)
            else {"index": index, "ok": True, "output": outcome}
            for index, outcome in enumerate(outcomes)
        ]

    # -- compensation -----------------------------------------------------
    async def _compensate(self, spec: WorkflowSpec, state: RunState, ctx: ExecutionContext) -> None:
        """Run compensations in reverse completion order (saga rollback)."""
        compensations = [
            (step_id, spec.step(step_id).compensate_with)
            for step_id in reversed(state.completed_order)
            if spec.step(step_id).compensate_with
        ]
        if not compensations:
            return

        state.status = RunStatus.COMPENSATING
        await self._checkpoint(state)
        logger.info(
            "compensating failed workflow",
            extra={"workflow": spec.name, "run_id": state.run_id, "count": len(compensations)},
        )

        for origin_step, compensation_id in compensations:
            if compensation_id is None:
                continue
            compensation = spec.step(compensation_id)
            scope = build_scope(
                state.inputs,
                state.outputs_by_step(),
                extra={"failed_step": origin_step},
            )
            try:
                inputs = resolve(compensation.inputs, scope)
                await with_timeout(
                    self._router.execute(compensation, inputs, ctx, scope),
                    compensation.timeout_seconds or self._settings.default_step_timeout_seconds,
                    operation=f"compensate:{compensation_id}",
                )
                state.record(StepResult(step_id=compensation_id, status=StepStatus.COMPENSATED))
                await event_bus.emit(
                    Events.COMPENSATION_RAN,
                    workflow=spec.name,
                    run_id=state.run_id,
                    step=compensation_id,
                    for_step=origin_step,
                )
            except Exception as exc:  # noqa: BLE001 - keep rolling back
                # A failed compensation is serious but must not stop the
                # remaining rollbacks; it is recorded for manual follow-up.
                logger.error(
                    "compensation failed",
                    exc_info=exc,
                    extra={
                        "workflow": spec.name,
                        "run_id": state.run_id,
                        "step": compensation_id,
                        "for_step": origin_step,
                    },
                )
                state.metadata.setdefault("failed_compensations", []).append(
                    {"step": compensation_id, "for_step": origin_step, "error": str(exc)}
                )

        state.status = RunStatus.COMPENSATED

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def _mark_skipped(state: RunState, step: WorkflowStep, reason: str) -> None:
        state.record(StepResult(step_id=step.id, status=StepStatus.SKIPPED, skipped_reason=reason))
        event_bus.emit_nowait(Events.STEP_SKIPPED, run_id=state.run_id, step=step.id, reason=reason)

    @staticmethod
    def _project_outputs(spec: WorkflowSpec, state: RunState) -> dict[str, Any]:
        if not spec.outputs:
            return state.outputs_by_step()
        scope = build_scope(state.inputs, state.outputs_by_step())
        projected = resolve(spec.outputs, scope)
        return projected if isinstance(projected, dict) else {"result": projected}

    async def _checkpoint(self, state: RunState) -> None:
        if self._settings.checkpoint_every_step:
            await self._state.save(state)


engine = OrchestrationEngine()

__all__ = ["OrchestrationEngine", "engine"]
