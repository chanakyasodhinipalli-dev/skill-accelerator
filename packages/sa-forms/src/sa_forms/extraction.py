"""Extraction: unstructured conversation in, field answers out.

Two passes, deliberately:

1. **Deterministic pre-pass.** Explicit ``Field: value`` statements and
   high-precision patterns (email, URL, ISO date) are matched in code. These
   are free, exact, and carry perfect provenance — there is no reason to spend
   a model call on "Owner: alice@example.com".
2. **Semantic pass.** Everything the pre-pass could not settle goes to the
   model with a schema built from the form, which reads intent across the whole
   message ("we'll aim for the end of next quarter", "Priya's team owns it").

Every extraction carries a confidence and the verbatim evidence that supports
it. Anything below the field's threshold is held as ``PROPOSED`` and confirmed
with the user rather than silently accepted — a form that quietly guesses is
worse than one that asks.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any

from sa_platform.logging import get_logger
from sa_platform.telemetry import get_tracer, metrics

from .coercion import CoercionError, coerce_and_validate, date_is_inferred, is_null_token
from .models import (
    AnswerState,
    FieldType,
    FormDefinition,
    FormField,
    Provenance,
    SourceMessage,
)

logger = get_logger(__name__)
tracer = get_tracer("sa.forms.extraction")

#: Confidence assigned to a deterministic pattern match. Not 1.0 — the pattern
#: is certain, but that the speaker meant it as *this field's* value is not.
_PATTERN_CONFIDENCE = 0.92
#: Confidence for an explicit "Label: value" statement.
_LABELLED_CONFIDENCE = 0.95

#: Ceiling applied to a date the speaker did not fully write out ("next Friday",
#: "Aug 15"). Below the default threshold on purpose: the value is accepted into
#: the session but held as PROPOSED, so the resolved date is read back and
#: confirmed rather than silently scheduled.
_INFERRED_DATE_CONFIDENCE = 0.55

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_URL_RE = re.compile(r"https?://\S+")
_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")

#: Author values that name nobody, so a first-person reference cannot be
#: resolved through them.
_ANONYMOUS_AUTHORS = frozenset(
    {"", "user", "users", "unknown", "anonymous", "system", "assistant", "operator", "me"}
)

#: First-person phrasings that mean "the person typing". Resolved to the
#: speaker's identity rather than stored verbatim — see `_SELF_REFERENCE` in
#: coercion for why "Change owner: myself" is not an answer.
_FIRST_PERSON_RE = re.compile(
    r"^(me|myself|i|self|mine|my ?self|it'?s me|that'?s me|i am|i will|i'?ll do it|"
    r"i did|i have|i own it|own(ed)? by me)$",
    re.I,
)


@dataclass(slots=True)
class Extraction:
    """One candidate answer, before it is merged into a session."""

    field_id: str
    raw_value: str
    value: Any = None
    confidence: float = 0.0
    evidence: str = ""
    method: str = "llm"
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.value is not None


@dataclass(slots=True)
class ExtractionResult:
    """Everything one pass over a message produced."""

    extractions: list[Extraction] = dataclass_field(default_factory=list)
    #: Fields the speaker touched but left genuinely ambiguous.
    ambiguities: list[dict[str, str]] = dataclass_field(default_factory=list)
    #: Commitments stated in the message ("I'll get the budget by Friday").
    action_items: list[dict[str, str]] = dataclass_field(default_factory=list)
    #: The speaker explicitly declined these.
    declined: list[str] = dataclass_field(default_factory=list)

    def accepted(self) -> list[Extraction]:
        return [e for e in self.extractions if e.ok]

    def rejected(self) -> list[Extraction]:
        return [e for e in self.extractions if not e.ok]


_EXTRACTION_SYSTEM = """\
You extract structured form data from unstructured conversation — chat turns, \
ticket comments, email threads, and meeting transcripts.

