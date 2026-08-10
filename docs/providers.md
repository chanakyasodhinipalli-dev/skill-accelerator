# Model providers

One contract, several vendors, and a gateway in front of them if that is how the
organisation buys model access.

```
        forms · extraction · question planning · authoring · planner
                                  │
                          LLMProvider (contract)
                                  │
                             LLMRouter
             ┌──────────┬─────────┴────────┬──────────────┐
        Anthropic     OpenAI            Gemini         Gateway
        (SDK)         (HTTP)            (HTTP)         (any dialect)
```

The router **is** a provider. That single fact is what makes switching cheap:
every component already depends on the provider interface, so changing vendor is
configuration and touches no business code.

## Choosing a profile

A *profile* is one named way to reach a model — vendor, model id, endpoint,
credential, and request shaping. Two profiles may name the same vendor (prod key
and sandbox key); one vendor may be reached directly or through a gateway. Those
are different profiles, not different code paths.

Three ways to select one, narrowest first:

| Scope | How | Use for |
|---|---|---|
| One call | `complete(..., profile="openai")` | A step that genuinely needs a specific model |
| One request | `X-LLM-Profile: openai` header | Trying a vendor from the console without changing anything for anyone else |
| The process | `POST /providers/{name}/activate` | The default everyone gets |

The header is applied globally in the API, so *any* endpoint that reaches a model
honours it — form extraction, question phrasing, form inference — without each
one having to ask for it. An unknown profile name falls back to the active one
rather than failing the request: choosing a model is not the caller's business to
get right.

## Configuration

**The default is OpenAI (`gpt-4o`).** With no config file at all, the top-level
`llm` settings are exposed as a profile named after `llm.provider`, and that
profile serves. Set the key and nothing else is required:

```bash
OPENAI_API_KEY=sk-...          # in .env, or exported in the environment
SA_LLM__PROVIDER=openai        # anthropic | openai | gemini | stub
SA_LLM__MODEL=gpt-4o
```

`gateway` is not valid as `llm.provider` — a gateway needs `base_url` and
`dialect`, which only a named profile carries. Declare it in `profiles` and
point `active_profile` at it.

See [examples/config/llm-profiles.yaml](../examples/config/llm-profiles.yaml) for
a complete file. The shape:

```yaml
llm:
  active_profile: openai
  fallback_profiles: [anthropic, gemini]
  profiles:
    - name: openai
      vendor: openai          # anthropic | openai | gemini | gateway | stub
      model: gpt-4o
      api_key_env: OPENAI_API_KEY
      temperature: 0.2
```

A profile named the same as `llm.provider` replaces the built-in default rather
than colliding with it, so the YAML above is the way to give the default profile
more settings than the flat `SA_LLM__*` variables carry.

Credentials resolve in order: an explicit `api_key`, then the variable named by
`api_key_env`, then the vendor's own conventional variable (`OPENAI_API_KEY`,
`GEMINI_API_KEY`, `ANTHROPIC_API_KEY`). So a developer machine that already has
one of those works with no extra configuration.

A profile with no credential resolves as **degraded**, not failed — a gateway may
authenticate by network identity (mTLS, workload identity, a sidecar), and that
is not detectable from here.

### Vendor-specific rules the config enforces

`temperature` and `top_p` on an Anthropic profile are **rejected at load time**
— including `llm.temperature` when `llm.provider` is anthropic. Current Claude
models return a 400 for them, so accepting the setting would mean every request
fails at runtime with an error that looks like a broken feature. Depth on
Anthropic is `effort`, not sampling.

Conversely, `thinking` and `effort` are Anthropic-only and are not carried into
a default profile of any other vendor, so leaving `SA_LLM__EFFORT` set while
running on OpenAI is harmless rather than a silent no-op sent on the wire.

## Tool use is Anthropic-only

The governed agent loop — tool execution routed through the platform's executor,
with a gated tool *pausing* the loop for a human — is implemented on the
Anthropic provider only. Workflow steps of type `agent` therefore fail with a
`ConfigurationError` while an OpenAI or Gemini profile is active. Single-shot
`complete`, `complete_structured`, and `stream` are unaffected, which is what
form extraction, question phrasing, and form authoring use.

Keep an `anthropic` profile configured if any workflow uses agent steps, and
activate it for those runs.

## Through a gateway

