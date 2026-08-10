# Operations

## Configuration

Precedence, highest first: constructor args → environment (`SA_` prefix, `__`
nests) → `.env` → the YAML file at `SA_CONFIG_FILE` → defaults.

```bash
SA_LLM__MODEL=gpt-4o               # settings.llm.model (default provider: openai)
SA_TOOLS__MAX_CONCURRENCY=32       # settings.tools.max_concurrency
```

`sa config` prints the resolved configuration with secrets masked. Run it first
when behaviour differs between environments — layered config is the usual cause.

### Settings that change behaviour most

| Setting | Effect |
|---|---|
| `SA_ENVIRONMENT` | `prod` blocks experimental and deprecated skills |
| `SA_TOOLS__APPROVAL_REQUIRED_ABOVE` | The approval threshold. Lowering it to `low` gates far more |
| `SA_SKILLS__ENFORCE_PERMISSIONS` | Off only for local development |
| `SA_LLM__EFFORT` | Cost and latency lever. Sweep it — defaults rarely transfer between workloads |
| `SA_ORCHESTRATOR__MAX_PARALLEL_STEPS` | Caps workflow fan-out against shared dependencies |
| `SA_API__REQUIRE_AUTH` | Must be `true` outside a trusted network |

## Secrets

Never put a credential in a config file. Components take a *reference* and
resolve it at the point of use:

```
env:OPENAI_API_KEY           # process environment
file:/run/secrets/api_token  # mounted secret
```

A rotated secret takes effect without a redeploy, because resolution happens
per-request rather than at startup.

To integrate a vault, implement `SecretProvider` and call
`set_secret_provider()` during bootstrap. Nothing else changes.

## Deployment

```bash
make docker-build
docker compose -f docker/docker-compose.yml up
```

The image runs as UID 10001 with `no-new-privileges`, and skills and examples
mount read-only. Do not relax either: this runtime executes skill and tool code,
and the container boundary is a real part of the security model.

### Probes

| Endpoint | Semantics |
|---|---|
| `/health/live` | Process can serve. Never touches dependencies. |
| `/health/ready` | Aggregate of registered checks. 503 only when a *critical* check fails. |

Keep them distinct. Wiring liveness to dependency health produces restart loops
during a downstream outage — restarting fixes nothing and removes the capacity
that was still working.

Connectors register as **non-critical**: an unavailable MCP server degrades the
service rather than pulling the pod out of rotation.

```yaml
livenessProbe:
  httpGet: { path: /health/live, port: 8000 }
  initialDelaySeconds: 10
  periodSeconds: 30
readinessProbe:
  httpGet: { path: /health/ready, port: 8000 }
  initialDelaySeconds: 15
  periodSeconds: 10
```

## Observability

### Logs

JSON, one object per line, automatically enriched with `correlation_id`,
`principal`, `run_id`, and `step_id` from the ambient context. Fields whose
names look sensitive are redacted before emission.

An inbound `X-Correlation-Id` is honoured, so a trace spans the caller and this
service. Every response carries it back.

```bash
# Everything that happened in one request
jq 'select(.correlation_id == "abc123")' app.log

# Failures with their platform error code
jq 'select(.level == "ERROR") | {ts: .timestamp, msg: .message, code: .error.code}' app.log
```

### Traces

Spans are emitted for `skill.invoke`, `tool.invoke`, `workflow.run`,
`workflow.step`, `http.request`, and `llm.complete`. Install
`sa-platform[otel]` and set `SA_TELEMETRY__OTLP_ENDPOINT` to export them.

### Metrics

`GET /metrics` returns the in-process snapshot. It is a debug and smoke-test
surface, not a metrics backend — use the OTLP exporter for that.

The ones worth alerting on:

| Metric | Watch for |
|---|---|
| `resilience.circuit_opened` | Any occurrence — a dependency is failing |
| `tool.approval_required` | A spike means work is queuing on humans |
| `tool.denied` | A spike means a policy change broke something, or an agent is probing |
| `skill.failed` / `workflow.step_failed` | Rate change |
| `llm.refusals` | Requests being declined by safety classifiers |
| `llm.cache_hit_ratio` | Near zero means a silent prompt-cache invalidator |

