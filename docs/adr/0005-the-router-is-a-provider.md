# ADR 0005: The model router is itself a provider

**Status:** Accepted
**Date:** 2026-08-06

## Context

The platform needed to reach models from several vendors — Anthropic, OpenAI,
Gemini — and, more importantly, through an enterprise gateway that fronts them.
Gateways are where model access actually lives in a large organisation, because
that is where quota, audit, DLP, and vendor contracts get applied.

By this point a dozen call sites already depended on `LLMProvider`: form
extraction, question phrasing, form authoring, the workflow planner, the agent
loop. Three shapes were available.

**A factory returning a provider per vendor.** Every caller decides which vendor
it wants, or a setting is read at each site. "Switch the model" then means
finding every construction point, and a caller that built its provider early
keeps using the old one after a switch.

**A configuration flag inside one provider class.** One class branching on vendor
for endpoints, auth, body shape, tool translation, structured output, streaming,
and error mapping. It works until the second vendor, then every method is a
three-way conditional and the vendor-specific rules leak into each other. The
concrete risk is real: Anthropic rejects `temperature`, OpenAI requires it to be
optional, Gemini names it `topP`. One class means one place where that goes
wrong for everyone.

**A router that implements the provider interface.**

## Decision

`LLMRouter` implements `LLMProvider`, and `build_provider()` returns it.

Callers keep depending on the interface they already depended on. Selection
happens inside the router, at three scopes, narrowest first:

1. `complete(..., profile="openai")` — one call.
2. `use_profile("openai")` — a scope, carried on a context variable so it
   survives nested awaits without being threaded through every signature. The
   API binds `X-LLM-Profile` to it globally, so every endpoint that reaches a
   model honours the header without asking for it.
3. `router.use("openai")` — the process default.

A *profile* is the unit: vendor, model, endpoint, credential, and request
shaping. Two profiles may name the same vendor; one vendor may be reached
directly or through a gateway. Those are different profiles, not different code
paths.

Vendor differences live in vendor classes. `HttpLLMProvider` owns what is
genuinely shared — client lifecycle, retries, deadline propagation, SSE, error
translation, telemetry, events — and a subclass supplies four things: where the
endpoint is, how to build the body, how to read the response, and how to read a
stream chunk.

A gateway is not a fourth vendor implementation. It is a `dialect` — what *this*
side of the call looks like — plus a base URL, an auth header, and extra headers.
What the gateway routes to behind it is the gateway's business.

## Consequences

Switching vendors is configuration. No business code names a vendor, and the
switch takes effect everywhere at once because the router is a process-wide
singleton — a per-caller router would make "switch the model" mean "switch it for
whichever component happened to build this one".

Cross-vendor fallback becomes possible, and is the main thing a direct
integration lacks. It applies only to *retryable* failures: a rejected request
fails identically on every vendor, so re-sending it just doubles the cost of the
same error. Streaming is excluded — a stream that fails part-way has already
delivered tokens, and restarting elsewhere would repeat them.

Tools are authored once. The registry emits Anthropic-shaped definitions and
each provider translates, so a tool written for one vendor works on all of them.

Not everything survives the abstraction, and the honest cost is stated rather
than hidden:

* **The governed agent loop is Anthropic-only.** Tool execution must pass through
  the platform's executor, and a gated tool has to *pause* the loop for a human.
  The router raises with that reason rather than silently dropping the tools,
  which would look like a model that chose not to call them.
* **Token counting is not universal.** Anthropic and Gemini have endpoints;
  OpenAI does not. The provider raises rather than estimating with a foreign
  tokenizer, because a wrong count silently mis-budgets context.
* **Conversations do not move mid-flight.** Only Anthropic round-trips thinking
  and tool_use blocks; the others reject foreign block types. A history carried
  across providers is flattened to text.

A deterministic `stub` profile is always available. It exists so a deployment
with no credential still has something selectable, and so the platform's central
claim — that selection, gap analysis, coercion, validation, approval, and
rendering are decided in code — is checkable rather than asserted.
