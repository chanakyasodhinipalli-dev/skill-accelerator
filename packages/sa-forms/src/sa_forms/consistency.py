"""Cross-field consistency: does this submission contradict itself?

Field validation checks one value at a time, so it cannot see the failure that
actually reaches an approver: every answer individually fine, the set of them
incoherent. A change that takes a shared platform down for six hours and is
marked as not customer-impacting passes every field rule there is.

Two passes, and the split is the same one used everywhere else in this package:

1. **Declared rules.** Authored in the form definition, evaluated with the
   workflow expression engine. Cheap, exact, no false positives, and they say
   what the form's owner considers contradictory rather than what a model
   guesses. This is where "reviewer is also the owner" and "customers affected
   but no comms owner" belong.
2. **Semantic review.** The model reads the answers *and* the conversation and
   reports contradictions no rule could express — a stated downtime that does
   not fit its own maintenance window, a risk level at odds with the
   description the participant wrote three turns earlier. Every finding must
   quote the words that support it, and none of them is ever applied to a
   field: they become questions.

Nothing here decides anything. A finding is put to the participant, who either
changes an answer — the finding resolves itself on the next evaluation — or
stands by it and says why, which is recorded and travels onto the document.
That is the part an approver actually needs: not the absence of contradictions,
but the owner's reason for the ones that remain.
"""

from __future__ import annotations

import re
import time
from contextlib import suppress
from datetime import date
from typing import Any

from sa_orchestrator.expressions import evaluate_condition, resolve
from sa_platform.logging import get_logger
from sa_platform.telemetry import get_tracer, metrics

from .coercion import render_value
from .durations import span_minutes
from .models import (
    ConsistencyFinding,
    ConsistencyRule,
    ConsistencySeverity,
    FieldType,
    FindingState,
    FormDefinition,
    FormSession,
)

logger = get_logger(__name__)
tracer = get_tracer("sa.forms.consistency")


# ---------------------------------------------------------------------------
# The scope rules evaluate against
# ---------------------------------------------------------------------------


def build_scope(form: FormDefinition, session: FormSession, *, today: date | None = None) -> dict:
    """Assemble the values a consistency rule can reference.

    The expression engine has no functions — deliberately, since workflow
    definitions run through it too. So the vocabulary a rule needs is supplied
    as data instead:

    ``answers.<id>``     the coerced value
    ``answered.<id>``    true when it is settled and non-empty
    ``text.<id>``        lowercased string form, for comparing against a literal
    ``days.<id>``        days from today for a date field; negative is the past
    ``minutes.<id>``     length in minutes, from a duration *or* a time range
    ``has_minutes.<id>`` true when that length could be read at all

    That covers presence, equality, enum comparison, date sanity, and duration
    arithmetic without giving rule authors — or a model that writes a rule —
    anything executable.

    ``minutes`` deliberately spans both forms: "12 hours" and "08:00-23:00" are
    the same question asked twice, and a rule can only compare them once they
    are the same kind of number.
    """
    reference = today or date.today()
    answers: dict[str, Any] = {}
    answered: dict[str, bool] = {}
    text: dict[str, str] = {}
    days: dict[str, int] = {}
    minutes: dict[str, int] = {}
    has_minutes: dict[str, bool] = {}

    for field in form.fields():
        answer = session.answers.get(field.id)
        value = answer.value if answer is not None else None
        settled = answer is not None and answer.is_settled and value is not None

        answers[field.id] = value
        answered[field.id] = settled
        text[field.id] = "" if value is None else str(render_value(field, value)).strip().lower()

        if field.type is FieldType.DATE and isinstance(value, str):
            with suppress(ValueError):
                days[field.id] = (date.fromisoformat(value[:10]) - reference).days

        length = span_minutes(text[field.id]) if settled else None
        has_minutes[field.id] = length is not None
        if length is not None:
            minutes[field.id] = length

    return {
        "answers": answers,
        "answered": answered,
        "text": text,
        "days": days,
        "minutes": minutes,
        "has_minutes": has_minutes,
    }


# ---------------------------------------------------------------------------
# Pass 1 — declared rules
# ---------------------------------------------------------------------------