## Runbook

### Circuit breaker open

`resilience.circuit_opened` fired; requests to a dependency return 503 with
`circuit_open`.

The breaker is doing its job — it prevents a failing dependency from consuming
the whole connection pool. Check the dependency, not the breaker. It half-opens
automatically after `SA_RESILIENCE__CIRCUIT_RESET_SECONDS` and closes on a
successful probe. `POST /connectors/{name}/reconnect` forces a reset once the
dependency is confirmed healthy.

### Workflow stuck in `awaiting_approval`

Expected behaviour, not a fault. A tool at or above the danger threshold needs a
human decision.

```bash
curl /workflows/runs/{run_id}          # inspect pending_approvals
curl -X POST /workflows/{name}/resume/{run_id} \
     -d '{"approvals": {"<invocation_id>": true}}'
```

Steps that already succeeded are not re-run. If approvals are queuing routinely,
either raise `SA_TOOLS__APPROVAL_REQUIRED_ABOVE` or supply a real
`approval_handler` that consults your approval system.

### MCP server unavailable

Startup logs `mcp server unavailable; continuing without it` and `sa doctor`
reports a warning. This is deliberate — one unreachable integration must not
prevent the service from starting.

Its tools are simply absent from the registry, so an agent will report it cannot
do that thing rather than failing mid-run. After fixing the server:

```bash
curl -X POST /connectors/{name}/reconnect
curl -X POST /connectors/{name}/refresh-tools
```

### Low prompt-cache hit ratio

`llm.cache_hit_ratio` near zero across repeated similar requests means something
is changing the cached prefix. In order of likelihood:

1. A timestamp, UUID, or per-user value interpolated into the system prompt
2. The tool set varying between requests (tool definitions render first)
3. The model changing mid-conversation — caches are model-scoped

The platform sorts tool definitions and exposes the clock as a tool rather than
a prompt field precisely to avoid (1) and (2). A custom system prompt is the
usual culprit.

### Slow workflows

`sa workflows graph <name>` shows the execution levels. A workflow that is one
step per level is fully serialised — check whether every `depends_on` reflects
real data flow, or whether some were added defensively.

Then check `SA_ORCHESTRATOR__MAX_PARALLEL_STEPS` and the workflow's own
`max_parallel`; the effective limit is the lower of the two.

### High LLM cost

1. Sweep `SA_LLM__EFFORT` — `low` and `medium` are stronger than their names
   suggest on current models, and defaults carried from a prior model rarely
   transfer.
2. Check `llm.cache_hit_ratio` (above).
3. Narrow the tool surface. `to_anthropic_tools(names=..., max_danger=...)`
   emits a filtered array; every unused definition costs tokens on every request
   and degrades tool selection.
4. Set `max_tool_iterations` to bound runaway agent loops.

## Security posture

| Boundary | Control |
|---|---|
| Inbound auth | `get_principal`; replace with OIDC for user-facing deployments |
| Skill authorization | Manifest `required_permissions`, enforced pre-execution |
| Tool authorization | Spec `required_permissions`, plus allow/deny and scope |
| Dangerous actions | Approval gate; defers rather than denying |
| Filesystem tools | Path canonicalisation and containment; traversal and symlink escapes rejected |
| HTTP tool | Mandatory host allowlist — there is no permissive default |
| Workflow expressions | No `eval`, no attribute access; dict and list traversal only |
| Secrets | Reference-based, resolved at use; redacted from logs |
| Container | Non-root, `no-new-privileges`, read-only skill mounts |

### Before going to production

- [ ] `SA_API__REQUIRE_AUTH=true`, or an OIDC verifier replacing `get_principal`
- [ ] `SA_API__DOCS_ENABLED=false`
- [ ] A real `approval_handler` wired to your approval system
- [ ] `SA_SKILLS__ENFORCE_PERMISSIONS=true`
- [ ] Secrets supplied as `env:` / `file:` references, never literals
- [ ] `allowed_hosts` set on any registered `HttpRequestTool`
- [ ] A durable `StateStore` if runs must survive a restart
- [ ] OTLP endpoint configured; alerts on the metrics above
- [ ] Log retention reviewed — audit events include tool arguments
