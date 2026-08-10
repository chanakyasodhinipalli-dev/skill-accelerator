# Conversational form intake

Replaces manual form filling — and the email and ticket back-and-forth around
it — with one resumable conversation that also mines the discussions that
already happened.

## The problem this addresses

A form gets filled by someone who has half the information, hand-held by an SME
who has the other half, over a week of Teams messages, three JIRA comments, and
a meeting. The information exists; it is just scattered, and nobody wants to
transcribe it into a spreadsheet.

So the design starts from the opposite end: **mine what exists first, and only
ask about what is genuinely missing.**

```
                     ┌─ answer it from the form ─┐
                     │  else the notes           │  a question they asked
                     └─ else a named team ───────┘
                                  ▲
JIRA thread ┐                     │
email chain ├─→ ingest ─→ extract ─→ gap analysis ─→ ask only what's left
transcript  ┘                            │
                                         ▼
    terms accepted → … → confirmed accurate → render → approve → baseline
```

Two things travel with the answers all the way to the document: what the
participant **agreed to**, in the words it was put to them, and what they
**asked** that nobody in the conversation could settle.

## Five minutes to a working form

```python
from sa_forms import forms_service as fs

# 1. Open a session (or resume this person's paused one).
started = await fs.start_session("change_request", participant="alice")
sid = started["session_id"]

# 2. Mine the ticket where the discussion already happened.
await fs.ingest(sid, "jira", jira_issue_payload)
# -> captured 6 of 11 required fields, asked nothing

# 3. Converse about the rest.
result = await fs.send(sid, "15 minutes downtime, customers will notice, medium risk")
# -> captured 3 more; the next question covers only what's still open

# 4. Render, review, baseline.
artifacts = await fs.generate(sid, ["xlsx", "pdf"])
await fs.approve(artifacts[0].id, approver="bob")   # -> baselined, checksummed
```

## How the conversation works

### Questions are computed, not written

There is no question list anywhere in the codebase. Each turn:

1. `completeness.analyse()` reads the form definition and the session and
   returns the outstanding fields — **what may be asked**.
2. `topics.plan()` groups them — **what belongs in one question** — taking up to
   four related fields, but at most **one** open-prose field. Two "describe X"
   asks in the same breath come back as a single run-on answer, and splitting it
   between the fields afterwards is guesswork that gets it wrong often enough to
   cost more than asking twice.
3. The model phrases *those* fields as one natural question.

The selection is deterministic; only the wording is generated. Adding a field to
a form changes the conversation with no code change.

### The question is about a subject, not about the fields

The model is given what it needs to **learn**, and asked for the question a
colleague would ask to learn it. It is told, in as many words, not to read the
labels back:

| The fields behind it | What gets asked |
|---|---|
| Affected system, Change owner, Change title | "What are you changing, and who's driving it?" |
| Target date, Maintenance window, Expected downtime | "When are you planning to do this, and how long will it be down?" |
| Technical risk, Business impact | "How risky is this, and what does it cost you if it goes wrong?" |

How pointed the question is escalates in code, not by the model's read of the
mood — from the ask counts the session already keeps:

* **An invitation** on the first substantive turn. Not a question at all: "tell
  me about the change in your own words — put in as much as you like in one go".
  Naming three things tells the participant the shape of the answer you want and
  they give you three things, when they arrived with the whole change in their
  head and would happily have typed all twelve.
* **Open** after that. A broad question gets a fuller answer and routinely
  settles several fields at once.
* **Specific** once something has been asked and missed: name the one or two
  things still outstanding.
* **Explicit** on the third pass. No more rephrasing: say what would settle it —
  the exact options, or the shape of the value — and offer to leave it out.

Specificity is what you spend when an open question fails. Spending it up front
is how a conversation becomes an interrogation.

**How much is asked at once follows the person, not the form.** The cap is not a
constant: it is read off how they have actually been answering in this
conversation — words per turn, and how much each turn settled.

| They answer like this | Items per question |
|---|---|
| In paragraphs, settling several fields at a time | 6 |
| Normally | 4 |
| In three words | 2 |

Somebody answering in paragraphs has more in their head than one question can
carry, and capping them means round trips to collect what they would have typed
in one go. Somebody answering in three words is telling you the opposite, and
handing them four things at once is how two of them get missed.

### Topics are computed from affinity, not read from sections

A section is how the *author* filed a field. It is not how the person answering
holds the subject, and the mismatch shows up in every form:

```
Overview  → change owner
Sign-off  → technical reviewer, business approver
```

Three fields, two sections, one question a human would ask: "who's driving this,
who reviewed it, and who's signing it off?" Asking by section splits it in two
and puts eight questions between the halves — which is how you get "I already
told you, Priya owns it".

So fields are scored against each other on signals the definition already
carries:

