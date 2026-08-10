# Architecture

## Why a monorepo of packages

Seven distributions in one repository, rather than one package or seven repos.

One package would let any module import any other, and the layering would erode
within a quarter. Seven repos would make a cross-cutting change — adding a field
to the execution context, say — a multi-day, multi-PR exercise.

The middle path: independently versioned and releasable packages, developed and
tested atomically. `sa-platform` can be published for a team that wants only the
resilience primitives; `sa-skills` can be consumed without the API layer.

The rule that makes it work is **dependencies point downward only**:

```
sa-api, sa-cli    →  sa-orchestrator  →  sa-skills, sa-tools  →  sa-connectors  →  sa-platform
```

`sa-platform` imports nothing internal. Any cycle is a design error, not a
packaging inconvenience.

## The ambient context

`ExecutionContext` carries identity, tenancy, correlation, and deadline through
every layer via `contextvars`. It is a frozen dataclass; derivation returns a
copy, so a step cannot affect its siblings.

Why ambient rather than an explicit parameter: correlation must reach the log
formatter, the telemetry span, and the outbound HTTP header. Threading it
through every signature would mean touching every function to add one field, and
would be forgotten in exactly the places that matter — inside an exception
handler, inside a retry.

Deadlines compose. `with_deadline_in()` never *extends* an existing deadline,
and `budget()` clamps any requested timeout to what remains. A skill with a
60-second timeout called from a workflow step with 10 seconds left gets 10.

## Errors are values at boundaries, exceptions internally

Inside a skill or tool, raise. At the boundary — `SkillResult`, `ToolResult` —
failures become data.

This matters for agent loops. A model that calls a tool and gets an exception
sees nothing; a model that gets `{"is_error": true, "content": "..."}` can
adapt and try something else. It matters for workflows too: an engine needs to
record a partial failure and decide, not unwind the stack.

Every failure carries an `ErrorCode`, which decides both HTTP status and
retryability. Retry logic asks the error whether another attempt could help
rather than inspecting exception types — so a 429 from an upstream API, a
circuit-open rejection, and a database timeout are all handled by one rule.

## Skills versus tools

They look similar and are not the same thing.

A **skill** is a unit of business capability, owned by a team, versioned,
with a manifest that survives independently of any caller. Skills are what the
organisation accumulates.

A **tool** is an invocation surface — the shape an LLM (or a workflow, or an
operator) uses to act. Tools include skills, but also MCP operations, OpenAPI
endpoints, and primitives like the clock.

The bridge is one-directional: a skill is *exposed as* a tool by `SkillTool`,
which derives the tool spec from the manifest. Skill authors never see tool
calling. The danger level is inferred — a non-idempotent skill is `high` — so a
new skill is conservatively classified by default rather than permissively.

## The approval gate

An LLM decides *which* tool to call. The policy layer decides whether that call
happens. Keeping the two separate is what makes an autonomous agent safe to
point at real systems.

Checks run in ascending order of cost:

1. deny list → allow list → scope (cheap string matching, deterministic)
2. permissions (evaluated against the ambient principal)
3. the approval handler (may block on a human)

The default handler returns `DEFER`, not `DENY`. Denying would make the agent's
plan fail silently and push it toward a workaround; deferring surfaces the
decision, returns HTTP 428, and lets a human answer. The run checkpoints and can
be resumed with the decision attached.

`ToolPolicy.scoped_to()` derives a narrower policy from a broader one. A skill
declaring `allowed_tools` gets an executor that cannot reach outside that set,
so a skill cannot widen its own blast radius at runtime.

## Workflows as data

A workflow definition contains no executable code. Steps name a target and bind
inputs through `${...}` expressions resolved against a restricted scope.

The expression evaluator supports path lookup, comparison, and boolean
composition — no `eval`, no attribute access, no imports. Path lookup walks
dicts and lists only; `${inputs.x.__class__}` resolves to `None`. This is what
makes it safe to store workflow definitions in a database, accept them over an
API, or have an LLM generate one.

**Bindings must match dependencies.** Reading `${steps.x.output}` without
declaring `x` in `depends_on` is rejected when the graph is built. Steps with no
dependency between them run concurrently, so an undeclared dependency is a race
that would pass in testing and fail under load.

The scheduler groups steps into levels via Kahn's algorithm. Everything in a
level runs concurrently under a bounded semaphore. A workflow's parallelism is a
property of its declared shape, not of how the author ordered the list.

## Failure handling in workflows

Three policies, per step:

* `FAIL` (default) — abort the run and compensate
* `CONTINUE` — record the failure and keep going
* `SKIP_BRANCH` — mark the step and everything downstream as skipped

`CONTINUE` has a subtlety worth stating: a step whose *dependency* failed is
skipped, not run. The data it expected does not exist, so running it would
either crash on a `None` or — worse — silently produce a result computed from
missing input.

Compensation is saga-style: on failure, steps that succeeded are rolled back in
reverse completion order via their declared `compensate_with`. A compensation
that itself fails is logged and recorded in `metadata.failed_compensations`, and
the remaining rollbacks still run — stopping halfway would leave the system in a
worse state than either extreme.

## State and resumption

`RunState` is fully serialisable, checkpointed after every level. That gives
three things: resumption after a restart, resumption after an approval pause,
and an inspectable record of what actually happened.

The in-memory store is the default and correct for a single process. It is
bounded by count and TTL — an unbounded run history is a memory leak in any
long-lived service. `StateStore` is a four-method interface precisely so a
Redis or Postgres backend is a drop-in.

## Connectors and the tool registry

Anything reaching outside the process is a `Connector` with a lifecycle and a
health probe. Connectors that expose operations implement `ToolProvider`.

The consequence: an MCP server's tools and an OpenAPI endpoint's operations land
in the same registry as native tools, and inherit the same policy, approval
gate, and audit trail. There is no path by which a remote server's tool executes
under weaker rules than a local one.

MCP annotations are advisory hints from the server, so they are read
pessimistically: an unannotated remote tool is assumed destructive, not
harmless.

## LLM provider design

`LLMProvider` is provider-neutral; `AnthropicProvider` implements it.

Content blocks are preserved as raw dicts through the conversation. Thinking
blocks in particular must be echoed back unmodified — an edited block is
rejected — so the round trip is deliberately lossless rather than normalised
into a tidy internal model.

The agent loop is hand-written rather than delegated to the SDK tool runner.
Two reasons, both structural: tool execution must go through the platform's
executor for policy and audit, and a gated tool must pause the loop and return
control to a human. The runner's per-turn hooks cover approval gating in
general; they do not cover suspending a run, checkpointing it, and resuming it
hours later with a decision attached.

Prompt caching shapes two decisions elsewhere in the codebase: tool definitions
are emitted in sorted order, and the clock is a tool rather than a system-prompt
field. Both exist to keep the cached prefix byte-identical across requests.

## What is deliberately not here

* **A database.** The state store is an interface with an in-memory
  implementation. Picking Postgres versus DynamoDB is a deployment decision.
* **A queue.** Async workflow execution uses FastAPI background tasks. A real
  distributed deployment wants Celery, Temporal, or SQS — `StateStore` plus the
  engine's resumption support is the seam for that.
* **A real auth provider.** `get_principal` implements static API keys.
  Replacing it with an OIDC verifier is a one-dependency change because
  everything downstream consumes `Principal`.
* **A metrics backend.** In-process counters exist as a debug and test surface.
  Wire the OTLP exporter for production.

Each is a seam, not an omission — but each is genuinely unimplemented, and a
production deployment needs to fill it in.
