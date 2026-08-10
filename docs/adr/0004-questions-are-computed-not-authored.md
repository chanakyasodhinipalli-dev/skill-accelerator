# ADR 0004: Form questions are computed, not authored

**Status:** Accepted
**Date:** 2026-08-06

## Context

The obvious way to build a form-filling bot is a script: a list of questions,
asked in order, one field at a time. It is easy to build and it is what most
"conversational forms" actually are.

It fails on contact with real use in three ways. Every new form needs new code
or new prompt text. A user who volunteers three facts in one sentence still gets
asked about all three separately, because the script only listens for the field
it just asked about. And a form that already has most of its answers sitting in
a JIRA thread still asks every question from the top.

## Decision

The question list does not exist. Each turn:

1. `completeness.analyse()` reads the form definition and the session state and
   returns the outstanding fields, in deterministic code.
2. `completeness.next_topic()` selects a **section** and up to four fields from
   it, preferring mandatory work in the author's declared section order.
3. The model is given exactly those fields and asked to phrase one natural
   question. It is explicitly told not to ask about anything else.

Selection is deterministic; only the wording is generated.

Two supporting rules make it work:

* **Every message is extracted against every outstanding field**, not the one
  last asked about.
* **A settled field leaves the outstanding set permanently**, however it was
  settled — this turn, ten turns ago, or via an ingested ticket comment.

## Consequences

**Good.** Adding a field to a YAML definition changes the conversation with no
code change. A user who answers four things at once is not re-asked any of them.
Ingestion and conversation share one mechanism, because both just reduce the
outstanding set. The engine can always state exactly what is left and why, which
is what makes progress reporting and action items fall out for free.

**Bad.** Question quality depends on the model. When it is unavailable the
fallback phrasing ("Could you tell me the owner and the target date?") is
correct but flat. Field ordering within a topic is the author's, not the
model's, so a badly ordered section reads badly.

**Neutral.** The `rationale`, `aliases`, and `description` fields become
load-bearing rather than documentation. A form authored without them still
works but converses poorly — which is why the authoring pass generates them and
the facilitator asks when it cannot.

## Why topics rather than fields

Asking "tell me about the rollout" gets a more complete answer than eleven
separate questions, and one open answer routinely settles several fields at
once. Asking about four related things reads as a conversation; asking about
eleven reads as a form — which is the thing being replaced.

The cap is four. Beyond that, people answer the first two and ignore the rest,
and the unanswered ones come back next turn anyway.
