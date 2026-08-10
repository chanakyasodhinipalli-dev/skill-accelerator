"""Answering the participant's questions, and knowing when to stop trying.

A form provokes questions. "What counts as customer impacting?" "Is a config
flag a change?" "Who is my business approver?" Today they are answered by
whoever the person happens to know, or not at all — and a question not answered
becomes a guess, and a guess becomes a wrong value on an approved record.

Three tiers, escalating only when the previous one failed:

1. **From the definition.** The field's description, its help text, its
   examples, its options, the section it sits in, its rationale. Deterministic,
   free, always available, and it is the answer the form's author wrote rather
   than one a model invented. Most questions end here.

2. **From the knowledge notes.** The model reads the reference material the
   form carries — policy extracts, thresholds, worked examples — and answers
   from it, citing which note it used. It is told to say when the material does
   not settle the question, and a refusal at this tier is the *correct* outcome,
   not a failure: the alternative is a confident sentence about an approval
   threshold that is wrong.

3. **To a human.** The question is routed to the team that owns that part of
   the form, recorded on the session as an open item, and travels onto the
   document. The participant is told who has it and what happens next.

The tier is chosen from a count, not from tone. A second question about the
same field means the first answer did not land, and answering it again more
slowly is not a strategy.

Nothing here writes an answer into a field. A question is a question; if it
produces a value, the participant says so on their next turn and the extractor
handles it like any other statement.
"""

from __future__ import annotations

import re
import time
from typing import Any

from sa_platform.logging import get_logger
from sa_platform.telemetry import metrics

from .models import (
    EscalationRoute,
    FormDefinition,
    FormField,
    FormSession,
    KnowledgeNote,
    SupportRequest,
    SupportStatus,
)

logger = get_logger(__name__)

#: "That didn't answer it" — an explicit signal that tier 1 or 2 failed,
#: independent of how many times they have asked.
UNSATISFIED = re.compile(
    r"\b(that (does\s?n[o']?t|did\s?n[o']?t) (answer|help|clarify)|still (do\s?n[o']?t|not) "
    r"(understand|clear|sure|follow)|not what i (asked|meant)|that'?s not what i|"
    r"you'?re not (answering|listening)|i already asked|no,? i mean)\b",
    re.I,
)

#: "Get me a human." An explicit request goes straight to tier 3 — arguing with
#: it by trying another explanation is exactly what makes people give up.
#:
#: Deliberately demanding about its objects. "Raise this" is what someone says
#: about the change request they are filling in; only "raise this *with*
#: somebody" is a request for help. So is "check with the team" — said far more
#: often as a promise the participant is making than as one they are asking for.
WANTS_A_HUMAN = re.compile(
    r"\bwho (can|should|do) i (ask|talk to|contact|speak)"
    r"|\bcan (i|we|you) (talk|speak) to\b"
    r"|\bput me (in touch|through)\b"
    r"|\b(raise|escalate|refer) (this|it|that|the question) (with|to)\b"
    r"|\b(can|could) (you|we|someone) (ask|check with|contact|find out from)\b"
    r"|\bi need (a human|someone|somebody|help from)\b"
    r"|\bis there (someone|somebody|anyone) i can\b"
    r"|\b(get|bring) (someone|somebody|a human) (in|on)\b",
    re.I,
)


# ---------------------------------------------------------------------------
# Tier 1 — what the form already knows
# ---------------------------------------------------------------------------


def explain(form: FormDefinition, fields: list[FormField]) -> str:
    """Assemble an explanation from the definition. Empty when it has nothing.

    Emptiness is the signal that matters: a field with no description, no help
    text and no examples cannot be explained from the definition, and repeating
    its label back as though that were an answer is worse than moving up a tier.
    """
    parts: list[str] = []
    for field in fields:
        detail = field.help_text or field.description
        if not detail and not field.options and not field.examples:
            continue
        piece = f"**{field.label}** — {detail or field.label}"
        if field.options:
            piece += f" It has to be one of: {', '.join(field.options)}."
        if field.examples:
            piece += f" For example: {'; '.join(str(e) for e in field.examples[:2])}."
        if field.unit:
            piece += f" Expressed in {field.unit}."
        if field.rationale:
            piece += f" It's asked because {_lower_first(field.rationale.strip())}"
        parts.append(piece)
    return "\n\n".join(parts)


