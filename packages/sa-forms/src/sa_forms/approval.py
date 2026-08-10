"""Review, approval, and baselining.

The lifecycle a submission moves through::

    collecting → ready_for_review → in_review → approved → baselined
                                        ↓
                                changes_requested → (back to collecting)

Two rules carry most of the weight:

* **A baseline is immutable.** Once baselined, the session is locked, its
  checksum is recorded, and any later change starts a new revision. That is what
  "baseline" has to mean for the document to be worth anything.
* **Contributors cannot approve their own submission** unless the form's policy
  explicitly allows it. Self-approval is the failure mode that makes an approval
  step decorative.
"""

from __future__ import annotations

import time
from typing import Any

from sa_platform.context import ExecutionContext, current_context
from sa_platform.errors import AuthorizationError, NotFoundError, ValidationError
from sa_platform.events import event_bus
from sa_platform.logging import get_logger
from sa_platform.telemetry import metrics

from .actions import derive_action_items
from .agreements import blocking_up_to as agreements_blocking_up_to
from .completeness import analyse
from .consistency import blocking as consistency_blocking
from .models import (
    AgreementStage,
    Approval,
    ArtifactRecord,
    ArtifactStatus,
    FormDefinition,
    FormSession,
    SessionStatus,
)
from .registry import FormRegistry, form_registry
from .rendering import render_session
from .store import ArtifactStore, InMemoryArtifactStore, SessionStore, utc_stamp

logger = get_logger(__name__)


class FormsEvents:
    """Event names emitted by the approval flow."""

    SUBMITTED = "forms.submitted"
    ARTIFACT_RENDERED = "forms.artifact_rendered"
    APPROVED = "forms.approved"
    REJECTED = "forms.rejected"
    BASELINED = "forms.baselined"


