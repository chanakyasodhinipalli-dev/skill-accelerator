"""Form catalogue, conversation, ingestion, artifact, and approval endpoints."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from pydantic import BaseModel, Field

from sa_forms.models import ArtifactRecord, FormDefinition, FormSession
from sa_forms.service import FormsService, forms_service

from ..dependencies import ContextDep

router = APIRouter(prefix="/forms", tags=["forms"])


def get_forms_service() -> FormsService:
    return forms_service


ServiceDep = Annotated[FormsService, Depends(get_forms_service)]


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class StartSessionRequest(BaseModel):
    participant: str = Field(description="Who is filling the form in")
    version: str | None = None
    title: str = ""
    resume: bool = Field(default=True, description="Resume this participant's paused session")


class MessageRequest(BaseModel):
    message: str
    author: str = "user"
    channel: str = "chat"


class IngestRequest(BaseModel):
    channel: str = Field(description="jira | email | meeting | document | chat")
    payload: Any = Field(description="Raw thread text, or the API payload for jira/email")
    base_url: str | None = Field(default=None, description="JIRA base URL, for deep links")


class SetAnswerRequest(BaseModel):
    field_id: str
    value: Any
    author: str = "user"


class AgreementDecisionRequest(BaseModel):
    accept: bool
    actor: str = "user"
    stated: str = Field(
        default="",
        description="What the person actually said or clicked, kept verbatim on the record.",
    )


class BulkAgreementDecisionRequest(BaseModel):
    agreement_ids: list[str] = Field(min_length=1)
    accept: bool
    actor: str = "user"
    stated: str = ""


class QuestionAnswerRequest(BaseModel):
    resolution: str = Field(description="What the team came back with")


class GenerateRequest(BaseModel):
    formats: list[str] | None = None
    allow_incomplete: bool = Field(
        default=False,
        description="Render despite open required fields; they are recorded as action items.",
    )


class DecisionRequest(BaseModel):
    decision: str = Field(description="approved | rejected")
    approver: str | None = None
    comment: str = ""


class UpdateFormRequest(BaseModel):
    changes: dict[str, Any]
    bump: str = Field(default="minor", description="major | minor | patch")
    change_note: str = ""


class RefineFormRequest(BaseModel):
    instructions: str = Field(
        description="Plain-language changes, e.g. 'make budget optional and add a rollback plan field'"
    )
    version: str | None = None


class AssistantRequest(BaseModel):
    question: str = Field(description="A question about any form, session, or artifact")
    conversation_id: str | None = Field(
        default=None, description="Continue an existing assistant thread"
    )
    participant: str = Field(default="user", description="Who is asking, for 'my sessions'")


# ---------------------------------------------------------------------------
# Assistant
#
# Declared before the catalogue routes because `/forms/{name}` would otherwise
# match `/forms/assistant` and try to load a form called "assistant".
# ---------------------------------------------------------------------------


@router.post("/assistant/ask", summary="Ask about any form conversation")
async def assistant_ask(request: AssistantRequest, service: ServiceDep) -> dict[str, Any]:
    """Answer a question spanning every session, form, and artifact.

    Evidence is retrieved deterministically and cited by id; the model only
    phrases the reply. With no model configured the answer is composed from the
    same evidence in plainer words rather than failing.
    """
    answer = await service.assistant.ask(
        request.question,
        conversation_id=request.conversation_id,
        participant=request.participant,
    )
    return answer.to_dict()


@router.get("/assistant/search", summary="Search sessions, forms, and artifacts")
async def assistant_search(
    service: ServiceDep,
    q: str = Query(default="", description="Free text; empty returns what changed most recently"),
    kind: str | None = Query(default=None, description="session | form | artifact"),
    limit: int = Query(default=10, ge=1, le=50),
) -> dict[str, Any]:
    hits = await service.assistant.search(q, limit=limit, kind=kind)
    return {"query": q, "count": len(hits), "results": [h.to_dict() for h in hits]}


@router.get("/sessions", summary="List sessions")
async def list_sessions(
    service: ServiceDep,
    form_name: str | None = Query(default=None),
    participant: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    """List sessions.

    Declared here, above ``GET /forms/{name}``: FastAPI matches in declaration
    order, so a literal path registered *after* a single-segment parameter route
    is unreachable — the request arrives as a form named "sessions".
    """
    sessions = await service.list_sessions(
        form_name=form_name, participant=participant, limit=limit
    )
    return {
        "count": len(sessions),
        "sessions": [
            {
                "session_id": s.id,
                "form": f"{s.form_name}@{s.form_version}",
                "title": s.title,
                "status": s.status.value,
                "participants": s.participants,
                "updated_at": s.updated_at,
            }
            for s in sessions
        ],
    }


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------


@router.get("", summary="List available forms")
async def list_forms(
    service: ServiceDep,
    query: str | None = Query(default=None),
    include_inactive: bool = Query(default=False),
) -> dict[str, Any]:
    forms = (
        service.registry.search(query=query)
        if query
        else service.list_forms(include_inactive=include_inactive)
    )
    return {
        "count": len(forms),
        "forms": [
            {
                "name": f.name,
                "version": f.version,
                "title": f.title,
                "kind": f.kind.value,
                "description": f.description,
                "status": f.status.value,
                "owner": f.owner,
                "required_fields": len(f.mandatory_fields()),
                "total_fields": f.field_count(),
                # An agreement form measured in fields reads as an empty form.
                "required_agreements": len(f.required_agreements()),
                "total_agreements": len(f.agreements),
                "tags": f.tags,
            }
            for f in forms
        ],
    }


@router.get("/{name}", response_model=FormDefinition, summary="Get a form definition")
async def get_form(
    name: str, service: ServiceDep, version: str | None = Query(default=None)
) -> FormDefinition:
    return service.get_form(name, version)


@router.get("/{name}/history", summary="List every version of a form")
async def form_history(name: str, service: ServiceDep) -> dict[str, Any]:
    return {
        "form": name,
        "versions": [
            {
                "version": f.version,
                "status": f.status.value,
                "updated_at": f.updated_at,
                "change_note": f.change_note,
                "fields": f.field_count(),
                "agreements": len(f.agreements),
            }
            for f in service.form_history(name)
        ],
    }


@router.post("", response_model=FormDefinition, status_code=201, summary="Create a form")
async def create_form(
    definition: FormDefinition,
    service: ServiceDep,
    activate: bool = Query(default=False),
) -> FormDefinition:
    return service.create_form(definition, activate=activate)


@router.patch("/{name}", response_model=FormDefinition, summary="Update a form")
async def update_form(
    name: str, request: UpdateFormRequest, service: ServiceDep, ctx: ContextDep
) -> FormDefinition:
    """Update a form.

    A draft is edited in place. A published version forks into a new draft, so a
    definition someone is already filling against never changes underneath them.
    """
    return service.update_form(
        name,
        request.changes,
        bump=request.bump,  # type: ignore[arg-type]
        change_note=request.change_note,
        editor=ctx.principal.subject,
    )


@router.post("/{name}/versions/{version}/activate", summary="Publish a version")
async def activate_version(name: str, version: str, service: ServiceDep) -> dict[str, Any]:
    """Make this version the one new sessions use, deprecating the previous."""
    form = service.activate_form(name, version)
    return {"form": form.name, "version": form.version, "status": form.status.value}


@router.delete("/{name}", status_code=204, summary="Delete a form or one version")
async def delete_form(
    name: str,
    service: ServiceDep,
    version: str | None = Query(default=None),
    force: bool = Query(default=False, description="Required to remove a published version"),
) -> Response:
    service.delete_form(name, version, force=force)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Authoring from a sample
# ---------------------------------------------------------------------------


@router.post("/infer", summary="Create a form from an uploaded sample")
async def infer_form(
    service: ServiceDep,
    file: UploadFile = File(description="An .xlsx, .csv, or .json sample of the form"),
    form_name: str | None = Query(default=None),
    register: bool = Query(default=True),
) -> dict[str, Any]:
    """Infer a form definition from a document you already fill in by hand.

    Returns a **draft** plus the questions the facilitator still needs answered.
    Answer them with `/forms/{name}/refine`, then activate it.
    """
    content = await file.read()
    report = await service.infer_form(
        content,
        filename=file.filename or "sample.xlsx",
        form_name=form_name,
        register=register,
    )
    return {
        **report.summary(),
        "definition": report.definition.model_dump(mode="json"),
    }


@router.post(
    "/{name}/refine", response_model=FormDefinition, summary="Refine a draft in plain language"
)
async def refine_form(name: str, request: RefineFormRequest, service: ServiceDep) -> FormDefinition:
    """Answer the facilitator's questions, or ask for changes in plain language."""
    return await service.refine_form(name, request.instructions, version=request.version)


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