def _lower_first(text: str) -> str:
    return (text[0].lower() + text[1:]) if text else text


#: Words that carry no meaning when matching a question to an authored one.
_QUESTION_NOISE = frozenset(
    {
        "a",
        "about",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "explain",
        "exactly",
        "for",
        "from",
        "get",
        "give",
        "has",
        "have",
        "how",
        "i",
        "in",
        "is",
        "it",
        "its",
        "just",
        "know",
        "me",
        "mean",
        "means",
        "more",
        "my",
        "of",
        "on",
        "or",
        "please",
        "really",
        "should",
        "so",
        "some",
        "tell",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "to",
        "us",
        "was",
        "we",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
    }
)

_WORD = re.compile(r"[a-z][a-z0-9'-]*")


def _significant(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _QUESTION_NOISE and len(w) > 2}


def answer_from_agreements(agreements: list[Any], question: str) -> tuple[str, str] | None:
    """Answer a question about a term from what its author wrote beside it.

    Returns ``(answer, agreement_id)`` or ``None``. Matching is on significant
    words shared with the authored question, which is crude and exactly right
    for the job: these are a handful of questions per clause, hand-written by
    whoever wrote the clause, and a near-miss costs nothing because the tiers
    below still run.

    This tier exists because the alternative was a ticket. "What does this
    mean?" about a term the participant is being asked to accept *now* is the
    most predictable question in the entire flow, and answering it with "I've
    put this to Platform Governance, they'll come back within two business
    days" is a worse experience than the paper form it replaced.
    """
    asked = _significant(question)
    if not asked:
        # "What does this mean, exactly?" — every word in it is noise, and it is
        # the single most common question there is. The clause's own explanation
        # is written for precisely this, so a question with nothing to match on
        # gets it rather than a ticket.
        glosses = [(a.explanation, a.id) for a in agreements if a.explanation]
        if len(glosses) == 1:
            return glosses[0]
        if glosses:
            return (
                "\n\n".join(
                    f"**{a.title}** — {a.explanation}" for a in agreements if a.explanation
                ),
                ",".join(i for _, i in glosses),
            )
        return None

    best: tuple[float, str, str] | None = None
    for agreement in agreements:
        for faq in agreement.faqs:
            for phrasing in [faq.question, *faq.aliases]:
                authored = _significant(phrasing)
                if not authored:
                    continue
                overlap = len(asked & authored) / len(authored)
                if overlap >= 0.5 and (best is None or overlap > best[0]):
                    best = (overlap, faq.answer, agreement.id)
    if best is not None:
        return best[1], best[2]

    # No FAQ matched. A question whose words appear in the clause itself is
    # still answerable from the clause: "what does retained for seven years
    # mean?" is asking about a sentence that is on the screen.
    for agreement in agreements:
        if not agreement.explanation:
            continue
        if asked & _significant(agreement.text):
            return agreement.explanation, agreement.id
    return None


def notes_for(form: FormDefinition, field_ids: list[str]) -> list[KnowledgeNote]:
    """Reference material bearing on these fields, plus the form-wide notes.

    A note with no ``applies_to`` covers the whole form — the retention policy,
    the definition of an emergency change — and is always in scope.
    """
    sections = {form.section_of(f).id for f in field_ids if form.try_field(f) is not None}
    wanted = set(field_ids) | sections
    return [n for n in form.knowledge if not n.applies_to or (set(n.applies_to) & wanted)]


# ---------------------------------------------------------------------------
# Tier 2 — grounded in the notes, or not answered at all
# ---------------------------------------------------------------------------


