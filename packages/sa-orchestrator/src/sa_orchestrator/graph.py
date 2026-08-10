"""DAG construction, validation, and level-order scheduling."""

from __future__ import annotations

from dataclasses import dataclass, field

from sa_platform.errors import ValidationError
from sa_platform.logging import get_logger

from .expressions import referenced_steps
from .models import WorkflowSpec, WorkflowStep

logger = get_logger(__name__)


@dataclass(slots=True)
class ExecutionGraph:
    """The scheduling view of a workflow.

    ``levels`` groups steps that may run concurrently: every step in level *n*
    depends only on steps in levels < *n*.
    """

    steps: dict[str, WorkflowStep]
    dependencies: dict[str, set[str]]
    dependents: dict[str, set[str]] = field(default_factory=dict)
    levels: list[list[str]] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.steps)

    @property
    def max_width(self) -> int:
        """Widest level — the peak parallelism the workflow can reach."""
        return max((len(level) for level in self.levels), default=0)

    def descendants(self, step_id: str) -> set[str]:
        """Every step transitively downstream of ``step_id``."""
        found: set[str] = set()
        frontier = [step_id]
        while frontier:
            current = frontier.pop()
            for child in self.dependents.get(current, set()):
                if child not in found:
                    found.add(child)
                    frontier.append(child)
        return found

    def roots(self) -> list[str]:
        return [sid for sid, deps in self.dependencies.items() if not deps]

    def leaves(self) -> list[str]:
        return [sid for sid in self.steps if not self.dependents.get(sid)]


def build_graph(spec: WorkflowSpec, *, strict_bindings: bool = True) -> ExecutionGraph:
    """Validate a workflow and compute its execution levels.

    ``strict_bindings`` rejects a step that reads ``${steps.x.output}`` without
    declaring ``x`` in ``depends_on`` — that combination is a race, not a
    shortcut, because nothing guarantees ``x`` has run.
    """
    steps = {step.id: step for step in spec.steps}
    dependencies: dict[str, set[str]] = {step.id: set(step.depends_on) for step in spec.steps}

    if strict_bindings:
        _validate_bindings(spec, dependencies)

    dependents: dict[str, set[str]] = {sid: set() for sid in steps}
    for step_id, deps in dependencies.items():
        for dep in deps:
            dependents[dep].add(step_id)

    levels = _topological_levels(dependencies, spec.name)

    graph = ExecutionGraph(
        steps=steps, dependencies=dependencies, dependents=dependents, levels=levels
    )
    logger.debug(
        "built execution graph",
        extra={
            "workflow": spec.qualified_name,
            "steps": graph.size,
            "levels": len(levels),
            "max_width": graph.max_width,
        },
    )
    return graph


def _validate_bindings(spec: WorkflowSpec, dependencies: dict[str, set[str]]) -> None:
    for step in spec.steps:
        referenced = referenced_steps(
            {
                "inputs": step.inputs,
                "when": step.when,
                "over": step.over,
                "prompt": step.prompt,
                "system": step.system,
            }
        )
        undeclared = referenced - dependencies[step.id] - {step.id}
        if undeclared:
            raise ValidationError(
                f"step '{step.id}' references step(s) {sorted(undeclared)} but does not "
                f"declare them in depends_on; add them or the ordering is undefined",
                details={"step": step.id, "undeclared": sorted(undeclared)},
            )


def _topological_levels(dependencies: dict[str, set[str]], workflow: str) -> list[list[str]]:
    """Kahn's algorithm, grouped into concurrency levels."""
    remaining = {sid: set(deps) for sid, deps in dependencies.items()}
    levels: list[list[str]] = []
    resolved: set[str] = set()

    while remaining:
        ready = sorted(sid for sid, deps in remaining.items() if not (deps - resolved))
        if not ready:
            # Everything left is part of, or blocked by, a cycle.
            cycle = _find_cycle(remaining)
            raise ValidationError(
                f"workflow '{workflow}' contains a dependency cycle: {' -> '.join(cycle)}",
                details={"workflow": workflow, "cycle": cycle},
            )
        levels.append(ready)
        resolved.update(ready)
        for sid in ready:
            del remaining[sid]

    return levels


def _find_cycle(remaining: dict[str, set[str]]) -> list[str]:
    """Locate one concrete cycle for the error message."""
    visiting: set[str] = set()
    path: list[str] = []

    def walk(node: str) -> list[str] | None:
        if node in visiting:
            start = path.index(node)
            return [*path[start:], node]
        if node not in remaining:
            return None
        visiting.add(node)
        path.append(node)
        for dependency in sorted(remaining[node]):
            found = walk(dependency)
            if found:
                return found
        visiting.discard(node)
        path.pop()
        return None

    for node in sorted(remaining):
        found = walk(node)
        if found:
            return found
    return sorted(remaining)


__all__ = ["ExecutionGraph", "build_graph"]
