"""The forms service — one object that wires the pieces together.

Everything else in this package is a component with a single job. This is the
facade the API, the CLI, the skills, and the tools all call, so there is exactly
one place where the conversation engine, the stores, the renderers, and the
approval flow are composed.
"""

from __future__ import annotations

import os
from typing import Any

from sa_platform.context import ExecutionContext, current_context
from sa_platform.errors import NotFoundError, ValidationError
from sa_platform.logging import get_logger

from .approval import ApprovalService
from .authoring import FormAuthor, InferenceReport, apply_answers
from .conversation import ConversationEngine, TurnResult
from .ingestion import parse_payload
from .models import (
    AgreementStage,
    ArtifactRecord,
    FormDefinition,
    FormSession,
    FormStatus,
    SessionStatus,
    SourceChannel,
)
from .registry import FormRegistry, form_registry
from .store import (
    ArtifactStore,
    SessionStore,
    build_artifact_store,
    build_session_store,
)

logger = get_logger(__name__)


class FormsService:
    """Single entry point for conversational form intake."""

    def __init__(
        self,
        *,
        registry: FormRegistry | None = None,
        sessions: SessionStore | None = None,
        artifacts: ArtifactStore | None = None,
        store_backend: str | None = None,
        llm_provider: Any | None = None,
    ) -> None:
        # `memory` by default so a fresh process works with no configuration;
        # `file` survives a restart. A database backend implements the same two
        # interfaces and drops in here.
        backend = store_backend or os.environ.get("SA_FORMS__STORE_BACKEND", "memory")

        self.registry = registry if registry is not None else form_registry
        self.sessions = sessions if sessions is not None else build_session_store(backend)
        self.artifacts = artifacts if artifacts is not None else build_artifact_store(backend)

        self.conversation = ConversationEngine(
            registry=self.registry,
            session_store=self.sessions,
            llm_provider=llm_provider,
        )
        self.approval = ApprovalService(
            sessions=self.sessions, artifacts=self.artifacts, registry=self.registry
        )
        self.author = FormAuthor(llm_provider)
        self._llm = llm_provider
        self._assistant: Any = None

    # -- forms ------------------------------------------------------------
    def list_forms(self, *, include_inactive: bool = False) -> list[FormDefinition]:
        return self.registry.list_forms(include_inactive=include_inactive)

    def get_form(self, name: str, version: str | None = None) -> FormDefinition:
        return self.registry.get(name, version)

    def create_form(self, definition: FormDefinition, *, activate: bool = False) -> FormDefinition:
        return self.registry.create(definition, activate=activate)

    def update_form(self, name: str, changes: dict[str, Any], **kwargs: Any) -> FormDefinition:
        return self.registry.update(name, changes, **kwargs)

    def activate_form(self, name: str, version: str) -> FormDefinition:
        return self.registry.activate(name, version)

    def delete_form(self, name: str, version: str | None = None, *, force: bool = False) -> None:
        self.registry.delete(name, version, force=force)

    def form_history(self, name: str) -> list[FormDefinition]:
        return self.registry.history(name)

    # -- authoring --------------------------------------------------------
    async def infer_form(
        self,
        content: bytes | str,
        *,
        filename: str = "sample.xlsx",
        form_name: str | None = None,
        register: bool = True,
    ) -> InferenceReport:
        """Build a draft form from an uploaded sample.

        Registered as a ``DRAFT``, never activated: the facilitator's questions
        should be answered before anyone fills it in.
        """
        report = await self.author.infer(content, filename=filename, form_name=form_name)

        if register:
            name = report.definition.name
            if name in self.registry:
                # Land alongside the existing versions rather than colliding.
                latest = self.registry.get(name)
                from .registry import next_version

                report.definition = report.definition.model_copy(
                    update={"version": next_version(latest.version, "minor")}
                )
            report.definition = self.registry.create(report.definition, activate=False)

        return report

    async def refine_form(
        self, name: str, instructions: str, *, version: str | None = None
    ) -> FormDefinition:
        """Apply a user's free-text corrections to a draft."""
        current = self.registry.get(name, version)
        if current.status is not FormStatus.DRAFT:
            raise ValidationError(
                f"form '{name}' v{current.version} is {current.status.value}; "
                "refine a draft, or update the form to fork a new one",
                details={"form": name, "version": current.version},
            )
        refined = await apply_answers(current, instructions, llm_provider=self._llm)
        return self.registry.update(
            name,
            refined.model_dump(mode="python", exclude={"name", "version", "status"}),
            version=current.version,
            change_note=instructions[:200],
        )

    # -- sessions ---------------------------------------------------------
    async def start_session(
        self,
        form_name: str,
        *,
        participant: str = "user",
        version: str | None = None,
        title: str = "",
        resume: bool = True,
        ctx: ExecutionContext | None = None,
    ) -> dict[str, Any]:
        session, greeting = await self.conversation.start(
            form_name,
            version=version,
            participant=participant,
            title=title,
            ctx=ctx or current_context(),
            resume_existing=resume,
        )
        return {
            "session_id": session.id,
            "form": f"{session.form_name}@{session.form_version}",
            "status": session.status.value,
            "message": greeting,
            "resumed": len(session.transcript) > 1,
        }

    async def send(
        self,
        session_id: str,
        message: str,
        *,
        author: str = "user",
        channel: SourceChannel | str = SourceChannel.CHAT,
        ctx: ExecutionContext | None = None,
    ) -> TurnResult:
        return await self.conversation.turn(
            session_id,
            message,
            author=author,
            channel=SourceChannel(channel) if isinstance(channel, str) else channel,
            ctx=ctx,
        )

    async def ingest(
        self,
        session_id: str,
        channel: SourceChannel | str,
        payload: Any,
        **adapter_kwargs: Any,
    ) -> dict[str, Any]:
        """Mine an external thread — JIRA comments, an email chain, a transcript."""
        messages = parse_payload(channel, payload, **adapter_kwargs)
        if not messages:
            return {
                "session_id": session_id,
                "messages_processed": 0,
                "captured": [],
                "next_message": "There was nothing usable in that thread.",
            }
        return await self.conversation.ingest(session_id, messages)

    async def ingest_email(
        self,
        session_id: str,
        raw: bytes | str,
        *,
        attachments: list[tuple[str, bytes]] | None = None,
    ) -> dict[str, Any]:
        """Mine an uploaded ``.eml`` file and everything attached to it.

        Attachments may arrive inside the MIME message or alongside it, because
        mail clients drop attachments on forward far more often than people
        expect and re-sending the mail is not always possible.

        The returned report names every attachment and whether its text could be
        read, so an unreadable file is visible rather than silently absent.
        """
        from .attachments import extract_attachment, parse_email
        from .ingestion import EmailFileSource

        parsed = parse_email(raw)
        for filename, content in attachments or []:
            parsed.attachments.append(extract_attachment(filename, content))

        messages = EmailFileSource().parse(parsed)
        if not messages:
            return {
                "session_id": session_id,
                "messages_processed": 0,
                "captured": [],
                "email": parsed.summary(),
                "next_message": "That email had no readable content.",
            }

        result = await self.conversation.ingest(session_id, messages)
        result["email"] = parsed.summary()
        return result

    async def get_session(self, session_id: str) -> FormSession:
        return await self.conversation.get_session(session_id)

    async def session_status(self, session_id: str) -> dict[str, Any]:
        return await self.conversation.status(session_id)

    async def list_sessions(self, **kwargs: Any) -> list[FormSession]:
        return await self.sessions.list_sessions(**kwargs)

    async def set_answer(
        self, session_id: str, field_id: str, value: Any, *, author: str = "user"
    ) -> FormSession:
        return await self.conversation.set_answer(session_id, field_id, value, author=author)

    # -- agreements --------------------------------------------------------
    async def agreements(self, session_id: str) -> dict[str, Any]:
        """Every agreement this form declares, and where each one stands."""
        from . import agreements as agreements_module

        session = await self.get_session(session_id)
        form = self.registry.get(session.form_name, session.form_version)
        return {
            "session_id": session.id,
            "agreements": agreements_module.summary(form, session),
            "outstanding": [
                {
                    "id": a.id,
                    "title": a.title,
                    "text": a.text,
                    "kind": a.kind.value,
                    "stage": a.stage.value,
                    "explanation": a.explanation,
                    "answers": [{"question": f.question, "answer": f.answer} for f in a.faqs],
                    # Undecided is not the same as askable. A caller offering a
                    # button for one that is not yet reachable is offering an
                    # attestation to a submission that does not exist.
                    "decidable": agreements_module.reachable(form, session, a.stage),
                }
                for stage in AgreementStage
                for a in agreements_module.outstanding(form, session, stage)
            ],
        }

    async def decide_agreements(
        self,
        session_id: str,
        agreement_ids: list[str],
        *,
        accept: bool,
        actor: str = "user",
        stated: str = "",
    ) -> dict[str, Any]:
        """Decide several agreements as one act, and speak once at the end.

        A caller that loops over `decide_agreement` gets a message back from
        each call, and each one announces the next term — so accepting two
        terms in a console produced the second term as a message and then
        immediately accepted it, leaving a transcript that puts the same
        agreement to the participant twice and answers itself. Deciding them
        together is both what the button means and what the record should say.
        """
        records = [
            await self.decide_agreement(
                session_id, agreement_id, accept=accept, actor=actor, stated=stated, prompt=False
            )
            for agreement_id in agreement_ids
        ]
        return {
            "session_id": session_id,
            "decisions": records,
            "message": await self.conversation.prompt_next(session_id),
        }

    async def decide_agreement(
        self,
        session_id: str,
        agreement_id: str,
        *,
        accept: bool,
        actor: str = "user",
        stated: str = "",
        prompt: bool = True,
    ) -> dict[str, Any]:
        """Record a decision taken outside the conversation.

        A console with a checkbox and a chat window that types "I agree" must
        produce the same record, so both land here. Only the *entry point*
        differs — the text, the hash, the actor and the timestamp are written
        identically either way.
        """
        from . import agreements as agreements_module
        from .models import AgreementDecision

        session = await self.get_session(session_id)
        form = self.registry.get(session.form_name, session.form_version)
        agreement = form.try_agreement(agreement_id)
        if agreement is None:
            raise NotFoundError(
                f"form '{form.name}' declares no agreement '{agreement_id}'",
                details={"form": form.name, "agreement": agreement_id},
            )
        if not session.status.is_editable:
            raise ValidationError(
                f"session '{session_id}' is {session.status.value} and cannot record agreements",
                details={"session_id": session_id, "status": session.status.value},
            )
        if not agreements_module.reachable(form, session, agreement.stage):
            raise ValidationError(
                f"'{agreement.title}' is taken {agreement.stage.value.replace('_', ' ')} "
                "and this submission has not got there yet",
                details={
                    "session_id": session_id,
                    "agreement": agreement_id,
                    "stage": agreement.stage.value,
                },
            )

        record = agreements_module.record(
            session,
            agreement,
            decision=AgreementDecision.ACCEPTED if accept else AgreementDecision.DECLINED,
            actor=actor,
            stated=stated,
        )
        await self.sessions.save(session)

        # A decision taken here changes what the conversation should be doing,
        # and the chat window has no way to know. Without this the participant
        # ticks the box and the screen sits there: the conversation waiting for
        # a message, the person waiting for a question.
        payload = record.model_dump(mode="json")
        payload["message"] = await self.conversation.prompt_next(session_id) if prompt else None
        return payload

    # -- questions the participant raised ----------------------------------
    async def questions(self, session_id: str, *, open_only: bool = False) -> list[dict[str, Any]]:
        """Questions this session provoked, answered or still with a team."""
        session = await self.get_session(session_id)
        chosen = session.open_support_requests() if open_only else session.support_requests
        return [r.model_dump(mode="json") for r in chosen]

    async def answer_question(
        self, session_id: str, request_id: str, resolution: str
    ) -> dict[str, Any]:
        """Close a routed question with what the team came back with."""
        from . import support

        session = await self.get_session(session_id)
        request = support.close(session, request_id, resolution)
        if request is None:
            raise NotFoundError(
                f"session '{session_id}' has no question '{request_id}'",
                details={"session_id": session_id, "request_id": request_id},
            )
        await self.sessions.save(session)
        return request.model_dump(mode="json")

    # -- artifacts and approval -------------------------------------------
    async def generate(
        self,
        session_id: str,
        formats: list[str] | None = None,
        *,
        ctx: ExecutionContext | None = None,
        allow_incomplete: bool = False,
    ) -> list[ArtifactRecord]:
        return await self.approval.generate(
            session_id, formats, ctx=ctx, allow_incomplete=allow_incomplete
        )

    async def approve(
        self, artifact_id: str, *, approver: str | None = None, comment: str = "", **kwargs: Any
    ) -> ArtifactRecord:
        return await self.approval.decide(
            artifact_id, "approved", approver=approver, comment=comment, **kwargs
        )

    async def reject(
        self, artifact_id: str, *, approver: str | None = None, comment: str = "", **kwargs: Any
    ) -> ArtifactRecord:
        return await self.approval.decide(
            artifact_id, "rejected", approver=approver, comment=comment, **kwargs
        )

    async def reopen(self, session_id: str, *, reason: str = "") -> FormSession:
        return await self.approval.reopen(session_id, reason=reason)

    async def download(self, artifact_id: str) -> tuple[bytes, ArtifactRecord]:
        record = await self.approval.get_artifact(artifact_id)
        return await self.approval.read_artifact(artifact_id), record

    async def verify_baseline(self, artifact_id: str) -> dict[str, Any]:
        return await self.approval.verify_baseline(artifact_id)

    async def pending_reviews(self, limit: int = 50) -> list[ArtifactRecord]:
        return await self.approval.pending_reviews(limit)

    # -- assistant ---------------------------------------------------------
    @property
    def assistant(self) -> Any:
        """Cross-session question answering. Built on first use.

        Lazily constructed because it is only needed by callers that ask
        questions *about* forms, and building it eagerly would pull the search
        index into every process that merely fills one in.
        """
        if self._assistant is None:
            from .assistant import FormsAssistant

            self._assistant = FormsAssistant(self, llm_provider=self._llm)
        return self._assistant

    # -- convenience -------------------------------------------------------
    async def resume_or_start(
        self, form_name: str, participant: str, **kwargs: Any
    ) -> dict[str, Any]:
        """What a chat bot calls when a user mentions a form by name."""
        return await self.start_session(form_name, participant=participant, resume=True, **kwargs)

    async def require_session(self, session_id: str) -> FormSession:
        session = await self.sessions.try_load(session_id)
        if session is None:
            raise NotFoundError(
                f"form session '{session_id}' was not found", details={"session_id": session_id}
            )
        return session

    async def health(self) -> dict[str, Any]:
        from .rendering import available_formats

        return {
            "forms_registered": len(self.registry),
            "active_forms": [f.name for f in self.registry.list_forms()],
            "renderers": available_formats(),
            "open_sessions": len(
                await self.sessions.list_sessions(status=SessionStatus.COLLECTING, limit=1000)
            ),
        }


#: Process-wide service. Applications may construct their own for isolation.
forms_service = FormsService()

__all__ = ["FormsService", "forms_service"]