_ANSWER_SYSTEM = """\
The participant has asked a question while filling in a form. Answer it from \
the reference material provided and nothing else.

Rules:
- Use only the form definition, the reference notes, and any terms quoted below. \
You have no other knowledge of this organisation, its policies, its teams, or \
its systems.
- Where the question is about wording that appears in a quoted term, the term \
itself is your source: read it back in plainer words and say what it commits \
them to. Do not go beyond what it says.
- If the material does not settle the question, set `answered` to false and say \
in `gap` what would be needed to answer it. That is the right outcome, not a \
failure. A confident wrong answer about a policy costs someone a rejected \
submission.
- Never invent a threshold, an owner, a team name, a deadline, or a rule.
- Never tell them what to put in the field unless the material states it. \
Explaining what the field means is help; deciding their answer is not.
- Cite the ids of the notes you used in `sources`.
- Two to four sentences, addressed to them, in plain language.\
"""

_ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "description": "The answer, or the reason there isn't one."},
        "answered": {
            "type": "boolean",
            "description": "False when the material does not settle the question.",
        },
        "gap": {
            "type": "string",
            "description": "What is missing, when `answered` is false.",
        },
        "sources": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["answer", "answered", "gap", "sources"],
    "additionalProperties": False,
}


async def answer_from_knowledge(
    form: FormDefinition,
    session: FormSession,
    question: str,
    fields: list[FormField],
    *,
    llm_provider: Any = None,
    extra_context: str = "",
    scope: list[str] | None = None,
) -> dict[str, Any]:
    """Answer from the form's reference material. Grounded or nothing.

    Returns ``{"answer", "answered", "gap", "sources"}``. A provider failure
    returns ``answered: False``, which routes the question to a human — the same
    outcome as material that does not cover it, and the right one: an outage is
    not a reason to guess at a policy.
    """
    # `scope` lets a caller widen the note lookup beyond fields — an agreement
    # id names material written about that clause, and a question about a term
    # should reach it.
    notes = notes_for(form, [f.id for f in fields] + (scope or []))
    lines: list[str] = [f"Question: {question.strip()}", ""]

    if form.guidance:
        lines += [f"Form context: {form.guidance}", ""]
    if extra_context:
        lines += [extra_context, ""]
    if fields:
        lines += ["The question appears to be about these fields:"]
        for field in fields:
            lines.append(f"- `{field.id}` — {field.prompt_descriptor()}")
            if field.help_text:
                lines.append(f"  Guidance: {field.help_text}")
            if field.rationale:
                lines.append(f"  Why it is asked: {field.rationale}")
        lines.append("")

    if notes:
        lines += ["Reference notes you may answer from:"]
        for note in notes:
            heading = note.title or note.id
            lines.append(f"- [{note.id}] {heading}: {note.text}")
            if note.source:
                lines.append(f"  Source: {note.source}")
        lines.append("")
    else:
        lines += [
            "There are no reference notes for this form. Unless the field "
            "definitions above settle the question, say so.",
            "",
        ]

    lines += ["Conversation so far:", _recent(session)]

    if llm_provider is None:
        return {
            "answer": "",
            "answered": False,
            "gap": "no reference material and no model available",
            "sources": [],
        }

    try:
        from sa_connectors.llm.base import Message

        response = await llm_provider.complete_structured(
            [Message.user("\n".join(lines))], _ANSWER_SCHEMA, system=_ANSWER_SYSTEM
        )
    except Exception as exc:  # noqa: BLE001 - an unanswered question escalates
        logger.error(
            "knowledge answer failed; escalating instead",
            extra={"form": form.name, "error": str(exc)},
        )
        return {
            "answer": "",
            "answered": False,
            "gap": "the assistant was unavailable",
            "sources": [],
        }

    answered = bool(response.get("answered")) and bool(str(response.get("answer", "")).strip())
    return {
        "answer": str(response.get("answer", "")).strip(),
        "answered": answered,
        "gap": str(response.get("gap", "")).strip(),
        "sources": [str(s) for s in (response.get("sources") or [])],
    }


def _recent(session: FormSession, limit: int = 8) -> str:
    return "\n".join(f"{e.role}: {e.text[:300]}" for e in session.recent_transcript(limit))


# ---------------------------------------------------------------------------
# Tier 3 — a human
# ---------------------------------------------------------------------------