def evaluate_rules(
    form: FormDefinition, session: FormSession, *, today: date | None = None
) -> list[ConsistencyFinding]:
    """Run the form's declared rules. Returns one finding per rule that fires."""
    if not form.consistency_rules:
        return []

    scope = build_scope(form, session, today=today)
    findings: list[ConsistencyFinding] = []

    for rule in form.consistency_rules:
        if not _fires(rule, scope):
            continue
        findings.append(
            ConsistencyFinding(
                id=rule.id,
                message=_interpolate(rule.message, scope),
                question=_interpolate(rule.question or rule.message, scope),
                fields=list(rule.fields),
                severity=rule.severity,
                source="rule",
                evidence=_evidence_for(form, session, rule.fields),
            )
        )
    return findings


def _interpolate(template: str, scope: dict) -> str:
    """Fill `${...}` references in a rule's wording from the scope.

    A rule that can quote the two values it is complaining about asks a far
    better question than one that describes the shape of the problem in the
    abstract. Failure falls back to the template: an odd-looking message beats
    no message.
    """
    try:
        return " ".join(str(resolve(template, scope)).split())
    except Exception as exc:  # noqa: BLE001 - wording must never break a check
        logger.warning(
            "could not interpolate a consistency message",
            extra={"template": template, "error": str(exc)},
        )
        return template


def _fires(rule: ConsistencyRule, scope: dict) -> bool:
    try:
        return bool(evaluate_condition(rule.when, scope))
    except Exception as exc:  # noqa: BLE001 - a broken rule must not block intake
        # Staying quiet is the right failure here. A rule that cannot be
        # evaluated is the form author's bug, and raising a contradiction the
        # participant cannot act on would be worse than missing one.
        logger.warning(
            "consistency rule failed to evaluate; skipping it",
            extra={"rule": rule.id, "expression": rule.when, "error": str(exc)},
        )
        return False


def _evidence_for(form: FormDefinition, session: FormSession, field_ids: list[str]) -> str:
    parts: list[str] = []
    for field_id in field_ids:
        field = form.try_field(field_id)
        answer = session.answers.get(field_id)
        if field is None or answer is None or answer.value is None or field.sensitive:
            continue
        parts.append(f"{field.label}: {render_value(field, answer.value)}")
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# Pass 2 — semantic review
# ---------------------------------------------------------------------------

_REVIEW_SYSTEM = """\
You are reviewing a completed form for internal contradictions before it goes \
to an approver.

You are looking for one thing: places where two things the participant said \
cannot both be true, or sit oddly enough together that an approver would stop \
and query it. Quantities that do not fit each other, a judgement at odds with \
the description behind it, a plan that does not undo what was done.

Rules:
- Every finding must quote the participant's own words as `evidence`. If you \
cannot quote it, it is not a finding.
- Report contradictions *within this submission*. Do not report a change as \
risky, unusual, or ill-advised — that is the approver's job and not yours.
- A missing answer is not a contradiction. Something else already handles those.
- **Never report a spelling mistake, a typo, a grammatical error, or clumsy \
wording.** Those are fixed silently elsewhere and are not contradictions. \
Putting one to the participant as something that "doesn't line up" spends a \
turn of their time to be told about a letter.
- **Never report a recorded value differing from the words it came from.** \
"02:00-22:00 IST" recorded from "2AM to 10PM IST" is the same answer written \
down properly, not a discrepancy — the values are tidied on the way to the \
record by design. Report a mismatch only where the *meaning* differs.
- One clause restating another in different words is not a contradiction. \
Neither is an answer that is vaguer than you would like.
- Do no arithmetic. Do not compare two durations, times, or dates and state which is longer, earlier, or larger — those comparisons are made deterministically elsewhere, and a restatement of them is more likely to be wrong than right. Report a mismatch only where it does not turn on a calculation.
- Phrase `question` as a real question to the participant, naming both sides of \
the discrepancy so they can say which one is wrong. Never imply they made a \
mistake — they may have meant exactly what they said, and the reason is what \
you are actually collecting.
- Return an empty list when the submission is coherent. That is the normal \
outcome and reporting nothing is a success.\
"""

REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "understanding": {
            "type": "string",
            "description": (
                "Two or three sentences restating what this submission says, in the "
                "participant's own terms, for them to confirm or correct."
            ),
        },
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "Short snake_case slug, e.g. downtime_exceeds_window",
                    },
                    "message": {"type": "string", "description": "What does not line up."},
                    "question": {"type": "string", "description": "What to ask about it."},
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "field_ids involved.",
                    },
                    "evidence": {
                        "type": "string",
                        "description": "Verbatim spans from the conversation, quoted.",
                    },
                    "severity": {"type": "string", "enum": ["info", "warning", "blocking"]},
                },
                "required": ["id", "message", "question", "fields", "evidence", "severity"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["understanding", "findings"],
    "additionalProperties": False,
}


class ConsistencyReviewer:
    """The semantic half. Reads everything; changes nothing."""

    def __init__(self, llm_provider: Any | None = None) -> None:
        self._llm = llm_provider

    def _provider(self) -> Any:
        if self._llm is None:
            from sa_connectors.llm import build_provider

            self._llm = build_provider()
        return self._llm

    async def review(
        self, form: FormDefinition, session: FormSession, *, transcript_limit: int = 40
    ) -> tuple[str, list[ConsistencyFinding]]:
        """Return the model's restated understanding and any contradictions.

        A model failure returns no findings rather than raising. The declared
        rules have already run and the deterministic path is unaffected — an
        outage in the review must not become an outage in the form.
        """
        prompt = self._build_prompt(form, session, transcript_limit)
        try:
            from sa_connectors.llm.base import Message

            raw = await self._provider().complete_structured(
                [Message.user(prompt)], REVIEW_SCHEMA, system=_REVIEW_SYSTEM
            )
        except Exception as exc:  # noqa: BLE001 - review is best-effort
            logger.error(
                "semantic consistency review failed",
                extra={"form": form.name, "session": session.id, "error": str(exc)},
            )
            metrics.increment("forms.consistency_errors", form=form.name)
            return "", []

        known = {f.id for f in form.fields()}
        findings: list[ConsistencyFinding] = []
        for item in raw.get("findings") or []:
            evidence = _clean_evidence(str(item.get("evidence", "")))
            message = str(item.get("message", "")).strip()
            # An unevidenced finding is a guess, and a guess that stops the form
            # is worse than a contradiction that slips through.
            if not evidence or not message:
                continue
            # Nor is the platform's own earlier wording evidence of anything.
            # Quoting itself, the reviewer reports its own mistakes as the
            # participant's contradiction and asks them to resolve both sides.
            if _quotes_the_assistant(evidence):
                logger.warning(
                    "discarded a finding evidenced by the assistant's own turn",
                    extra={"finding": item.get("id"), "evidence": evidence[:120]},
                )
                continue
            # Nor is a typo a contradiction. Told not to, the reviewer still
            # raises them — three in one real session, each costing the owner a
            # turn to be told about a letter, and each one blocking the
            # document behind a question with no substantive answer.
            if is_about_wording(message) or is_normalisation_artefact(message, form, session):
                logger.info(
                    "discarded a wording finding; the wording pass owns that",
                    extra={"finding": item.get("id"), "message": message[:120]},
                )
                metrics.increment("forms.consistency_wording_discarded", form=form.name)
                continue
            findings.append(
                ConsistencyFinding(
                    id=_slug(str(item.get("id", "")) or message),
                    message=message,
                    question=str(item.get("question", "")).strip() or message,
                    fields=[f for f in (item.get("fields") or []) if f in known],
                    severity=_severity(str(item.get("severity", "warning"))),
                    source="model",
                    evidence=evidence[:500],
                )
            )
        return str(raw.get("understanding", "")).strip(), findings

    def _build_prompt(
        self, form: FormDefinition, session: FormSession, transcript_limit: int
    ) -> str:
        lines = [f"# Submission: {form.title}", form.description or "", ""]
        if form.guidance:
            lines += [f"Form context: {form.guidance}", ""]

        lines.append("## What has been recorded")
        for section in form.ordered_sections():
            rows: list[str] = []
            for field in section.fields:
                answer = session.answers.get(field.id)
                if answer is None or answer.value is None:
                    continue
                shown = "[redacted]" if field.sensitive else render_value(field, answer.value)
                rows.append(f"- `{field.id}` ({field.label}): {shown}")
            if rows:
                lines += [f"### {section.title}", *rows]

        lines += [
            "",
            "## The conversation these came from",
            "Only PARTICIPANT lines are evidence. ASSISTANT lines are this platform's",
            "own earlier turns: they can be wrong, and a mismatch between two of them",
            "is a bug here, not a contradiction in the submission.",
            "",
            "\n".join(
                f"{'PARTICIPANT' if entry.role == 'user' else 'ASSISTANT'}: {entry.text[:600]}"
                for entry in session.recent_transcript(transcript_limit)
            ),
        ]
        return "\n".join(lines)


