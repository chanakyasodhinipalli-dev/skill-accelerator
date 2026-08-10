"""Forms exposed as platform tools.

Registering these lets an existing agent gather a form as part of a wider
conversation — it does not need a dedicated form bot. The tools inherit the
platform's policy, permissions, approval gate, and audit trail like any other.

Danger levels are set deliberately: reading is ``SAFE``, contributing answers is
``LOW``, producing a document is ``MEDIUM``, and approving is ``HIGH`` — the
approval gate should stand between a model and a signed-off baseline.

There is deliberately **no tool that accepts an agreement.** Consent goes
through ``forms_contribute`` like anything else the person said, so the only way
to record acceptance is for the terms to have been put to them by the engine
first, in the engine's words. A dedicated accept tool would let a model record
consent to text it had merely summarised — which is the one thing an agreement
record exists to rule out.
"""

from __future__ import annotations

from typing import Any

from sa_platform.context import ExecutionContext
from sa_tools.base import Tool
from sa_tools.models import DangerLevel, ToolSpec

from .service import FormsService, forms_service


class _FormsTool(Tool):
    """Base for tools that share one :class:`FormsService`."""

    def __init__(self, spec: ToolSpec, service: FormsService | None = None) -> None:
        super().__init__(spec)
        self._service = service if service is not None else forms_service


class ListFormsTool(_FormsTool):
    def __init__(self, service: FormsService | None = None) -> None:
        super().__init__(
            ToolSpec(
                name="forms_list",
                description=(
                    "List the forms available to fill in, with a one-line description of each. "
                    "Call this when someone mentions needing to complete, submit, or raise "
                    "a form, request, or template, or to accept, sign, or acknowledge terms, "
                    "and you need to know which ones exist. `kind` distinguishes the two: an "
                    "`intake` form gathers answers, an `agreement` form records what somebody "
                    "accepted."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Filter by name or description substring.",
                        },
                        "kind": {
                            "type": "string",
                            "enum": ["intake", "agreement"],
                            "description": "Return only forms of this kind.",
                        },
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                danger=DangerLevel.SAFE,
                tags=["forms", "introspection"],
            ),
            service,
        )

    async def invoke(self, ctx: ExecutionContext, arguments: dict[str, Any]) -> Any:
        query = arguments.get("query")
        forms = self._service.registry.search(query=query) if query else self._service.list_forms()
        wanted = arguments.get("kind")
        if wanted:
            forms = [f for f in forms if f.kind.value == wanted]
        return {
            "count": len(forms),
            "forms": [
                {
                    "name": f.name,
                    "version": f.version,
                    "title": f.title,
                    "kind": f.kind.value,
                    "description": f.description,
                    "required_fields": len(f.mandatory_fields()),
                    "total_fields": f.field_count(),
                    # An agreement form is measured in agreements. Reporting it
                    # as "0 of 0 fields" tells a model it has nothing to do.
                    "required_agreements": len(f.required_agreements()),
                    "total_agreements": len(f.agreements),
                }
                for f in forms
            ],
        }


class DescribeFormTool(_FormsTool):
    def __init__(self, service: FormsService | None = None) -> None:
        super().__init__(
            ToolSpec(
                name="forms_describe",
                description=(
                    "Return everything a form asks for: its topics, each field's meaning, "
                    "whether it is required, and why it is needed. Call this to answer "
                    "'what will this form ask me?' or 'why does it need X?' before starting."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "form_name": {"type": "string"},
                        "version": {"type": "string"},
                    },
                    "required": ["form_name"],
                    "additionalProperties": False,
                },
                danger=DangerLevel.SAFE,
                tags=["forms", "introspection"],
            ),
            service,
        )

    async def invoke(self, ctx: ExecutionContext, arguments: dict[str, Any]) -> Any:
        form = self._service.get_form(arguments["form_name"], arguments.get("version"))
        return {
            "name": form.name,
            "version": form.version,
            "title": form.title,
            "kind": form.kind.value,
            "description": form.description,
            "sections": [
                {
                    "title": section.title,
                    "description": section.description,
                    "fields": [
                        {
                            "id": field.id,
                            "label": field.label,
                            "type": field.type.value,
                            "importance": field.importance.value,
                            "description": field.description,
                            # The answer to "why are you asking me this?"
                            "why_it_matters": field.rationale,
                            "options": field.options,
                        }
                        for field in section.fields
                    ],
                }
                for section in form.ordered_sections()
            ],
            # What they will have to agree to is part of "what will this form
            # ask me?", and finding out at the end is how someone abandons a
            # half-filled submission.
            "agreements": [
                {
                    "id": a.id,
                    "title": a.title,
                    "kind": a.kind.value,
                    "stage": a.stage.value,
                    "required": a.required,
                    "text": a.text,
                    # So an agent can answer "what does this mean?" itself
                    # rather than promising that a team will come back.
                    "explanation": a.explanation,
                    "answers": [{"question": f.question, "answer": f.answer} for f in a.faqs],
                }
                for a in form.agreements
            ],
            "who_to_ask": [
                {"team": r.team, "contact": r.contact, "covers": r.covers, "about": r.note}
                for r in form.escalation
            ],
        }