| Signal | Weight |
|---|---|
| `related_fields` names the other field | 4 |
| An `ask_when` guard references it | 4 |
| A consistency rule compares the two | 3 |
| Shared significant word in label, id, or aliases | 2 each, capped at 4 |
| The same kind of answer — two people, two dates, two scales | 2 |
| Filed in the same section | 1 |

A topic grows from a seed — mandatory work first, then the author's order — by
repeatedly adding the outstanding field most related to what is already in the
batch, wherever in the form it lives. It stops at four fields, at one prose
field, or as soon as nothing is related to the batch at all. **A fourth
unrelated field does not improve a question**; it turns it back into a form.

The author's order still leads: cohesion decides what a question covers, not
where the conversation starts. The exception is an *authored* relationship —
weight 4 — which jumps the queue, because that is the author saying these two
belong together and honouring it eight questions later is not honouring it:

> You said customers are affected — who's sending the notification?

`group_by_affinity: false` restores section-at-a-time for a questionnaire whose
section order is itself the requirement.

### Nothing is asked twice

The planner is shown **every answer already on the record**, with its value, not
just told which fields to ask about. Telling a model not to re-ask is weaker
than showing it the answer: it cannot ask again for a date it can see.

And when it slips anyway, "I already answered that" is an intent, not noise. The
reply is the recorded value read back — proof it landed, and an invitation to
correct it — or, where the value genuinely never reached the record, saying so
plainly. Asking a fourth time is not the answer, and neither is an apology on
its own.


Every message is extracted against **all** outstanding fields, not just the one
last asked about. Someone answering "Priya owns it, and we're going on the 15th"
settles two fields, and neither is raised again — whether it was answered this
turn, ten turns ago, or in a ticket comment ingested last week.

Nor is anything asked endlessly. A field put to the participant twice without an
answer stops driving topic selection: the conversation moves on and comes back
to it, rather than rephrasing the same question a third time. It still blocks
completion and still becomes an action item — dropping it from the agenda is a
courtesy, not a waiver.

### Uncertainty is surfaced, not guessed

Each extraction carries a confidence. Below the field's threshold the answer is
held as `PROPOSED` and confirmed with the user rather than silently accepted. A
bare "yes" promotes whatever is pending, which is what makes a proposal a
question with a default rather than a dead end.

Fields where a wrong guess is expensive — dates, owners, money — set
`require_explicit: true` and refuse to be inferred at all. "Probably sometime in
March" does not become a target date.

Values that are not answers are refused in code rather than stored: a bare yes
or no for a free-text field (`Tracking ticket: yes` reads as answered and points
at nothing), and a first-person reference for a `person` field. "Me" resolves to
the speaker's identity where the channel knows it, and is otherwise sent back
for a name — the artifact outlives the conversation, and whoever reads it at 2am
cannot resolve "myself".

### Dates people actually say

"Next Friday", "Aug 15", "end of the month", "in two weeks" all resolve, in
deterministic code with no model call and no `dateutil`. Anything the platform
completed — the year, or the reference point — lowers confidence, so the
resolved date is read back for confirmation rather than quietly scheduled.

"The last Sunday of September", "first Monday of next month", and "last Friday
of the quarter" resolve as whole phrases. Reading only the weekday out of one
answers with the *next* Sunday — a confident, specific, wrong date, which is
worse than not understanding at all.

Only expressions naming **one day** resolve. A bare "next quarter" names
thirteen weeks; picking a day out of it would invent a decision the speaker has
not made, so it comes back as a question instead. So does a backwards reference
like "last Friday": a target date in the past is not what anyone means.

### What was typed, written up

People type answers, not prose. "8AM ro 11PM". "from the serivces start log for
any issues". Each is a perfectly good answer and a terrible line in a document a
change board reads — and nobody is going to proofread nineteen fields.

So the record keeps both. `raw_value` and the provenance appendix hold exactly
what was said; the value on the document is the same content written up. It runs
once, when the answers have stopped moving, so nothing is polished and then
superseded:

| As typed | On the document |
|---|---|
| `8AM ro 11PM` | `08:00-23:00` |
| `Revert back the JDK version to previous one` | `Revert the JDK to the previous version.` |
| `from the serivces start log for any issues` | `Check the service start logs for issues.` |

Times, whitespace, and sentence shape are deterministic and need no model, so
they still happen during an outage. Spelling, grammar, and turning a fragment
into a sentence need a reader, which is what the model is for.

**A rewrite must never add a fact.** One that does is fabrication in a clean
font, and invisible precisely because it reads well. Three guards, applied in
code after the model has spoken:

* **No new numbers.** Every digit in the rewrite must already appear in the
  value or in something *the participant* said. The assistant's own turns don't
  count — they quote back proposed values, and that would let a number the
  platform suggested return as though it had been confirmed.
* **No padding.** A rewrite far longer than its source is elaborating.
* **Typed values are never sent.** Dates, enums, booleans, and numbers are
  already canonical after coercion; a model near them is all risk and no gain.

