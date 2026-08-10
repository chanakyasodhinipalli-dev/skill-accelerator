# ADR 0007: Consent and unanswered questions belong in the record

**Status:** Accepted
**Date:** 2026-08-08

## Context

The platform gathered answers. Around every real intake there are two other
things happening that it did not gather, and both of them end up mattering more
than several of the fields.

**Agreements.** Terms of recording, a declaration of authority, a confirmation
that the finished submission is accurate. Today these are a checkbox on a screen
before the form, accepted without being read, and nothing about them reaches the
document an approver signs. Whether the person who raised a production change
was authorised to raise it is not a footnote; it is the first thing a change
board asks.

**Questions.** A form provokes them. "What counts as customer impacting?" "Who
is my business approver?" They are answered today by whoever the person happens
to know, or not at all — and an unanswered question does not stop anyone. It
becomes a guess, the guess becomes a value, and the value gets approved. Nothing
downstream can tell the guessed values from the known ones.

## Decision

Both become part of the form definition and part of the record.

### Agreements

Declared as data, with a kind and a stage — and a form may be made of nothing
else. `kind: agreement` on the definition makes the agreements the content: a
policy acknowledgement, a terms-of-use acceptance, a joiner's declarations pack.
Sections become optional, terms are put **one at a time** rather than bundled,
and "complete" means every required agreement has been decided rather than that
a field count was reached — under field counting a form with no fields is
complete the moment it starts, which is the wrong answer about a document nobody
has agreed to anything on.

One at a time is the substantive half of that. On an intake form the terms are a
preamble and bundling three of them is proportionate. Where the terms *are* the
form, five clauses behind a single "I agree" reproduces exactly the record this
exists to replace: one click, five attestations, no evidence any of them was
read. The kind says whose statement it is —
`system` (the platform's), `user` (a declaration only the participant can make),
`confirmation` (a statement about *this* submission). The stage says when it is
due: `before_start`, `before_review`, `before_generate`.

Four rules do the work:

* **The text is presented and stored verbatim, and hashed.** It is never handed
  to a model to phrase. Everything around it is conversation; the words being
  agreed to are the words the form declares.
* **Acceptance is per version.** A session that accepted v1 has not accepted v2.
* **A decline is a recorded outcome, not an error.** It blocks what it gates,
  goes on the document, and is routed to the owning team.
* **Nothing is inferred.** Acceptance happens when the participant says so, and
  never because the conversation moved on.

Consent precedes collection: while a `before_start` agreement stands, nothing is
extracted. Someone who volunteers their whole change first has to say it again —
a small cost, paid once, against a record that would otherwise hold text
gathered under terms nobody had accepted.

There is deliberately **no tool** that accepts an agreement. Consent goes
through `forms_contribute` like anything else the participant said, so the only
route to acceptance is the engine having put the terms in its own words. A
dedicated accept tool would let a model record consent to text it summarised.

### Questions

A three-tier ladder, escalating only when the tier below it failed:

1. **The definition** — description, `help_text`, examples, options, rationale.
   Deterministic, free, and it is the answer the form's author wrote.
2. **The knowledge notes** — a grounded answer from reference material the form
   carries, citing which note it used. The model is told to refuse when the
   material does not settle the question, and a refusal here is the *correct*
   outcome: a confident wrong answer about an approval threshold costs somebody
   a rejected submission.
3. **A human** — routed to the team that owns that part of the form, recorded on
   the session, and carried onto the document.

The tier is chosen by counting, not by reading tone: a second question about the
same field means the first answer did not land. An explicit "that didn't answer
it" skips the tier that just missed.

An escalated question does not stop the form. The field is left open — not
skipped, which would be a decision the participant has not made — and the
conversation moves to something they can answer.

## Consequences

**Good.** The document states what was agreed, in the words that were agreed,
by whom, and when — beside the answers those terms govern. A value nobody could
settle is visibly a value nobody could settle. The questions a form provokes
accumulate as evidence of where its wording is wrong, which is the cheapest
form-improvement signal there is and is invisible today because it happens in
chat windows nobody reads back.

**Bad.** A form with no `escalation` routes and no `knowledge` notes gets the
first tier and then names its owner, which is worse than a well-authored form
and better than a guess. Authors now have three more things to write.

**Neutral.** Escalation records rather than sends. Delivery is a connector's job
and every deployment does it differently; a question that is logged, owned, and
on the document is one somebody can act on either way.
