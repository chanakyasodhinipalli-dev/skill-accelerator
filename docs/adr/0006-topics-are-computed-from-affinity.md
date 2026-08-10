# ADR 0006: Conversation topics are computed from affinity, not read from sections

**Status:** Accepted
**Date:** 2026-08-08

## Context

[ADR 0004](0004-questions-are-computed-not-authored.md) removed the authored
question list and replaced it with computed selection: gap analysis returns the
outstanding fields, the engine picks a **section**, takes up to four fields from
it, and the model phrases one question about them.

Picking a section was the easy half of that decision and it is the half that was
wrong. A section is how the *author* filed a field. It is not how the person
answering holds the subject in their head, and the mismatch is visible in every
real form:

```
Overview  → change owner
Sign-off  → technical reviewer, business approver
```

Three fields, two sections, and one question a human would ask: "who's driving
this, who reviewed it, and who's signing it off?" Asking by section splits it in
two and puts eight unrelated questions between the halves. The participant then
answers the reviewer question with "I already told you — Priya owns it", because
from where they sit the two asks were the same ask.

The reverse failure is just as common. A section groups fields an author thought
belonged on one page, which regularly means a date, a headcount and a free-text
justification arrive in one breath, and the answer that comes back settles one
of them.

## Decision

Selection is split in two:

* `completeness.analyse` decides **eligibility** — what may be asked, given what
  the session knows. Unchanged.
* `topics.plan` decides **grouping** — what belongs in one question, computed
  from how the fields relate to each other, wherever in the form they live.

Affinity is scored over signals already present in the definition. Nothing new
has to be authored for a form to converse better:

| Signal | Weight |
|---|---|
| `related_fields` names the other field | 4 |
| An `ask_when` guard references it | 4 |
| A consistency rule compares the two | 3 |
| Shared significant word in label, id, or aliases | 2 per word, capped at 4 |
| The same kind of answer — two people, two dates, two scales | 2 |
| Filed in the same section | 1 |

A topic is grown from a seed: mandatory work first, then the author's declared
order, then repeatedly add the outstanding field most related to what is already
in the batch. Growth stops at four fields, at one open-prose field, or as soon
as nothing is related to the batch at all — a fourth unrelated field does not
improve a question, it turns it back into a form.

Two things are deliberately *not* changed:

**The author's order still leads.** Cohesion decides what a question covers; it
does not decide where the conversation starts. A form that opens on "what are
you changing" continues to. The single exception is an *authored* relationship
(weight ≥ 4): the author has said those two belong together, and honouring it
eight questions later is the same as not honouring it. That is what makes "you
said customers are affected — who tells them?" follow immediately.

**Selection stays deterministic.** Affinity is arithmetic over the definition.
The same session always produces the same next question, and a form author can
reason about why.

`group_by_affinity: false` restores section-at-a-time for a questionnaire whose
section order is itself the requirement.

## Consequences

**Good.** A question covers what a person would cover in one answer, and one
answer settles more of the form. Cross-cutting groups — everyone named on the
change, everything about the window — form on their own from definitions that
already existed. A guarded follow-up is asked while its context is still warm.

**Bad.** The reading order of the conversation no longer matches the reading
order of the document, so an author cannot fully predict the flow from the YAML.
Diagnosis needs the affinity graph rather than the file, which is why `Topic`
carries its `cohesion` and `session.topics_opened` records what was opened.

**Neutral.** `aliases` and `related_fields` gain a second job: they were recall
aids for extraction, and they are now grouping signals too. A well-authored form
groups better, which is the same incentive ADR 0004 already created.
