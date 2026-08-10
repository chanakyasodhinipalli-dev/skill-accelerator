"""Gap analysis — what still needs asking.

This module is why the conversation is not a hardcoded question list. Nothing
here knows any specific form: it reads the definition, reads what the session
has learned, and computes the outstanding set.

It answers *what may be asked*. :mod:`sa_forms.topics` answers *what belongs in
one question*, and the conversation engine phrases whatever the two agree on.
People answer "tell me about the rollout" far more completely than they answer
eleven separate questions about it, and one open question routinely settles
several fields at once.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field as dataclass_field

from sa_orchestrator.expressions import evaluate_condition
from sa_platform.logging import get_logger

from .models import (
    AnswerState,
    FormDefinition,
    FormField,
    FormSection,
    FormSession,
    Importance,
)
from .topics import Topic, plan

logger = get_logger(__name__)


@dataclass(slots=True)
class FieldGap:
    """One outstanding field and why it is outstanding."""

    field: FormField
    section: FormSection
    reason: str  # unanswered | needs_confirmation | invalid

    @property
    def is_blocking(self) -> bool:
        return self.field.is_mandatory and self.reason != "needs_confirmation"


@dataclass(slots=True)
class Completeness:
    """A full picture of where a session stands."""

    total_fields: int = 0
    mandatory_total: int = 0
    mandatory_answered: int = 0
    recommended_total: int = 0
    recommended_answered: int = 0
    optional_answered: int = 0
    answered_total: int = 0
    skipped: int = 0

    #: Required agreements, and how many have been accepted. Counted here
    #: because for an agreement form they *are* the progress, and for an intake
    #: form "all the fields are in but nobody has confirmed anything" is a state
    #: worth being able to see.
    agreements_required: int = 0
    agreements_accepted: int = 0
    agreements_declined: list[str] = dataclass_field(default_factory=list)

    gaps: list[FieldGap] = dataclass_field(default_factory=list)
    confirmations: list[FieldGap] = dataclass_field(default_factory=list)
    #: Fields not asked because their `ask_when` condition is false.
    inactive: list[str] = dataclass_field(default_factory=list)

    @property
    def mandatory_complete(self) -> bool:
        """True when no *field* blocks producing the artifact.

        Deliberately about fields only. Agreements gate the document through
        their own check, which runs at each stage and at render, and folding
        them in here would make a before-review confirmation look like an
        unanswered question all the way through the conversation.
        """
        return self.mandatory_answered >= self.mandatory_total

    @property
    def agreements_complete(self) -> bool:
        return self.agreements_accepted >= self.agreements_required

    @property
    def finished(self) -> bool:
        """Everything this form needs: its fields answered and its terms decided.

        What "complete" means for an agreement form, where the field counts are
        both zero and `mandatory_complete` is therefore trivially true.
        """
        return self.mandatory_complete and self.agreements_complete

    @property
    def is_complete(self) -> bool:
        """Mandatory closed *and* nothing left worth probing for."""
        return self.mandatory_complete and not self.gaps

    @property
    def mandatory_percent(self) -> float:
        if self.mandatory_total == 0:
            return 100.0
        return round(100.0 * self.mandatory_answered / self.mandatory_total, 1)

    @property
    def overall_percent(self) -> float:
        if self.total_fields == 0:
            return 100.0
        return round(100.0 * self.answered_total / self.total_fields, 1)

    def blocking_gaps(self) -> list[FieldGap]:
        return [g for g in self.gaps if g.is_blocking]

    def summary(self) -> dict[str, object]:
        return {
            "mandatory_complete": self.mandatory_complete,
            "agreements_complete": self.agreements_complete,
            "finished": self.finished,
            "agreements": f"{self.agreements_accepted}/{self.agreements_required}",
            "agreements_declined": self.agreements_declined,
            "mandatory": f"{self.mandatory_answered}/{self.mandatory_total}",
            "recommended": f"{self.recommended_answered}/{self.recommended_total}",
            "overall_percent": self.overall_percent,
            "outstanding_mandatory": [g.field.id for g in self.blocking_gaps()],
            "outstanding_recommended": [
                g.field.id for g in self.gaps if g.field.importance is Importance.RECOMMENDED
            ],
            "needs_confirmation": [g.field.id for g in self.confirmations],
            "skipped": self.skipped,
        }


#: Field references inside an `ask_when` guard, e.g. `${answers.risk_level != 'low'}`.
_GUARD_REFERENCE = re.compile(r"answers\.([a-z][a-z0-9_]*)")


def is_field_active(field: FormField, session: FormSession) -> bool:
    """Evaluate a field's ``ask_when`` guard against what we know so far.

    A conditional field that is not active is not a gap — asking about disaster
    recovery when the user already said the system is non-critical is exactly
    the kind of noise this whole design exists to remove.

    A guard whose inputs are all still unanswered is treated as **not yet
    active**. Evaluating it would be meaningless, and the result would depend on
    the operator used: ``== true`` on a missing answer is false and stays quiet,
    while ``!= 'low'`` on the same missing answer is true and would ask about
    mitigation before anyone had said what the risk is. Deferring until the
    guard can actually be decided makes both behave the same way.
    """
    if not field.ask_when:
        return True

    values = session.all_values()
    referenced = set(_GUARD_REFERENCE.findall(field.ask_when))
    if referenced and not (referenced & values.keys()):
        return False

    scope = {"answers": values, "inputs": values}
    try:
        return evaluate_condition(field.ask_when, scope)
    except Exception as exc:  # noqa: BLE001 - a bad guard must not hide the field
        logger.warning(
            "field ask_when guard failed to evaluate; treating the field as active",
            extra={"field": field.id, "expression": field.ask_when, "error": str(exc)},
        )
        return True


def analyse(form: FormDefinition, session: FormSession) -> Completeness:
    """Compute the outstanding work for a session."""
    report = Completeness()

    # Counted from the session's own records, not from what is due — a stage
    # nobody has reached yet is still work this form has not finished.
    for agreement in form.agreements:
        if not agreement.required:
            continue
        report.agreements_required += 1
        decision = session.agreement_record(agreement.id, agreement.version)
        if decision is None:
            continue
        if decision.accepted:
            report.agreements_accepted += 1
        else:
            report.agreements_declined.append(agreement.id)

    for section in form.ordered_sections():
        for field in section.fields:
            if not is_field_active(field, session):
                report.inactive.append(field.id)
                continue

            report.total_fields += 1
            if field.importance is Importance.MANDATORY:
                report.mandatory_total += 1
            elif field.importance is Importance.RECOMMENDED:
                report.recommended_total += 1

            answer = session.answers.get(field.id)
            state = answer.state if answer else AnswerState.EMPTY

            if state in (AnswerState.ANSWERED, AnswerState.CONFIRMED):
                report.answered_total += 1
                if field.importance is Importance.MANDATORY:
                    report.mandatory_answered += 1
                elif field.importance is Importance.RECOMMENDED:
                    report.recommended_answered += 1
                else:
                    report.optional_answered += 1
                continue

            if state in (AnswerState.SKIPPED, AnswerState.NOT_APPLICABLE):
                report.skipped += 1
                # A skipped mandatory field still cannot count as answered, but
                # it must not be re-asked either. It becomes an action item at
                # completion instead.
                continue

            if state is AnswerState.PROPOSED:
                report.confirmations.append(
                    FieldGap(field=field, section=section, reason="needs_confirmation")
                )
                continue

            reason = "invalid" if (answer and answer.note) else "unanswered"
            report.gaps.append(FieldGap(field=field, section=section, reason=reason))

    return report


def next_topic(
    form: FormDefinition,
    completeness: Completeness,
    *,
    max_fields: int = 4,
    stalled: set[str] | frozenset[str] = frozenset(),
    recently_settled: list[str] | None = None,
) -> tuple[Topic, list[FormField]] | None:
    """Choose the next topic to open and the fields to cover in it.

    This function decides **eligibility**; :mod:`sa_forms.topics` decides
    **grouping**. The split matters: what may be asked is a property of the
    session's state, and what belongs in one breath is a property of the form's
    shape, and mixing them is what produced a conversation that walked the
    sections in file order.

    Eligibility, in order:

    1. Outstanding **mandatory** fields, if there are any.
    2. Otherwise **recommended** ones, then optional.
    3. ``stalled`` fields — already put to the participant twice with no answer
       — drop out while anything else is outstanding. Somebody who has passed
       over a question twice is telling you something, and a third rephrasing
       reads as an interrogation. They still block completion and still become
       action items; they just stop setting the agenda.

    ``recently_settled`` lets a strongly-related follow-up jump the author's
    order: answering "customers are affected" should be followed by "who tells
    them?", not by whatever the next section happens to hold.

    Returns the topic and its fields. The tuple is redundant — ``topic.fields``
    is the same list — and is kept because every caller wants both names.
    """
    if not completeness.gaps:
        return None

    blocking = completeness.blocking_gaps()
    pool = (
        blocking
        or [g for g in completeness.gaps if g.field.importance is not Importance.OPTIONAL]
        or completeness.gaps
    )
    pool = [g for g in pool if g.field.id not in stalled] or pool

    topic = plan(
        form,
        [(g.field, g.section) for g in pool],
        max_fields=max_fields,
        recently_settled=recently_settled or [],
    )
    if topic is None:
        return None
    return topic, topic.fields


def unresolved_mandatory(form: FormDefinition, session: FormSession) -> list[FormField]:
    """Mandatory fields that were skipped or left empty.

    These become action items when a session is finalised — the form records
    what is missing rather than pretending it is complete.
    """
    outstanding: list[FormField] = []
    for field in form.mandatory_fields():
        if not is_field_active(field, session):
            continue
        answer = session.answers.get(field.id)
        if answer is None or answer.state not in (AnswerState.ANSWERED, AnswerState.CONFIRMED):
            outstanding.append(field)
    return outstanding


def progress_line(completeness: Completeness) -> str:
    """A short status string for the user, e.g. after 'how far along are we?'."""
    # An agreement form has no fields to count, so counting them says "100%"
    # about a document nobody has agreed to anything on.
    if completeness.total_fields == 0 and completeness.agreements_required:
        remaining = completeness.agreements_required - completeness.agreements_accepted
        if completeness.agreements_declined:
            return (
                f"{completeness.agreements_accepted} of "
                f"{completeness.agreements_required} accepted, "
                f"{len(completeness.agreements_declined)} declined."
            )
        if remaining <= 0:
            return "Everything here has been agreed."
        return (
            f"{completeness.agreements_accepted} of {completeness.agreements_required} "
            f"agreed; {remaining} left."
        )

    if completeness.is_complete and completeness.agreements_complete:
        return "Everything needed is captured."
    if completeness.mandatory_complete:
        remaining = len(completeness.gaps)
        return (
            f"All {completeness.mandatory_total} required fields are captured. "
            f"{remaining} optional item(s) left if you want to cover them."
        )
    return (
        f"{completeness.mandatory_answered} of {completeness.mandatory_total} required fields "
        f"captured ({completeness.mandatory_percent:.0f}%)."
    )


__all__ = [
    "Completeness",
    "FieldGap",
    "Topic",
    "analyse",
    "is_field_active",
    "next_topic",
    "progress_line",
    "unresolved_mandatory",
]