Anything that fails is discarded and the original stands — a field that reads
awkwardly is a far smaller problem than one that reads well and is wrong. Set
`preserve_verbatim: true` on a field whose exact wording is the record, or
`normalise_wording: false` on the form to turn the pass off entirely.

### Times carry their timezone

`requires_timezone: true` refuses a value that states a clock time without a
zone. "8AM to 11PM" is eight hours out between London and Bangalore, and it is
only unambiguous to the person who typed it — on-call in another region, the
approver, and the change calendar all have to guess.

The refusal becomes a question, and answering it costs one word: the rejected
text is held, so replying `IST` completes the window rather than requiring the
whole thing retyped. Joining a time to its zone is string concatenation, so it
is done in code. UTC/IST/PST-style abbreviations, explicit offsets (`+05:30`,
`GMT+1`), and IANA names (`Asia/Kolkata`) all count as stated.

### A responsibility has a name on it

`requires_named_party: true` asks a responsibility field for a **named party** —
a person, or a team by its name. Plenty of responsibilities genuinely sit with a
group, so the rule is about naming, not headcount:

| Accepted | Refused |
|---|---|
| `Chandra`, `Priya Raman` | `me`, `myself` |
| `Platform Support`, `Payments Squad` | `my scrum team`, `our platform team` |
| `iDocs Development Team` | `the team`, `this group` |
| | `the DBA`, `the developer of iDocs` |

What is refused is anything that identifies nobody once the conversation ends —
a group known only as "mine", or a post that will be held by someone else next
quarter. A qualifier makes a role sound specific and changes nothing.

### A confirmation is a closed question

When a value is put back for confirmation, that turn asks nothing else. Bundling
the next question with it asks someone to say yes to one thing and answer
another in the same breath: the "yes" then reads as an answer to whichever the
extractor preferred, and the participant cannot tell which was heard.

"Yes", "no", "skip it", and "I'll come back later" are all answers to that turn,
and each moves the conversation on by itself. The next topic opens once they
have replied.

### Cross-field consistency

Field validation checks one value at a time, so it cannot see the failure that
actually reaches an approver: every answer individually fine, the set of them
incoherent. A change that takes a shared platform down for six hours and is
marked as not customer-impacting passes every field rule there is.

Two passes run once the answers stop moving: at wrap-up, when the questions are
exhausted, and again before any document is produced.

**Not when the mandatory set closes.** Mandatory-complete means "you may stop
here", not "we have finished asking" — running the review there put it ahead of
every recommended and optional question, and a raised finding then kept the
floor, so those fields were never asked at all.

**Declared rules** are authored beside the fields they relate. `when` is true
when something is *wrong*:

```yaml
consistency_rules:
  - id: downtime_without_customer_impact
    when: >-
      ${answered.expected_downtime and text.expected_downtime != "none"
      and answers.customer_impacting == false}
    message: An outage is expected but the change is marked as not customer impacting.
    question: Is the service genuinely invisible to customers during the outage?
    fields: [expected_downtime, customer_impacting]
    severity: blocking          # info | warning | blocking
```

The expression engine has no functions, so the vocabulary a rule needs is
supplied as data:

| In a rule | What it holds |
|---|---|
| `answers.<id>` | the coerced value |
| `answered.<id>` | true when settled and non-empty |
| `text.<id>` | lowercased string form, for comparing to a literal |
| `days.<id>` | days from today for a date; negative is the past |
| `minutes.<id>` | length in minutes, from a duration **or** a clock range |
| `has_minutes.<id>` | true when that length could be read at all |

`minutes` deliberately spans both forms — "12 hours" and `08:00-23:00 IST` are
the same question asked twice, and a rule can only compare them once they are
the same kind of number. A range gives its **upper bound**: "4-6 hours" has to
fit the window on its worst day. That is what makes this expressible:

```yaml
  - id: downtime_exceeds_window
    when: >-
      ${has_minutes.expected_downtime and has_minutes.maintenance_window
      and minutes.expected_downtime > minutes.maintenance_window}
    message: >-
      The expected downtime (${answers.expected_downtime}) is longer than the
      maintenance window it has to fit inside (${answers.maintenance_window}).
```

`message` and `question` interpolate from the same scope, so the question names
the two values it is about rather than describing the problem in the abstract.

Rule authors get presence, equality, enum comparison, date sanity, and duration
arithmetic — and nothing executable.

**Arithmetic belongs here, not in the review.** Asked to compare a downtime with
its window, a model reported that "12 hours exceeds 8AM to 11PM, which is 15
hours" — both values read correctly, the comparison inverted. A confident,
specific, wrong contradiction costs the owner a turn to refute, so the semantic
reviewer is now told to do no arithmetic at all and leave those comparisons to
rules.

**Semantic review** covers what no rule can express. The model reads the answers
*and* the conversation and reports contradictions with the participant's own
words as evidence: a stated downtime that does not fit its own maintenance
window, a risk level at odds with the description written three turns earlier.
A finding without a verbatim quote is discarded — an unevidenced finding is a
guess, and a guess that stops the form is worse than a contradiction that slips
through. Set `semantic_consistency_review: false` to run rules only.