class ApprovalService:
    """Owns the review → approve → baseline transition."""

    def __init__(
        self,
        *,
        sessions: SessionStore,
        artifacts: ArtifactStore | None = None,
        registry: FormRegistry | None = None,
    ) -> None:
        self._sessions = sessions
        self._artifacts = artifacts if artifacts is not None else InMemoryArtifactStore()
        self._registry = registry if registry is not None else form_registry

    @property
    def artifacts(self) -> ArtifactStore:
        return self._artifacts

    # -- rendering --------------------------------------------------------
    async def generate(
        self,
        session_id: str,
        formats: list[str] | None = None,
        *,
        ctx: ExecutionContext | None = None,
        include_provenance: bool = True,
        allow_incomplete: bool = False,
    ) -> list[ArtifactRecord]:
        """Render the submission and move it into review.

        Refuses by default when mandatory fields are open. ``allow_incomplete``
        overrides that for a deliberate interim draft — the artifact then
        carries the gaps as action items, so an incomplete document is always
        visibly incomplete.
        """
        ctx = ctx or current_context()
        session = await self._sessions.load(session_id)
        form = self._registry.get(session.form_name, session.form_version)

        if session.status is SessionStatus.BASELINED:
            raise ValidationError(
                f"session '{session_id}' is baselined; start a revision to change it",
                details={"session_id": session_id},
            )

        completeness = analyse(form, session)
        if not completeness.mandatory_complete and not allow_incomplete:
            raise ValidationError(
                f"{len(completeness.blocking_gaps())} required field(s) are still open",
                details={
                    "session_id": session_id,
                    "outstanding": [g.field.id for g in completeness.blocking_gaps()],
                },
            )

        # Consent is not a completeness question and `allow_incomplete` does not
        # reach it. An interim draft of a submission is a legitimate thing to
        # want; a document produced under terms nobody accepted is not, and the
        # flag that permits the first must not quietly permit the second.
        unagreed = agreements_blocking_up_to(form, session, AgreementStage.BEFORE_GENERATE)
        if unagreed:
            raise ValidationError(
                f"{len(unagreed)} required agreement(s) have not been accepted",
                details={
                    "session_id": session_id,
                    "agreements": [
                        {"id": a.id, "title": a.title, "stage": a.stage.value} for a in unagreed
                    ],
                },
            )

        # A blocking contradiction is the same class of problem as a missing
        # mandatory field: the document would be internally false rather than
        # merely incomplete. It is only evaluated here, never re-derived — the
        # conversation raises it, and the participant either fixes it or stands
        # by it on the record.
        halting = consistency_blocking(session)
        if halting and not allow_incomplete:
            raise ValidationError(
                f"{len(halting)} unresolved contradiction(s) in this submission",
                details={
                    "session_id": session_id,
                    "findings": [{"id": f.id, "message": f.message} for f in halting],
                },
            )

        # Action items are settled at completion, not during the conversation:
        # this is the moment the record has to state what is still missing.
        session.action_items = derive_action_items(form, session, session.action_items)

        chosen = formats or form.output_formats
        records: list[ArtifactRecord] = []
        revision = await self._next_revision(session_id)

        for fmt in chosen:
            try:
                content, filename, media_type = render_session(
                    form, session, fmt, include_provenance=include_provenance
                )
            except Exception as exc:  # noqa: BLE001 - one bad format must not block the rest
                logger.error(
                    "artifact rendering failed",
                    extra={"session": session_id, "format": fmt, "error": str(exc)},
                )
                continue

            record = ArtifactRecord(
                session_id=session.id,
                form_name=form.name,
                form_version=form.version,
                format=fmt,
                filename=f"{form.name}_{utc_stamp()}_r{revision}.{filename.rsplit('.', 1)[-1]}",
                revision=revision,
                status=ArtifactStatus.IN_REVIEW,
                created_by=ctx.principal.subject,
                metadata={
                    "media_type": media_type,
                    "incomplete": not completeness.mandatory_complete,
                },
            )
            records.append(await self._artifacts.put(record, content))

        if not records:
            raise ValidationError(
                "no artifact could be produced; none of the requested formats are available",
                details={"session_id": session_id, "requested": chosen},
            )

        # Supersede the previous revision so only one set is ever current.
        await self._supersede_older(session_id, revision)

        session.artifacts.extend(r.id for r in records)
        session.status = SessionStatus.IN_REVIEW
        await self._sessions.save(session)

        metrics.increment("forms.artifacts_generated", form=form.name)
        await event_bus.emit(
            FormsEvents.ARTIFACT_RENDERED,
            session_id=session.id,
            form=form.qualified_name,
            formats=[r.format for r in records],
            revision=revision,
        )
        logger.info(
            "generated artifacts",
            extra={
                "session": session.id,
                "revision": revision,
                "formats": [r.format for r in records],
            },
        )
        return records

    async def _next_revision(self, session_id: str) -> int:
        existing = await self._artifacts.list_artifacts(session_id=session_id, limit=500)
        return max((r.revision for r in existing), default=0) + 1

    async def _supersede_older(self, session_id: str, current_revision: int) -> None:
        for record in await self._artifacts.list_artifacts(session_id=session_id, limit=500):
            if record.revision < current_revision and record.status not in (
                ArtifactStatus.BASELINED,
                ArtifactStatus.SUPERSEDED,
            ):
                record.status = ArtifactStatus.SUPERSEDED
                await self._artifacts.update(record)

    # -- approval ---------------------------------------------------------
    async def decide(
        self,
        artifact_id: str,
        decision: str,
        *,
        approver: str | None = None,
        comment: str = "",
        ctx: ExecutionContext | None = None,
    ) -> ArtifactRecord:
        """Record an approve or reject decision.

        Baselines automatically once the form's required approval count is met.
        """
        ctx = ctx or current_context()

        if decision not in ("approved", "rejected"):
            raise ValidationError(
                f"decision must be 'approved' or 'rejected', got '{decision}'",
                details={"decision": decision},
            )

        # Recording a decision under someone else's name is a distinct, more
        # privileged act than approving as yourself: without this check a caller
        # could attribute their own approval to a colleague, and the role check
        # below would silently validate the *caller's* permissions against the
        # *other person's* recorded name.
        who = approver or ctx.principal.subject
        on_behalf = bool(approver) and approver != ctx.principal.subject
        if on_behalf and not ctx.principal.has_permission("forms:approve:on_behalf"):
            raise AuthorizationError(
                f"'{ctx.principal.subject}' may not record a decision on behalf of '{approver}'",
                details={
                    "caller": ctx.principal.subject,
                    "claimed_approver": approver,
                    "required_permission": "forms:approve:on_behalf",
                },
            )

        record = await self._artifacts.get(artifact_id)
        session = await self._sessions.load(record.session_id)
        form = self._registry.get(record.form_name, record.form_version)
        policy = form.approval

        if record.status is ArtifactStatus.BASELINED:
            raise ValidationError(
                f"artifact '{artifact_id}' is already baselined",
                details={"artifact_id": artifact_id},
            )
        if record.status is ArtifactStatus.SUPERSEDED:
            raise ValidationError(
                f"artifact '{artifact_id}' has been superseded by a newer revision",
                details={"artifact_id": artifact_id, "revision": record.revision},
            )

        if not policy.allow_self_approval and who in session.participants:
            raise AuthorizationError(
                f"'{who}' contributed to this submission and cannot approve it",
                details={
                    "artifact_id": artifact_id,
                    "approver": who,
                    "contributors": session.participants,
                },
            )

        if policy.approver_roles and not any(
            ctx.principal.has_permission(f"forms:approve:{role}") for role in policy.approver_roles
        ):
            raise AuthorizationError(
                f"'{who}' does not hold an approver role for this form",
                details={"required_roles": policy.approver_roles, "approver": who},
            )

        if any(a.approver == who for a in record.approvals):
            raise ValidationError(
                f"'{who}' has already recorded a decision on this artifact",
                details={"artifact_id": artifact_id, "approver": who},
            )

        # Note who actually made the call when it was recorded on behalf of
        # someone else — the audit trail needs both names, not just the one
        # that appears on the document.
        if on_behalf:
            comment = f"{comment} (recorded by {ctx.principal.subject})".strip()
        record.approvals.append(Approval(approver=who, decision=decision, comment=comment))

        if decision == "rejected":
            record.status = ArtifactStatus.REJECTED
            session.status = (
                SessionStatus.CHANGES_REQUESTED
                if policy.reopen_on_rejection
                else SessionStatus.ABANDONED
            )
            metrics.increment("forms.rejected", form=form.name)
            await event_bus.emit(
                FormsEvents.REJECTED,
                session_id=session.id,
                artifact_id=record.id,
                approver=who,
                comment=comment,
            )
            logger.info(
                "artifact rejected",
                extra={"artifact": record.id, "approver": who, "session": session.id},
            )
        else:
            record.status = ArtifactStatus.APPROVED
            metrics.increment("forms.approved", form=form.name)
            await event_bus.emit(
                FormsEvents.APPROVED,
                session_id=session.id,
                artifact_id=record.id,
                approver=who,
                approvals=record.approval_count(),
                required=policy.required_approvals,
            )
            if record.approval_count() >= policy.required_approvals:
                await self._baseline(record, session, form)
            else:
                session.status = SessionStatus.APPROVED

        await self._artifacts.update(record)
        await self._sessions.save(session)
        return record

    async def _baseline(
        self, record: ArtifactRecord, session: FormSession, form: FormDefinition
    ) -> None:
        """Lock the artifact and the session.

        The checksum was computed when the bytes were stored; recording the
        baseline timestamp alongside it is what lets a later reader prove the
        document has not changed since sign-off.
        """
        record.status = ArtifactStatus.BASELINED
        record.baselined_at = time.time()
        session.status = SessionStatus.BASELINED

        metrics.increment("forms.baselined", form=form.name)
        await event_bus.emit(
            FormsEvents.BASELINED,
            session_id=session.id,
            artifact_id=record.id,
            form=form.qualified_name,
            checksum=record.checksum,
        )
        logger.info(
            "baselined artifact",
            extra={
                "artifact": record.id,
                "session": session.id,
                "form": form.qualified_name,
                "checksum": record.checksum[:16],
            },
        )

    # -- revisions --------------------------------------------------------
    async def reopen(
        self, session_id: str, *, reason: str = "", ctx: ExecutionContext | None = None
    ) -> FormSession:
        """Reopen a session for edits.

        A baselined session is never edited in place — its artifacts stay
        immutable and the next generate produces a new revision.
        """
        ctx = ctx or current_context()
        session = await self._sessions.load(session_id)

        if session.status is SessionStatus.COLLECTING:
            return session

        previous = session.status
        session.status = SessionStatus.COLLECTING
        session.mandatory_complete_announced = False
        session.metadata.setdefault("reopen_history", []).append(
            {
                "from": previous.value,
                "by": ctx.principal.subject,
                "reason": reason,
                "at": time.time(),
            }
        )
        await self._sessions.save(session)
        logger.info(
            "reopened session",
            extra={"session": session_id, "from": previous.value, "reason": reason},
        )
        return session

    async def verify_baseline(self, artifact_id: str) -> dict[str, Any]:
        """Confirm a baselined artifact's bytes still match its recorded checksum."""
        record = await self._artifacts.get(artifact_id)
        if not record.is_baselined:
            raise ValidationError(
                f"artifact '{artifact_id}' is not baselined",
                details={"artifact_id": artifact_id, "status": record.status.value},
            )
        content = await self._artifacts.read(artifact_id)
        actual = ArtifactStore.checksum(content)
        intact = actual == record.checksum
        if not intact:
            logger.error(
                "baseline checksum mismatch",
                extra={"artifact": artifact_id, "expected": record.checksum, "actual": actual},
            )
        return {
            "artifact_id": artifact_id,
            "intact": intact,
            "expected_checksum": record.checksum,
            "actual_checksum": actual,
            "baselined_at": record.baselined_at,
        }

    # -- queries ----------------------------------------------------------
    async def pending_reviews(self, limit: int = 50) -> list[ArtifactRecord]:
        records = await self._artifacts.list_artifacts(limit=500)
        pending = [r for r in records if r.status is ArtifactStatus.IN_REVIEW]
        return pending[:limit]

    async def baseline_for(self, session_id: str) -> ArtifactRecord | None:
        """The current baselined artifact for a session, if any."""
        records = await self._artifacts.list_artifacts(session_id=session_id, limit=500)
        baselined = [r for r in records if r.is_baselined]
        return max(baselined, key=lambda r: r.revision) if baselined else None

    async def get_artifact(self, artifact_id: str) -> ArtifactRecord:
        return await self._artifacts.get(artifact_id)

    async def read_artifact(self, artifact_id: str) -> bytes:
        return await self._artifacts.read(artifact_id)

    async def require_session(self, session_id: str) -> FormSession:
        session = await self._sessions.try_load(session_id)
        if session is None:
            raise NotFoundError(
                f"form session '{session_id}' was not found",
                details={"session_id": session_id},
            )
        return session


__all__ = ["ApprovalService", "FormsEvents"]
