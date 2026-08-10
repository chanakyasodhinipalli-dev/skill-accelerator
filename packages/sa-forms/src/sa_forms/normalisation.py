"""The wording pass: what was typed, written up.

People answering questions in a chat box type answers, not prose. "8AM ro
11PM". "from the serivces start log for any issues and see if all the
operations are fine". Every one of those is a perfectly good answer and a
terrible line in a document a change board reads — and the person who typed it
is not going to proofread nineteen fields.

So the record keeps two things. ``raw_value`` and the provenance evidence hold
exactly what was said, forever. ``value`` holds it written up: typos fixed,
times in a consistent format, terse fragments turned into sentences that stand
on their own away from the conversation that produced them.

The line this must not cross is inventing content. A rewrite that adds a fact
is not formatting, it is fabrication with a clean font, and it would be
invisible precisely because it reads well. Three guards, all deterministic and
applied after the model has spoken:

* **No new numbers.** Every digit in the rewrite must already appear in the
  original or in what the participant said. This is the one that matters —
  dates, durations, and versions are what an approver acts on.
* **No padding.** A rewrite far longer than its source is elaborating, not
  formatting.
* **Typed values are never touched.** Dates, enums, booleans, and numbers are
  already normalised by coercion; letting a model near them would be all risk
  and no gain.

Anything that fails a guard is discarded and the original stands. A field that
reads awkwardly is a much smaller problem than one that reads well and is wrong.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sa_platform.logging import get_logger
from sa_platform.telemetry import get_tracer, metrics

from .models import (
    FieldType,
    FormDefinition,
    FormField,
    FormSession,
)

logger = get_logger(__name__)
tracer = get_tracer("sa.forms.normalisation")

#: Only free text is rewritten. Everything else has already been through
#: coercion, which produces a canonical form deterministically.
_REWRITABLE = (FieldType.STRING, FieldType.TEXT)

#: A rewrite may tidy and join up, not elaborate. Beyond this multiple of the
#: original word count it is writing new content.
_MAX_EXPANSION = 3.0

_DIGITS = re.compile(r"\d+")
_WORD = re.compile(r"[a-z0-9']+")

#: 8AM, 8 am, 08:00 — the shapes people actually type for a time.
_TIME = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?\b", re.I)
#: The separators people use between two times — including the typo, because
#: "8AM ro 11PM" is what someone actually typed and the meaning is not in doubt.
_RANGE_SEPARATOR = re.compile(r"\s*(?:-|\bto\b|\bro\b|\btill\b|\buntil\b)\s*", re.I)


@dataclass(slots=True)
class Rewrite:
    """One field's before and after."""

    field_id: str
    original: str
    rewritten: str
    #: Set when a rewrite was produced but refused by a guard.
    rejected: str = ""

    @property
    def applied(self) -> bool:
        return not self.rejected and self.rewritten != self.original


# ---------------------------------------------------------------------------
# Deterministic tidying
# ---------------------------------------------------------------------------


def tidy(field: FormField, text: str) -> str:
    """Clean up what code can clean up without judgement.

    Whitespace, times, and sentence shape. No spelling, no grammar, no
    rephrasing — those need a reader, and a reader is what the model is for.
    """
    cleaned = " ".join(text.split())
    if not cleaned:
        return cleaned

    cleaned = _normalise_times(cleaned)
    cleaned = cleaned[0].upper() + cleaned[1:]
    if field.type is FieldType.TEXT and cleaned[-1] not in ".!?:;":
        cleaned += "."
    return cleaned


def _normalise_times(text: str) -> str:
    """ "8AM ro 11PM" becomes "08:00-23:00".

    A maintenance window is read by someone deciding whether to be awake for it.
    Two different clock formats in one field, or a typo in the separator, is the
    kind of thing that gets misread at four in the morning.
    """

    def to_24h(match: re.Match[str]) -> str:
        hour = int(match.group(1))
        minute = match.group(2) or "00"
        if hour > 12:
            return match.group(0)
        if match.group(3).lower() == "a":
            hour = 0 if hour == 12 else hour
        elif hour != 12:
            hour += 12
        return f"{hour:02d}:{minute}"

    converted = _TIME.sub(to_24h, text)
    # Join two clock times with one separator, whatever was typed between them.
    return re.sub(
        r"(\b\d{2}:\d{2})" + _RANGE_SEPARATOR.pattern + r"(\d{2}:\d{2}\b)",
        r"\1-\2",
        converted,
    )


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