**A typo is not a contradiction, and neither is a value written down properly.**
Two more findings are discarded in code, because telling the reviewer not to
raise them does not stop it:

* Anything about spelling, grammar, capitalisation, or phrasing. The wording
  pass owns that and fixes it silently. Putting a misspelling to the owner as
  something that "doesn't line up" spends a turn of their time to be told about
  a letter — and blocks the document behind a question whose only honest answer
  is "yes, that is a typo".
* Anything comparing a recorded value against the words it came from.
  "Recorded as 02:00-22:00 IST but stated as 2AM to 10PM IST" is this platform's
  own wording pass reported back as the participant's contradiction. Detected by
  checking the message against both the stored value and its `raw_value`, which
  is exact.

In one real session those two accounted for three of the four findings raised,
and cost three round trips to resolve nothing.

### A discrepancy is a question, not a verdict

Nothing is ever corrected on the participant's behalf. A finding is put to them
once, with the platform's restated understanding of the submission:

> You're switching ICMP's document classification from Anthropic to OpenAI on
> 15 August, in a 4am–12pm IST window, to cut token spend.
>
> Before I call this done — these don't line up:
>
> - **An outage is expected but the change is marked as not customer impacting.**
>   *Expected downtime: 4-6 hours; Customer impacting: No*
> - **The window is eight hours but the outage is stated as 4-6 hours.**
>
> Which is right? Correct whichever one is wrong, or tell me why both hold and
> I'll record your reason on the document for the approver.

Correcting an answer resolves the finding on the next evaluation — including a
restatement at the same confidence, since a later answer to a question you just
asked is a correction, not a competing claim. Standing by it records what they
said, and that lands on the artifact under **Noted discrepancies** beside the
thing that prompted it. The reason is the point: "low technical risk, high
business impact" is a coherent pair once someone explains the change is a config
flag but the platform is down while it deploys, and that explanation exists
nowhere in the form's fields.

When several are raised together, the reply is **attributed** to the ones it
actually answers. Filing one explanation against all of them produces records
where the owner's reason for reviewing their own change is a sentence about the
maintenance window — worse than recording nothing, because it reads like a
considered answer. Whatever the reply did not cover is put again, once; after
that the document says it was raised and left unexplained, which is true and
more use than asking a third time.

A `blocking` finding stops the document until it is resolved or accepted —
enforced at the render call too, so it cannot be routed around. A `warning` is
raised once and travels onto the document. Nothing is ever raised twice.

### Nothing left to ask ≠ nothing left to answer

Skipping the last outstanding question ends the asking, not the requirement. The
engine reports what is still open, records it as an action item, and leaves the
session in `collecting` — a submission never reaches an approver headed "that's
everything" with a required field rendered as `_(not provided)_`.

### "What do you think it should be?"

A judgement field the participant would rather hand back gets a **proposal**,
grounded in verbatim evidence from the conversation and stored as `PROPOSED`:

> **Risk level** — I'd put this at **high**. You said it takes the whole platform
> down for four to six hours and every upstream consumer is affected.
> Confirm and I'll record it, or give me the value you want.

It never counts as answered until they say so, so the judgement stays theirs.
Refusing to engage at all was the old behaviour, and it made people restate
their own words to satisfy a field.

### Two kinds of form

```yaml
kind: intake        # the default: fields to gather
kind: agreement     # the agreements *are* the content
```

An **intake** form gathers answers, and may carry agreements as terms the
gathering happens under. An **agreement** form is a policy acknowledgement, a
terms-of-use acceptance, a joiner's declarations pack: what makes it complete is
that every required agreement has been decided.

The distinction is not cosmetic. Under field counting a form with no fields is
complete the moment it starts — "0 of 0 required, 100%" — which is the wrong
answer about a document nobody has agreed to anything on. So `kind` changes
three things:

| | `intake` | `agreement` |
|---|---|---|
| `sections` | required | optional — it may ask for nothing at all |
| Terms are put | all due at a stage, together | **one at a time** |
| Complete when | mandatory fields are answered | every required agreement is decided |

One at a time is the part that matters. Five clauses behind a single "I agree"
is the record this exists to replace: one click, five attestations, no evidence
any of them was read. It also means a refusal attributes itself, and a question
about clause three is asked while clause three is on the screen.

An agreement form may still declare a field or two — an acceptance nobody can
tie to a person is evidence of very little — and they are asked once the terms
are settled. Everything else is the same machinery: the same conversation, the
same help-and-escalation ladder, the same artifacts, approval, and baselining.

See [`examples/forms/platform_access_agreement.yaml`](../examples/forms/platform_access_agreement.yaml).

### Agreements, and what they are worth

A form platform that gathers answers but not the agreements around them has done
half the job. The terms exist either way — someone clicked past them on a screen
before they got here, or nobody did and the submission is worth less than it
looks.

