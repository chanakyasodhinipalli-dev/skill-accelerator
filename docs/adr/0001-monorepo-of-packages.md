# ADR 0001: A monorepo of independently versioned packages

**Status:** Accepted
**Date:** 2026-08-06

## Context

The platform spans concerns with genuinely different consumers and release
cadences: resilience primitives, business skills, an action surface for LLMs,
outbound integrations, a workflow engine, and two entry points.

Three shapes were considered.

**One package.** Simplest to start. But nothing prevents `sa_platform` importing
from `sa_orchestrator`, and layering violations accumulate silently — each one
individually reasonable, collectively fatal to modularity. Consumers who want
only the retry and circuit-breaker helpers must take FastAPI as a dependency.

**Seven repositories.** Enforces boundaries absolutely. But a cross-cutting
change — adding a field to `ExecutionContext`, say — becomes seven PRs across
seven repos with a version-bump dance between them. In practice teams stop
making such changes, and the abstraction rots in place instead.

**A monorepo of packages.** Boundaries are enforced by distribution metadata;
changes are made and tested atomically.

## Decision

Seven distributions under `packages/`, developed together, versioned and
releasable independently.

Dependencies point downward only:

```
sa-api, sa-cli → sa-orchestrator → sa-skills, sa-tools → sa-connectors → sa-platform
```

`sa-platform` depends on nothing internal.

## Consequences

**Good.** A team can depend on `sa-platform` alone. Layering violations fail at
install time, not review time. Cross-cutting changes stay a single PR with the
whole test suite as the gate. Optional dependencies are scoped to the package
that needs them — `anthropic` and `mcp` are extras of `sa-connectors`, so an
installation using only skills carries neither.

**Bad.** Seven `pyproject.toml` files to keep coherent. The editable install is
a loop rather than one command (`make install`, or `uv sync` with the declared
workspace). Contributors must know which package a change belongs in.

**Neutral.** Version skew between packages is possible once they publish
separately. Acceptable — that is the point of independent versioning — but it
means the compatibility matrix becomes real work at that stage.

## Alternatives rejected

*Namespace packages* (`accelerator.platform`, `accelerator.skills`) give the
same boundaries with a shared top-level name, but namespace-package tooling
remains a persistent source of import confusion for marginal benefit.

*A `src/` layout with enforced import linting* would work, but relies on a lint
rule staying enabled rather than on a structural property.
