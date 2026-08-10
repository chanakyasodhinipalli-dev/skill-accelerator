"""Consent, taken in the conversation and recorded as evidence.

A form platform that gathers answers but not the agreements around them has
only done half the job. The terms exist either way — someone accepted them on a
screen before they got here, or nobody did and the submission is worth less than
it looks. Taking them here means the record holds the words that were shown, who
accepted them, and when, beside the answers they govern.

Three kinds, and the distinction is load-bearing:

* **System** — the platform's statement. How this works, what is recorded, what
  happens to the text afterwards.
* **User** — a declaration the participant makes about themselves. "I am
  authorised to raise this change." Nobody else can make it for them.
* **Confirmation** — a statement about *this* submission, once it exists.
  "Everything above is accurate." Taken before the answers it is meaningless,
  which is why stage is separate from kind.

Four rules the rest of the package relies on:

**The text is presented verbatim and stored verbatim.** An agreement paraphrased
on the way to the participant is not the agreement they accepted. The stored
copy carries a SHA-256 so a definition edited afterwards cannot quietly restate
what somebody agreed to.

**Acceptance is per version.** A session that accepted v1 has not accepted v2.
Re-asking is the only honest way to get it.

**A decline is a recorded outcome, not an error.** It stops what it gates and it
goes on the document. Someone who will not certify they are authorised has told
the approver something important.

**Nothing is inferred.** A required agreement is accepted when the participant
says so and never because the conversation moved on.
"""

from __future__ import annotations

import hashlib
import re
import time

from sa_orchestrator.expressions import evaluate_condition
from sa_platform.logging import get_logger
from sa_platform.telemetry import metrics

from .models import (
    Agreement,
    AgreementDecision,
    AgreementKind,
    AgreementRecord,
    AgreementStage,
    FormDefinition,
    FormSession,
)

logger = get_logger(__name__)

#: An unambiguous acceptance. Deliberately narrow: this is consent, and the
#: cost of reading agreement into an ambiguous reply is a record that says
#: somebody accepted terms they did not.
ACCEPTANCE = re.compile(
    r"^\W*(i\s+)?(agree|accept|consent|confirm(ed)?|acknowledge|approved?|"
    r"understood|ok(ay)?|yes|yep|yeah|sure|fine|go ahead|proceed|"
    r"that'?s fine|happy with (that|this)|sounds good|lgtm|"
    # People say these far more often than "I agree", and every one of them was
    # falling through to "I need this settled before I record anything" —
    # which reads as not listening to somebody who just said yes.
    r"all good|looks good|that works|works for me|no (issues?|objections?|"
    r"problems?|concerns?)|content with (that|this)|i'?m happy|good to go|"
    r"agreed|accepted|noted|understood)\b",
    re.I,
)

#: An unambiguous refusal. Checked first — "I do not agree" opens with the same
#: words as "I agree" and means the opposite.
#:
#: The bare-"no" branch is anchored to a standalone reply. It used to match any
#: sentence *starting* with "no", which made **"no issues" a refusal** — a
#: recorded decline against a term the person had just accepted, which is the
#: worst thing this module can get wrong.
REFUSAL = re.compile(
    r"\b(i\s+)?(do\s?n[o']?t|don'?t|can\s?not|can'?t|won'?t|will not|refuse|declin(e|ing)|"
    r"disagree|not (happy|willing|prepared|comfortable)|no,?\s+i\b)"
    r"|^\W*(no|nope|nah|reject(ed)?|declined?|disagree)\W*$",
    re.I,
)