Rules:
- Only extract what the text actually supports. Never invent a plausible value.
- Report values exactly as the speaker expressed them. Do not normalise or \
reformat; a separate deterministic step handles that.
- `evidence` must be a verbatim span copied from the message, not a paraphrase.
- Set `confidence` honestly. Use above 0.85 only when the speaker stated the \
value directly for this field. Use 0.4-0.7 when you are inferring from context.
- If a speaker addresses a field but is genuinely unsure ("not decided yet", \
"need to check with legal"), report it under `ambiguities`, not `extractions`.
- If a speaker explicitly declines a field ("skip that", "not relevant"), list \
its field_id under `declined`.
- Capture commitments people make as `action_items`: who will do what, by when.
- A single sentence can answer several fields. Extract all of them.
- Fields marked "explicit only" must be stated directly; do not infer them.
- Everything else may be inferred when the speaker's own words clearly entail \
it — "taking the whole platform down for four hours" entails that customers are \
affected. Extract it at 0.4-0.7 with the entailing span as `evidence`. The \
platform reads a value back for confirmation before recording it, so a \
well-grounded inference costs the speaker one word; making them restate what \
they just said costs a whole turn and reads as though nobody was listening.
- Inference means *entailed by this message*, not *typical of changes like \
this*. If you are reasoning from what usually happens rather than from what was \
said, it is an ambiguity, not an extraction.\
"""

#: The extraction contract. Values are strings across the board — coercion to
#: the declared type happens deterministically afterwards, which is far more
#: reliable than asking a model for polymorphic JSON.
EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "extractions": {
            "type": "array",
            "description": "Values the message supports.",
            "items": {
                "type": "object",
                "properties": {
                    "field_id": {"type": "string"},
                    "value": {
                        "type": "string",
                        "description": "The value as the speaker expressed it.",
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "evidence": {
                        "type": "string",
                        "description": "Verbatim span from the message supporting this value.",
                    },
                },
                "required": ["field_id", "value", "confidence", "evidence"],
                "additionalProperties": False,
            },
        },
        "ambiguities": {
            "type": "array",
            "description": "Fields the speaker raised but left unresolved.",
            "items": {
                "type": "object",
                "properties": {
                    "field_id": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["field_id", "reason"],
                "additionalProperties": False,
            },
        },
        "declined": {
            "type": "array",
            "description": "field_ids the speaker explicitly refused or marked not applicable.",
            "items": {"type": "string"},
        },
        "action_items": {
            "type": "array",
            "description": "Commitments made in the message.",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "owner": {"type": "string"},
                    "due_date": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["description"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["extractions"],
    "additionalProperties": False,
}


class ExtractionEngine:
    """Extracts field answers from messages."""

    def __init__(self, llm_provider: Any | None = None) -> None:
        self._llm = llm_provider

    def _provider(self) -> Any:
        if self._llm is None:
            from sa_connectors.llm import build_provider

            self._llm = build_provider()
        return self._llm

    # -- public API -------------------------------------------------------
    async def extract(
        self,
        form: FormDefinition,
        message: SourceMessage,
        *,
        target_fields: list[str] | None = None,
        known_values: dict[str, Any] | None = None,
        context: str = "",
    ) -> ExtractionResult:
        """Extract answers from one message.

        ``target_fields`` narrows the schema to fields still outstanding. That
        keeps the prompt small, and stops the model re-reporting settled fields
        from conversational echoes.
        """
        candidates = self._candidate_fields(form, target_fields)
        if not candidates:
            return ExtractionResult()

        with tracer.span(
            "forms.extract", form=form.name, fields=len(candidates), channel=message.channel.value
        ) as span:
            result = ExtractionResult()

            # Pass 1 — deterministic.
            settled = self._deterministic_pass(candidates, message, result)
            remaining = [f for f in candidates if f.id not in settled]
            span.set_attribute("pattern_hits", len(settled))

            # Pass 2 — semantic, only for what is left.
            if remaining and message.text.strip():
                await self._semantic_pass(
                    form, remaining, message, result, known_values or {}, context
                )

            span.set_attribute("extracted", len(result.accepted()))
            metrics.increment("forms.extractions", form=form.name)
            metrics.observe("forms.extracted_fields", len(result.accepted()), form=form.name)
            return result

    @staticmethod
    def _candidate_fields(form: FormDefinition, target_fields: list[str] | None) -> list[FormField]:
        if target_fields is None:
            return form.fields()
        wanted = set(target_fields)
        return [f for f in form.fields() if f.id in wanted]

    # -- pass 1: deterministic --------------------------------------------
    def _deterministic_pass(
        self,
        fields: list[FormField],
        message: SourceMessage,
        result: ExtractionResult,
    ) -> set[str]:
        """Match explicit labels and high-precision patterns.

        Returns the ids settled here so the semantic pass can skip them.
        """
        settled: set[str] = set()
        text = message.text

        for field in fields:
            labelled = self._match_labelled(field, text)
            if labelled is not None:
                self._add(
                    result,
                    field,
                    labelled,
                    _LABELLED_CONFIDENCE,
                    labelled,
                    "pattern",
                    speaker=message.author,
                )
                settled.add(field.id)
                continue

            # Patterns only fire for types where the format is unambiguous and
            # the field is the only plausible home for that shape.
            pattern = {
                FieldType.EMAIL: _EMAIL_RE,
                FieldType.URL: _URL_RE,
                FieldType.DATE: _ISO_DATE_RE,
            }.get(field.type)
            if pattern is None or field.require_explicit:
                continue

            matches = pattern.findall(text)
            # One match is a signal; several means we cannot tell which is meant.
            if len(matches) == 1:
                self._add(
                    result,
                    field,
                    matches[0],
                    _PATTERN_CONFIDENCE,
                    matches[0],
                    "pattern",
                    speaker=message.author,
                )
                settled.add(field.id)

        return settled

    @staticmethod
    def _match_labelled(field: FormField, text: str) -> str | None:
        """Find an explicit ``Label: value`` line.

        This is how ticket comments and email bodies usually carry structure,
        so it is worth matching precisely before reaching for a model.
        """
        names = [field.label, field.id.replace("_", " "), *field.aliases]
        for name in names:
            escaped = re.escape(name.strip())
            # Tolerate markdown bold/bullets around the label.
            pattern = rf"(?im)^[\s>*\-•]*\**{escaped}\**\s*[:=]\s*(.+?)\s*$"
            match = re.search(pattern, text)
            if match:
                value = match.group(1).strip().strip("*_`")
                if value and not is_null_token(value):
                    return value
        return None

    @staticmethod
    def _resolve_first_person(field: FormField, raw: str, speaker: str) -> str:
        """Turn "me" into the speaker's identity for a person field.

        The speaker knows who they are; the artifact's reader, weeks later, does
        not. Substituting here — rather than rejecting outright — means the
        common case ("owner? me") costs the user nothing while still producing a
        record that names somebody.
        """
        if field.type is not FieldType.PERSON:
            return raw
        if not _FIRST_PERSON_RE.match(raw.strip()):
            return raw
        named = speaker.strip()
        if not named or named.lower() in _ANONYMOUS_AUTHORS:
            return raw  # coercion rejects it, and the engine asks for a name
        return named

    def _add(
        self,
        result: ExtractionResult,
        field: FormField,
        raw: str,
        confidence: float,
        evidence: str,
        method: str,
        *,
        speaker: str = "",
    ) -> None:
        """Coerce and record one candidate.

        A coercion failure is kept, not dropped: the conversation engine turns
        it into a targeted clarifying question, which is far more useful than
        silently losing what the user said.
        """
        raw = self._resolve_first_person(field, raw, speaker)

        # A date the speaker did not fully write out is an answer, but not one
        # to act on unread. Accept it, then confirm the resolution out loud.
        if date_is_inferred(field, raw):
            confidence = min(confidence, _INFERRED_DATE_CONFIDENCE)

        extraction = Extraction(
            field_id=field.id,
            raw_value=raw,
            confidence=confidence,
            evidence=evidence[:500],
            method=method,
        )
        try:
            extraction.value = coerce_and_validate(field, raw)
            if extraction.value is None:
                extraction.error = "resolved to an empty value"
        except CoercionError as exc:
            extraction.error = exc.message
            logger.debug(
                "extraction failed coercion",
                extra={"field": field.id, "raw": raw[:80], "error": exc.message},
            )
        result.extractions.append(extraction)

    # -- pass 2: semantic --------------------------------------------------
    async def _semantic_pass(
        self,
        form: FormDefinition,
        fields: list[FormField],
        message: SourceMessage,
        result: ExtractionResult,
        known_values: dict[str, Any],
        context: str,
    ) -> None:
        from sa_connectors.llm.base import Message

        prompt = self._build_prompt(form, fields, message, known_values, context)
        try:
            raw = await self._provider().complete_structured(
                [Message.user(prompt)], EXTRACTION_SCHEMA, system=_EXTRACTION_SYSTEM
            )
        except Exception as exc:  # noqa: BLE001 - extraction is best-effort
            # A model outage must not lose the message. The deterministic hits
            # stand, and the conversation continues with what it has.
            logger.error(
                "semantic extraction failed",
                extra={"form": form.name, "error": str(exc)},
            )
            metrics.increment("forms.extraction_errors", form=form.name)
            return

        by_id = {f.id: f for f in fields}

        for item in raw.get("extractions", []) or []:
            field = by_id.get(item.get("field_id", ""))
            if field is None:
                continue  # hallucinated or already-settled field id
            value = str(item.get("value", "")).strip()
            if not value or is_null_token(value):
                continue
            confidence = float(item.get("confidence", 0.5))
            # An "explicit only" field cannot be satisfied by inference, so a
            # low-confidence hit is discarded rather than proposed.
            if field.require_explicit and confidence < 0.85:
                result.ambiguities.append(
                    {
                        "field_id": field.id,
                        "reason": "stated indirectly; this field needs an explicit answer",
                    }
                )
                continue
            self._add(
                result,
                field,
                value,
                confidence,
                str(item.get("evidence", "")),
                "llm",
                speaker=message.author,
            )

        for item in raw.get("ambiguities", []) or []:
            if item.get("field_id") in by_id:
                result.ambiguities.append(
                    {"field_id": item["field_id"], "reason": str(item.get("reason", ""))}
                )

        result.declined.extend([fid for fid in (raw.get("declined") or []) if fid in by_id])

        for item in raw.get("action_items", []) or []:
            description = str(item.get("description", "")).strip()
            if description:
                result.action_items.append(
                    {
                        "description": description,
                        "owner": str(item.get("owner", "") or message.author),
                        "due_date": str(item.get("due_date", "")),
                        "evidence": str(item.get("evidence", "")),
                    }
                )

    def _build_prompt(
        self,
        form: FormDefinition,
        fields: list[FormField],
        message: SourceMessage,
        known_values: dict[str, Any],
        context: str,
    ) -> str:
        lines = [
            f"# Form: {form.title}",
            form.description or "",
            "",
            "## Fields to look for",
        ]
        for field in fields:
            marker = "REQUIRED" if field.is_mandatory else field.importance.value
            explicit = " [explicit only]" if field.require_explicit else ""
            lines.append(f"- `{field.id}` — {field.prompt_descriptor()} ({marker}){explicit}")

        if known_values:
            lines += [
                "",
                "## Already known (do not re-extract unless the speaker is correcting them)",
                *[f"- `{k}`: {v}" for k, v in list(known_values.items())[:40]],
            ]

        if context:
            lines += ["", "## Recent conversation context", context]

        lines += [
            "",
            "## Message to extract from",
            f"Channel: {message.channel.value} | Author: {message.author}",
            "```",
            message.text[:12000],
            "```",
        ]
        return "\n".join(line for line in lines if line is not None)


# ---------------------------------------------------------------------------
# Merging extractions into a session
# ---------------------------------------------------------------------------


def merge_into_session(
    session: Any,
    form: FormDefinition,
    result: ExtractionResult,
    message: SourceMessage,
) -> dict[str, list[str]]:
    """Fold an :class:`ExtractionResult` into a session's answers.

    Returns a summary of what changed, which the conversation engine uses to
    decide what to say next.

    Precedence rules, in order:

    * A human confirmation is never overwritten by a later extraction.
    * A higher-confidence extraction supersedes a lower-confidence one.
    * An equal-or-lower-confidence extraction of a *different* value is recorded
      as a conflict for the user to resolve, not silently applied.
    """
    changed: dict[str, list[str]] = {
        "accepted": [],
        "proposed": [],
        "conflicts": [],
        "rejected": [],
        "declined": [],
    }

    for extraction in result.extractions:
        field = form.try_field(extraction.field_id)
        if field is None:
            continue
        answer = session.answer_for(field.id)

        if not extraction.ok:
            changed["rejected"].append(field.id)
            answer.note = extraction.error or ""
            # Hold what they said even though it could not be stored. A value
            # rejected for one missing detail — a timezone, say — is repairable
            # from the next message without making them type it all again.
            if not answer.is_settled:
                answer.raw_value = extraction.raw_value
            continue

        # A human already confirmed this; a model does not get to overrule it.
        if answer.state is AnswerState.CONFIRMED and extraction.method != "user_confirmed":
            if answer.value != extraction.value:
                changed["conflicts"].append(field.id)
            continue

        if answer.is_settled and answer.value == extraction.value:
            continue  # same answer restated; nothing to do

        # A restatement at the same confidence is a correction, and the later
        # one wins. Requiring it to be *more* confident than the original is
        # how "14 hours, for the whole window" got filed as a conflict against
        # "12 hours" and silently dropped — the participant answered the
        # question and the answer went nowhere. Only a genuinely weaker claim
        # is held back for them to resolve.
        if answer.is_settled and extraction.confidence < answer.confidence:
            changed["conflicts"].append(field.id)
            continue

        state = (
            AnswerState.ANSWERED
            if extraction.confidence >= field.confidence_threshold
            else AnswerState.PROPOSED
        )
        answer.supersede_with(
            extraction.value,
            raw_value=extraction.raw_value,
            state=state,
            confidence=extraction.confidence,
            provenance=Provenance(
                channel=message.channel,
                author=message.author,
                message_id=message.id,
                external_url=message.external_url,
                # Never copy evidence for a sensitive field into the record.
                evidence="" if field.sensitive else extraction.evidence,
                extracted_at=time.time(),
                method=extraction.method,
            ),
        )
        changed["accepted" if state is AnswerState.ANSWERED else "proposed"].append(field.id)

    for field_id in result.declined:
        field = form.try_field(field_id)
        if field is None:
            continue
        answer = session.answer_for(field_id)
        if not answer.is_settled:
            answer.state = AnswerState.SKIPPED
            answer.note = "declined by the participant"
            answer.updated_at = time.time()
        if field_id not in session.skipped_fields:
            session.skipped_fields.append(field_id)
        changed["declined"].append(field_id)

    session.touch()
    return changed


__all__ = [
    "EXTRACTION_SCHEMA",
    "Extraction",
    "ExtractionEngine",
    "ExtractionResult",
    "merge_into_session",
]