def route_for(form: FormDefinition, field_ids: list[str]) -> EscalationRoute | None:
    """Which team owns a question about these fields.

    Most specific first: the field's own route, then its section's, then a route
    that names the field or section in ``covers``, then the form default. A form
    that declares no routes at all returns ``None`` and the caller falls back to
    naming the form's owner, which is better than nothing and visibly worse than
    a real route — which is the point.
    """
    for field_id in field_ids:
        field = form.try_field(field_id)
        if field is None:
            continue
        if field.route:
            resolved = form.route(field.route)
            if resolved is not None:
                return resolved
        section = form.section_of(field_id)
        if section.route:
            resolved = form.route(section.route)
            if resolved is not None:
                return resolved

    sections = {form.section_of(f).id for f in field_ids if form.try_field(f) is not None}
    scope = set(field_ids) | sections
    for candidate in form.escalation:
        if candidate.covers and set(candidate.covers) & scope:
            return candidate
    return form.default_route()


def escalate(
    form: FormDefinition,
    session: FormSession,
    question: str,
    fields: list[FormField],
    *,
    asked_by: str,
    reason: str = "",
    route: EscalationRoute | None = None,
) -> SupportRequest:
    """Hand the question to a team and record it on the session.

    ``route`` overrides the field-based lookup, for a question that is not about
    a field at all — the wording of an agreement belongs to whoever owns that
    agreement, and resolving it from an empty field list would send it to the
    form's default queue instead.

    Recording is the substantive part. Sending a message is a connector's job
    and every deployment does it differently; a question that is logged, owned,
    and visible on the document is one somebody can act on, whereas a question
    answered into a chat window and forgotten is how the same gap in a form gets
    hit by the next twenty people too.
    """
    route = route or route_for(form, [f.id for f in fields])
    request = SupportRequest(
        question=question.strip()[:1000],
        asked_by=asked_by,
        fields=[f.id for f in fields],
        tier="routed",
        answer="",
        status=SupportStatus.ROUTED,
        route_id=route.id if route else None,
        team=route.team if route else (form.owner or "the form owner"),
        contact=route.contact if route else "",
        channel=route.channel if route else "",
        resolution=reason,
    )
    session.support_requests.append(request)
    session.touch()
    metrics.increment("forms.support_escalated", form=form.name, route=request.route_id or "none")
    logger.info(
        "form question escalated",
        extra={
            "session": session.id,
            "form": form.name,
            "route": request.route_id,
            "team": request.team,
            "fields": request.fields,
        },
    )
    return request


def record_answer(
    session: FormSession,
    question: str,
    *,
    asked_by: str,
    fields: list[FormField],
    tier: str,
    answer: str,
    sources: list[str] | None = None,
) -> SupportRequest:
    """Log a question that was answered inside the conversation.

    Kept for the same reason the escalated ones are: the questions a form
    provokes are the cheapest evidence there is of where its wording is wrong,
    and they are invisible today because they happen in a chat nobody reads back.
    """
    request = SupportRequest(
        question=question.strip()[:1000],
        asked_by=asked_by,
        fields=[f.id for f in fields],
        tier=tier,
        answer=answer.strip()[:2000],
        sources=sources or [],
        status=SupportStatus.ANSWERED,
    )
    session.support_requests.append(request)
    session.touch()
    metrics.increment("forms.support_answered", tier=tier)
    return request


def describe_route(request: SupportRequest, *, sla: str = "") -> str:
    """What to tell the participant once a question has been routed."""
    where = f" ({request.contact})" if request.contact else ""
    promise = f" They usually come back within {sla}." if sla else ""
    return (
        f"I've put this to **{request.team}**{where} and recorded it against this "
        f"submission as an open question.{promise}"
    )


def close(session: FormSession, request_id: str, resolution: str) -> SupportRequest | None:
    """Mark a routed question as answered by the team it went to."""
    for request in session.support_requests:
        if request.id == request_id:
            request.status = SupportStatus.CLOSED
            request.resolution = resolution.strip()[:2000]
            request.updated_at = time.time()
            session.touch()
            return request
    return None


__all__ = [
    "UNSATISFIED",
    "WANTS_A_HUMAN",
    "answer_from_agreements",
    "answer_from_knowledge",
    "close",
    "describe_route",
    "escalate",
    "explain",
    "notes_for",
    "record_answer",
    "route_for",
]
