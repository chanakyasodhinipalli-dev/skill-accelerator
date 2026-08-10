# Skill Accelerator

An enterprise Python monorepo for building, governing, and orchestrating
reusable AI capabilities.

The problem it solves: teams end up with skills scattered across services, tool
calling reimplemented per project, no consistent authorization story, and no
audit trail once an LLM starts taking actions. This repo puts one contract
under all of it.

```
┌──────────────────────────────────────────────────────────────┐
│  sa-console (browser UI)                                     │  operator UI
├──────────────────────────────────────────────────────────────┤
│  sa-api (HTTP)                    sa-cli (operators)         │  entry points
├──────────────────────────────────────────────────────────────┤
│  sa-forms                                                    │  form intake
│  conversation · extraction · ingestion · attachments ·       │
│  authoring · rendering · approval · assistant                │
├──────────────────────────────────────────────────────────────┤
│  sa-orchestrator                                             │  DAG workflows
│  graph · expressions · engine · state · saga · planner       │
├───────────────────────────────┬──────────────────────────────┤
│  sa-skills                    │  sa-tools                    │  capabilities
│  manifest · registry ·        │  spec · registry · policy ·  │
│  discovery · runtime          │  approval gate · executor    │
├───────────────────────────────┴──────────────────────────────┤
│  sa-connectors                                               │  integrations
│  HTTP · OpenAPI · MCP · LLM router                           │
│  Anthropic · OpenAI · Gemini · enterprise gateway            │
├──────────────────────────────────────────────────────────────┤
│  sa-platform                                                 │  foundation
│  config · context · errors · logging · telemetry ·           │
│  resilience · registry · security · events · health          │
└──────────────────────────────────────────────────────────────┘
```

Dependencies point downward only. `sa-platform` depends on nothing internal;
that acyclic rule is what keeps the packages independently releasable.

## The five concepts

| | What it is | Governed by |
|---|---|---|
| **Skill** | A versioned business capability with a declared contract | Manifest: input/output schema, permissions, timeout, stability |
| **Tool** | A callable action an LLM or workflow can invoke | Danger level, permission set, approval gate |
| **Connector** | A live relationship with something outside the process | Circuit breaker, retry policy, health probe |
| **Workflow** | A declarative DAG coordinating the above | Step policy, deadlines, compensation |
| **Form** | A versioned intake contract gathered by conversation | Field importance, approval policy, baselining |

A skill is automatically bridged into a tool, so authors never write tool-calling
code. An MCP server's tools land in the same registry as native ones — and
therefore under the same policy, approval, and audit path. There is no
privileged side channel.

## Quick start

```bash
make install          # editable install of all nine packages
make check            # lint + tests
sa doctor             # verify the wiring
make ui               # http://127.0.0.1:8100 — the console, API mounted in-process
sa serve              # http://localhost:8000/docs — the API on its own
```

`make ui` is the fastest way to see the whole thing work. It needs no credential:
pick **Deterministic (no model)** in the header and every screen still functions —
only generated wording falls back to fixed phrasing.

Optional extras: `make install-llm` adds the Anthropic SDK and the MCP client.

> Install into a virtual environment. `make install` targets whatever `python`
> resolves to, and installing into a shared interpreter can upgrade packages
> other projects pin.
>
> ```bash
> python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
> make install
> ```

## Authoring a skill

```python
from sa_skills import skill

@skill(category="analysis", owner="risk-platform", stability="stable",
       required_permissions=["skills:risk:score"])
async def score_counterparty(counterparty_id: str, as_of: str | None = None) -> dict:
    """Score a counterparty's credit risk from the latest filings.

    Args:
        counterparty_id: Internal counterparty identifier.
        as_of: ISO date to score against. Defaults to today.
    """
    ...
```

The input schema, description, and parameter docs are derived from the
signature and docstring. Nothing else is required — the skill is now:

* invocable via `POST /skills/score_counterparty/invoke`
* runnable from `sa skills run score_counterparty -p '{...}'`
* usable as a workflow step
* callable by a model as the tool `skill_score_counterparty`