@router.post("/{name}/sessions", status_code=201, summary="Start or resume a session")
async def start_session(
    name: str, request: StartSessionRequest, service: ServiceDep, ctx: ContextDep
) -> dict[str, Any]:
    return await service.start_session(
        name,
        participant=request.participant,
        version=request.version,
        title=request.title,
        resume=request.resume,
        ctx=ctx,
    )


@router.post("/sessions/{session_id}/messages", summary="Send a message to a session")
async def send_message(
    session_id: str, request: MessageRequest, service: ServiceDep, ctx: ContextDep
) -> dict[str, Any]:
    """One conversational turn.

    Extracts every field the message answers — not only the one last asked
    about — and returns the next question.
    """
    result = await service.send(
        session_id,
        request.message,
        author=request.author,
        channel=request.channel,
        ctx=ctx,
    )
    return result.to_dict()


@router.post("/sessions/{session_id}/ingest", summary="Mine an existing thread")
async def ingest_thread(
    session_id: str, request: IngestRequest, service: ServiceDep
) -> dict[str, Any]:
    """Pull answers out of JIRA comments, an email chain, or a meeting transcript.

    Run this before asking anything — it is what removes most of the
    back-and-forth.
    """
    kwargs: dict[str, Any] = {}
    if request.base_url:
        kwargs["base_url"] = request.base_url
    return await service.ingest(session_id, request.channel, request.payload, **kwargs)