def digest(text: str) -> str:
    """SHA-256 of the exact words presented."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def applicable(
    form: FormDefinition, session: FormSession, stage: AgreementStage
) -> list[Agreement]:
    """Agreements due at this stage, honouring their ``ask_when`` guards.

    A conditional agreement whose guard cannot yet be decided is not due. The
    same rule as a conditional field, for the same reason: an undecidable guard
    would otherwise resolve differently depending on which operator the author
    happened to use.
    """
    values = session.all_values()
    due: list[Agreement] = []
    for agreement in form.agreements:
        if agreement.stage is not stage:
            continue
        if agreement.ask_when:
            try:
                if not evaluate_condition(
                    agreement.ask_when, {"answers": values, "inputs": values}
                ):
                    continue
            except Exception as exc:  # noqa: BLE001 - a bad guard must not hide consent
                logger.warning(
                    "agreement ask_when failed to evaluate; treating it as due",
                    extra={"agreement": agreement.id, "error": str(exc)},
                )
        due.append(agreement)
    return due


def reachable(form: FormDefinition, session: FormSession, stage: AgreementStage) -> bool:
    """Whether this stage is one the session has actually got to.

    A confirmation of accuracy is undecided from the first turn, and it is not
    therefore *askable* from the first turn: a statement about a submission
    cannot be taken before the submission exists. The conversation gets this
    right by construction — it only presents review-stage terms at the review —
    but a console with a checkbox, or an integration posting decisions, would
    otherwise record an attestation to nothing.
    """
    if stage is AgreementStage.BEFORE_START:
        return True
    from .completeness import analyse

    return analyse(form, session).mandatory_complete


def outstanding(
    form: FormDefinition, session: FormSession, stage: AgreementStage
) -> list[Agreement]:
    """Due agreements with no decision recorded against the current version."""
    return [
        agreement
        for agreement in applicable(form, session, stage)
        if session.agreement_record(agreement.id, agreement.version) is None
    ]


def next_batch(
    form: FormDefinition, session: FormSession, stage: AgreementStage
) -> list[Agreement]:
    """The agreements to put in this turn.

    An intake form puts everything due at a stage in one message: the terms are
    a preamble to the work, and three of them with one "I agree" is proportionate
    to what they are — nobody wants four screens before a change request.

    An **agreement form** puts them one at a time, because there the agreements
    *are* the work. Bundling five clauses behind a single "I agree" produces
    exactly the record this exists to replace: one click, five attestations, no
    evidence that any of them was read. One at a time also means a refusal
    attributes itself, and a question about clause three is asked while clause
    three is on the screen.
    """
    due = outstanding(form, session, stage)
    if form.is_agreement_form:
        return due[:1]
    return due


def blocking(form: FormDefinition, session: FormSession, stage: AgreementStage) -> list[Agreement]:
    """What stops this stage: required agreements undecided *or* declined.

    A declined required agreement is as blocking as an unanswered one, and
    stays blocking. Recording the refusal is what makes it visible instead of
    an abandoned session nobody hears about.
    """
    stopped: list[Agreement] = []
    for agreement in applicable(form, session, stage):
        if not agreement.required:
            continue
        record = session.agreement_record(agreement.id, agreement.version)
        if record is None or not record.accepted:
            stopped.append(agreement)
    return stopped


def blocking_up_to(
    form: FormDefinition, session: FormSession, stage: AgreementStage
) -> list[Agreement]:
    """Everything blocking at this stage and every stage before it.

    Rendering a document is downstream of starting the conversation, so a
    start-stage term nobody accepted blocks the document too. Checking one
    stage in isolation is how a gate gets routed around by calling a later API
    directly.
    """
    order = list(AgreementStage)
    upto = order[: order.index(stage) + 1]
    return [a for earlier in upto for a in blocking(form, session, earlier)]


def record(
    session: FormSession,
    agreement: Agreement,
    *,
    decision: AgreementDecision,
    actor: str,
    stated: str = "",
) -> AgreementRecord:
    """Write the decision to the session.

    Supersedes any earlier decision on the same version — someone may accept
    after first declining, and the earlier record is kept in the list rather
    than edited, so the sequence stays readable.
    """
    entry = AgreementRecord(
        agreement_id=agreement.id,
        version=agreement.version,
        decision=decision,
        actor=actor,
        text=agreement.text,
        text_hash=digest(agreement.text),
        stated=stated.strip()[:500],
        decided_at=time.time(),
    )
    session.agreements.append(entry)
    session.touch()
    metrics.increment(
        "forms.agreement",
        agreement=agreement.id,
        kind=agreement.kind.value,
        decision=decision.value,
    )
    logger.info(
        "agreement decision recorded",
        extra={
            "session": session.id,
            "agreement": agreement.id,
            "version": agreement.version,
            "decision": decision.value,
            "actor": actor,
        },
    )
    return entry


def read_decision(text: str) -> AgreementDecision | None:
    """Classify a reply to an agreement. ``None`` means it was neither.

    Refusal is tested first because English puts the same word at the front of
    both: "I agree" and "I do not agree" share their first token, and a
    prefix-matched acceptance would read the second as the first.
    """
    stripped = text.strip()
    if not stripped:
        return None
    if REFUSAL.search(stripped):
        return AgreementDecision.DECLINED
    if ACCEPTANCE.match(stripped):
        return AgreementDecision.ACCEPTED
    return None


def identify(candidates: list[Agreement], text: str) -> Agreement | None:
    """Which of these is the participant naming? ``None`` when it is unclear.

    Asked "which of these can't you accept?", people answer in two or three
    words — "how recorded", "the authority one" — not by quoting the title.
    Matching on the significant words those titles and clauses share is enough
    to tell two or three apart, and refusing to guess when two match equally is
    what keeps a refusal from landing against the wrong term.
    """
    asked = _significant(text)
    if not asked or len(candidates) < 2:
        return candidates[0] if (asked and candidates) else None

    scored: list[tuple[int, Agreement]] = []
    for agreement in candidates:
        vocabulary = _significant(f"{agreement.title} {agreement.id.replace('_', ' ')}")
        score = 2 * len(asked & vocabulary)
        # The clause body is a weaker signal than its title — every clause
        # mentions "change" in a change request — so it only breaks ties.
        score += len(asked & _significant(agreement.text))
        scored.append((score, agreement))

    scored.sort(key=lambda pair: -pair[0])
    if scored[0][0] == 0 or scored[0][0] == scored[1][0]:
        return None  # nothing matched, or nothing to choose between
    return scored[0][1]


_IDENTIFY_NOISE = frozenset(
    {
        "a",
        "about",
        "an",
        "and",
        "any",
        "are",
        "be",
        "can",
        "cannot",
        "for",
        "from",
        "have",
        "how",
        "is",
        "it",
        "not",
        "of",
        "one",
        "or",
        "the",
        "this",
        "that",
        "these",
        "to",
        "with",
        "you",
        "your",
        "accept",
        "agree",
    }
)

_IDENTIFY_WORD = re.compile(r"[a-z][a-z0-9'-]*")


def _significant(text: str) -> set[str]:
    return {
        word
        for word in _IDENTIFY_WORD.findall(text.lower())
        if word not in _IDENTIFY_NOISE and len(word) > 2
    }


def present(agreement: Agreement) -> str:
    """The agreement as the participant sees it.

    The text is never rewritten, summarised, or handed to a model. Everything
    around it may be phrased; the words being agreed to are the words the form
    declares.
    """
    ask = agreement.prompt or _default_prompt(agreement)
    return f"**{agreement.title}**\n\n{agreement.text.strip()}\n\n{ask}"


def present_all(agreements: list[Agreement]) -> str:
    """Several agreements in one message, each with its own text."""
    if len(agreements) == 1:
        return present(agreements[0])
    blocks = [f"**{a.title}**\n\n{a.text.strip()}" for a in agreements]
    closing = (
        "Reply 'I agree' to accept all of these, or tell me which one you have a "
        "problem with and I'll take it from there."
    )
    return "\n\n".join(blocks) + f"\n\n{closing}"


def _default_prompt(agreement: Agreement) -> str:
    """What to ask when the author did not write an acceptance line."""
    if agreement.kind is AgreementKind.CONFIRMATION:
        return (
            "Confirm this and I'll record it. If anything above is wrong, tell me what to change."
        )
    if agreement.kind is AgreementKind.USER:
        return "Do you confirm this? Reply 'I agree', or tell me if you can't."
    return "Reply 'I agree' to continue, or ask me anything about it first."


def describe(agreements: list[Agreement]) -> str:
    """One line per agreement, for a status report rather than for consent."""
    return "\n".join(f"- **{a.title}** ({a.kind.value}, v{a.version})" for a in agreements)


def summary(form: FormDefinition, session: FormSession) -> list[dict[str, object]]:
    """Every agreement this form declares, and where it stands.

    Includes the ones not yet due, so a caller building a progress view can
    show what is coming rather than only what is late.
    """
    rows: list[dict[str, object]] = []
    due_now = {a.id for stage in AgreementStage for a in applicable(form, session, stage)}
    for agreement in form.agreements:
        entry = session.agreement_record(agreement.id, agreement.version)
        rows.append(
            {
                "id": agreement.id,
                "title": agreement.title,
                "kind": agreement.kind.value,
                "stage": agreement.stage.value,
                "version": agreement.version,
                "required": agreement.required,
                "due": agreement.id in due_now,
                "decision": entry.decision.value if entry else None,
                "actor": entry.actor if entry else None,
                "decided_at": entry.decided_at if entry else None,
            }
        )
    return rows


__all__ = [
    "ACCEPTANCE",
    "REFUSAL",
    "applicable",
    "blocking",
    "blocking_up_to",
    "describe",
    "digest",
    "identify",
    "next_batch",
    "outstanding",
    "present",
    "present_all",
    "read_decision",
    "reachable",
    "record",
    "summary",
]