`dialect` is what *this* side of the call looks like. What the gateway routes to
behind it is the gateway's business.

```yaml
- name: corp-gateway
  vendor: gateway
  dialect: openai                       # openai | anthropic | gemini
  model: gpt-4o
  base_url: https://llm-gateway.corp.internal/v1
  api_key_env: SA_GATEWAY_API_KEY
  auth_header: x-virtual-key            # blank uses the vendor default
  headers:
    x-cost-centre: risk-platform
```

This covers the common cases without new code: Azure OpenAI (`api-key` header
plus `api_version`), LiteLLM, vLLM, Ollama, an API-management layer, or a broker
that speaks Anthropic's Messages API.

`GET /providers/{name}/models` asks the endpoint what it will serve. Pointed at a
gateway, that is the organisation's approved model list — which is otherwise a
wiki page that goes stale.

## Fallback

`fallback_profiles` is tried in order when the active profile fails with a
**retryable** error — a rate limit, a timeout, a 5xx. Cross-vendor on purpose: a
vendor outage degrades to a different vendor instead of to an error.

A *rejected* request is never retried elsewhere. A bad schema or a malformed body
fails identically on every vendor, and re-sending it just doubles the cost of the
same error.

Streaming is not routed through the chain. A stream that fails part-way has
already delivered tokens to the caller, and restarting on another vendor would
repeat them.

## The deterministic profile

`stub` is always available, even with nothing configured. It calls no model and
returns schema-shaped empty values, which every caller reads as "the model
contributed nothing" and handles with its own deterministic path.

It is not a test double. It is how you check the claim this platform makes: field
selection, gap analysis, coercion, validation, extraction from labelled text,
approval, and rendering are all deterministic. Switch to `stub` and everything
still works; only *generated wording* degrades to fixed phrasing.

It also means the console is fully usable with no credential at all.

## What each vendor implementation handles

| | Anthropic | OpenAI dialect | Gemini |
|---|---|---|---|
| Transport | Official SDK | httpx | httpx |
| Tool definitions | Native | Translated from the registry's Anthropic shape | Translated to `functionDeclarations` |
| Structured output | `output_config.format` | `response_format: json_schema` | `responseSchema` (filtered) |
| Token counting | Native endpoint | **None** — raises rather than estimating | Native `:countTokens` |
| Refusal | `stop_reason: "refusal"` | `message.refusal` | `finishReason: SAFETY` |

Three details worth knowing:

* **Tools are authored once.** The registry emits Anthropic-shaped definitions;
  each provider translates. A tool written for one vendor works on all of them.
* **Gemini's `responseSchema` is a subset of JSON Schema.** `additionalProperties`,
  `$ref`, and `oneOf` are a 400 rather than an ignored field, so schemas are
  filtered before they are sent. That loosens validation; the platform validates
  the parsed result anyway.
* **OpenAI's token parameter is negotiated.** Newer servers want
  `max_completion_tokens`, older OpenAI-compatible ones only accept `max_tokens`,
  and which one a gateway wants is not knowable up front. The provider starts
  modern and flips once, permanently, on rejection.

Structured output also tolerates a fenced code block. A gateway that silently
routes to a model without schema support returns ```` ```json ```` — recovering
turns a hard failure into a working call.

## Operating it

```bash
sa doctor                                    # which profile serves, and what else exists
curl localhost:8000/providers                # profiles with live counters
curl localhost:8000/providers/health         # probe every one
curl -XPOST localhost:8000/providers/openai/test    # prove a completion comes back
```

`/providers/health` shows the endpoint answers. `/providers/{name}/test` shows a
completion actually returns — credential, endpoint, and model id together, which
is the thing that fails in practice.

`POST /providers/compare` runs one prompt across several profiles. It is the
honest way to choose a model for a task, and the honest way to check a gateway
routes where it claims to.

Per-profile counters — calls, failures, fallbacks served, average latency, tokens
— are on every `/providers` response and on the console's Models page.

## Adding a vendor

Subclass `HttpLLMProvider` and supply four things: where the endpoint is, how to
build the body, how to read the response, and how to read a stream chunk.
Lifecycle, retries, deadline propagation, SSE, error translation, telemetry, and
events are inherited. Register it in `build_provider_for`.

Roughly 150 lines for a new dialect. The Gemini provider is the reference.
