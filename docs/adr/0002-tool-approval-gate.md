# ADR 0002: Tool invocations pass through an approval gate that defers

**Status:** Accepted
**Date:** 2026-08-06

## Context

An LLM decides which tool to call. Some of those tools mutate business state,
move money, or contact customers. Two failure modes matter and they pull in
opposite directions:

* an agent takes an irreversible action nobody sanctioned
* an agent is so constrained it cannot complete useful work, and people
  route around the platform

Model-side controls (careful tool descriptions, `tool_choice`) reduce the
frequency of bad calls but cannot bound them, because the model is the thing
being constrained.

## Decision

Every tool declares a `DangerLevel`. Tools at or above a configured threshold
require an explicit approval decision before execution, evaluated by the
platform rather than the model.

The approval handler returns `ALLOW`, `DENY`, or `DEFER`. **The default is
`DEFER`.**

A deferred call produces `ToolStatus.APPROVAL_REQUIRED` — not an error. The
agent loop halts, the workflow checkpoints its state and reports
`awaiting_approval`, and the API returns HTTP 428 with the pending request.
Resuming with the decision attached re-runs only what had not yet succeeded.

Danger level is inferred where it can be: a non-idempotent skill bridges to
`HIGH`, an MCP tool without a `readOnlyHint` is assumed destructive. Defaults
are conservative, and authors opt *down*.

## Consequences

**Good.** No irreversible action happens without a decision. The pause is a
first-class state that survives a restart rather than a request blocking on a
human for minutes. Denials and approvals are audit events. Because deferral is
the default, forgetting to configure a handler fails safe.

**Bad.** Autonomous throughput is bounded by approval latency for gated tools.
Teams needing full autonomy must supply a handler that auto-approves, which is
an explicit, reviewable decision rather than a silent default.

**Neutral.** The threshold is configuration, so it can be tuned per environment
— `low` in production, `high` in a sandbox.

## Why defer rather than deny

Denying looks safer and is worse in practice. A denial reaches the model as a
failed tool result, and the model does what it should: adapts and finds another
route to the goal. That route is unconstrained and unreviewed.

Deferring stops the run and puts the decision where it belongs. The agent does
not get a chance to work around it, because the agent is not running.