class StartFormTool(_FormsTool):
    def __init__(self, service: FormsService | None = None) -> None:
        super().__init__(
            ToolSpec(
                name="forms_start",
                description=(
                    "Begin filling in a form, or resume the caller's paused session for it. "
                    "Call this once the person has said which form they need. Returns a "
                    "session id and the opening question to relay to them."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "form_name": {"type": "string"},
                        "participant": {
                            "type": "string",
                            "description": "Who is filling it in; used to find their paused session.",
                        },
                        "title": {
                            "type": "string",
                            "description": "Optional label for this submission.",
                        },
                    },
                    "required": ["form_name", "participant"],
                    "additionalProperties": False,
                },
                danger=DangerLevel.LOW,
                tags=["forms"],
                idempotent=False,
                parallel_safe=False,
            ),
            service,
        )

    async def invoke(self, ctx: ExecutionContext, arguments: dict[str, Any]) -> Any:
        return await self._service.start_session(
            arguments["form_name"],
            participant=arguments["participant"],
            title=arguments.get("title", ""),
            ctx=ctx,
        )


class ContributeTool(_FormsTool):
    def __init__(self, service: FormsService | None = None) -> None:
        super().__init__(
            ToolSpec(
                name="forms_contribute",
                description=(
                    "Pass what someone said into an in-progress form session. It extracts "
                    "every field the text answers and returns the next question to ask. "
                    "Call this with the person's message verbatim — do not pre-parse it, "
                    "and do not restrict it to the field you last asked about."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string"},
                        "message": {
                            "type": "string",
                            "description": "What the person said, word for word.",
                        },
                        "author": {"type": "string"},
                    },
                    "required": ["session_id", "message"],
                    "additionalProperties": False,
                },
                danger=DangerLevel.LOW,
                tags=["forms"],
                idempotent=False,
                parallel_safe=False,
            ),
            service,
        )

    async def invoke(self, ctx: ExecutionContext, arguments: dict[str, Any]) -> Any:
        result = await self._service.send(
            arguments["session_id"],
            arguments["message"],
            author=arguments.get("author", ctx.principal.subject),
            ctx=ctx,
        )
        return result.to_dict()


class IngestThreadTool(_FormsTool):
    def __init__(self, service: FormsService | None = None) -> None:
        super().__init__(
            ToolSpec(
                name="forms_ingest_thread",
                description=(
                    "Mine an existing discussion for form answers: JIRA comments, an email "
                    "chain, or a meeting transcript. Call this before asking any questions "
                    "when the information already exists somewhere — it usually removes most "
                    "of the back-and-forth."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string"},
                        "channel": {
                            "type": "string",
                            "enum": ["jira", "email", "meeting", "document", "chat"],
                        },
                        "content": {
                            "type": "string",
                            "description": "The raw thread text, or JSON for jira/email payloads.",
                        },
                    },
                    "required": ["session_id", "channel", "content"],
                    "additionalProperties": False,
                },
                danger=DangerLevel.LOW,
                tags=["forms", "ingestion"],
                idempotent=False,
                parallel_safe=False,
            ),
            service,
        )

    async def invoke(self, ctx: ExecutionContext, arguments: dict[str, Any]) -> Any:
        import json

        raw = arguments["content"]
        payload: Any = raw
        # JIRA and email adapters take structured payloads; chat and transcripts
        # take text. Accept either and let the adapter decide.
        if arguments["channel"] in ("jira", "email"):
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = raw

        return await self._service.ingest(arguments["session_id"], arguments["channel"], payload)


class FormStatusTool(_FormsTool):
    def __init__(self, service: FormsService | None = None) -> None:
        super().__init__(
            ToolSpec(
                name="forms_status",
                description=(
                    "Report how complete a form session is: what has been captured, what is "
                    "still required, and any open action items. Call this when asked 'how "
                    "far along are we?' or before offering to generate the document."
                ),
                parameters={
                    "type": "object",
                    "properties": {"session_id": {"type": "string"}},
                    "required": ["session_id"],
                    "additionalProperties": False,
                },
                danger=DangerLevel.SAFE,
                tags=["forms"],
            ),
            service,
        )

    async def invoke(self, ctx: ExecutionContext, arguments: dict[str, Any]) -> Any:
        return await self._service.session_status(arguments["session_id"])


