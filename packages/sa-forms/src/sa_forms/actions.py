"""Action items.

Two sources, and the second is the one that matters:

1. **Commitments** people made during the conversation ("I'll confirm the
   budget with finance on Monday"). The extractor surfaces these per message.
2. **Unresolved fields.** A mandatory field that was skipped or never answered
   becomes an explicit open item on the artifact.

The second rule is what stops a form quietly shipping with holes in it. The
document says what is missing and who needs to close it, instead of presenting
an incomplete record as if it were complete.
"""

from __future__ import annotations

from sa_platform.logging import get_logger

from .completeness import unresolved_mandatory
from .models import (
    ActionItem,
    ActionItemStatus,
    AnswerState,
    ConsistencyFinding,
    FindingState,
    FormDefinition,
    FormSession,
    Importance,
)

logger = get_logger(__name__)


def derive_action_items(
    form: FormDefinition,
    session: FormSession,
    existing: list[ActionItem] | None = None,
) -> list[ActionItem]:
    """Return the full action item list for a session.

    Idempotent: calling it repeatedly as the conversation progresses updates the
    generated items rather than duplicating them, and closes any whose field has
    since been answered.
    """
    items = list(existing or [])

    # Conversation-sourced commitments are never touched here.
    keep: list[ActionItem] = [a for a in items if a.origin != "unresolved_field"]
    generated = {a.source_field_id: a for a in items if a.origin == "unresolved_field"}

    outstanding = {f.id: f for f in unresolved_mandatory(form, session)}

    for field_id, field in outstanding.items():
        answer = session.answers.get(field_id)
        skipped = answer is not None and answer.state is AnswerState.SKIPPED

        description = (
            f"Provide '{field.label}' — required by {form.title} and left blank"
            if skipped
            else f"Provide '{field.label}' — required by {form.title} and not yet answered"
        )
        if field.rationale:
            description += f". {field.rationale}"

        previous = generated.pop(field_id, None)
        if previous is not None:
            previous.description = description
            previous.status = ActionItemStatus.OPEN
            keep.append(previous)
        else:
            keep.append(
                ActionItem(
                    description=description,
                    owner=_likely_owner(session),
                    source_field_id=field_id,
                    origin="unresolved_field",
                    evidence=(answer.note if answer else ""),
                )
            )

    # Whatever is left in `generated` was raised earlier and is no longer
    # outstanding. Close it rather than deleting it: an approver reading the
    # record should see that a gap was flagged and then filled, not that it
    # never existed.
    for item in generated.values():
        if item.status is ActionItemStatus.OPEN:
            item.status = ActionItemStatus.DONE
        keep.append(item)

    return keep


def recommended_gaps_as_notes(form: FormDefinition, session: FormSession) -> list[str]:
    """Nice-to-have fields left blank.

    Recorded as notes on the artifact rather than action items — they did not
    block the submission and should not read as outstanding work.
    """
    notes: list[str] = []
    for field in form.fields():
        if field.importance is not Importance.RECOMMENDED:
            continue
        answer = session.answers.get(field.id)
        if answer is None or answer.state not in (AnswerState.ANSWERED, AnswerState.CONFIRMED):
            notes.append(f"{field.label} was not captured")
    return notes


def _likely_owner(session: FormSession) -> str | None:
    """Best guess at who should close a gap: whoever has been answering."""
    participants = [p for p in session.participants if p not in ("assistant", "system")]
    return participants[0] if participants else None


def open_items(session: FormSession) -> list[ActionItem]:
    return [a for a in session.action_items if a.status is ActionItemStatus.OPEN]


def noted_discrepancies(session: FormSession) -> list[ConsistencyFinding]:
    """Contradictions the owner was asked about and stood by, with their reason.

    These are not defects in the submission. "Low technical risk, high business
    impact" is a coherent pair once someone explains that the change itself is a
    config flag but the platform is down while it deploys. The explanation is
    what an approver would otherwise have to ask for, so it goes on the
    document beside the thing that prompted it.
    """
    return [
        f
        for f in session.consistency_findings
        if f.state is FindingState.ACKNOWLEDGED and f.resolution
    ]


__all__ = [
    "derive_action_items",
    "noted_discrepancies",
    "open_items",
    "recommended_gaps_as_notes",
]