#: A finding that is really about how something is written rather than what it
#: says. The wording pass owns this: it rewrites what people typed into
#: something a change board can read, and it does so without spending a turn of
#: the participant's time. A reviewer that reports the same thing as a
#: contradiction blocks the document behind a question whose only honest answer
#: is "yes, that is a typo".
_WORDING_FINDING = re.compile(
    r"\b(typo|typographical|mis-?spell(ing|ed|t)?|spelling|grammar|grammatical|"
    r"capitali[sz]ation|punctuation|phrasing|wording|worded|"
    r"formatting|reads? awkwardly|should read)\b",
    re.I,
)


def is_about_wording(message: str) -> bool:
    """True when a finding is about how something is written, not what it says."""
    return bool(_WORDING_FINDING.search(message))


def is_normalisation_artefact(message: str, form: FormDefinition, session: FormSession) -> bool:
    """True when a finding compares a value against the words it came from.

    "The maintenance window is recorded as 02:00-22:00 IST but was stated as
    2AM to 10PM IST" is not a contradiction. It is this platform writing an
    answer down properly, which it does by design and says so — and the record
    keeps both halves precisely so nobody has to choose between them.

    Detected rather than prompted away because the reviewer keeps doing it: it
    is handed the tidy value and the raw transcript, so the difference is
    genuinely visible to it, and "these two strings differ" is a much easier
    observation than "these two claims cannot both be true".
    """
    haystack = " ".join(message.lower().split())
    for field in form.fields():
        answer = session.answers.get(field.id)
        if answer is None or not answer.raw_value or answer.value is None:
            continue
        stored = " ".join(str(render_value(field, answer.value)).lower().split())
        typed = " ".join(str(answer.raw_value).lower().split())
        if stored == typed or len(stored) < 3 or len(typed) < 3:
            continue
        if stored in haystack and typed in haystack:
            return True
    return False


def _clean_evidence(text: str) -> str:
    """Strip this module's own scaffolding out of a quoted span.

    A model handed a formatted field listing sometimes hands it straight back.
    Bullets, backticks, and role labels are the prompt's punctuation, not the
    participant's, and they read as noise in the question.
    """
    cleaned = [line.strip(" -*\t").replace("`", "") for line in text.splitlines()]
    return " ".join(" ".join(cleaned).split()).strip()


def _quotes_the_assistant(evidence: str) -> bool:
    """True when the span is one of the platform's own turns, not the person's."""
    return bool(re.match(r"^(the\s+)?assistant\s*:", evidence, re.I))


def _slug(text: str) -> str:
    cleaned = "".join(c if c.isalnum() else "_" for c in text.lower()).strip("_")
    collapsed = "_".join(part for part in cleaned.split("_") if part)
    return (collapsed or "finding")[:60]


def _severity(value: str) -> ConsistencySeverity:
    try:
        return ConsistencySeverity(value.lower())
    except ValueError:
        return ConsistencySeverity.WARNING


# ---------------------------------------------------------------------------
# Putting the two together
# ---------------------------------------------------------------------------