A `skill.yaml` beside the module overrides any manifest field, so permissions
and stability are reviewable without reading Python.

## Authoring a tool

```python
from sa_tools import tool

@tool(danger="medium", required_permissions=["crm:write"])
async def create_ticket(subject: str, priority: str = "normal") -> dict:
    """File a support ticket. Call this when the user asks to open, raise, or
    escalate an issue that needs tracking.

    Args:
        subject: One-line summary of the problem.
        priority: One of low, normal, high.
    """
    ...
```

The description is the highest-leverage field: state *when* to call the tool,
not only what it does.

## Workflows

Workflows are data — a DAG whose steps bind inputs via `${...}` expressions:

```yaml
name: document_review
steps:
  - id: summarize
    type: skill
    target: document.summarize
    inputs: { text: ${inputs.text} }

  - id: policy                    # no dependency on summarize, so both
    type: skill                   # run concurrently in level 0
    target: compliance.check_policy
    inputs: { content: ${inputs.text}, rules: ${inputs.rules} }
    on_error: continue

  - id: escalate
    type: transform
    depends_on: [policy]
    when: ${steps.policy.output.passed == false}
    inputs: { severity: ${steps.policy.output.highest_severity} }

outputs:
  passed: ${steps.policy.output.passed}
```

```bash
sa workflows graph document_review   # shows what runs in parallel
sa workflows run document_review -i @payload.json
```

Expressions are path lookups plus comparison and boolean operators. There is no
`eval` and no attribute access, so a workflow definition — including one an LLM
generated — cannot execute arbitrary code.

Reading `${steps.x.output}` without declaring `x` in `depends_on` is rejected at
load time. That combination is a race, not a shortcut.

## Conversational form intake

`sa-forms` replaces manual form filling — and the email and ticket back-and-forth
around it — with one resumable conversation that also mines the discussions that
already happened.

```python
started = await forms_service.start_session("change_request", participant="alice")
sid = started["session_id"]

await forms_service.ingest(sid, "jira", jira_payload)      # mine the ticket first
await forms_service.send(sid, "15 min downtime, medium risk, Priya owns it")
artifacts = await forms_service.generate(sid, ["xlsx", "pdf"])
await forms_service.approve(artifacts[0].id, approver="bob")   # -> baselined
```

What makes it generic rather than one bot per form:

* **Questions are computed, not written.** Gap analysis reads the definition and
  the session; the model only phrases the result. Adding a field changes the
  conversation with no code change.
* **Every message is extracted against every outstanding field.** "Priya owns it
  and we're going on the 15th" settles two fields, and neither is asked again —
  whether it was said this turn or in a ticket comment last week.
* **One pipeline, many channels.** Chat, JIRA, email, meeting transcripts, and
  uploaded `.eml` files *with their attachments* all normalise to
  `SourceMessage`, with quoted history and signatures stripped before
  extraction. An attached spreadsheet of impacted systems gets mined the same
  way the covering note does — and an attachment that could not be read is
  reported rather than silently dropped.
* **Ask about any of it.** A cross-session assistant answers "what did we decide
  about the December release?" and "what is waiting on me?" from retrieved
  records, cited by id. Retrieval is deterministic; only the prose is generated.
* **Forms are data.** Upload the spreadsheet you fill in today and the authoring
  pass infers the definition — including the "why do you need this?" rationale —
  then asks about whatever it could not settle.
* **Answers are written up, not transcribed.** "8AM ro 11PM" becomes
  `08:00-23:00`; a typo-ridden fragment becomes a sentence that stands on its
  own. The exact text typed stays on the record, and deterministic guards
  discard any rewrite that introduces a number nobody stated or pads the
  original — a field that reads awkwardly beats one that reads well and is wrong.