@router.post("/sessions/{session_id}/ingest/email", summary="Upload an email with attachments")
async def ingest_email_file(
    session_id: str,
    service: ServiceDep,
    email: UploadFile = File(description="An .eml file (save the mail as MIME, not .msg)"),
    attachments: list[UploadFile] = File(
        default=[],
        description="Files to mine alongside the mail — useful when a forward dropped them",
    ),
) -> dict[str, Any]:
    """Fill the form from a mail thread and everything attached to it.

    The response names each attachment and whether its text could be read, so an
    unreadable file is visible rather than silently missing from the artifact.
    """
    extra: list[tuple[str, bytes]] = [
        (f.filename or "attachment", await f.read()) for f in attachments if f is not None
    ]
    return await service.ingest_email(session_id, await email.read(), attachments=extra)


@router.get("/sessions/{session_id}", response_model=FormSession, summary="Get a session")
async def get_session(session_id: str, service: ServiceDep) -> FormSession:
    return await service.get_session(session_id)


@router.get("/sessions/{session_id}/status", summary="Get session progress")
async def session_status(session_id: str, service: ServiceDep) -> dict[str, Any]:
    return await service.session_status(session_id)


@router.put("/sessions/{session_id}/answers", summary="Set a field directly")
async def set_answer(
    session_id: str, request: SetAnswerRequest, service: ServiceDep
) -> dict[str, Any]:
    """Set a value without going through the conversation.

    Used by a form UI or a reviewer correcting a value. The answer is marked
    confirmed, so later extraction cannot overwrite it.
    """
    session = await service.set_answer(
        session_id, request.field_id, request.value, author=request.author
    )
    return {
        "session_id": session.id,
        "field_id": request.field_id,
        "state": session.answers[request.field_id].state.value,
    }


@router.get("/sessions/{session_id}/agreements", summary="Agreements and their decisions")
async def session_agreements(session_id: str, service: ServiceDep) -> dict[str, Any]:
    return await service.agreements(session_id)


@router.post("/sessions/{session_id}/agreements", summary="Record several decisions at once")
async def decide_agreements(
    session_id: str, request: BulkAgreementDecisionRequest, service: ServiceDep
) -> dict[str, Any]:
    """Accept or decline a set of agreements as one act.

    What an "I agree to all of these" button means. Looping over the single
    endpoint instead makes each acceptance announce the next term, so the
    transcript shows the same agreement put to the participant twice with
    nobody having said anything in between.
    """
    return await service.decide_agreements(
        session_id,
        request.agreement_ids,
        accept=request.accept,
        actor=request.actor,
        stated=request.stated,
    )