def _numbers(text: str) -> set[str]:
    """Digit runs, with leading zeros stripped so 8 and 08 are the same."""
    return {n.lstrip("0") or "0" for n in _DIGITS.findall(text)}


def check(original: str, rewritten: str, *, context: str = "") -> str:
    """Return the reason a rewrite must be refused, or "" when it is safe."""
    candidate = rewritten.strip()
    if not candidate:
        return "empty"

    invented = _numbers(candidate) - _numbers(original) - _numbers(context)
    if invented:
        return f"introduces numbers not stated: {', '.join(sorted(invented))}"

    original_words = len(_WORD.findall(original.lower())) or 1
    if len(_WORD.findall(candidate.lower())) > original_words * _MAX_EXPANSION:
        return "expands well beyond the original; that is elaboration, not formatting"

    return ""


def is_rewritable(field: FormField) -> bool:
    return field.type in _REWRITABLE and not field.preserve_verbatim and not field.sensitive


# ---------------------------------------------------------------------------
# The model pass
# ---------------------------------------------------------------------------

_REWRITE_SYSTEM = """\
You are copy-editing answers someone typed into a chat box so they read \
properly in a formal record.

For each field, return the same content written clearly:
- Fix spelling, grammar, and capitalisation.
- Turn a fragment into a complete sentence that makes sense on its own, away \
from the question that prompted it.
- Use the participant's own terminology, including their system names, \
acronyms, and spellings of those.
- Expand an abbreviation only where the participant themselves spelled it out \
somewhere in the conversation.

Absolute rules:
- Add no information. Not a cause, not a consequence, not a qualifier, not a \
number. If the answer is thin, it stays thin — someone else will decide \
whether to ask for more.
- Change no quantity, date, time, version, or name.
- Where the conversation says more about a field than the recorded value does, \
you may draw the missing detail from what the participant actually said in the \
conversation. You may not draw on anything else, including what is usual for \
work of this kind.
- If the value is already well written, return it unchanged. That is a normal \
outcome, not a failure.\
"""

REWRITE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "rewrites": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field_id": {"type": "string"},
                    "value": {
                        "type": "string",
                        "description": "The same content, written properly.",
                    },
                    "unchanged": {
                        "type": "boolean",
                        "description": "True when the original already reads well.",
                    },
                },
                "required": ["field_id", "value", "unchanged"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["rewrites"],
    "additionalProperties": False,
}


class WordingPass:
    """Rewrites free-text answers. Never changes what they say."""

    def __init__(self, llm_provider: Any | None = None) -> None:
        self._llm = llm_provider

    def _provider(self) -> Any:
        if self._llm is None:
            from sa_connectors.llm import build_provider

            self._llm = build_provider()
        return self._llm

    async def rewrite(
        self, form: FormDefinition, session: FormSession, fields: list[FormField]
    ) -> dict[str, str]:
        """Ask the model for a clean version of each field. Empty on failure."""
        if not fields:
            return {}

        context = self._context(session)
        lines = ["Rewrite each of these answers.", ""]
        for field in fields:
            answer = session.answers[field.id]
            lines += [
                f"- `{field.id}` — {field.label}",
                f"  what it means: {field.description or field.label}",
                f"  as typed: {answer.value}",
            ]
        lines += ["", "The conversation these came from:", context]

        try:
            from sa_connectors.llm.base import Message

            raw = await self._provider().complete_structured(
                [Message.user("\n".join(lines))], REWRITE_SCHEMA, system=_REWRITE_SYSTEM
            )
        except Exception as exc:  # noqa: BLE001 - the pass is cosmetic; never fatal
            logger.error(
                "wording pass failed; keeping the original text",
                extra={"form": form.name, "session": session.id, "error": str(exc)},
            )
            metrics.increment("forms.normalisation_errors", form=form.name)
            return {}

        wanted = {f.id for f in fields}
        return {
            str(item.get("field_id")): str(item.get("value", ""))
            for item in (raw.get("rewrites") or [])
            if item.get("field_id") in wanted and not item.get("unchanged")
        }

    @staticmethod
    def _context(session: FormSession, limit: int = 40) -> str:
        return "\n".join(
            f"{entry.role}: {entry.text[:600]}" for entry in session.recent_transcript(limit)
        )