```yaml
agreements:
  - id: authority_to_raise
    title: Authority to raise this change
    kind: user                    # system | user | confirmation
    stage: before_start           # before_start | before_review | before_generate
    version: 1.0.0
    text: >-
      I am authorised to raise this change on behalf of the team that owns the
      affected system, and the people named in it know they are named.
    on_decline: >-
      That's recorded, and it's the right answer if you're not sure.
    route: change_management
```

**Kind** says whose statement it is. `system` — the platform's: how this works,
what is recorded. `user` — a declaration only the participant can make.
`confirmation` — a statement about *this* submission, made once it exists.

**Stage** says when it is due. The three are separate from kind because a
confirmation of accuracy taken before the answers attests to nothing: it is put
with the finished summary in front of them, and accepting it is what moves the
session to review.

Four rules carry the weight:

* **The text is presented and stored verbatim, and hashed.** It never goes near
  a model. Everything around it is phrasing; the words being agreed to are the
  words the form declares. The stored SHA-256 means a definition edited later
  cannot quietly restate what somebody agreed to.
* **Acceptance is per version.** A session that accepted 1.0.0 has accepted
  1.0.0. Rewording the text means bumping `version`, and it is asked again.
* **A decline is a recorded outcome, not an error.** It blocks what it gates,
  goes on the document, and is routed to the owning team. Someone who will not
  certify they were authorised has told the approver something important.
* **Nothing is inferred.** Acceptance happens when they say so, never because
  the conversation moved on.

**Consent precedes collection.** While a `before_start` agreement stands,
nothing is extracted — someone who volunteers their whole change first has to
say it again. That is the cost of taking it seriously, it is paid once, and the
alternative is a record holding text gathered under terms nobody accepted.

Questions about the terms are answered, then the terms are put again. Replying
"please say 'I agree'" to "what does *retained* mean?" is how consent becomes a
formality nobody read.

**Every clause answers its own questions.** A term nobody can explain becomes a
two-day ticket the first time somebody asks what it means — and they always ask.
So each agreement carries the material to answer them:

```yaml
- id: recording_notice
  title: How this conversation is recorded
  text: >-
    What you type here is stored against this change request … retained for
    seven years under the change management policy.
  explanation: >-                 # the plain-language version
    In short: this conversation is the record. Everything you type is kept
    against this change request and an approver will read it.
  faqs:
    - question: Why is it retained for seven years?
      aliases: [what does retention mean, how long is it kept, why seven years]
      answer: >-
        Seven years is the retention period the change management policy sets
        for production change records, so an auditor can trace a change made
        today back to the reason for it years later.
```

`explanation` answers the commonest question there is — "what does this mean?" —
which has no matchable words in it at all and would otherwise fall through every
tier to a human. `faqs` are matched on the significant words they share with
what was asked, so "can you explain the retention for change management policy?"
finds the clause about retention.

Three properties make this worth authoring:

* **No model, no wait, no ticket.** The answer is the one the clause's author
  wrote, returned instantly, identically every time.
* **The clause is legitimate grounding for the model too.** A question about
  "retained for seven years" is answerable from the sentence it appears in, so
  the tier below reads the term back in plainer words rather than refusing.
* **A repeat is measured by the answer, not by a counter.** Two *different*
  questions about the terms are two questions — the earlier design counted them
  together and sent the second one to a human unanswered.

Anything not covered still escalates, and an explicit "I still don't understand"
skips straight to it. That is the ladder working, not failing.

Ingest is behind the same gate. Mining a JIRA thread stores the participant's
words exactly as typing them would, and an agreement the upload path walks
around is not a gate, it is a notice.

Both entry points write the same record. A console checkbox
(`POST /forms/sessions/{id}/agreements/{agreement_id}`) and a typed "I agree"
produce the same text, hash, actor, and timestamp — because they have to be
worth the same thing when someone reads the record back. Deciding from outside
the chat also makes the conversation continue: the response carries the next
question and it is recorded on the transcript, because a gate that opens in
silence leaves the conversation waiting for a message and the person waiting for
a question.

**Undecided is not the same as askable.** A confirmation of accuracy is
undecided from the first turn and is refused until the mandatory set is closed —
the conversation gets that right by construction, and an API caller with a
checkbox would otherwise record an attestation to a submission that does not
exist. Each outstanding agreement reports `decidable` so a UI knows which to
offer.

There is deliberately **no tool** that accepts an agreement. Consent goes
through `forms_contribute` like anything else the participant said, so the only
route to acceptance is the engine having put the terms in its own words. An
accept tool would let a model record consent to text it had merely summarised.

### When they have a question

A form provokes questions, and a question nobody answers becomes a guess, and
the guess gets approved. Three tiers, each used only when the one below it
failed:

**1. The definition.** `help_text`, description, examples, options, rationale.
Deterministic, free, no model call, and it is the answer the form's author
wrote. Most questions end here.