class AgreementsTool(_FormsTool):
    """What a session must agree to, and what it has agreed to already.

    Read-only, and there is no companion tool that *accepts* one. Consent goes
    back through ``forms_contribute`` like anything else the person said, so the
    only route to acceptance is the engine having put the exact wording to them.
    A tool that recorded acceptance would let a model attest on someone's behalf
    to text it had only summarised, which is precisely what an agreement record
    exists to rule out.
    """

    def __init__(self, service: FormsService | None = None) -> None:
        super().__init__(
            ToolSpec(
                name="forms_agreements",
                description=(
                    "Return the agreements a session is waiting on, with their exact wording, "
                    "and every decision taken so far. Call this to show someone what they are "
                    "being asked to accept, or to answer 'what did I agree to?'. Relay the "
                    "text word for word — never summarise it. To record acceptance, pass what "
                    "the person actually said to forms_contribute."
                ),
                parameters={
                    "type": "object",
                    "properties": {"session_id": {"type": "string"}},
                    "required": ["session_id"],
                    "additionalProperties": False,
                },
                danger=DangerLevel.SAFE,
                tags=["forms", "agreements"],
            ),
            service,
        )

    async def invoke(self, ctx: ExecutionContext, arguments: dict[str, Any]) -> Any:
        return await self._service.agreements(arguments["session_id"])


class GenerateArtifactTool(_FormsTool):
    def __init__(self, service: FormsService | None = None) -> None:
        super().__init__(
            ToolSpec(
                name="forms_generate",
                description=(
                    "Produce the finished document (Excel, PDF, Word, or Markdown) from a "
                    "completed session and put it up for review. Call this only after the "
                    "person has confirmed the summary is correct. Refuses while required "
                    "fields are still open."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string"},
                        "formats": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Defaults to the form's configured formats.",
                        },
                    },
                    "required": ["session_id"],
                    "additionalProperties": False,
                },
                # Produces a durable, distributable document, so it goes through
                # the approval gate rather than firing on the model's say-so.
                danger=DangerLevel.MEDIUM,
                tags=["forms", "artifact"],
                idempotent=False,
                parallel_safe=False,
                required_permissions=["forms:generate"],
            ),
            service,
        )

    async def invoke(self, ctx: ExecutionContext, arguments: dict[str, Any]) -> Any:
        records = await self._service.generate(
            arguments["session_id"], arguments.get("formats"), ctx=ctx
        )
        return {
            "artifacts": [
                {
                    "artifact_id": r.id,
                    "format": r.format,
                    "filename": r.filename,
                    "revision": r.revision,
                    "status": r.status.value,
                    "checksum": r.checksum,
                }
                for r in records
            ]
        }


class ApproveArtifactTool(_FormsTool):
    def __init__(self, service: FormsService | None = None) -> None:
        super().__init__(
            ToolSpec(
                name="forms_approve",
                description=(
                    "Record an approve or reject decision on a generated document. Approving "
                    "baselines it once the form's required approval count is met, after which "
                    "it cannot be edited. Only call this when a named human has explicitly "
                    "given their decision."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "artifact_id": {"type": "string"},
                        "decision": {"type": "string", "enum": ["approved", "rejected"]},
                        "approver": {"type": "string", "description": "Who decided."},
                        "comment": {"type": "string"},
                    },
                    "required": ["artifact_id", "decision", "approver"],
                    "additionalProperties": False,
                },
                # Irreversible and externally meaningful: always gated.
                danger=DangerLevel.HIGH,
                tags=["forms", "approval"],
                idempotent=False,
                parallel_safe=False,
                requires_approval=True,
                required_permissions=["forms:approve"],
            ),
            service,
        )

    async def invoke(self, ctx: ExecutionContext, arguments: dict[str, Any]) -> Any:
        record = await self._service.approval.decide(
            arguments["artifact_id"],
            arguments["decision"],
            approver=arguments["approver"],
            comment=arguments.get("comment", ""),
            ctx=ctx,
        )
        return {
            "artifact_id": record.id,
            "status": record.status.value,
            "approvals": record.approval_count(),
            "baselined": record.is_baselined,
            "checksum": record.checksum,
        }


FORM_TOOLS = (
    ListFormsTool,
    DescribeFormTool,
    StartFormTool,
    ContributeTool,
    IngestThreadTool,
    FormStatusTool,
    AgreementsTool,
    GenerateArtifactTool,
    ApproveArtifactTool,
)


def register_form_tools(
    tool_registry: Any | None = None,
    *,
    service: FormsService | None = None,
    replace: bool = True,
) -> list[str]:
    """Register every forms tool into a tool registry."""
    from sa_tools.registry import tool_registry as default_registry

    target = tool_registry if tool_registry is not None else default_registry
    registered: list[str] = []
    for factory in FORM_TOOLS:
        instance = factory(service)
        target.register(instance, replace=replace)
        registered.append(instance.spec.name)
    return registered


__all__ = [
    "FORM_TOOLS",
    "AgreementsTool",
    "ApproveArtifactTool",
    "ContributeTool",
    "DescribeFormTool",
    "FormStatusTool",
    "GenerateArtifactTool",
    "IngestThreadTool",
    "ListFormsTool",
    "StartFormTool",
    "register_form_tools",
]