async def review(
    form: FormDefinition,
    session: FormSession,
    *,
    llm_provider: Any | None = None,
    semantic: bool | None = None,
    today: date | None = None,
) -> tuple[str, list[ConsistencyFinding]]:
    """Run both passes and fold the result into the session.

    Returns the restated understanding and the findings that are still
    outstanding. The session's own list is updated in place: findings that no
    longer fire are marked resolved, and anything the participant already
    acknowledged stays acknowledged rather than being raised a second time.
    """
    with tracer.span("forms.consistency", form=form.name, session=session.id) as span:
        fresh = evaluate_rules(form, session, today=today)
        understanding = ""

        use_semantic = form.semantic_consistency_review if semantic is None else semantic
        # Nothing to be inconsistent *with*. An agreement form holds decisions,
        # not values, and asking a model to find contradictions among no answers
        # spends a call to be told what is true by construction — or worse,
        # invites it to invent one.
        if use_semantic and not session.settled_values():
            use_semantic = False
        if use_semantic:
            reviewer = ConsistencyReviewer(llm_provider)
            understanding, semantic_findings = await reviewer.review(form, session)
            fresh.extend(semantic_findings)

        merge(session, fresh)
        outstanding = [f for f in session.consistency_findings if f.is_outstanding]
        span.set_attribute("findings", len(fresh))
        span.set_attribute("outstanding", len(outstanding))
        metrics.observe("forms.consistency_findings", len(outstanding), form=form.name)
        return understanding, outstanding


def merge(session: FormSession, fresh: list[ConsistencyFinding]) -> None:
    """Fold a fresh evaluation into the session's finding list.

    The rules, in order:

    * A finding the participant **acknowledged** stays acknowledged. They have
      already explained it; raising it again every turn would be nagging.
    * A previously-recorded finding that no longer fires becomes **resolved** —
      they changed an answer, and the contradiction is genuinely gone.
    * Everything else keeps its state, so a finding already put to the
      participant is not re-asked while they are answering it.
    """
    by_id = {f.id: f for f in fresh}
    now = time.time()

    # Deduplicating by id alone is not enough, because the id comes from the
    # model's own wording: the same objection about the same field arrives as
    # `expected_downtime_not_standard`, then `downtime_vs_window`, then
    # `downtime_description_mismatch`, and each one reads as new. In a real
    # session that put the same field to the owner four times in a row, each
    # time overwriting the value with their reply and then objecting to the
    # value it had just written.
    #
    # A field the participant has already explained is settled. Whatever the
    # reviewer has thought of this time, they have had their turn on it.
    explained = {
        frozenset(f.fields)
        for f in session.consistency_findings
        if f.state is FindingState.ACKNOWLEDGED and f.fields
    }
    for finding in list(by_id.values()):
        scope = frozenset(finding.fields)
        if scope and any(scope <= settled for settled in explained):
            logger.info(
                "discarded a finding about a field the participant already explained",
                extra={"finding": finding.id, "fields": finding.fields},
            )
            metrics.increment("forms.consistency_repeat_discarded")
            by_id.pop(finding.id, None)

    for existing in session.consistency_findings:
        if existing.state is FindingState.ACKNOWLEDGED:
            by_id.pop(existing.id, None)
            continue
        if existing.id in by_id:
            incoming = by_id.pop(existing.id)
            existing.message = incoming.message
            existing.question = incoming.question
            existing.evidence = incoming.evidence
            existing.severity = incoming.severity
            existing.updated_at = now
        elif existing.state is not FindingState.RESOLVED:
            existing.state = FindingState.RESOLVED
            existing.updated_at = now

    session.consistency_findings.extend(by_id.values())


def mark_raised(findings: list[ConsistencyFinding]) -> None:
    """Record that these have been put to the participant."""
    now = time.time()
    for finding in findings:
        if finding.state is FindingState.OPEN:
            finding.state = FindingState.RAISED
        finding.times_raised += 1
        finding.updated_at = now


def acknowledge(session: FormSession, findings: list[ConsistencyFinding], explanation: str) -> None:
    """The participant stands by it. Record what they said.

    Their reason is the point. "Low risk, high impact — the change itself is a
    config flag, but ICMP is down while it deploys" is precisely what the
    approver needs, and it exists nowhere in the form's fields.
    """
    for finding in findings:
        finding.state = FindingState.ACKNOWLEDGED
        finding.resolution = explanation.strip()[:1000]
        finding.updated_at = time.time()