def participant_words(session: FormSession, limit: int = 40) -> str:
    """Only what the participant themselves said.

    Used as the reference for the no-new-numbers guard. The assistant's own
    turns are excluded deliberately: they quote back proposed values and
    resolved dates, so counting them as "stated" would let a number the
    platform suggested come back as though the participant had confirmed it.
    """
    return "\n".join(
        entry.text for entry in session.recent_transcript(limit) if entry.role == "user"
    )


async def normalise(
    form: FormDefinition,
    session: FormSession,
    *,
    llm_provider: Any | None = None,
    enabled: bool | None = None,
) -> list[Rewrite]:
    """Tidy every free-text answer in a session, in place.

    Returns what changed, including rewrites that were produced and refused —
    a refusal is worth logging, because a model that keeps inventing numbers is
    a prompt problem somebody should see.
    """
    if not (form.normalise_wording if enabled is None else enabled):
        return []

    with tracer.span("forms.normalise", form=form.name, session=session.id) as span:
        candidates: list[FormField] = []
        # One entry per field, holding the net before-and-after. A value that is
        # both tidied and rewritten changed once as far as anyone reading the
        # summary is concerned, and counting it twice would misreport how much
        # was touched.
        changes: dict[str, Rewrite] = {}
        refusals: list[Rewrite] = []

        # Deterministic tidying first, and on its own terms: it needs no model,
        # so it still happens when the model is unavailable.
        for field in form.fields():
            answer = session.answers.get(field.id)
            if answer is None or not answer.is_settled:
                continue
            if not isinstance(answer.value, str) or not answer.value.strip():
                continue
            if not is_rewritable(field):
                continue

            original = answer.value
            tidied = tidy(field, original)
            if tidied != original:
                _apply(answer, original, tidied)
                changes[field.id] = Rewrite(field.id, original, tidied)
            candidates.append(field)

        proposed = await WordingPass(llm_provider).rewrite(form, session, candidates)
        stated = participant_words(session)

        for field_id, candidate in proposed.items():
            answer = session.answers[field_id]
            current = str(answer.value)
            # The tidied value counts as stated too: turning "8AM" into "08:00"
            # is this module's own deterministic work, not the model inventing
            # a number, and the guard must not trip over it.
            reason = check(current, candidate, context=f"{answer.raw_value or ''}\n{stated}")
            if reason:
                logger.warning(
                    "wording rewrite refused",
                    extra={"field": field_id, "reason": reason, "candidate": candidate[:120]},
                )
                metrics.increment("forms.normalisation_refused", form=form.name)
                refusals.append(Rewrite(field_id, current, candidate, rejected=reason))
                continue
            cleaned = tidy(form.field(field_id), candidate)
            if cleaned != current:
                _apply(answer, current, cleaned)
                already = changes.get(field_id)
                changes[field_id] = Rewrite(
                    field_id, already.original if already else current, cleaned
                )

        rewrites = [*changes.values(), *refusals]
        applied = [r for r in rewrites if r.applied]
        span.set_attribute("rewritten", len(applied))
        metrics.observe("forms.normalised_fields", len(applied), form=form.name)
        return rewrites


def _apply(answer: Any, original: str, rewritten: str) -> None:
    """Store the tidy value while keeping what was typed.

    ``raw_value`` is only set the first time, so a second pass polishing an
    already-polished value cannot quietly overwrite the true original.
    """
    if not answer.polished or not answer.raw_value:
        answer.raw_value = answer.raw_value or original
    answer.value = rewritten
    answer.polished = True


__all__ = [
    "REWRITE_SCHEMA",
    "Rewrite",
    "WordingPass",
    "check",
    "is_rewritable",
    "normalise",
    "tidy",
]