* **The submission is checked against itself.** Declared cross-field rules plus
  a semantic review catch what per-field validation cannot see: a six-hour
  outage marked as not customer-impacting, a reviewer who is also the owner, a
  downtime that does not fit its own maintenance window. Each one is put to the
  owner as a question, once. Correcting an answer clears it; standing by it
  records *why*, and that reason goes on the document — which is the thing an
  approver would otherwise have to ask for.
* **Artifacts carry provenance.** Each answer records which channel, which
  person, and the verbatim text supporting it. A manually filled form never has
  that.

Full guide: [docs/forms.md](docs/forms.md).

## Governance

Three checks stand between a model's intent and a real side effect:

1. **Allow/deny and scope.** Cheap, deterministic, evaluated first. A skill
   declares `allowed_tools`; the executor enforces it, so a skill cannot widen
   its own blast radius.
2. **Permissions.** The `Principal` on the ambient context must hold every
   permission the skill or tool declares.
3. **The approval gate.** Tools at or above the configured danger level need an
   explicit decision. The default handler *defers* rather than denying, so a
   run pauses and a human decides instead of the agent silently failing.

A paused workflow checkpoints its state and returns `awaiting_approval`. Resume
it with `POST /workflows/{name}/resume/{run_id}` — steps that already succeeded
are not re-run.

## The operator console

`sa-console` is a browser UI over the API — a separate deployable, so it can run
beside the platform for a demo or as its own container pointed at a remote
deployment.

```bash
make ui                                   # API mounted in this process
sa-console --api https://sa.internal      # proxy to a remote deployment
```

It covers the whole surface: the form catalogue and its versions, the form
builder, the session workspace (chat beside the form's live state), email and
attachment upload, artifacts and approvals, the cross-session assistant, model
switching, and a read-mostly view of skills, tools, workflows, and connectors.

Vanilla ES modules, one stylesheet, no build step. `npm` is not in the loop.

Full guide: [docs/console.md](docs/console.md).

## Model providers

OpenAI by default; Anthropic, Gemini, or an enterprise gateway fronting several
of them — selected per call, per request, or per process. Out of the box the
platform reaches `gpt-4o` and needs only `OPENAI_API_KEY` in the environment.

```yaml
llm:
  active_profile: openai
  fallback_profiles: [anthropic, gemini]  # cross-vendor, on retryable errors only
  profiles:
    - { name: anthropic, vendor: anthropic, model: claude-opus-5, api_key_env: ANTHROPIC_API_KEY }
    - name: corp-gateway
      vendor: gateway
      dialect: openai                     # what this side of the call looks like
      base_url: https://llm-gateway.corp.internal/v1
      auth_header: x-virtual-key
      headers: { x-cost-centre: risk-platform }
```

The router **is** an `LLMProvider`. Every component already depends on that
interface, so switching vendors is configuration and touches no business code.
Send `X-LLM-Profile: <name>` on any request to pin the model for that one call.

Tools are authored once — the registry emits Anthropic-shaped definitions and
each provider translates — so a tool written for one vendor works on all of them.

A deterministic `stub` profile is always available. It calls no model and makes
the platform's own claim checkable: field selection, gap analysis, coercion,
validation, approval, and rendering all still work without one.

Full guide: [docs/providers.md](docs/providers.md).

The governed agent loop (workflow `agent` steps, tool use) is implemented on the
Anthropic provider only — keep an `anthropic` profile configured if a workflow
needs it. Everything else runs on any vendor.

### The Anthropic provider

Uses `claude-opus-5` with adaptive thinking, and depth is controlled by
`effort` rather than a token budget. Deliberately never sent: `temperature`,
`top_p`, `top_k`, and `budget_tokens` — all rejected on current models. Setting
`temperature` on an Anthropic profile is refused at load time rather than
failing every request at runtime. Assistant-turn prefill is likewise
unsupported; use `complete_structured()` instead.

The agent loop is hand-written rather than using the SDK tool runner, because
tool execution must pass through the platform's executor (policy, permissions,
audit) and because a gated tool has to *pause* the loop for a human rather than
fail it.

Other behaviour worth knowing:

* Streaming is the default. `max_tokens` caps thinking *and* output together.
* Refusals arrive as HTTP 200 with `stop_reason: "refusal"`. `was_refused` is
  checked before any content is read.
* Server-side refusal fallback is enabled by default (`fallbacks: "default"`),
  so a policy decline is re-served rather than simply stopping.
* Prompt caching puts the breakpoint on the last system block, and tool
  definitions are emitted in sorted order — an unstable prefix would miss the
  cache on every request.

## Repository layout

```
packages/
  sa-platform/       config, context, errors, logging, telemetry, resilience,
                     registry, security, events, health, schema
  sa-skills/         manifest, base, decorator, loader, registry, policy,
                     runtime, contract-test harness
  sa-tools/          spec, base, decorator, registry, policy, executor,
                     builtin/ (clock, filesystem, http, introspection)
  sa-connectors/     base, auth, http, openapi, mcp, llm/ (router + Anthropic,
                     OpenAI, Gemini, gateway dialects, deterministic stub)
  sa-orchestrator/   models, expressions, graph, state, router, middleware,
                     engine, registry, planner
  sa-forms/          models, coercion, completeness, extraction, conversation,
                     ingestion, attachments, authoring, rendering, approval,
                     assistant, service
  sa-api/            app, bootstrap, dependencies, errors, middleware, routers/
  sa-cli/            typer CLI
  sa-console/        console app, BFF proxy, and the zero-build browser UI

skills/              reference skills (summarizer, profiler, policy checker)
examples/workflows/  reference workflow definitions
examples/forms/      reference form definition (production change request)
examples/config/     multi-vendor model configuration
docs/                architecture, skill authoring, operations, ADRs
docker/              Dockerfile, compose stack, OTel collector config
tests/               platform, skills/tools, orchestrator suites
```

## Commands

| | |
|---|---|
| `make install` | Editable install of every package |
| `make check` | Lint and test — the CI gate |
| `make cov` | Tests with a coverage report |
| `sa doctor` | Verify skills, tools, workflows, and health |
| `sa skills verify` | Run the skill contract checks |
| `sa tools definitions` | Emit the Anthropic `tools` array |
| `sa workflows graph <name>` | Show execution levels |
| `make ui` | Run the console with the API mounted in-process |
| `make ui-remote API=<url>` | Run the console against a remote API |
| `make docker-up` | Run the stack with an OTel collector |

## Extending it

| To add | Do this |
|---|---|
| A skill | Drop a `skill.py` + `skill.yaml` under `skills/`, or ship a package advertising the `sa.skills` entry point |
| An MCP server | Add an entry to `SA_MCP_SERVERS`; its tools register at startup |
| A REST API | `OpenApiConnector.from_file(...)` — every operation becomes a tool |
| A state backend | Implement `StateStore` and register it in `build_state_store` |
| An auth scheme | Replace the `get_principal` dependency; everything downstream consumes `Principal` |
| A cross-cutting concern | Implement `Middleware` and add it to the engine's chain |
| A form | Drop a YAML file in `examples/forms/`, or upload a sample spreadsheet to `POST /forms/infer` |
| An intake channel | Implement `ConversationSource`; the extraction pipeline is unchanged |
| An attachment format | Add a reader to `_READERS` in `sa_forms.attachments` |
| A model vendor | Subclass `HttpLLMProvider` (endpoint, body, response, stream chunk) and register it in `build_provider_for` |
| A gateway | Configuration only — a profile with `vendor: gateway` and a dialect |

## Documentation

* [docs/architecture.md](docs/architecture.md) — design decisions and boundaries
* [docs/authoring-skills.md](docs/authoring-skills.md) — the authoring guide
* [docs/forms.md](docs/forms.md) — conversational form intake
* [docs/providers.md](docs/providers.md) — model providers, gateways, and routing
* [docs/console.md](docs/console.md) — the operator console
* [docs/operations.md](docs/operations.md) — deployment, observability, runbook
* [docs/adr/](docs/adr/) — architecture decision records