# ---------------------------------------------------------------------------
# Which discrepancy did they just answer?
# ---------------------------------------------------------------------------

_ATTRIBUTION_SYSTEM = """\
Several discrepancies were put to someone at once. They have replied with one \
message. Work out which of them the reply actually addresses, and with what.

Rules:
- A discrepancy is addressed only if the message says something about *that* \
one. A reply about the maintenance window says nothing about who reviewed the \
change; do not stretch it to cover both.
- `explanation` must come from the participant's own words — the part of their \
message that bears on this discrepancy, lightly tidied. Never write a \
justification they did not give.
- It is entirely normal for a reply to address one discrepancy and ignore the \
rest. Return the ones it addresses and nothing else.
- A reply that merely says "go ahead" or "that's fine" addresses none of them. \
Accepting without explaining is a different thing and is handled elsewhere.\
"""

ATTRIBUTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "addressed": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "The discrepancy's id."},
                    "explanation": {
                        "type": "string",
                        "description": "What they said about this one, in their words.",
                    },
                },
                "required": ["id", "explanation"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["addressed"],
    "additionalProperties": False,
}


async def attribute(
    findings: list[ConsistencyFinding],
    message: str,
    *,
    llm_provider: Any | None = None,
    assume_single: bool = True,
) -> dict[str, str]:
    """Map one reply onto the discrepancies it actually answers.

    Returns ``{finding_id: explanation}`` for the ones addressed. Anything
    absent was not answered, and the caller asks again rather than filing the
    reply against it — recording an explanation of the maintenance window as
    the owner's reason for reviewing their own change is worse than recording
    nothing, because it reads like a considered answer.

    With one finding on the table and no history behind it, no model is needed:
    they were just asked, so the reply is about that. ``assume_single`` turns
    that off once the same finding has already been followed up — at which
    point assuming is exactly the mistake this function exists to prevent.
    """
    text = message.strip()
    if not findings or not text:
        return {}
    if len(findings) == 1 and assume_single:
        return {findings[0].id: text}

    listing = "\n".join(f"- `{f.id}`: {f.message}" for f in findings)
    prompt = f"Discrepancies put to them:\n{listing}\n\nTheir reply:\n{text}"

    try:
        from sa_connectors.llm import build_provider
        from sa_connectors.llm.base import Message

        provider = llm_provider or build_provider()
        raw = await provider.complete_structured(
            [Message.user(prompt)], ATTRIBUTION_SCHEMA, system=_ATTRIBUTION_SYSTEM
        )
    except Exception as exc:  # noqa: BLE001 - fall back to asking again
        logger.error(
            "could not attribute a reply to a discrepancy",
            extra={"error": str(exc), "findings": [f.id for f in findings]},
        )
        return {}

    known = {f.id for f in findings}
    return {
        str(item.get("id")): str(item.get("explanation", "")).strip() or text
        for item in (raw.get("addressed") or [])
        if item.get("id") in known
    }


def outstanding(session: FormSession) -> list[ConsistencyFinding]:
    return [f for f in session.consistency_findings if f.is_outstanding]


def blocking(session: FormSession) -> list[ConsistencyFinding]:
    return [f for f in outstanding(session) if f.severity.blocks]


def describe(findings: list[ConsistencyFinding]) -> str:
    """Render findings for a chat reply."""
    lines: list[str] = []
    for finding in findings:
        lines.append(f"- **{finding.message}**")
        if finding.evidence:
            lines.append(f"  _{finding.evidence}_")
        if finding.question and finding.question != finding.message:
            lines.append(f"  {finding.question}")
    return "\n".join(lines)


__all__ = [
    "REVIEW_SCHEMA",
    "ConsistencyReviewer",
    "acknowledge",
    "blocking",
    "build_scope",
    "describe",
    "evaluate_rules",
    "mark_raised",
    "merge",
    "outstanding",
    "review",
]