```yaml
- id: customer_impacting
  description: Whether customers will notice any effect.
  help_text: >-
    Ask whether a customer could notice: an outage, a slower page, a different
    screen, an email. Touching a customer-facing system is not the same thing.
```

`description` says what the field holds; `help_text` says how to decide it.

**2. The knowledge notes.** Reference material the form carries — policy
extracts, thresholds, worked examples. The model answers from it and cites which
note it used, so an answer about policy can be traced to the policy:

```yaml
knowledge:
  - id: customer_impact_definition
    text: >-
      A change is customer impacting if a customer could notice it: an outage, a
      degraded response time, a changed screen, or an email they receive.
    applies_to: [customer_impacting, customer_comms_owner]
    source: Change Management Policy §4.2
```

It is told to refuse when the material does not settle the question, and **a
refusal here is the correct outcome**. A confident wrong answer about an
approval threshold costs somebody a rejected submission; "let me find out" costs
a day.

**3. A human.**

```yaml
escalation:
  - id: sre
    team: SRE On-Call
    contact: sre-oncall@example.com
    channel: ticket
    covers: [maintenance_window, expected_downtime]
    sla: one business day
```

Most specific route first — the field's, then its section's, then one whose
`covers` names either, then the form default. The question is recorded on the
session, travels onto the document, and comes back as data on the turn so a
console can open a ticket and a chat client can @-mention the team.

The tier is chosen by **counting, not by reading tone**: a second question about
the same field means the first answer did not land, and answering it again more
slowly is not a strategy. An explicit "that doesn't answer it" skips the tier
that just missed. "Who can I ask?" goes straight to a human — arguing with that
by producing another explanation is exactly what makes people give up.

An escalated question **does not stop the form**. The field is left open — not
skipped, which would be a decision the participant has not made — and the
conversation moves to something they can answer while the team comes back:

> I've put this to **SRE On-Call** (sre-oncall@example.com) and recorded it
> against this submission as an open question. They usually come back within one
> business day. I've left Maintenance window open rather than guessing at it.
> Come back to me when you hear, and we'll keep going with the rest meanwhile.

`POST /forms/sessions/{id}/questions/{request_id}` closes it with what the team
said.

### "Why do you need this?"

Answered from the field's `rationale`, verbatim from the definition:

```yaml
- id: rollback_plan
  rationale: >-
    "Redeploy the previous version" is not a plan. Writing the steps down
    before the change is what makes them executable under pressure.
```

Sourced rather than generated, so every user gets the reason the form's owner
actually wrote, and it stays consistent. The question is then re-asked, so
asking "why?" never costs the user their place.

### Conditional fields

```yaml
- id: customer_comms_owner
  ask_when: ${answers.customer_impacting == true}
```

A guard whose inputs are all still unanswered is treated as **not yet active**.
Without that rule the behaviour would depend on the operator: `== true` on a
missing answer is false and stays quiet, while `!= 'low'` on the same missing
answer is true and would ask about mitigation before anyone said what the risk
was.

### Coming back later

Sessions are fully serialisable and resume by participant:

```python
await fs.start_session("change_request", participant="alice")
# same person, three days later -> their session back, not a blank one
```

A session pins the form version it started on, so publishing a new version
mid-flight never changes the questions underneath someone.

## Ingesting existing discussions

| Channel | Adapter | What it handles |
|---|---|---|
| `jira` | `JiraCommentSource` | ADF and wiki markup, description + comments, bot noise |
| `email` | `EmailThreadSource` | Quoted history, signatures, disclaimers, display names |
| `email_file` | `EmailFileSource` | An uploaded `.eml` **and its attachments** |
| `meeting` | `MeetingTranscriptSource` | Speaker turns, timestamps, merges consecutive lines |
| `document` | `DocumentSource` | Pasted or uploaded text |
| `chat` | `ChatSource` | Direct turns |

Everything normalises to `SourceMessage`, so one extraction pipeline serves all
of them. Adding a channel means writing a parser; nothing downstream changes.

The cleanup is not cosmetic. A reply that quotes the original question would let
the extractor re-read superseded values and overwrite current answers with stale
ones — so quoted history is cut before extraction, and messages are processed
oldest-first so later corrections supersede earlier statements.

### Emails with attachments

The answers are very often in the *attachment* — the spreadsheet of impacted
systems, the runbook, the design note — and asking someone to retype it is
exactly the manual work this exists to remove.

```bash
curl -F email=@thread.eml -F attachments=@impact.xlsx \
  "http://localhost:8000/forms/sessions/$SID/ingest/email"
```

An `.eml` with three attachments becomes one email message plus one message per
readable attachment, all normalised to `SourceMessage`. Nothing downstream knows
the difference.

Readable: `xlsx`, `csv`, `docx`, `pdf`, `json`, `html`, `txt`, `md`, `yaml`, and
a forwarded `.eml` one level deep. A two-column sheet is rendered as
`Label: value`, which the deterministic matcher already understands — so a
key/value spreadsheet fills the form with no model involved.

