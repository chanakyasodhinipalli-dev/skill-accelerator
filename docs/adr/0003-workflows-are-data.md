# ADR 0003: Workflow definitions are data, not code

**Status:** Accepted
**Date:** 2026-08-06

## Context

Workflows must be authorable by people who are not platform engineers, storable
in a database, submittable over an API, reviewable by compliance, and —
increasingly — generatable by an LLM from a stated goal.

Every one of those uses is unsafe if a workflow definition can execute arbitrary
code. An LLM-generated Python callable that the engine `exec`s is a remote code
execution primitive with extra steps.

## Decision

A workflow is a declarative DAG. Steps name a target and bind inputs through
`${...}` expressions resolved against a restricted scope.

The expression language supports:

* path lookup — `${inputs.x}`, `${steps.fetch.output.email}`, `${items.0}`
* comparison — `==`, `!=`, `<`, `>`, `<=`, `>=`
* boolean composition — `and`, `or`, `not`
* literals — strings, numbers, booleans, null

It does **not** support: function calls, arithmetic, attribute access, imports,
or `eval`. Path traversal walks dicts and lists only, so `${inputs.x.__class__}`
resolves to `None` rather than reaching a Python object.

Two further rules make the model safe in practice:

**Bindings must match declared dependencies.** Reading `${steps.x.output}`
without `x` in `depends_on` is rejected when the graph is built.

**A missing path resolves to `None`, not an error.** An optional upstream output
should not abort a run.

## Consequences

**Good.** Definitions are safe to store, transmit, and generate. A compliance
reviewer can read a YAML file and know exactly what it does. The planner can
emit a workflow and have it validated — including cycle detection and binding
checks — before anything executes; validation failures are fed back for repair.

**Bad.** Genuine computation needs a step. Reshaping data means a `transform`
step or a small skill, where a Python lambda would have been three lines. This
is the cost of the guarantee, and it is paid on every workflow.

**Neutral.** The language will accrete features under pressure — string
formatting, arithmetic. Each addition must be weighed against the property that
motivated the design, and "someone asked for it" is not sufficient.

## Why the dependency rule is strict

Steps with no dependency between them run concurrently. A step that reads
another's output without declaring the dependency is therefore a race: it passes
in development, where the upstream step happens to be fast, and fails under load
when it is not.

Making this a load-time error rather than a runtime `None` converts a class of
intermittent production bugs into a message at authoring time. It caught a real
mistake in this repository's own example workflow the first time it ran.