@router.post("/sessions/{session_id}/agreements/{agreement_id}", summary="Record a decision")
async def decide_agreement(
    session_id: str,
    agreement_id: str,
    request: AgreementDecisionRequest,
    service: ServiceDep,
) -> dict[str, Any]:
    """Accept or decline an agreement from a UI rather than in the conversation.

    The record written here is identical to the one the chat path writes —
    same text, same hash, same actor — because a checkbox and a typed "I agree"
    have to be worth the same thing when somebody reads the record back.
    """
    return await service.decide_agreement(
        session_id,
        agreement_id,
        accept=request.accept,
        actor=request.actor,
        stated=request.stated,
    )


@router.get("/sessions/{session_id}/questions", summary="Questions this session raised")
async def session_questions(
    session_id: str, service: ServiceDep, open_only: bool = Query(default=False)
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "questions": await service.questions(session_id, open_only=open_only),
    }


@router.post("/sessions/{session_id}/questions/{request_id}", summary="Answer a routed question")
async def answer_question(
    session_id: str, request_id: str, request: QuestionAnswerRequest, service: ServiceDep
) -> dict[str, Any]:
    """What the team came back with. Closes the question on the record."""
    return await service.answer_question(session_id, request_id, request.resolution)


@router.post("/sessions/{session_id}/reopen", summary="Reopen a session for edits")
async def reopen_session(
    session_id: str, service: ServiceDep, reason: str = Query(default="")
) -> dict[str, Any]:
    session = await service.reopen(session_id, reason=reason)
    return {"session_id": session.id, "status": session.status.value}


# ---------------------------------------------------------------------------
# Artifacts and approval
# ---------------------------------------------------------------------------


@router.post("/sessions/{session_id}/generate", summary="Render the document")
async def generate_artifact(
    session_id: str, request: GenerateRequest, service: ServiceDep, ctx: ContextDep
) -> dict[str, Any]:
    """Produce the artifact(s) and move the session into review."""
    records = await service.generate(
        session_id,
        request.formats,
        ctx=ctx,
        allow_incomplete=request.allow_incomplete,
    )
    return {
        "count": len(records),
        "artifacts": [r.model_dump(mode="json") for r in records],
    }


@router.get(
    "/artifacts/{artifact_id}", response_model=ArtifactRecord, summary="Get artifact metadata"
)
async def get_artifact(artifact_id: str, service: ServiceDep) -> ArtifactRecord:
    return await service.approval.get_artifact(artifact_id)


@router.get("/artifacts/{artifact_id}/content", summary="Download an artifact")
async def download_artifact(artifact_id: str, service: ServiceDep) -> Response:
    content, record = await service.download(artifact_id)
    return Response(
        content=content,
        media_type=record.metadata.get("media_type", "application/octet-stream"),
        headers={"Content-Disposition": f'attachment; filename="{record.filename}"'},
    )


@router.post("/artifacts/{artifact_id}/decision", summary="Approve or reject an artifact")
async def decide(
    artifact_id: str, request: DecisionRequest, service: ServiceDep, ctx: ContextDep
) -> dict[str, Any]:
    """Record a review decision.

    Approving baselines the artifact once the form's required approval count is
    met; a baselined artifact is immutable.
    """
    record = await service.approval.decide(
        artifact_id,
        request.decision,
        approver=request.approver,
        comment=request.comment,
        ctx=ctx,
    )
    return {
        "artifact_id": record.id,
        "status": record.status.value,
        "approvals": record.approval_count(),
        "baselined": record.is_baselined,
        "checksum": record.checksum,
    }


@router.get("/artifacts/{artifact_id}/verify", summary="Verify a baseline is intact")
async def verify_baseline(artifact_id: str, service: ServiceDep) -> dict[str, Any]:
    """Confirm the stored bytes still match the checksum recorded at sign-off."""
    return await service.verify_baseline(artifact_id)


@router.get("/reviews/pending", summary="List artifacts awaiting review")
async def pending_reviews(
    service: ServiceDep, limit: int = Query(default=50, ge=1, le=200)
) -> dict[str, Any]:
    records = await service.pending_reviews(limit)
    return {
        "count": len(records),
        "artifacts": [
            {
                "artifact_id": r.id,
                "session_id": r.session_id,
                "form": f"{r.form_name}@{r.form_version}",
                "format": r.format,
                "revision": r.revision,
                "created_at": r.created_at,
                "approvals": r.approval_count(),
            }
            for r in records
        ],
    }