Three deliberate behaviours:

* **Attachments may be uploaded alongside the mail.** Mail clients drop them on
  forward far more often than people expect, and re-sending the mail is not
  always possible.
* **An unreadable attachment is reported, not dropped.** The response names every
  file and whether its text could be read. A form that silently omits what was in
  an image is worse than one that says there was an image.
* **Outlook `.msg` is rejected with an explanation.** It is a compound binary
  format; read as a body it produces confident nonsense, so the error says how
  to export MIME instead.

Large files are capped rather than streamed into memory: 25 MB per attachment,
60 000 characters of extracted text, 400 rows of a table.

## Building a form from a sample

Upload the spreadsheet you fill in today:

```bash
curl -F file=@change_log.xlsx "http://localhost:8000/forms/infer?form_name=change_log"
```

Two stages, split deliberately:

**Structural inspection** (deterministic) — find the header row past title and
spacer rows, infer each column's type from its values, detect picklists from
repeated low-cardinality values, guess required-ness from fill rate. This is
arithmetic; a model would only make it less reliable.

**Semantic enrichment** (the model's job) — turn `req_dt` into "Requested date",
write the description and the rationale, propose aliases people would actually
say, and group columns into topics.

Then the facilitator asks about what it could not settle:

> I marked these as required based on how consistently they were filled in your
> sample: Requester, Cost Centre. Is that right?
>
> I treated Priority as a picklist (high, low). Should it allow other values?

Answer in plain language:

```python
await fs.refine_form("change_log", "make cost centre optional and add a field for the rollback plan")
```

The result registers as a **draft** and is never auto-activated — the questions
should be answered before anyone fills it in.

## Versioning and CRUD

| Operation | Behaviour |
|---|---|
| Create | Registers a version; `activate=True` publishes it |
| Update a **draft** | Edited in place |
| Update a **published** version | Forks a new draft at the next version |
| Activate | Publishes and deprecates whatever was active |
| Delete | Drafts only, unless forced |
| Archive | Permanent; new sessions can never use it |

`registry.resolve(name)` returns the latest **active** version — never a draft,
never a deprecated one. That single method is what enforces "always use the
latest active one", and everything downstream calls it.

Published versions are never edited in place because someone may already be
filling against them, and a baselined artifact references the exact version it
was produced from.

## Artifacts

Five renderers: `xlsx`, `pdf`, `docx`, `markdown`, `json`. One whose library is
absent reports itself unavailable rather than failing at import, so a deployment
can ship Markdown-only.

Every artifact carries:

1. **The answers**, grouped by topic.
2. **Agreements** — what was put to the participant, in the words it was put in,
   who decided, and when. A refusal is on there in bold.
3. **Open action items** — commitments people made, plus any required field
   nobody could close. The document states what is missing rather than
   presenting a partial record as complete.
4. **Open questions** — anything the participant asked that had to go to a team.
   An approver reading a value that was arrived at without an answer needs to
   know it was.
5. **A provenance appendix** — for each answer: which channel, which person, the
   confidence, and the verbatim text supporting it.

The last three are what make a conversationally-gathered document auditable, and
they are the parts a manually filled form never has.

A required agreement that was never accepted stops the document — and
`allow_incomplete` does not reach it. That flag exists for a deliberate interim
draft, which is a legitimate thing to want; a document produced under terms
nobody accepted is not, and the flag that permits the first must not quietly
permit the second.

## Review, approval, baseline

```
collecting → ready_for_review → in_review → approved → baselined
                                    ↓
                            changes_requested → (back to collecting)
```

Three rules carry the weight:

* **Contributors cannot approve their own submission** unless the form's policy
  allows it. Self-approval makes an approval step decorative.
* **Recording a decision under someone else's name needs
  `forms:approve:on_behalf`.** Without it, a caller could attribute their own
  approval to a colleague — and the role check would validate the *caller's*
  permissions against the *other person's* recorded name.
* **A baseline is immutable.** The session locks, the SHA-256 is recorded, and
  regenerating produces a new revision that supersedes the old.

```python
await fs.verify_baseline(artifact_id)
# {"intact": true, "expected_checksum": "...", "actual_checksum": "..."}
```

## Asking about the forms themselves

The conversation engine fills one form. The assistant answers about *all* of
them — the questions that span sessions:

```bash
curl -XPOST localhost:8000/forms/assistant/ask \
  -d '{"question": "what did we decide about the December release?", "participant": "priya"}'
```

```json
{
  "answer": "...",
  "citations": [{"kind": "session", "id": "fs_...", "title": "...", "summary": "..."}],
  "actions": [{"action": "open_session", "label": "Open ...", "session_id": "fs_..."}],
  "grounded": true,
  "generated": true
}
```

Two rules shape it:

**Retrieval is deterministic; only the prose is generated.** The same choice the
question planner makes. Records are scored in code — field-weighted term
matching, inverse document frequency so the specific words in a question outrank
the form name, and a recency curve — then cited by id so an answer can be checked
against the session it came from.

**Nothing is answered without evidence.** `generated: false` means the model was
unavailable or the deterministic profile is active, and the answer was composed
from the same evidence in plainer words. An assistant over governed records that
paraphrases from memory is worse than useless.

Sensitive fields are named but not valued. A search surface is the wrong place to
widen who can read a salary or a personal identifier.

`actions` are returned as data rather than rendered links, so the same answer
serves a web console, a chat integration, and a CLI.

`GET /forms/assistant/search` exposes the retrieval on its own, filterable by
`kind` (`session`, `form`, `artifact`). An empty query browses by recency.

The index is a linear scan over the stores. Correct and fast enough for the
thousands of sessions a form platform actually holds; `FormsAssistant._documents`
is the single seam for a search backend.

## Using it from an existing agent

The eight forms tools register into the platform's tool registry, so an agent
already doing other work can gather a form mid-conversation:

| Tool | Danger | Purpose |
|---|---|---|
| `forms_list` / `forms_describe` / `forms_status` | safe | Discovery and progress |
| `forms_agreements` | safe | What must be accepted, in its exact wording |
| `forms_start` / `forms_contribute` / `forms_ingest_thread` | low | Gather |
| `forms_generate` | medium | Produce the document |
| `forms_approve` | high | Sign off — always gated |

They inherit the platform's policy, permissions, approval gate, and audit trail.
`forms_approve` sets `requires_approval`, so a model can never baseline a
document on its own say-so.

`forms_list` reports each form's `kind`, and takes it as a filter — "what do I
have to sign?" is a different question from "what can I raise?", and an
agreement form counted in fields reads as an empty form.

There is deliberately **no tool that accepts an agreement.** Consent goes
through `forms_contribute` like anything else the person said, so the only route
to acceptance is the engine having put the exact wording to them. A dedicated
accept tool would let a model attest on someone's behalf to text it had only
summarised, which is the one thing an agreement record exists to rule out.

## Authoring a form by hand

```yaml
name: change_request          # snake_case, stable
version: 1.0.0
title: Production Change Request
kind: intake                  # intake | agreement
status: active
guidance: >-                  # framing held for the whole conversation
  They're busy and know their system. Stay brief. Risk and rollback are
  their judgement — propose when asked, but never record one they have
  not agreed to.

sections:
  - id: overview
    title: What is changing
    opening_prompt: >-        # optional; generated when absent
      What are you changing, which system, and who owns it?
    fields:
      - id: change_owner
        label: Change owner
        type: person
        importance: mandatory       # mandatory | recommended | optional
        rationale: >-               # the "why do you need this?" answer
          Someone must be reachable during the change window. Without a
          named owner there is nobody to call at 2am.
        aliases: [owner, responsible, who is doing]   # what people say
        require_explicit: true      # never infer this
```

### Field checklist

- [ ] `rationale` reads as a real reason, not a restatement of the label
- [ ] `aliases` cover what people say in tickets and email, not just the label
- [ ] `importance` is honest — `mandatory` blocks completion
- [ ] `require_explicit` on dates, owners, and money
- [ ] `validation.pattern` wherever "do you have one?" is a yes/no question but
      the field wants the reference — a ticket id, a change number, a URL
- [ ] One field per judgement. Likelihood and consequence are different
      questions, and a single `risk_level` forces the owner to throw half their
      answer away
- [ ] `consistency_rules` for the combinations that would send a submission
      back — self-review, an outage nobody is told about, a date in the past
- [ ] `requires_named_party` on every responsibility field
- [ ] `preserve_verbatim` where the exact wording is the record
- [ ] `requires_timezone` on anything holding a clock time
- [ ] `sensitive: true` on anything that must not appear in the provenance
      appendix
- [ ] `ask_when` on fields that only apply in some cases
- [ ] `help_text` wherever "what does this mean?" has a real answer — it is the
      first tier of the help ladder and the only one that costs nothing
- [ ] At least one `escalation` route, so a blocked participant has somewhere to
      go that is not a guess
- [ ] `knowledge` notes for the policy questions this form reliably provokes,
      each with a `source` so the answer can be checked
- [ ] `agreements` for anything the submission is taken *under* — and the
      `version` bumped whenever the wording changes
- [ ] `related_fields` where two fields belong in one question; it is a grouping
      signal now as well as an extraction hint

## Production considerations

The default stores are in-memory. Set `SA_FORMS__STORE_BACKEND=file` for
single-node durability, or implement `SessionStore` and `ArtifactStore` against
a database — that is the seam, and it is a four-method interface.

Other things to set before going live:

* An approver-role mapping, so `approver_roles` is enforced against real roles
* `forms:approve:on_behalf` granted only to service integrations
* Artifact retention — provenance evidence contains verbatim user text
* `sensitive: true` on any field carrying personal or regulated data
