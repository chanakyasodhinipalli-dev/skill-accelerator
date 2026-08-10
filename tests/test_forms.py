"""Tests for conversational form intake.

The LLM is replaced with a scripted stub so the suite runs offline and
deterministically. What is exercised is the platform's own logic: gap analysis,
coercion, provenance, versioning, ingestion parsing, rendering, and the
approval/baseline lifecycle — not the model's phrasing.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from typing import Any

import pytest
from pydantic import ValidationError as PydanticValidationError

from sa_forms.actions import derive_action_items
from sa_forms.agreements import digest as agreements_digest
from sa_forms.agreements import outstanding as agreements_outstanding
from sa_forms.authoring import FormAuthor, profile_columns, read_tabular
from sa_forms.coercion import (
    CoercionError,
    coerce_and_validate,
    date_is_inferred,
    render_value,
)
from sa_forms.completeness import analyse, next_topic, progress_line
from sa_forms.consistency import (
    ConsistencyReviewer,
    acknowledge,
    build_scope,
    evaluate_rules,
    merge,
)
from sa_forms.consistency import outstanding as consistency_outstanding
from sa_forms.consistency import outstanding as outstanding_findings
from sa_forms.conversation import ConversationEngine, Intent
from sa_forms.dates import resolve as resolve_date
from sa_forms.durations import parse_duration, parse_window, span_minutes
from sa_forms.extraction import ExtractionEngine
from sa_forms.ingestion import (
    EmailThreadSource,
    JiraCommentSource,
    MeetingTranscriptSource,
    parse_payload,
)
from sa_forms.models import (
    Agreement,
    AgreementDecision,
    AgreementFaq,
    AgreementKind,
    AgreementStage,
    AnswerState,
    ApprovalPolicy,
    ArtifactStatus,
    ConsistencyFinding,
    ConsistencyRule,
    ConsistencySeverity,
    EscalationRoute,
    FieldAnswer,
    FieldType,
    FindingState,
    FormDefinition,
    FormField,
    FormKind,
    FormSection,
    FormSession,
    FormStatus,
    Importance,
    KnowledgeNote,
    SessionStatus,
    SourceChannel,
    SourceMessage,
    TranscriptEntry,
)
from sa_forms.normalisation import check, normalise, tidy
from sa_forms.registry import FormRegistry
from sa_forms.rendering import available_formats, render_session
from sa_forms.service import FormsService
from sa_forms.store import InMemoryArtifactStore, InMemorySessionStore
from sa_forms.support import route_for as support_route_for
from sa_orchestrator.expressions import evaluate_condition
from sa_platform.context import ExecutionContext, Principal, bind_context
from sa_platform.errors import AuthorizationError, ValidationError


@pytest.fixture(autouse=True)
def _service_principal() -> Any:
    """Run the suite as a service principal.

    Recording an approval under another person's name needs
    `forms:approve:on_behalf`, which is what a service integration would hold.
    The unprivileged path is covered explicitly in TestApproval.
    """
    with bind_context(
        ExecutionContext(principal=Principal(subject="forms-service", permissions=frozenset({"*"})))
    ):
        yield


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class StubProvider:
    """A scripted LLM.

    ``extractions`` is consumed one entry per structured call that looks like an
    extraction; anything else returns a canned question. Recording the prompts
    lets tests assert on what the engine actually asked the model for — which is
    where the real logic lives.
    """

    def __init__(
        self,
        extractions: list[dict[str, Any]] | None = None,
        *,
        suggestions: list[dict[str, Any]] | None = None,
        review: dict[str, Any] | None = None,
        rewrites: list[dict[str, Any]] | None = None,
        attribution: list[dict[str, Any]] | None = None,
    ) -> None:
        self.extractions = list(extractions or [])
        self.suggestions = list(suggestions or [])
        self.rewrites = list(rewrites or [])
        self.attribution = list(attribution or [])
        # Default to a coherent submission: the semantic reviewer finding
        # nothing is the normal outcome and must not colour other tests.
        self.review = review if review is not None else {"understanding": "", "findings": []}
        self.prompts: list[str] = []
        self.reply = "Thanks — what else can you tell me?"
        # A question the reference material cannot settle is the default. Being
        # unable to answer routes it to a human, which is the behaviour that
        # should hold when nothing has been scripted.
        self.support_answer: dict[str, Any] = {
            "answer": "",
            "answered": False,
            "gap": "nothing in the notes covers it",
            "sources": [],
        }

    async def complete_structured(
        self, messages: Any, schema: dict[str, Any], *, system: str | None = None, **kwargs: Any
    ) -> Any:
        prompt = messages[0].content if messages else ""
        self.prompts.append(str(prompt))

        properties = schema.get("properties", {})
        if "extractions" in properties:
            return self.extractions.pop(0) if self.extractions else {"extractions": []}
        if "understanding" in properties:
            return self.review
        if "rewrites" in properties:
            return {"rewrites": self.rewrites}
        if "addressed" in properties:
            return {"addressed": self.attribution}
        if "answered" in properties:
            return self.support_answer
        if "suggestions" in properties:
            return {"suggestions": self.suggestions}
        if "reply" in properties:
            return {"reply": self.reply}
        if "form_title" in properties:
            return {"form_title": "Inferred Form", "sections": [], "fields": []}
        return {}


def extraction(
    *items: tuple[str, str, float], actions: list[dict[str, str]] | None = None
) -> dict[str, Any]:
    """Build one scripted extraction response."""
    return {
        "extractions": [
            {"field_id": fid, "value": value, "confidence": confidence, "evidence": value}
            for fid, value, confidence in items
        ],
        "action_items": actions or [],
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def simple_form() -> FormDefinition:
    return FormDefinition(
        name="test_form",
        version="1.0.0",
        title="Test Form",
        description="A form used by the test suite.",
        status=FormStatus.ACTIVE,
        sections=[
            FormSection(
                id="basics",
                title="Basics",
                order=0,
                fields=[
                    FormField(
                        id="owner",
                        label="Owner",
                        type=FieldType.PERSON,
                        importance=Importance.MANDATORY,
                        rationale="Someone must be accountable for this.",
                        aliases=["responsible", "accountable"],
                    ),
                    FormField(
                        id="target_date",
                        label="Target date",
                        type=FieldType.DATE,
                        importance=Importance.MANDATORY,
                        rationale="Checked against the freeze calendar.",
                        require_explicit=True,
                    ),
                    FormField(
                        id="notes",
                        label="Notes",
                        type=FieldType.TEXT,
                        importance=Importance.RECOMMENDED,
                        rationale="Extra context for the approver.",
                    ),
                ],
            ),
            FormSection(
                id="risk",
                title="Risk",
                order=1,
                fields=[
                    FormField(
                        id="risk_level",
                        label="Risk level",
                        type=FieldType.ENUM,
                        importance=Importance.MANDATORY,
                        options=["low", "medium", "high"],
                        rationale="Sets the approval threshold.",
                    ),
                    FormField(
                        id="mitigation",
                        label="Mitigation",
                        type=FieldType.TEXT,
                        importance=Importance.MANDATORY,
                        rationale="How the risk is contained.",
                        # Only relevant once the risk is non-trivial.
                        ask_when="${answers.risk_level != 'low'}",
                    ),
                ],
            ),
        ],
    )


@pytest.fixture
def registry(simple_form: FormDefinition) -> FormRegistry:
    reg = FormRegistry()
    reg.create(simple_form, activate=True)
    return reg


@pytest.fixture
def service(registry: FormRegistry) -> FormsService:
    return FormsService(
        registry=registry,
        sessions=InMemorySessionStore(),
        artifacts=InMemoryArtifactStore(),
        llm_provider=StubProvider(),
    )


def make_service(registry: FormRegistry, provider: StubProvider) -> FormsService:
    return FormsService(
        registry=registry,
        sessions=InMemorySessionStore(),
        artifacts=InMemoryArtifactStore(),
        llm_provider=provider,
    )


# ---------------------------------------------------------------------------
# Coercion
# ---------------------------------------------------------------------------


class TestCoercion:
    def _field(self, **kwargs: Any) -> FormField:
        defaults = {"id": "f", "label": "F", "type": FieldType.STRING}
        return FormField(**{**defaults, **kwargs})

    def test_dates_accept_many_written_forms(self) -> None:
        field = self._field(type=FieldType.DATE)
        for raw in ("2026-03-15", "15/03/2026", "15 Mar 2026", "March 15, 2026"):
            assert coerce_and_validate(field, raw) == "2026-03-15"

    def test_date_extracted_from_surrounding_prose(self) -> None:
        field = self._field(type=FieldType.DATE)
        assert (
            coerce_and_validate(field, "we're aiming for 2026-03-15 if that works") == "2026-03-15"
        )

    def test_unparseable_date_is_rejected(self) -> None:
        with pytest.raises(CoercionError, match="expects a date"):
            coerce_and_validate(self._field(type=FieldType.DATE), "sometime next quarter")

    def test_boolean_accepts_conversational_phrasing(self) -> None:
        field = self._field(type=FieldType.BOOLEAN)
        assert coerce_and_validate(field, "yes, definitely") is True
        assert coerce_and_validate(field, "no") is False
        assert coerce_and_validate(field, "Not required") is False

    def test_enum_matching_tolerates_case_and_spacing(self) -> None:
        field = self._field(type=FieldType.ENUM, options=["low", "medium", "high"])
        assert coerce_and_validate(field, "Medium") == "medium"
        assert coerce_and_validate(field, "  HIGH ") == "high"

    def test_enum_rejects_an_unknown_value_with_the_options(self) -> None:
        field = self._field(type=FieldType.ENUM, options=["low", "high"])
        with pytest.raises(CoercionError) as caught:
            coerce_and_validate(field, "catastrophic")
        assert "low, high" in caught.value.message

    def test_lists_split_on_natural_separators(self) -> None:
        field = self._field(type=FieldType.LIST)
        assert coerce_and_validate(field, "alice, bob and carol") == ["alice", "bob", "carol"]

    def test_null_tokens_become_none(self) -> None:
        assert coerce_and_validate(self._field(), "N/A") is None
        assert coerce_and_validate(self._field(), "tbd") is None

    def test_email_is_extracted_from_prose(self) -> None:
        field = self._field(type=FieldType.EMAIL)
        assert coerce_and_validate(field, "ping Alice at alice@example.com") == "alice@example.com"

    def test_validation_rules_are_enforced(self) -> None:
        from sa_forms.models import FieldValidation

        field = self._field(validation=FieldValidation(min_length=10))
        with pytest.raises(CoercionError, match="at least 10"):
            coerce_and_validate(field, "short")

    def test_rendering_uses_units_and_yes_no(self) -> None:
        assert render_value(self._field(type=FieldType.BOOLEAN), True) == "Yes"
        assert render_value(self._field(type=FieldType.INTEGER, unit="days"), 5) == "5 days"


# ---------------------------------------------------------------------------
# Gap analysis
# ---------------------------------------------------------------------------


class TestCompleteness:
    async def test_all_mandatory_fields_start_outstanding(
        self, service: FormsService, simple_form: FormDefinition
    ) -> None:
        started = await service.start_session("test_form", participant="alice")
        session = await service.get_session(started["session_id"])
        report = analyse(simple_form, session)

        # `mitigation` is gated behind risk_level != low, so it is not yet counted.
        assert report.mandatory_total == 3
        assert report.mandatory_answered == 0
        assert not report.mandatory_complete

    async def test_conditional_field_activates_when_its_guard_passes(
        self, service: FormsService, simple_form: FormDefinition
    ) -> None:
        started = await service.start_session("test_form", participant="alice")
        sid = started["session_id"]

        await service.set_answer(sid, "risk_level", "low")
        session = await service.get_session(sid)
        assert "mitigation" in analyse(simple_form, session).inactive

        await service.set_answer(sid, "risk_level", "high")
        session = await service.get_session(sid)
        report = analyse(simple_form, session)
        assert "mitigation" not in report.inactive
        assert any(g.field.id == "mitigation" for g in report.gaps)

    async def test_next_topic_prefers_mandatory_work_in_section_order(
        self, service: FormsService, simple_form: FormDefinition
    ) -> None:
        started = await service.start_session("test_form", participant="alice")
        session = await service.get_session(started["session_id"])
        section, fields = next_topic(simple_form, analyse(simple_form, session))

        assert section.id == "basics"
        # The recommended `notes` field waits until mandatory work is done.
        assert [f.id for f in fields] == ["owner", "target_date"]

    async def test_answered_fields_leave_the_outstanding_set(
        self, service: FormsService, simple_form: FormDefinition
    ) -> None:
        started = await service.start_session("test_form", participant="alice")
        sid = started["session_id"]
        await service.set_answer(sid, "owner", "Priya")

        session = await service.get_session(sid)
        report = analyse(simple_form, session)
        assert report.mandatory_answered == 1
        assert "owner" not in [g.field.id for g in report.gaps]


# ---------------------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------------------


class TestConversation:
    async def test_intent_classification(self) -> None:
        classify = ConversationEngine._classify
        assert classify("why do you need that?") is Intent.ASK_RATIONALE
        assert classify("how much is left?") is Intent.ASK_STATUS
        assert classify("skip that one") is Intent.SKIP
        assert classify("that's everything, generate the document") is Intent.FINALIZE
        assert classify("let me come back later") is Intent.PAUSE
        assert classify("Priya owns it") is Intent.PROVIDE_INFO

    async def test_a_long_message_starting_with_actually_is_still_information(self) -> None:
        # "actually" opens plenty of substantive answers; only treat a short
        # message as a bare correction.
        text = "actually the owner is Priya and we are targeting the fifteenth of March"
        assert ConversationEngine._classify(text) is Intent.PROVIDE_INFO

    async def test_one_message_can_answer_several_fields(
        self, registry: FormRegistry, simple_form: FormDefinition
    ) -> None:
        provider = StubProvider(
            [extraction(("owner", "Priya Raman", 0.95), ("risk_level", "high", 0.9))]
        )
        service = make_service(registry, provider)
        started = await service.start_session("test_form", participant="alice")

        result = await service.send(
            started["session_id"], "Priya Raman owns it and it's high risk."
        )
        assert set(result.captured) == {"owner", "risk_level"}

    async def test_a_settled_field_is_never_asked_about_again(self, registry: FormRegistry) -> None:
        provider = StubProvider([extraction(("owner", "Priya", 0.95))])
        service = make_service(registry, provider)
        started = await service.start_session("test_form", participant="alice")

        result = await service.send(started["session_id"], "Priya owns it")
        assert "owner" in result.captured
        assert "owner" not in result.targeted_fields

    async def test_low_confidence_extraction_is_held_for_confirmation(
        self, registry: FormRegistry
    ) -> None:
        provider = StubProvider([extraction(("owner", "maybe Priya", 0.4))])
        service = make_service(registry, provider)
        started = await service.start_session("test_form", participant="alice")

        result = await service.send(started["session_id"], "I think Priya handles this?")
        assert "owner" in result.needs_confirmation
        assert "owner" not in result.captured

        session = await service.get_session(started["session_id"])
        assert session.answers["owner"].state is AnswerState.PROPOSED

    async def test_explicit_only_fields_reject_low_confidence_inference(
        self, registry: FormRegistry
    ) -> None:
        # target_date is require_explicit: a hedged mention must not be stored.
        provider = StubProvider([extraction(("target_date", "2026-03-15", 0.5))])
        service = make_service(registry, provider)
        started = await service.start_session("test_form", participant="alice")

        result = await service.send(started["session_id"], "probably mid March some time")
        assert "target_date" not in result.captured
        assert "target_date" not in result.needs_confirmation

    async def test_asking_why_answers_from_the_form_rationale(self, registry: FormRegistry) -> None:
        service = make_service(registry, StubProvider())
        started = await service.start_session("test_form", participant="alice")

        result = await service.send(started["session_id"], "why do you need the owner?")
        assert result.intent is Intent.ASK_RATIONALE
        # Verbatim from the definition, not invented by the model.
        assert "Someone must be accountable for this." in result.reply

    async def test_status_request_reports_progress(self, registry: FormRegistry) -> None:
        provider = StubProvider([extraction(("owner", "Priya", 0.95))])
        service = make_service(registry, provider)
        started = await service.start_session("test_form", participant="alice")
        await service.send(started["session_id"], "Priya owns it")

        result = await service.send(started["session_id"], "how much is left?")
        assert result.intent is Intent.ASK_STATUS
        assert "1 of 3" in result.reply

    async def test_skipping_a_mandatory_field_creates_an_action_item(
        self, registry: FormRegistry
    ) -> None:
        service = make_service(registry, StubProvider())
        started = await service.start_session("test_form", participant="alice")
        sid = started["session_id"]

        result = await service.send(sid, "skip the owner for now")
        assert result.intent is Intent.SKIP

        session = await service.get_session(sid)
        assert "owner" in session.skipped_fields

        from sa_forms.models import FormSession

        form = registry.get("test_form")
        items = derive_action_items(form, session)
        assert any(i.source_field_id == "owner" for i in items)
        assert isinstance(session, FormSession)

    async def test_finalize_is_refused_while_mandatory_fields_are_open(
        self, registry: FormRegistry
    ) -> None:
        service = make_service(registry, StubProvider())
        started = await service.start_session("test_form", participant="alice")

        result = await service.send(started["session_id"], "that's everything, generate it")
        assert result.intent is Intent.FINALIZE
        assert "still open" in result.reply
        assert not result.ready_for_review

    async def test_a_session_resumes_for_the_same_participant(self, registry: FormRegistry) -> None:
        provider = StubProvider([extraction(("owner", "Priya", 0.95))])
        service = make_service(registry, provider)

        first = await service.start_session("test_form", participant="alice")
        await service.send(first["session_id"], "Priya owns it")

        # Same person, later. They get their own session back, not a blank one.
        second = await service.start_session("test_form", participant="alice")
        assert second["session_id"] == first["session_id"]
        assert second["resumed"] is True

    async def test_a_different_participant_gets_a_new_session(self, registry: FormRegistry) -> None:
        service = make_service(registry, StubProvider())
        first = await service.start_session("test_form", participant="alice")
        second = await service.start_session("test_form", participant="bob")
        assert first["session_id"] != second["session_id"]

    async def test_directly_set_answers_are_confirmed_and_not_overwritten(
        self, registry: FormRegistry
    ) -> None:
        provider = StubProvider([extraction(("owner", "Someone Else", 0.99))])
        service = make_service(registry, provider)
        started = await service.start_session("test_form", participant="alice")
        sid = started["session_id"]

        await service.set_answer(sid, "owner", "Priya Raman")
        await service.send(sid, "I heard Someone Else is doing it")

        session = await service.get_session(sid)
        assert session.answers["owner"].value == "Priya Raman"
        assert session.answers["owner"].state is AnswerState.CONFIRMED

    async def test_setting_an_unknown_field_is_rejected(self, service: FormsService) -> None:
        started = await service.start_session("test_form", participant="alice")
        with pytest.raises(Exception, match="no field"):
            await service.set_answer(started["session_id"], "not_a_field", "x")

    async def test_provenance_records_channel_author_and_evidence(
        self, registry: FormRegistry
    ) -> None:
        provider = StubProvider([extraction(("owner", "Priya Raman", 0.95))])
        service = make_service(registry, provider)
        started = await service.start_session("test_form", participant="alice")

        await service.send(
            started["session_id"], "Priya Raman owns it", author="alice", channel="chat"
        )
        session = await service.get_session(started["session_id"])
        provenance = session.answers["owner"].provenance

        assert provenance is not None
        assert provenance.author == "alice"
        assert provenance.channel is SourceChannel.CHAT
        assert provenance.evidence == "Priya Raman"


# ---------------------------------------------------------------------------
# Behaviour derived from a real intake session
#
# Every test below encodes something an operator hit while filling in a change
# request by hand. They are grouped rather than scattered because the failures
# share a cause: the engine was strict where a person was being reasonable, and
# lenient where the record had to be trustworthy.
# ---------------------------------------------------------------------------


class TestNaturalLanguageDates:
    def _field(self) -> FormField:
        return FormField(id="d", label="Target date", type=FieldType.DATE)

    def test_a_weekday_resolves_to_the_next_occurrence(self) -> None:
        # Wednesday 2026-08-05 → the coming Friday.
        found = resolve_date("next Friday", reference=date(2026, 8, 5))
        assert found is not None
        assert found.iso == "2026-08-07"
        assert found.inferred

    def test_a_bare_month_and_day_takes_the_year_from_context(self) -> None:
        assert resolve_date("Aug 15", reference=date(2026, 8, 5)).iso == "2026-08-15"
        assert resolve_date("15th August", reference=date(2026, 8, 5)).iso == "2026-08-15"
        # Already gone this year: nobody schedules a change into the past.
        assert resolve_date("Aug 15", reference=date(2026, 9, 1)).iso == "2027-08-15"

    def test_offsets_and_boundaries_resolve(self) -> None:
        reference = date(2026, 8, 5)
        assert resolve_date("tomorrow", reference=reference).iso == "2026-08-06"
        assert resolve_date("in 2 weeks", reference=reference).iso == "2026-08-19"
        assert resolve_date("end of the month", reference=reference).iso == "2026-08-31"

    def test_a_week_offset_and_a_named_day_are_one_expression(self) -> None:
        """ "In a couple of weeks over the weekend" names a day.

        Reading only the second half lands two weeks early; reading only the
        first lands on a Saturday's Wednesday. Both halves, or the participant
        ends up saying it four more times.
        """
        reference = date(2026, 8, 8)  # a Saturday
        assert resolve_date("in a couple of weeks over the weekend", reference=reference).iso == (
            "2026-08-22"
        )
        assert resolve_date("in two weeks on Friday", reference=reference).iso == "2026-08-21"
        assert resolve_date("over the weekend", reference=reference).iso == "2026-08-15"
        assert resolve_date("in a few days", reference=reference).iso == "2026-08-11"

    def test_the_nth_weekday_of_a_month(self) -> None:
        """ "The last Sunday of September" is one phrase.

        Reading only the "Sunday" answers with the next one — a confident,
        specific, wrong date, which is worse than not understanding at all. It
        is what recorded a change for tomorrow when the owner said September.
        """
        reference = date(2026, 8, 8)
        assert resolve_date("last Sunday of September", reference=reference).iso == "2026-09-27"
        assert resolve_date("the last Sunday of Sept", reference=reference).iso == "2026-09-27"
        assert resolve_date("last Sunday of this quarter", reference=reference).iso == "2026-09-27"
        assert resolve_date("first Monday of October", reference=reference).iso == "2026-10-05"
        assert resolve_date("second Tuesday of next month", reference=reference).iso == "2026-09-08"
        assert resolve_date("last Friday of the month", reference=reference).iso == "2026-08-28"

    def test_a_backwards_weekday_is_refused(self) -> None:
        """ "Last Friday" points at the past, which no target date means."""
        assert resolve_date("last Friday", reference=date(2026, 8, 8)) is None

    def test_a_period_is_not_a_date(self) -> None:
        """ "Next quarter" names thirteen weeks. Picking a day out of it invents
        a decision the speaker has not made — better to ask."""
        assert resolve_date("sometime next quarter", reference=date(2026, 8, 5)) is None
        assert resolve_date("31 February", reference=date(2026, 8, 5)) is None

    def test_coercion_accepts_what_people_actually_say(self) -> None:
        field = self._field()
        assert coerce_and_validate(field, "Aug 15") == resolve_date("Aug 15").iso
        assert coerce_and_validate(field, "next Friday") == resolve_date("next Friday").iso

    def test_a_resolved_date_is_flagged_for_confirmation(self) -> None:
        """The value is accepted, but the speaker never said the year — so it is
        read back rather than scheduled on their behalf."""
        field = self._field()
        assert date_is_inferred(field, "next Friday")
        assert date_is_inferred(field, "Aug 15")
        assert not date_is_inferred(field, "2026-08-15")
        assert not date_is_inferred(field, "15 Mar 2026")

    async def test_an_inferred_date_is_held_as_proposed(self, registry: FormRegistry) -> None:
        provider = StubProvider([extraction(("target_date", "next Friday", 0.95))])
        service = make_service(registry, provider)
        started = await service.start_session("test_form", participant="alice")

        result = await service.send(started["session_id"], "we're going next Friday")
        assert "target_date" in result.needs_confirmation
        assert "target_date" not in result.captured

        session = await service.get_session(started["session_id"])
        assert session.answers["target_date"].value == resolve_date("next Friday").iso


class TestValuesThatAreNotAnswers:
    def test_a_bare_yes_is_not_a_value(self) -> None:
        """ "Do you have a ticket?" — "yes" answers the question and records
        nothing. `Tracking ticket: yes` is worse than an empty field, which at
        least becomes an action item."""
        field = FormField(id="t", label="Tracking ticket", type=FieldType.STRING)
        with pytest.raises(CoercionError, match="actual value"):
            coerce_and_validate(field, "yes")
        assert coerce_and_validate(field, "OPS-1423") == "OPS-1423"

    def test_a_person_field_rejects_a_first_person_reference(self) -> None:
        field = FormField(id="o", label="Change owner", type=FieldType.PERSON)
        with pytest.raises(CoercionError, match="needs a name"):
            coerce_and_validate(field, "myself")

    async def test_me_resolves_to_the_speaker(self, registry: FormRegistry) -> None:
        provider = StubProvider([extraction(("owner", "me", 0.95))])
        service = make_service(registry, provider)
        started = await service.start_session("test_form", participant="alice")

        await service.send(started["session_id"], "I own it", author="priya.raman")
        session = await service.get_session(started["session_id"])
        assert session.answers["owner"].value == "priya.raman"

    async def test_an_anonymous_speaker_is_asked_for_a_name(self, registry: FormRegistry) -> None:
        """With nothing to resolve "me" to, storing it would name nobody."""
        provider = StubProvider([extraction(("owner", "myself", 0.95))])
        service = make_service(registry, provider)
        started = await service.start_session("test_form", participant="alice")

        result = await service.send(started["session_id"], "I own it", author="user")
        assert "owner" not in result.captured
        session = await service.get_session(started["session_id"])
        assert session.answers["owner"].state is AnswerState.EMPTY


class TestAskingTheSameThingTwice:
    async def test_a_repeatedly_unanswered_field_stops_setting_the_agenda(
        self, service: FormsService, simple_form: FormDefinition
    ) -> None:
        started = await service.start_session("test_form", participant="alice")
        session = await service.get_session(started["session_id"])
        session.note_asked(["owner"])
        session.note_asked(["owner"])
        assert session.stalled_fields() == {"owner"}

        _, fields = next_topic(
            simple_form, analyse(simple_form, session), stalled=session.stalled_fields()
        )
        assert "owner" not in [f.id for f in fields]

    async def test_a_stalled_field_still_blocks_completion(
        self, service: FormsService, simple_form: FormDefinition
    ) -> None:
        """Dropping it from the agenda is a courtesy, not a waiver."""
        started = await service.start_session("test_form", participant="alice")
        session = await service.get_session(started["session_id"])
        session.note_asked(["owner"])
        session.note_asked(["owner"])
        assert not analyse(simple_form, session).mandatory_complete

    def test_one_prose_field_per_question(self) -> None:
        """Two "describe X" asks in one breath come back as one run-on answer,
        and splitting it between the fields is guesswork."""
        section = FormSection(
            id="risk",
            title="Risk",
            fields=[
                FormField(id="tested", label="Tested", type=FieldType.BOOLEAN),
                FormField(id="blast", label="Blast radius", type=FieldType.TEXT),
                FormField(id="monitoring", label="Monitoring", type=FieldType.TEXT),
            ],
        )
        form = FormDefinition(name="f", version="1.0.0", title="F", sections=[section])
        session = FormSession(form_name="f", form_version="1.0.0")

        _, fields = next_topic(form, analyse(form, session))
        prose = [f.id for f in fields if f.type is FieldType.TEXT]
        assert len(prose) == 1


class TestNotListening:
    """The failures that make somebody give up on a form.

    Every case here is from one real session: a question asked again after it
    was answered, a complaint about it ignored, and a typo raised as though it
    were a contradiction. None of them is a crash and all of them cost the
    participant more than the thing they were reporting.
    """

    async def test_the_planner_shows_the_model_what_is_already_answered(
        self, registry: FormRegistry
    ) -> None:
        """Telling a model not to re-ask is weaker than showing it the answer.

        It cannot ask for a date it can see, and the participant saying "I
        already answered that" three times is what this prevents.
        """
        provider = StubProvider([extraction(("owner", "Priya Raman", 0.95))])
        service = make_service(registry, provider)
        sid = (await service.start_session("test_form", participant="alice"))["session_id"]

        provider.prompts.clear()
        await service.send(sid, "Priya Raman owns it")

        prompt = " ".join(provider.prompts)
        assert "Already answered" in prompt
        assert "Owner: Priya Raman" in prompt

    async def test_i_already_answered_that_is_met_with_the_recorded_value(
        self, registry: FormRegistry
    ) -> None:
        provider = StubProvider([extraction(("owner", "Priya Raman", 0.95))])
        service = make_service(registry, provider)
        sid = (await service.start_session("test_form", participant="alice"))["session_id"]
        await service.send(sid, "Priya Raman owns it")

        result = await service.send(sid, "I already answerd that")

        assert result.intent is Intent.ALREADY_ANSWERED
        assert "Priya Raman" in result.reply

    async def test_it_admits_when_an_answer_never_reached_the_record(
        self, registry: FormRegistry
    ) -> None:
        """Usually the reason somebody says this. Asking a fourth time is not
        the answer; saying plainly that it did not land is."""
        service = make_service(registry, StubProvider([extraction()]))
        sid = (await service.start_session("test_form", participant="alice"))["session_id"]
        await service.send(sid, "the owner is obviously me")

        result = await service.send(sid, "didn't I answer that already?")

        assert "didn't reach the record" in result.reply
        assert "owner" in result.reply.lower()

    async def test_an_answer_is_not_lost_because_its_own_guard_was_still_shut(
        self, registry: FormRegistry
    ) -> None:
        """The root cause of "I already told you".

        One message says both "customers are affected" and "the platform team
        will tell them". The first settles the guard on the second — but the
        second was not a gap when the message arrived, so it was never offered
        to the extractor and the answer was thrown away. Two turns later the
        engine asks who tells the customers, and they had already said.
        """
        form = FormDefinition(
            name="guarded",
            version="1.0.0",
            title="Guarded",
            status=FormStatus.ACTIVE,
            sections=[
                FormSection(
                    id="s",
                    title="S",
                    fields=[
                        FormField(
                            id="impacted",
                            label="Customers impacted",
                            type=FieldType.BOOLEAN,
                            importance=Importance.MANDATORY,
                        ),
                        FormField(
                            id="comms_owner",
                            label="Comms owner",
                            type=FieldType.PERSON,
                            importance=Importance.MANDATORY,
                            ask_when="${answers.impacted == true}",
                        ),
                    ],
                )
            ],
        )
        reg = FormRegistry()
        reg.create(form, activate=True)
        provider = StubProvider(
            [
                extraction(("impacted", "yes", 0.95)),
                extraction(("comms_owner", "Platform Support", 0.9)),
            ]
        )
        service = make_service(reg, provider)
        sid = (await service.start_session("guarded", participant="op"))["session_id"]

        result = await service.send(
            sid, "customers will notice, and platform support will tell them", author="op"
        )

        assert "comms_owner" in result.captured
        session = await service.get_session(sid)
        assert session.answers["comms_owner"].value == "Platform Support"

    async def test_a_protest_that_carries_an_answer_keeps_the_answer(
        self, registry: FormRegistry
    ) -> None:
        """ "Didn't I answer that — it's reviewed by Haja" is a complaint *and*
        an answer. Skipping extraction threw the name away and asked for it
        again, so it had to be said a third time."""
        provider = StubProvider([extraction(("owner", "Haja", 0.95))])
        service = make_service(registry, provider)
        sid = (await service.start_session("test_form", participant="op"))["session_id"]

        result = await service.send(sid, "didn't I already say the owner is Haja")

        assert result.intent is Intent.ALREADY_ANSWERED
        session = await service.get_session(sid)
        assert session.answers["owner"].value == "Haja"
        assert "landed now" in result.reply

    def test_the_word_the_assistant_asks_for_is_recognised(self) -> None:
        """The message above it says *Say 'generate' to produce the document*,
        and typing exactly that got the same summary back again."""
        classify = ConversationEngine._classify
        for word in ("generate", "Generate", "generate it", "go ahead", "produce the document"):
            assert classify(word) is Intent.FINALIZE, word

    def test_no_issues_is_not_a_refusal(self) -> None:
        """The worst thing consent detection can get wrong: a decline recorded
        against a term the person just accepted."""
        from sa_forms.agreements import read_decision

        assert read_decision("no issues") is AgreementDecision.ACCEPTED
        assert read_decision("all good") is AgreementDecision.ACCEPTED
        assert read_decision("looks good") is AgreementDecision.ACCEPTED
        assert read_decision("no") is AgreementDecision.DECLINED
        assert read_decision("I can not accept this") is AgreementDecision.DECLINED

    def test_the_same_objection_is_not_raised_under_a_new_name(self) -> None:
        """Ids come from the model's wording, so one objection about one field
        arrives three times with three ids and reads as new each time. In a real
        session that put the same field to the owner four times running."""
        from sa_forms.consistency import merge

        session = FormSession(form_name="f", form_version="1.0.0")
        session.consistency_findings.append(
            ConsistencyFinding(
                id="downtime_not_standard",
                message="The downtime is not a standard duration.",
                fields=["expected_downtime"],
                state=FindingState.ACKNOWLEDGED,
                resolution="Both are the same thing.",
            )
        )

        merge(
            session,
            [
                ConsistencyFinding(
                    id="downtime_description_mismatch",
                    message="The downtime description differs from what was said.",
                    fields=["expected_downtime"],
                )
            ],
        )
        assert not [f for f in session.consistency_findings if f.is_outstanding]

    async def test_how_much_is_asked_at_once_follows_the_person(
        self, registry: FormRegistry
    ) -> None:
        """Somebody answering in paragraphs has more in their head than three
        items; somebody answering in three words has less."""
        service = make_service(registry, StubProvider())
        sid = (await service.start_session("test_form", participant="op"))["session_id"]
        session = await service.get_session(sid)
        engine = service.conversation

        assert engine._batch_size(session) == 4  # nothing to go on yet

        session.record(TranscriptEntry(role="user", text=" ".join(["word"] * 60), author="op"))
        assert engine._batch_size(session) == 6

        terse = FormSession(form_name="test_form", form_version="1.0.0")
        terse.record(TranscriptEntry(role="user", text="yes", author="op"))
        assert engine._batch_size(terse) == 2

    async def test_the_first_substantive_turn_is_an_invitation(
        self, registry: FormRegistry
    ) -> None:
        """Naming three things tells them the shape of the answer you want, and
        they give you three things — when they arrived with all twelve."""
        provider = StubProvider()
        service = make_service(registry, provider)
        await service.start_session("test_form", participant="op")

        assert "ASKING STYLE: opening invitation" in " ".join(provider.prompts)

    def test_a_typo_is_not_a_contradiction(self) -> None:
        """Three of these in one session, each costing a turn to be told about
        a letter, each blocking the document behind an unanswerable question."""
        from sa_forms.consistency import is_about_wording

        assert is_about_wording('The rollback plan contains a typo: "procerdures".')
        assert is_about_wording("The blast radius description has a spelling mistake.")
        assert not is_about_wording(
            "An outage is expected but the change is marked as not customer impacting."
        )

    def test_writing_an_answer_down_properly_is_not_a_discrepancy(self) -> None:
        """ "Recorded as 02:00-22:00 IST but stated as 2AM to 10PM IST" is this
        platform's own wording pass, reported back as the participant's
        contradiction."""
        from sa_forms.consistency import is_normalisation_artefact

        form = FormDefinition(
            name="w",
            version="1.0.0",
            title="W",
            sections=[
                FormSection(
                    id="s", title="S", fields=[FormField(id="window", label="Maintenance window")]
                )
            ],
        )
        session = FormSession(form_name="w", form_version="1.0.0")
        answer = session.answer_for("window")
        answer.value, answer.raw_value = "02:00 IST and 22:00 IST", "2AM IST and 10 PM IST"
        answer.state, answer.polished = AnswerState.ANSWERED, True

        assert is_normalisation_artefact(
            'The window is recorded as "02:00 IST and 22:00 IST" but was stated as '
            '"2AM IST and 10 PM IST".',
            form,
            session,
        )
        assert not is_normalisation_artefact(
            "The downtime is longer than the window it has to fit inside.", form, session
        )

    def test_a_corrected_value_is_no_longer_a_written_up_one(self) -> None:
        """The flag survived the correction, so the record claimed a polished
        value while holding raw text — and a late correction is exactly the text
        most likely to reach the document as typed."""
        answer = FieldAnswer(
            field_id="rollback_plan", value="Follow the standard procedures.", polished=True
        )
        answer.supersede_with(
            "standard procerdures have it to ds=isable the changes through flag",
            raw_value="standard procerdures have it to ds=isable the changes through flag",
            state=AnswerState.ANSWERED,
            confidence=0.9,
            provenance=None,
        )
        assert answer.polished is False


class TestCompletionIsNotJustSilence:
    async def test_skipping_the_last_question_does_not_complete_the_form(
        self, registry: FormRegistry
    ) -> None:
        """The regression this class exists for.

        With every remaining question skipped there is nothing left to *ask*,
        which is not the same as nothing left to *answer*. The engine used to
        announce "That's everything", print the summary with the missing field
        rendered as `_(not provided)_`, and move the session to review — while
        `finalize` on the very same state would have refused.
        """
        provider = StubProvider(
            [
                extraction(("owner", "Priya Raman", 0.95)),
                extraction(("risk_level", "low", 0.95)),
            ]
        )
        service = make_service(registry, provider)
        sid = (await service.start_session("test_form", participant="alice"))["session_id"]

        await service.send(sid, "Priya Raman owns it")
        await service.send(sid, "skip the target date")
        await service.send(sid, "risk is low")
        result = await service.send(sid, "skip the notes")

        assert not result.ready_for_review
        assert "Target date" in result.reply
        session = await service.get_session(sid)
        assert session.status is not SessionStatus.READY_FOR_REVIEW
        # And the gap is on the record rather than only in the reply.
        assert any(a.source_field_id == "target_date" for a in session.action_items)

    async def test_a_genuinely_complete_form_still_completes(self, registry: FormRegistry) -> None:
        provider = StubProvider(
            [
                extraction(
                    ("owner", "Priya Raman", 0.95),
                    ("target_date", "2026-03-15", 0.95),
                    ("risk_level", "low", 0.95),
                ),
            ]
        )
        service = make_service(registry, provider)
        sid = (await service.start_session("test_form", participant="alice"))["session_id"]

        await service.send(sid, "Priya owns it, 2026-03-15, low risk")
        result = await service.send(sid, "skip the notes")

        assert result.ready_for_review
        assert "That's everything" in result.reply


class TestProposingAValue:
    async def test_asking_for_help_is_not_a_request_for_justification(self) -> None:
        classify = ConversationEngine._classify
        assert classify("what do you think the risk level is?") is Intent.ASK_ASSISTANCE
        assert classify("why can't you work that out yourself?") is Intent.ASK_ASSISTANCE
        # Still distinct from the neighbouring intents.
        assert classify("why do you need that?") is Intent.ASK_RATIONALE
        assert classify("what do you mean by blast radius?") is Intent.ASK_CLARIFICATION

    async def test_a_proposal_is_recorded_but_never_counted_as_answered(
        self, registry: FormRegistry
    ) -> None:
        provider = StubProvider(
            suggestions=[
                {
                    "field_id": "risk_level",
                    "value": "high",
                    "reasoning": "You said it takes the whole platform down for 4-6 hours.",
                    "confident": True,
                }
            ]
        )
        service = make_service(registry, provider)
        sid = (await service.start_session("test_form", participant="alice"))["session_id"]

        result = await service.send(sid, "what do you think the risk level should be?")
        assert result.intent is Intent.ASK_ASSISTANCE
        assert "high" in result.reply

        session = await service.get_session(sid)
        answer = session.answers["risk_level"]
        assert answer.value == "high"
        # The judgement stays the participant's until they say so.
        assert answer.state is AnswerState.PROPOSED
        assert not analyse(
            service.conversation.registry.get("test_form", "1.0.0"), session
        ).mandatory_complete

    async def test_yes_promotes_a_proposal_to_an_answer(self, registry: FormRegistry) -> None:
        """Without this a proposal is a dead end: a bare "yes" carries nothing
        for the extractor to find, so the field would be re-proposed forever."""
        provider = StubProvider(
            suggestions=[
                {
                    "field_id": "risk_level",
                    "value": "high",
                    "reasoning": "Four hours of downtime on a shared platform.",
                    "confident": True,
                }
            ]
        )
        service = make_service(registry, provider)
        sid = (await service.start_session("test_form", participant="alice"))["session_id"]

        await service.send(sid, "what do you think the risk level should be?")
        result = await service.send(sid, "yes")

        assert result.intent is Intent.CONFIRM
        session = await service.get_session(sid)
        assert session.answers["risk_level"].state is AnswerState.CONFIRMED

    async def test_an_unsupported_proposal_says_so_rather_than_guessing(
        self, registry: FormRegistry
    ) -> None:
        provider = StubProvider(
            suggestions=[
                {
                    "field_id": "risk_level",
                    "value": "",
                    "reasoning": "nothing said so far points at a risk level",
                    "confident": False,
                }
            ]
        )
        service = make_service(registry, provider)
        sid = (await service.start_session("test_form", participant="alice"))["session_id"]

        result = await service.send(sid, "what do you think the risk level should be?")
        session = await service.get_session(sid)
        assert session.answers.get("risk_level") is None
        assert "can't call this one" in result.reply

    async def test_a_confirmation_gets_the_turn_to_itself(self, registry: FormRegistry) -> None:
        """Asking someone to say yes to one thing and answer another in the
        same breath makes the "yes" ambiguous — it reads as an answer to
        whichever the extractor liked better, and nobody knows which was heard.
        """
        provider = StubProvider([extraction(("target_date", "next Friday", 0.95))])
        service = make_service(registry, provider)
        sid = (await service.start_session("test_form", participant="alice"))["session_id"]

        result = await service.send(sid, "we're going next Friday")

        assert result.targeted_fields == ["target_date"]
        assert result.needs_confirmation == ["target_date"]

    async def test_the_next_questions_follow_the_confirmation(self, registry: FormRegistry) -> None:
        provider = StubProvider([extraction(("target_date", "next Friday", 0.95))])
        service = make_service(registry, provider)
        sid = (await service.start_session("test_form", participant="alice"))["session_id"]
        await service.send(sid, "we're going next Friday")

        result = await service.send(sid, "yes")

        assert "target_date" not in result.targeted_fields
        assert result.targeted_fields  # the conversation moved on

    async def test_a_confirmation_can_be_skipped(self, registry: FormRegistry) -> None:
        """ "Skip it" and "I'll come back later" are answers to a confirmation
        too, and both have to move the conversation forward."""
        provider = StubProvider([extraction(("target_date", "next Friday", 0.95))])
        service = make_service(registry, provider)
        sid = (await service.start_session("test_form", participant="alice"))["session_id"]
        await service.send(sid, "we're going next Friday")

        result = await service.send(sid, "skip that for now")

        assert result.intent is Intent.SKIP
        session = await service.get_session(sid)
        assert session.answers["target_date"].state is AnswerState.SKIPPED

    async def test_agreement_buried_in_a_sentence_still_confirms(
        self, registry: FormRegistry
    ) -> None:
        """ "Yes that's right for the date, and didn't I tell you the risk?"

        Nobody replies with a bare "yes". Requiring one is what produced
        "again and again am saying" in a real session: the value stayed
        unconfirmed and kept coming back.
        """
        provider = StubProvider([extraction(("target_date", "next Friday", 0.95))])
        service = make_service(registry, provider)
        sid = (await service.start_session("test_form", participant="alice"))["session_id"]
        await service.send(sid, "we're going next Friday")

        session = await service.get_session(sid)
        assert session.answers["target_date"].state is AnswerState.PROPOSED

        await service.send(sid, "yes that's correct for the date, what else do you need?")

        session = await service.get_session(sid)
        assert session.answers["target_date"].state is AnswerState.CONFIRMED

    async def test_agreement_followed_by_a_correction_is_a_correction(
        self, registry: FormRegistry
    ) -> None:
        """ "Yes, but make it the 20th" must not confirm the old value."""
        provider = StubProvider(
            [
                extraction(("target_date", "next Friday", 0.95)),
                extraction(("target_date", "2026-03-20", 0.99)),
            ]
        )
        service = make_service(registry, provider)
        sid = (await service.start_session("test_form", participant="alice"))["session_id"]
        await service.send(sid, "we're going next Friday")

        await service.send(sid, "yes, but actually make it 2026-03-20")

        session = await service.get_session(sid)
        assert session.answers["target_date"].value == "2026-03-20"

    async def test_yes_still_answers_a_yes_no_question(self, registry: FormRegistry) -> None:
        """With nothing pending confirmation, "yes" is just an answer.

        The turn reports itself as information rather than a confirmation,
        because that is the path it actually took.
        """
        provider = StubProvider([extraction(("owner", "Priya", 0.95))])
        service = make_service(registry, provider)
        sid = (await service.start_session("test_form", participant="alice"))["session_id"]

        result = await service.send(sid, "yes")
        assert result.intent is Intent.PROVIDE_INFO
        assert "owner" in result.captured


# ---------------------------------------------------------------------------
# The wording pass
# ---------------------------------------------------------------------------


class TestTidying:
    """Deterministic clean-up. No model, no judgement."""

    def test_a_maintenance_window_reads_the_same_way_however_it_was_typed(self) -> None:
        field = FormField(id="w", label="Window", type=FieldType.STRING)
        assert tidy(field, "8AM ro 11PM") == "08:00-23:00"
        assert tidy(field, "8 am to 11 pm") == "08:00-23:00"
        assert tidy(field, "12AM till 12PM") == "00:00-12:00"
        # Already unambiguous: left alone apart from the separator.
        assert tidy(field, "22:00 - 23:30") == "22:00-23:30"

    def test_prose_gets_a_capital_and_a_full_stop(self) -> None:
        field = FormField(id="m", label="Monitoring", type=FieldType.TEXT)
        assert (
            tidy(field, "  from the start  log for   issues ") == "From the start log for issues."
        )

    def test_a_short_string_field_is_not_given_a_full_stop(self) -> None:
        field = FormField(id="s", label="System", type=FieldType.STRING)
        assert tidy(field, "ICMP") == "ICMP"


class TestRewriteGuards:
    """The rewrite must not become a way to add facts in better prose."""

    def test_a_number_nobody_stated_is_refused(self) -> None:
        assert "14" in check("12 hours downtime", "A 14 hour outage is expected.")

    def test_a_number_the_participant_stated_is_allowed(self) -> None:
        assert check("12 hours", "The outage lasts 12 hours.", context="we need 12 hours") == ""

    def test_padding_is_refused(self) -> None:
        reason = check(
            "revert the JDK",
            "Revert the JDK to the previously deployed build, restart every node in the "
            "cluster, and confirm health checks pass before releasing traffic.",
        )
        assert "elaboration" in reason

    def test_an_empty_rewrite_is_refused(self) -> None:
        assert check("something", "   ") == "empty"


class TestWordingPass:
    def _form(self, **overrides: Any) -> FormDefinition:
        field = FormField(
            id="monitoring",
            label="Monitoring plan",
            type=FieldType.TEXT,
            importance=Importance.MANDATORY,
            **overrides,
        )
        return FormDefinition(
            name="w",
            version="1.0.0",
            title="W",
            sections=[FormSection(id="s", title="S", fields=[field])],
        )

    def _session(self, form: FormDefinition, value: str) -> FormSession:
        session = FormSession(form_name=form.name, form_version=form.version)
        session.answers["monitoring"] = FieldAnswer(
            field_id="monitoring", value=value, raw_value=value, state=AnswerState.ANSWERED
        )
        return session

    async def test_the_document_reads_properly_and_the_record_stays_faithful(self) -> None:
        typed = "from the serivces start log for any issues"
        form = self._form()
        session = self._session(form, typed)
        provider = StubProvider(
            rewrites=[
                {
                    "field_id": "monitoring",
                    "value": "The service start log will be watched for errors",
                    "unchanged": False,
                }
            ]
        )

        applied = [r for r in await normalise(form, session, llm_provider=provider) if r.applied]

        answer = session.answers["monitoring"]
        assert answer.value == "The service start log will be watched for errors."
        assert answer.polished
        # What they actually typed is never lost.
        assert answer.raw_value == typed
        assert [r.field_id for r in applied] == ["monitoring"]

    async def test_a_rewrite_that_invents_a_number_is_discarded(self) -> None:
        """A field that reads awkwardly beats one that reads well and is wrong."""
        form = self._form()
        session = self._session(form, "watch the logs")
        provider = StubProvider(
            rewrites=[
                {
                    "field_id": "monitoring",
                    "value": "The logs will be watched for 48 hours.",
                    "unchanged": False,
                }
            ]
        )

        rewrites = await normalise(form, session, llm_provider=provider)

        assert session.answers["monitoring"].value == "Watch the logs."
        assert any("48" in r.rejected for r in rewrites)

    async def test_preserve_verbatim_is_left_exactly_as_typed(self) -> None:
        form = self._form(preserve_verbatim=True)
        session = self._session(form, "run   deploy.sh --force")
        provider = StubProvider(
            rewrites=[{"field_id": "monitoring", "value": "Run deploy.", "unchanged": False}]
        )

        await normalise(form, session, llm_provider=provider)

        assert session.answers["monitoring"].value == "run   deploy.sh --force"
        assert not session.answers["monitoring"].polished

    async def test_typed_values_are_never_sent_to_the_model(self) -> None:
        """Coercion already produces a canonical date. A rewrite is all risk."""
        form = FormDefinition(
            name="w",
            version="1.0.0",
            title="W",
            sections=[
                FormSection(
                    id="s",
                    title="S",
                    fields=[
                        FormField(id="go_live", label="Go live", type=FieldType.DATE),
                        FormField(
                            id="risk", label="Risk", type=FieldType.ENUM, options=["low", "high"]
                        ),
                    ],
                )
            ],
        )
        session = FormSession(form_name="w", form_version="1.0.0")
        for fid, value in (("go_live", "2026-08-22"), ("risk", "high")):
            session.answers[fid] = FieldAnswer(
                field_id=fid, value=value, state=AnswerState.ANSWERED
            )
        provider = StubProvider()

        assert await normalise(form, session, llm_provider=provider) == []
        assert provider.prompts == []

    async def test_tidying_still_happens_when_the_model_is_unavailable(self) -> None:
        class Broken:
            async def complete_structured(self, *a: Any, **k: Any) -> Any:
                raise RuntimeError("no model")

        form = self._form()
        session = self._session(form, "8AM ro 11PM window watched")

        await normalise(form, session, llm_provider=Broken())

        assert session.answers["monitoring"].value.startswith("08:00-23:00")


class TestTimezones:
    """A clock time with no zone is only unambiguous to whoever typed it."""

    def _field(self) -> FormField:
        return FormField(
            id="window",
            label="Maintenance window",
            type=FieldType.STRING,
            requires_timezone=True,
        )

    def test_a_time_without_a_zone_is_refused(self) -> None:
        with pytest.raises(CoercionError, match="no timezone"):
            coerce_and_validate(self._field(), "8AM ro 11PM")

    def test_every_way_of_saying_the_zone_is_accepted(self) -> None:
        field = self._field()
        for raw in (
            "8AM to 11PM IST",
            "22:00-23:30 UTC",
            "Saturday 02:00-04:00 +05:30",
            "08:00-23:00 Asia/Kolkata",
            "22:00 to 23:30 GMT+1",
        ):
            assert coerce_and_validate(field, raw) == raw

    def test_a_value_with_no_time_at_all_needs_no_zone(self) -> None:
        assert coerce_and_validate(self._field(), "overnight") == "overnight"

    def test_the_zone_survives_the_wording_pass(self) -> None:
        assert tidy(self._field(), "8AM ro 11PM IST") == "08:00-23:00 IST"

    async def test_answering_with_just_the_zone_completes_the_window(
        self, registry: FormRegistry
    ) -> None:
        """They should not have to retype the window to answer "which zone?"."""
        form = FormDefinition(
            name="win",
            version="1.0.0",
            title="Win",
            semantic_consistency_review=False,
            sections=[
                FormSection(
                    id="s",
                    title="S",
                    fields=[
                        FormField(
                            id="window",
                            label="Maintenance window",
                            type=FieldType.STRING,
                            importance=Importance.MANDATORY,
                            requires_timezone=True,
                        )
                    ],
                )
            ],
        )
        reg = FormRegistry()
        reg.create(form, activate=True)
        provider = StubProvider([extraction(("window", "8AM ro 11PM", 0.9))])
        service = make_service(reg, provider)
        sid = (await service.start_session("win", participant="alice"))["session_id"]

        result = await service.send(sid, "8AM ro 11PM")
        assert "window" not in result.captured
        assert "timezone" in (await service.get_session(sid)).answers["window"].note

        await service.send(sid, "IST")

        answer = (await service.get_session(sid)).answers["window"]
        # Repaired, then written up by the wording pass in the same breath.
        assert answer.value == "08:00-23:00 IST"
        assert answer.is_settled

    async def test_a_fresh_time_is_a_new_answer_not_a_zone(self) -> None:
        """ "9AM to 5PM UTC" replaces the window; it does not get appended."""
        session = FormSession(form_name="f", form_version="1.0.0")
        form = FormDefinition(
            name="f",
            version="1.0.0",
            title="F",
            sections=[
                FormSection(
                    id="s",
                    title="S",
                    fields=[
                        FormField(
                            id="window", label="W", type=FieldType.STRING, requires_timezone=True
                        )
                    ],
                )
            ],
        )
        session.answers["window"] = FieldAnswer(
            field_id="window", raw_value="8AM to 11PM", note="timezone missing"
        )

        repaired = ConversationEngine._apply_timezone(
            form, session, SourceMessage(text="9AM to 5PM UTC", author="alice")
        )

        assert repaired == []


class TestNamedResponsibility:
    """A responsibility may sit with a person or a team — but it must be named."""

    def _field(self, **overrides: Any) -> FormField:
        return FormField(id="p", label="Technical reviewer", type=FieldType.PERSON, **overrides)

    def test_a_named_team_is_a_perfectly_good_answer(self) -> None:
        field = self._field(requires_named_party=True)
        for raw in ("Platform Support", "iDocs Development Team", "Payments Squad"):
            assert coerce_and_validate(field, raw) == raw

    def test_a_group_nobody_can_identify_is_refused(self) -> None:
        """ "My scrum team" is clear in the conversation and unresolvable after
        it — which is when the artifact starts being read."""
        field = self._field(requires_named_party=True)
        for raw in ("my scrum team", "the team", "our platform team"):
            with pytest.raises(CoercionError, match="needs a name"):
                coerce_and_validate(field, raw)

    def test_a_role_is_not_a_person_either(self) -> None:
        field = self._field(requires_named_party=True)
        for raw in ("the DBA", "a developer", "the developer of iDocs"):
            with pytest.raises(CoercionError, match="rather than a role"):
                coerce_and_validate(field, raw)

    def test_a_qualifier_does_not_turn_a_role_into_a_person(self) -> None:
        """ "The developer of iDocs" sounds specific and names nobody: posts are
        held by whoever is in them this quarter."""
        field = self._field(requires_named_party=True)
        with pytest.raises(CoercionError):
            coerce_and_validate(field, "the scrum master for payments")

    def test_a_name_is_accepted(self) -> None:
        field = self._field(requires_named_party=True)
        assert coerce_and_validate(field, "Chandra") == "Chandra"

    def test_a_plain_person_field_accepts_anything(self) -> None:
        """The rule is opt-in; most person fields have no such requirement."""
        field = FormField(id="c", label="Comms owner", type=FieldType.PERSON)
        assert coerce_and_validate(field, "the team") == "the team"


# ---------------------------------------------------------------------------
# Cross-field consistency
# ---------------------------------------------------------------------------


def consistent_form() -> FormDefinition:
    """A form whose fields can contradict each other, like a real one."""
    return FormDefinition(
        name="release",
        version="1.0.0",
        title="Release",
        status=FormStatus.ACTIVE,
        semantic_consistency_review=False,
        sections=[
            FormSection(
                id="plan",
                title="Plan",
                fields=[
                    FormField(
                        id="downtime",
                        label="Downtime",
                        type=FieldType.STRING,
                        importance=Importance.MANDATORY,
                    ),
                    FormField(
                        id="customer_impacting",
                        label="Customer impacting",
                        type=FieldType.BOOLEAN,
                        importance=Importance.MANDATORY,
                    ),
                    FormField(id="owner", label="Owner", type=FieldType.PERSON),
                    FormField(id="reviewer", label="Reviewer", type=FieldType.PERSON),
                    FormField(id="go_live", label="Go live", type=FieldType.DATE),
                ],
            )
        ],
        consistency_rules=[
            ConsistencyRule(
                id="downtime_without_impact",
                when='${answered.downtime and text.downtime != "none" '
                "and answers.customer_impacting == false}",
                message="An outage is expected but the change is marked as not customer impacting.",
                question="Which is it?",
                fields=["downtime", "customer_impacting"],
                severity=ConsistencySeverity.BLOCKING,
            ),
            ConsistencyRule(
                id="self_review",
                when="${answered.reviewer and answers.reviewer == answers.owner}",
                message="The reviewer is also the owner.",
                fields=["reviewer", "owner"],
                severity=ConsistencySeverity.WARNING,
            ),
        ],
    )


def answered_session(form: FormDefinition, **values: Any) -> FormSession:
    session = FormSession(form_name=form.name, form_version=form.version)
    for field_id, value in values.items():
        session.answers[field_id] = FieldAnswer(
            field_id=field_id, value=value, state=AnswerState.ANSWERED, confidence=1.0
        )
    return session


class TestDurations:
    """Arithmetic in code, because the model got it backwards.

    Asked to compare a downtime with its window, a model reported that "12
    hours exceeds 8AM to 11PM, which is 15 hours" — both values read correctly
    and the comparison inverted. A confident, specific, wrong contradiction
    costs the participant a turn to refute.
    """

    def test_stated_lengths(self) -> None:
        assert parse_duration("12 hours") == 720
        assert parse_duration("90 mins") == 90
        assert parse_duration("1 hour 30 minutes") == 90
        assert parse_duration("2h") == 120
        assert parse_duration("three days") == 4320
        assert parse_duration("half an hour") == 30
        assert parse_duration("none") == 0

    def test_a_range_resolves_to_its_upper_bound(self) -> None:
        """ "4-6 hours" has to fit the window on its worst day, not its best."""
        assert parse_duration("4-6 hours") == 360
        assert parse_duration("4 to 6 hours") == 360
        assert parse_duration("between 2 and 3 days") == 4320

    def test_clock_ranges(self) -> None:
        assert parse_window("08:00-23:00 IST") == 900
        assert parse_window("8AM ro 11PM") == 900
        assert parse_window("Saturday 02:00-04:00 IST") == 120
        assert parse_window("2:30 PM to 4:00 PM") == 90

    def test_a_window_crossing_midnight(self) -> None:
        assert parse_window("22:00-02:00 UTC") == 240

    def test_things_that_are_not_durations(self) -> None:
        assert parse_window("2026-08-22") is None
        assert parse_duration("as soon as possible") is None
        assert span_minutes("") is None

    def test_a_length_beats_a_clock_range_in_the_same_text(self) -> None:
        """ "A 4 hour window starting at 22:00" means four hours."""
        assert span_minutes("4 hour window starting 22:00") == 240


class TestDowntimeAgainstWindow:
    def _check(self, window: str, downtime: str) -> list[str]:
        form = FormDefinition(
            name="cr",
            version="1.0.0",
            title="CR",
            sections=[
                FormSection(
                    id="s",
                    title="S",
                    fields=[
                        FormField(id="maintenance_window", label="Window", type=FieldType.STRING),
                        FormField(id="expected_downtime", label="Downtime", type=FieldType.STRING),
                    ],
                )
            ],
            consistency_rules=[
                ConsistencyRule(
                    id="downtime_exceeds_window",
                    when="${has_minutes.expected_downtime and has_minutes.maintenance_window "
                    "and minutes.expected_downtime > minutes.maintenance_window}",
                    message="The downtime (${answers.expected_downtime}) is longer than the "
                    "window (${answers.maintenance_window}).",
                    fields=["expected_downtime", "maintenance_window"],
                    severity=ConsistencySeverity.BLOCKING,
                )
            ],
        )
        session = answered_session(form, maintenance_window=window, expected_downtime=downtime)
        return [f.message for f in evaluate_rules(form, session)]

    def test_a_downtime_that_fits_is_not_flagged(self) -> None:
        """12 hours inside a 15-hour window. The model called this a conflict."""
        assert self._check("08:00-23:00 IST", "12 hours") == []

    def test_a_downtime_that_does_not_fit_is_flagged_with_both_values(self) -> None:
        [message] = self._check("08:00-23:00 IST", "16 hours")
        assert "16 hours" in message
        assert "08:00-23:00 IST" in message

    def test_the_upper_bound_of_a_range_must_fit(self) -> None:
        assert self._check("22:00-02:00 UTC", "4-6 hours") != []
        assert self._check("22:00-02:00 UTC", "2-3 hours") == []

    def test_a_value_that_cannot_be_read_raises_nothing(self) -> None:
        """A rule that fires on what it failed to parse is worse than no rule."""
        assert self._check("overnight-ish", "as long as it takes") == []


class TestConsistencyRules:
    def test_a_rule_fires_on_the_combination_not_the_values(self) -> None:
        """Each answer here is individually valid. Together they are not."""
        form = consistent_form()
        session = answered_session(form, downtime="4-6 hours", customer_impacting=False)

        findings = evaluate_rules(form, session)
        assert [f.id for f in findings] == ["downtime_without_impact"]
        assert findings[0].severity is ConsistencySeverity.BLOCKING
        # The evidence quotes both sides, so the question can be answered.
        assert "4-6 hours" in findings[0].evidence

    def test_a_coherent_submission_produces_nothing(self) -> None:
        form = consistent_form()
        session = answered_session(form, downtime="4-6 hours", customer_impacting=True)
        assert evaluate_rules(form, session) == []

    def test_an_unanswered_field_is_not_a_contradiction(self) -> None:
        """Missing answers are gap analysis's job, not this one's."""
        form = consistent_form()
        session = answered_session(form, customer_impacting=False)
        assert evaluate_rules(form, session) == []

    def test_the_scope_exposes_presence_and_date_distance(self) -> None:
        form = consistent_form()
        session = answered_session(form, downtime="none", go_live="2026-08-15")
        scope = build_scope(form, session, today=date(2026, 8, 8))

        assert scope["answered"]["downtime"] is True
        assert scope["answered"]["reviewer"] is False
        assert scope["text"]["downtime"] == "none"
        assert scope["days"]["go_live"] == 7

    def test_a_broken_rule_is_skipped_rather_than_blocking_intake(self) -> None:
        """A rule the form author got wrong is their bug, not the user's."""
        form = consistent_form()
        form.consistency_rules.append(
            ConsistencyRule(id="broken", when="${answers.a >", message="never seen")
        )
        session = answered_session(form, downtime="4-6 hours", customer_impacting=True)
        assert evaluate_rules(form, session) == []

    def test_grouped_conditions_are_honoured(self) -> None:
        """`(a or b) and c` must not be torn apart at the `or`.

        Splitting blindly leaves fragments with unbalanced brackets, each of
        which resolves to None and reads as false — so the rule silently never
        fires, which is worse than having no rule.
        """
        scope = {"answers": {"tier": "gold", "active": True}}
        assert evaluate_condition(
            '${(answers.tier == "gold" or answers.tier == "silver") and answers.active}', scope
        )
        assert not evaluate_condition(
            '${(answers.tier == "bronze" or answers.tier == "silver") and answers.active}', scope
        )


class TestFindingLifecycle:
    def test_a_finding_resolves_itself_when_the_answer_changes(self) -> None:
        form = consistent_form()
        session = answered_session(form, downtime="4-6 hours", customer_impacting=False)
        merge(session, evaluate_rules(form, session))
        assert len(outstanding_findings(session)) == 1

        session.answers["customer_impacting"].value = True
        merge(session, evaluate_rules(form, session))

        assert outstanding_findings(session) == []
        assert session.consistency_findings[0].state is FindingState.RESOLVED

    def test_an_acknowledged_finding_is_never_raised_again(self) -> None:
        """They have explained it. Asking every turn would be nagging."""
        form = consistent_form()
        session = answered_session(form, downtime="4-6 hours", customer_impacting=False)
        merge(session, evaluate_rules(form, session))
        acknowledge(session, outstanding_findings(session), "internal service, no customer path")

        merge(session, evaluate_rules(form, session))  # still fires

        assert outstanding_findings(session) == []
        finding = session.consistency_findings[0]
        assert finding.state is FindingState.ACKNOWLEDGED
        assert finding.resolution == "internal service, no customer path"

    def test_a_finding_without_evidence_is_discarded(self) -> None:
        """An unevidenced finding is a guess, and a guess that stops the form
        is worse than a contradiction that slips through."""
        provider = StubProvider(
            review={
                "understanding": "",
                "findings": [
                    {
                        "id": "no_evidence",
                        "message": "something feels off",
                        "question": "?",
                        "fields": [],
                        "evidence": "",
                        "severity": "blocking",
                    }
                ],
            }
        )
        reviewer = ConsistencyReviewer(provider)
        form = consistent_form()
        session = answered_session(form, downtime="none", customer_impacting=False)

        async def run() -> Any:
            return await reviewer.review(form, session)

        _, findings = asyncio.run(run())
        assert findings == []


class TestConsistencyInTheConversation:
    """The whole point: it is a question, not a verdict."""

    def _service(self, provider: StubProvider) -> tuple[FormsService, FormDefinition]:
        form = consistent_form()
        form.semantic_consistency_review = False
        reg = FormRegistry()
        reg.create(form, activate=True)
        return make_service(reg, provider), form

    async def _settle_the_rest(
        self, service: FormsService, sid: str, *, owner: str = "alice", reviewer: str = "bob"
    ) -> None:
        """Close the optional fields so the conversation can reach its end.

        The review runs at wrap-up, *after* the recommended and optional
        questions — running it the moment the mandatory set closed put it ahead
        of them and they never got asked at all.
        """
        await service.set_answer(sid, "owner", owner)
        await service.set_answer(sid, "reviewer", reviewer)
        await service.set_answer(sid, "go_live", "2026-09-01")

    async def test_a_contradiction_is_raised_before_the_form_is_called_complete(self) -> None:
        provider = StubProvider(
            [extraction(("downtime", "4-6 hours", 0.95), ("customer_impacting", "no", 0.95))]
        )
        service, _ = self._service(provider)
        sid = (await service.start_session("release", participant="alice"))["session_id"]
        await self._settle_the_rest(service, sid)

        result = await service.send(sid, "4-6 hours down, customers won't notice")

        assert not result.ready_for_review
        assert "not customer impacting" in result.reply
        session = await service.get_session(sid)
        assert session.status is not SessionStatus.READY_FOR_REVIEW
        assert [f.state for f in session.consistency_findings] == [FindingState.RAISED]

    async def test_correcting_an_answer_clears_it_and_completes(self) -> None:
        provider = StubProvider(
            [
                extraction(("downtime", "4-6 hours", 0.95), ("customer_impacting", "no", 0.95)),
                extraction(("customer_impacting", "yes", 0.99)),
            ]
        )
        service, _ = self._service(provider)
        sid = (await service.start_session("release", participant="alice"))["session_id"]
        await self._settle_the_rest(service, sid)

        await service.send(sid, "4-6 hours down, customers won't notice")
        result = await service.send(sid, "actually yes, customers will see it")

        assert result.ready_for_review
        session = await service.get_session(sid)
        assert session.consistency_findings[0].state is FindingState.RESOLVED

    async def test_standing_by_it_records_the_reason_for_the_approver(self) -> None:
        """The reason is the deliverable. It exists nowhere in the fields."""
        provider = StubProvider(
            [extraction(("downtime", "4-6 hours", 0.95), ("customer_impacting", "no", 0.95))]
        )
        service, _ = self._service(provider)
        sid = (await service.start_session("release", participant="alice"))["session_id"]
        await self._settle_the_rest(service, sid)

        await service.send(sid, "4-6 hours down, customers won't notice")
        result = await service.send(
            sid, "the outage is internal only, no customer traffic touches it"
        )

        assert result.ready_for_review
        session = await service.get_session(sid)
        finding = session.consistency_findings[0]
        assert finding.state is FindingState.ACKNOWLEDGED
        assert "internal only" in finding.resolution

        # And it reaches the document, beside what prompted it.
        content, _, _ = render_session(
            service.conversation.registry.get("release", "1.0.0"), session, "markdown"
        )
        markdown = content.decode()
        assert "Noted discrepancies" in markdown
        assert "internal only" in markdown

    async def test_one_reply_is_filed_against_the_discrepancy_it_answers(self) -> None:
        """Two raised at once, one answered — the other must not inherit it.

        Recording a sentence about the maintenance window as the owner's reason
        for reviewing their own change reads like a considered answer and is
        worse than recording nothing.
        """
        service, _ = self._service(StubProvider())
        sid = (await service.start_session("release", participant="alice"))["session_id"]
        await service.set_answer(sid, "downtime", "4-6 hours")
        await service.set_answer(sid, "customer_impacting", False)
        await service.set_answer(sid, "owner", "alice")
        await service.set_answer(sid, "reviewer", "alice")
        await service.set_answer(sid, "go_live", "2026-09-01")

        first = await service.send(sid, "generate the document")
        assert len(consistency_outstanding(await service.get_session(sid))) == 2

        # The stub attributes the reply to the impact finding only.
        service.conversation._llm.attribution = [
            {"id": "downtime_without_impact", "explanation": "the outage is internal only"}
        ]
        await service.send(sid, "the outage is internal only, no customer traffic touches it")

        session = await service.get_session(sid)
        by_id = {f.id: f for f in session.consistency_findings}
        assert by_id["downtime_without_impact"].state is FindingState.ACKNOWLEDGED
        assert by_id["downtime_without_impact"].resolution == "the outage is internal only"
        # Untouched by a reply that said nothing about it.
        assert by_id["self_review"].state is FindingState.RAISED
        assert by_id["self_review"].resolution == ""
        assert first.reply  # the first turn did put both to them

    async def test_an_unanswered_discrepancy_is_followed_up_once_then_recorded(self) -> None:
        """Answered around twice is itself an answer. Asking a third time is not."""
        service, _ = self._service(StubProvider())
        sid = (await service.start_session("release", participant="alice"))["session_id"]
        await service.set_answer(sid, "downtime", "4-6 hours")
        await service.set_answer(sid, "customer_impacting", False)
        await service.set_answer(sid, "owner", "alice")
        await service.set_answer(sid, "reviewer", "alice")
        await service.set_answer(sid, "go_live", "2026-09-01")

        await service.send(sid, "generate the document")

        # Both times the reply covers only the impact finding.
        service.conversation._llm.attribution = [
            {"id": "downtime_without_impact", "explanation": "internal only"}
        ]
        follow_up = await service.send(sid, "the outage is internal only")
        assert "still needs an answer" in follow_up.reply

        await service.send(sid, "still internal only")

        by_id = {f.id: f for f in (await service.get_session(sid)).consistency_findings}
        assert by_id["self_review"].state is FindingState.ACKNOWLEDGED
        assert "not explained" in by_id["self_review"].resolution
        # The one they did answer keeps their words, not the fallback.
        assert by_id["downtime_without_impact"].resolution == "internal only"

    async def test_the_review_does_not_jump_ahead_of_the_optional_questions(self) -> None:
        """Mandatory-complete means "you may stop", not "we're finished asking".

        Running the review the moment the mandatory set closed put it ahead of
        every recommended and optional field — and because a raised finding
        kept the floor, those fields were never asked at all. A submission went
        to review with none of them, and the summary was raw chat text, because
        the wording pass runs at wrap-up too.
        """
        provider = StubProvider(
            [extraction(("downtime", "4-6 hours", 0.95), ("customer_impacting", "no", 0.95))]
        )
        service, _ = self._service(provider)
        sid = (await service.start_session("release", participant="alice"))["session_id"]

        result = await service.send(sid, "4-6 hours down, customers won't notice")

        # The optional fields are still open, so they are what gets asked.
        assert set(result.targeted_fields) & {"owner", "reviewer", "go_live"}
        assert not consistency_outstanding(await service.get_session(sid))

    async def test_generate_cannot_skip_the_review(self) -> None:
        """Answers set through the form UI never pass through a conversation
        turn, so "generate" is the first moment they can be checked."""
        service, _ = self._service(StubProvider())
        sid = (await service.start_session("release", participant="alice"))["session_id"]
        await service.set_answer(sid, "downtime", "4-6 hours")
        await service.set_answer(sid, "customer_impacting", False)
        await self._settle_the_rest(service, sid)

        result = await service.send(sid, "generate the document")

        assert not result.ready_for_review
        assert "not customer impacting" in result.reply

    async def test_saying_generate_again_accepts_it_on_the_record(self) -> None:
        """Asked once, then never again — the alternative is a loop.

        What gets recorded is a statement of what happened, not the word
        "generate": an instruction would read as nonsense on the document under
        a column headed "the owner's answer".
        """
        service, _ = self._service(StubProvider())
        sid = (await service.start_session("release", participant="alice"))["session_id"]
        await service.set_answer(sid, "downtime", "4-6 hours")
        await service.set_answer(sid, "customer_impacting", False)
        await self._settle_the_rest(service, sid)

        await service.send(sid, "generate the document")
        second = await service.send(sid, "generate the document")

        assert second.ready_for_review
        session = await service.get_session(sid)
        finding = session.consistency_findings[0]
        assert finding.state is FindingState.ACKNOWLEDGED
        assert "without change" in finding.resolution
        assert "generate" not in finding.resolution.lower()

    async def test_a_blocking_finding_stops_the_artifact(self) -> None:
        provider = StubProvider(
            [extraction(("downtime", "4-6 hours", 0.95), ("customer_impacting", "no", 0.95))]
        )
        service, _ = self._service(provider)
        sid = (await service.start_session("release", participant="alice"))["session_id"]
        await self._settle_the_rest(service, sid)
        await service.send(sid, "4-6 hours down, customers won't notice")

        with pytest.raises(ValidationError, match="contradiction"):
            await service.generate(sid, ["markdown"])

        # An interim draft is still allowed, and carries the discrepancy.
        records = await service.generate(sid, ["markdown"], allow_incomplete=True)
        assert len(records) == 1


# ---------------------------------------------------------------------------
# Extraction internals
# ---------------------------------------------------------------------------


class TestExtraction:
    async def test_labelled_lines_are_matched_without_a_model_call(
        self, simple_form: FormDefinition
    ) -> None:
        provider = StubProvider()
        engine = ExtractionEngine(provider)
        message = SourceMessage(
            text="Owner: Priya Raman\nRisk level: high\nSome other prose.",
            channel=SourceChannel.JIRA,
        )
        result = await engine.extract(simple_form, message)

        values = {e.field_id: e.value for e in result.accepted()}
        assert values["owner"] == "Priya Raman"
        assert values["risk_level"] == "high"
        assert all(e.method == "pattern" for e in result.accepted())

    async def test_aliases_are_matched_as_labels(self, simple_form: FormDefinition) -> None:
        engine = ExtractionEngine(StubProvider())
        message = SourceMessage(text="Responsible: Dev Patel")
        result = await engine.extract(simple_form, message)
        assert {e.field_id: e.value for e in result.accepted()}["owner"] == "Dev Patel"

    async def test_a_failed_coercion_is_kept_as_a_rejection(
        self, simple_form: FormDefinition
    ) -> None:
        engine = ExtractionEngine(StubProvider())
        message = SourceMessage(text="Risk level: apocalyptic")
        result = await engine.extract(simple_form, message)

        # Kept rather than dropped, so the engine can ask a targeted question.
        rejected = result.rejected()
        assert any(e.field_id == "risk_level" for e in rejected)
        assert "must be one of" in (rejected[0].error or "")

    async def test_extraction_survives_an_llm_outage(self, simple_form: FormDefinition) -> None:
        class BrokenProvider:
            async def complete_structured(self, *args: Any, **kwargs: Any) -> Any:
                raise RuntimeError("model unavailable")

        engine = ExtractionEngine(BrokenProvider())
        # The deterministic pass still lands; the semantic pass fails silently.
        message = SourceMessage(text="Owner: Priya Raman\nsomething vague about risk")
        result = await engine.extract(simple_form, message)
        assert {e.field_id for e in result.accepted()} == {"owner"}


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


class TestIngestion:
    def test_jira_adf_body_is_flattened(self) -> None:
        payload = {
            "key": "OPS-1",
            "fields": {
                "reporter": {"displayName": "Alice"},
                "description": {
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": "Owner: Priya Raman"}],
                        }
                    ],
                },
                "comment": {
                    "comments": [
                        {
                            "id": "10",
                            "author": {"displayName": "Bob"},
                            "body": "Risk level: high",
                            "created": "2026-03-01T10:00:00.000+0000",
                        }
                    ]
                },
            },
        }
        messages = JiraCommentSource(base_url="https://jira.example.com").parse(payload)

        assert len(messages) == 2
        assert "Priya Raman" in messages[0].text
        assert messages[1].author == "Bob"
        assert messages[0].external_url == "https://jira.example.com/browse/OPS-1"

    def test_jira_bot_comments_are_dropped(self) -> None:
        payload = {
            "fields": {
                "comment": {
                    "comments": [
                        {
                            "author": {"displayName": "Automation for Jira"},
                            "body": "Status changed",
                        },
                        {"author": {"displayName": "Alice"}, "body": "Owner: Priya"},
                    ]
                }
            }
        }
        messages = JiraCommentSource().parse(payload)
        assert [m.author for m in messages] == ["Alice"]

    def test_email_quoted_history_is_stripped(self) -> None:
        body = (
            "The owner is Priya Raman.\n\n"
            "On Tue, 3 Mar 2026 at 09:14, Bob <bob@x.com> wrote:\n"
            "> Who is the owner? Is it still Dev?\n"
        )
        stripped = EmailThreadSource.strip_quoted(body)
        assert "Priya Raman" in stripped
        # The stale question must not survive, or it gets re-extracted.
        assert "Dev" not in stripped

    def test_email_signature_is_stripped(self) -> None:
        body = "Risk is high.\n\nBest regards,\nAlice Chen\nPrincipal Engineer\n"
        cleaned = EmailThreadSource.strip_signature(body)
        assert "Risk is high." in cleaned
        assert "Principal Engineer" not in cleaned

    def test_email_display_name_is_extracted(self) -> None:
        messages = EmailThreadSource().parse(
            [
                {
                    "from": '"Alice Chen" <alice@example.com>',
                    "subject": "Change",
                    "body": "Owner: Priya",
                }
            ]
        )
        assert messages[0].author == "Alice Chen"
        assert "Subject: Change" in messages[0].text

    def test_transcript_merges_consecutive_turns_by_one_speaker(self) -> None:
        transcript = (
            "[00:01] Alice: The owner is Priya.\n"
            "Alice: And we're targeting March.\n"
            "Bob: Risk is high.\n"
        )
        messages = MeetingTranscriptSource().parse(transcript)
        assert len(messages) == 2
        assert "Priya" in messages[0].text and "March" in messages[0].text
        assert messages[1].author == "Bob"

    def test_parse_payload_dispatches_by_channel(self) -> None:
        messages = parse_payload("meeting", "Alice: hello there everyone")
        assert messages[0].channel is SourceChannel.MEETING

    async def test_ingesting_a_thread_fills_fields_without_asking(
        self, registry: FormRegistry
    ) -> None:
        provider = StubProvider()
        service = make_service(registry, provider)
        started = await service.start_session("test_form", participant="alice")

        payload = {
            "key": "OPS-9",
            "fields": {
                "reporter": {"displayName": "Alice"},
                "description": "Owner: Priya Raman\nRisk level: high",
                "comment": {"comments": []},
            },
        }
        report = await service.ingest(started["session_id"], "jira", payload)

        assert set(report["captured"]) == {"owner", "risk_level"}
        assert report["messages_processed"] == 1

        session = await service.get_session(started["session_id"])
        assert session.answers["owner"].provenance.channel is SourceChannel.JIRA


# ---------------------------------------------------------------------------
# Versioning and CRUD
# ---------------------------------------------------------------------------


class TestFormRegistry:
    def test_resolve_returns_the_latest_active_version(self, registry: FormRegistry) -> None:
        base = registry.get("test_form", "1.0.0")
        registry.create(base.model_copy(update={"version": "2.0.0"}), activate=True)

        assert registry.resolve("test_form").version == "2.0.0"
        # Activating the new one deprecated the old.
        assert registry.get("test_form", "1.0.0").status is FormStatus.DEPRECATED

    def test_resolve_never_returns_a_draft(self, registry: FormRegistry) -> None:
        base = registry.get("test_form", "1.0.0")
        registry.create(base.model_copy(update={"version": "1.1.0", "status": FormStatus.DRAFT}))
        assert registry.resolve("test_form").version == "1.0.0"

    def test_resolve_fails_clearly_when_nothing_is_active(
        self, simple_form: FormDefinition
    ) -> None:
        reg = FormRegistry()
        reg.create(simple_form.model_copy(update={"status": FormStatus.DRAFT}))
        with pytest.raises(ValidationError, match="no active version"):
            reg.resolve("test_form")

    def test_updating_a_published_form_forks_a_draft(self, registry: FormRegistry) -> None:
        updated = registry.update("test_form", {"title": "Renamed"}, change_note="rename")

        assert updated.version == "1.1.0"
        assert updated.status is FormStatus.DRAFT
        # The published version is untouched — sessions using it are unaffected.
        assert registry.get("test_form", "1.0.0").title == "Test Form"

    def test_updating_a_draft_edits_it_in_place(self, registry: FormRegistry) -> None:
        draft = registry.update("test_form", {"title": "Draft A"})
        again = registry.update("test_form", {"title": "Draft B"}, version=draft.version)
        assert again.version == draft.version
        assert again.title == "Draft B"

    def test_a_published_version_cannot_be_deleted_without_force(
        self, registry: FormRegistry
    ) -> None:
        with pytest.raises(ValidationError, match="archive it instead"):
            registry.delete("test_form", "1.0.0")

    def test_a_draft_can_be_deleted(self, registry: FormRegistry) -> None:
        draft = registry.update("test_form", {"title": "Scratch"})
        registry.delete("test_form", draft.version)
        assert draft.version not in registry.versions("test_form")

    def test_history_lists_every_version(self, registry: FormRegistry) -> None:
        registry.update("test_form", {"title": "v2"})
        assert len(registry.history("test_form")) == 2

    def test_export_round_trips_through_yaml(self, registry: FormRegistry) -> None:
        import yaml

        exported = registry.export("test_form", "1.0.0")
        reloaded = FormDefinition(**yaml.safe_load(exported))
        assert reloaded.field_count() == registry.get("test_form", "1.0.0").field_count()

    async def test_an_in_flight_session_keeps_its_original_version(
        self, registry: FormRegistry
    ) -> None:
        service = make_service(registry, StubProvider())
        started = await service.start_session("test_form", participant="alice")

        # Publish a new version mid-session.
        base = registry.get("test_form", "1.0.0")
        registry.create(base.model_copy(update={"version": "2.0.0"}), activate=True)

        session = await service.get_session(started["session_id"])
        assert session.form_version == "1.0.0"


# ---------------------------------------------------------------------------
# Authoring from a sample
# ---------------------------------------------------------------------------


class TestAuthoring:
    def test_csv_headers_and_rows_are_read(self) -> None:
        csv_text = "Name,Target Date,Risk\nAlpha,2026-01-01,high\nBeta,2026-02-01,low\n"
        headers, rows = read_tabular(csv_text, filename="sample.csv")
        assert headers == ["Name", "Target Date", "Risk"]
        assert len(rows) == 2

    def test_a_title_row_above_the_headers_is_skipped(self) -> None:
        csv_text = "Quarterly Change Log,,\n,,\nName,Target Date,Risk\nAlpha,2026-01-01,high\n"
        headers, _ = read_tabular(csv_text, filename="sample.csv")
        assert headers == ["Name", "Target Date", "Risk"]

    def test_column_types_are_inferred_from_values(self) -> None:
        headers = ["Owner", "Target Date", "Cost", "Approved"]
        rows = [
            ["Alice", "2026-01-01", "1200", "yes"],
            ["Bob", "2026-02-01", "980", "no"],
        ]
        profiles = {p.name: p for p in profile_columns(headers, rows)}

        assert profiles["Target Date"].inferred_type is FieldType.DATE
        assert profiles["Approved"].inferred_type is FieldType.BOOLEAN
        assert profiles["Cost"].inferred_type is FieldType.CURRENCY
        assert profiles["Owner"].inferred_type is FieldType.PERSON

    def test_low_cardinality_columns_become_picklists(self) -> None:
        headers = ["Risk"]
        rows = [["high"], ["low"], ["high"], ["medium"], ["low"], ["high"]]
        profile = profile_columns(headers, rows)[0]
        assert profile.inferred_type is FieldType.ENUM
        assert set(profile.options) == {"high", "low", "medium"}

    def test_fill_rate_drives_inferred_importance(self) -> None:
        headers = ["Always", "Sometimes"]
        rows = [["x", "y"], ["x", ""], ["x", ""], ["x", ""]]
        profiles = {p.name: p for p in profile_columns(headers, rows)}
        assert profiles["Always"].inferred_importance is Importance.MANDATORY
        assert profiles["Sometimes"].inferred_importance is Importance.OPTIONAL

    def test_json_samples_are_supported(self) -> None:
        payload = json.dumps([{"owner": "Alice", "risk": "high"}, {"owner": "Bob", "risk": "low"}])
        headers, rows = read_tabular(payload, filename="sample.json")
        assert headers == ["owner", "risk"]
        assert len(rows) == 2

    async def test_inference_produces_a_draft_with_facilitator_questions(self) -> None:
        csv_text = "Owner,Target Date,Risk\nAlice,2026-01-01,high\nBob,2026-02-01,low\n"
        author = FormAuthor(StubProvider())
        report = await author.infer(csv_text, filename="change_log.csv", form_name="change_log")

        assert report.definition.status is FormStatus.DRAFT
        assert report.definition.field_count() == 3
        # It should ask the human to confirm what it guessed.
        assert report.questions

    async def test_an_inferred_form_registers_as_a_draft(self, registry: FormRegistry) -> None:
        service = make_service(registry, StubProvider())
        csv_text = "Owner,Risk\nAlice,high\nBob,low\n"
        report = await service.infer_form(csv_text, filename="thing.csv", form_name="thing")

        assert registry.get("thing").status is FormStatus.DRAFT
        # Never auto-activated: the facilitator's questions come first.
        with pytest.raises(ValidationError, match="no active version"):
            registry.resolve("thing")
        assert report.definition.name == "thing"

    def test_excel_round_trip(self) -> None:
        pytest.importorskip("openpyxl")
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Owner", "Target Date"])
        sheet.append(["Alice", "2026-01-01"])
        import io

        buffer = io.BytesIO()
        workbook.save(buffer)

        headers, rows = read_tabular(buffer.getvalue(), filename="sample.xlsx")
        assert headers == ["Owner", "Target Date"]
        assert rows[0][0] == "Alice"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


class TestRendering:
    @pytest.fixture
    async def filled(self, registry: FormRegistry) -> tuple[FormsService, str]:
        service = make_service(registry, StubProvider())
        started = await service.start_session("test_form", participant="alice")
        sid = started["session_id"]
        for field_id, value in (
            ("owner", "Priya Raman"),
            ("target_date", "2026-03-15"),
            ("risk_level", "low"),
            ("notes", "Straightforward config change."),
        ):
            await service.set_answer(sid, field_id, value)
        return service, sid

    async def test_markdown_contains_answers_and_provenance(
        self, filled: tuple[FormsService, str], registry: FormRegistry
    ) -> None:
        service, sid = filled
        session = await service.get_session(sid)
        content, filename, media = render_session(registry.get("test_form"), session, "markdown")
        text = content.decode("utf-8")

        assert "Priya Raman" in text
        assert "2026-03-15" in text
        assert "## Provenance" in text
        assert filename.endswith(".md")
        assert media == "text/markdown"

    async def test_json_export_carries_confidence_and_provenance(
        self, filled: tuple[FormsService, str], registry: FormRegistry
    ) -> None:
        service, sid = filled
        session = await service.get_session(sid)
        content, _, _ = render_session(registry.get("test_form"), session, "json")
        payload = json.loads(content)

        owner = next(f for s in payload["sections"] for f in s["fields"] if f["id"] == "owner")
        assert owner["value"] == "Priya Raman"
        assert owner["provenance"]["method"] == "user_confirmed"

    async def test_excel_renders(
        self, filled: tuple[FormsService, str], registry: FormRegistry
    ) -> None:
        pytest.importorskip("openpyxl")
        service, sid = filled
        session = await service.get_session(sid)
        content, filename, _ = render_session(registry.get("test_form"), session, "xlsx")

        assert filename.endswith(".xlsx")
        assert content[:2] == b"PK"  # a zip container, which xlsx is

    async def test_pdf_renders(
        self, filled: tuple[FormsService, str], registry: FormRegistry
    ) -> None:
        pytest.importorskip("fpdf")
        service, sid = filled
        session = await service.get_session(sid)
        content, filename, _ = render_session(registry.get("test_form"), session, "pdf")

        assert filename.endswith(".pdf")
        assert content[:4] == b"%PDF"

    async def test_pdf_handles_non_latin1_characters(self, registry: FormRegistry) -> None:
        pytest.importorskip("fpdf")
        service = make_service(registry, StubProvider())
        started = await service.start_session("test_form", participant="alice")
        sid = started["session_id"]
        # Smart quotes and dashes routinely arrive pasted from email.
        await service.set_answer(  # - deliberately non-Latin-1
            sid, "notes", "It’s a “low-risk” change — really."
        )
        session = await service.get_session(sid)

        content, _, _ = render_session(registry.get("test_form"), session, "pdf")
        assert content[:4] == b"%PDF"

    def test_available_formats_reports_what_is_installed(self) -> None:
        formats = available_formats()
        assert "json" in formats and "markdown" in formats


# ---------------------------------------------------------------------------
# Approval and baselining
# ---------------------------------------------------------------------------


class TestApproval:
    async def _complete(self, registry: FormRegistry) -> tuple[FormsService, str]:
        service = make_service(registry, StubProvider())
        started = await service.start_session("test_form", participant="alice")
        sid = started["session_id"]
        for field_id, value in (
            ("owner", "Priya Raman"),
            ("target_date", "2026-03-15"),
            ("risk_level", "low"),
        ):
            await service.set_answer(sid, field_id, value)
        return service, sid

    async def test_generation_is_refused_while_mandatory_fields_are_open(
        self, registry: FormRegistry
    ) -> None:
        service = make_service(registry, StubProvider())
        started = await service.start_session("test_form", participant="alice")

        with pytest.raises(ValidationError, match="required field"):
            await service.generate(started["session_id"], ["markdown"])

    async def test_allow_incomplete_renders_anyway(self, registry: FormRegistry) -> None:
        service = make_service(registry, StubProvider())
        started = await service.start_session("test_form", participant="alice")

        records = await service.generate(started["session_id"], ["markdown"], allow_incomplete=True)
        assert records[0].metadata["incomplete"] is True

    async def test_generation_moves_the_session_into_review(self, registry: FormRegistry) -> None:
        service, sid = await self._complete(registry)
        records = await service.generate(sid, ["markdown", "json"])

        assert len(records) == 2
        assert all(r.status is ArtifactStatus.IN_REVIEW for r in records)
        session = await service.get_session(sid)
        assert session.status is SessionStatus.IN_REVIEW

    async def test_a_contributor_cannot_approve_their_own_submission(
        self, registry: FormRegistry
    ) -> None:
        service, sid = await self._complete(registry)
        records = await service.generate(sid, ["markdown"])

        with pytest.raises(AuthorizationError, match="cannot approve"):
            await service.approve(records[0].id, approver="alice")

    async def test_recording_a_decision_for_someone_else_needs_permission(
        self, registry: FormRegistry
    ) -> None:
        """A caller must not be able to attribute their approval to a colleague."""
        service, sid = await self._complete(registry)
        records = await service.generate(sid, ["markdown"])

        unprivileged = ExecutionContext(
            principal=Principal(subject="mallory", permissions=frozenset())
        )
        with bind_context(unprivileged), pytest.raises(AuthorizationError, match="on behalf"):
            await service.approve(records[0].id, approver="bob")

    async def test_approval_baselines_the_artifact(self, registry: FormRegistry) -> None:
        service, sid = await self._complete(registry)
        records = await service.generate(sid, ["markdown"])

        approved = await service.approve(records[0].id, approver="bob", comment="looks fine")
        assert approved.status is ArtifactStatus.BASELINED
        assert approved.baselined_at is not None

        session = await service.get_session(sid)
        assert session.status is SessionStatus.BASELINED

    async def test_a_baselined_session_rejects_further_edits(self, registry: FormRegistry) -> None:
        service, sid = await self._complete(registry)
        records = await service.generate(sid, ["markdown"])
        await service.approve(records[0].id, approver="bob")

        result = await service.send(sid, "actually change the owner")
        assert "can no longer be edited" in result.reply

    async def test_rejection_reopens_the_session(self, registry: FormRegistry) -> None:
        service, sid = await self._complete(registry)
        records = await service.generate(sid, ["markdown"])

        rejected = await service.reject(
            records[0].id, approver="bob", comment="needs a rollback plan"
        )
        assert rejected.status is ArtifactStatus.REJECTED

        session = await service.get_session(sid)
        assert session.status is SessionStatus.CHANGES_REQUESTED
        assert session.status.is_editable

    async def test_the_same_approver_cannot_decide_twice(self, registry: FormRegistry) -> None:
        registry.create(
            registry.get("test_form", "1.0.0").model_copy(
                update={"version": "1.5.0", "approval": ApprovalPolicy(required_approvals=2)}
            ),
            activate=True,
        )
        service, sid = await self._complete(registry)
        records = await service.generate(sid, ["markdown"])

        await service.approve(records[0].id, approver="bob")
        with pytest.raises(ValidationError, match="already recorded a decision"):
            await service.approve(records[0].id, approver="bob")

    async def test_two_approvals_are_required_when_the_policy_says_so(
        self, registry: FormRegistry
    ) -> None:
        registry.create(
            registry.get("test_form", "1.0.0").model_copy(
                update={"version": "1.5.0", "approval": ApprovalPolicy(required_approvals=2)}
            ),
            activate=True,
        )
        service, sid = await self._complete(registry)
        records = await service.generate(sid, ["markdown"])

        first = await service.approve(records[0].id, approver="bob")
        assert first.status is ArtifactStatus.APPROVED
        assert not first.is_baselined

        second = await service.approve(records[0].id, approver="carol")
        assert second.is_baselined

    async def test_regeneration_supersedes_the_previous_revision(
        self, registry: FormRegistry
    ) -> None:
        service, sid = await self._complete(registry)
        first = await service.generate(sid, ["markdown"])

        await service.reopen(sid, reason="typo")
        await service.set_answer(sid, "notes", "Corrected.")
        second = await service.generate(sid, ["markdown"])

        assert second[0].revision == 2
        refreshed = await service.approval.get_artifact(first[0].id)
        assert refreshed.status is ArtifactStatus.SUPERSEDED

    async def test_baseline_checksum_verification(self, registry: FormRegistry) -> None:
        service, sid = await self._complete(registry)
        records = await service.generate(sid, ["markdown"])
        await service.approve(records[0].id, approver="bob")

        verification = await service.verify_baseline(records[0].id)
        assert verification["intact"] is True
        assert verification["expected_checksum"] == verification["actual_checksum"]

    async def test_pending_reviews_lists_artifacts_awaiting_a_decision(
        self, registry: FormRegistry
    ) -> None:
        service, sid = await self._complete(registry)
        await service.generate(sid, ["markdown"])

        pending = await service.pending_reviews()
        assert len(pending) == 1
        assert pending[0].session_id == sid


# ---------------------------------------------------------------------------
# Action items
# ---------------------------------------------------------------------------


class TestActionItems:
    async def test_unanswered_mandatory_fields_become_open_items(
        self, registry: FormRegistry
    ) -> None:
        service = make_service(registry, StubProvider())
        started = await service.start_session("test_form", participant="alice")
        session = await service.get_session(started["session_id"])

        items = derive_action_items(registry.get("test_form"), session)
        # owner, target_date, risk_level are mandatory and unanswered.
        assert {i.source_field_id for i in items} == {"owner", "target_date", "risk_level"}

    async def test_an_item_closes_once_its_field_is_answered(self, registry: FormRegistry) -> None:
        service = make_service(registry, StubProvider())
        started = await service.start_session("test_form", participant="alice")
        sid = started["session_id"]
        form = registry.get("test_form")

        session = await service.get_session(sid)
        items = derive_action_items(form, session)

        await service.set_answer(sid, "owner", "Priya")
        session = await service.get_session(sid)
        updated = derive_action_items(form, session, items)

        owner_item = next(i for i in updated if i.source_field_id == "owner")
        assert owner_item.status.value == "done"
        assert "owner" not in {i.source_field_id for i in open_items_from(updated)}

    async def test_derivation_is_idempotent(self, registry: FormRegistry) -> None:
        service = make_service(registry, StubProvider())
        started = await service.start_session("test_form", participant="alice")
        session = await service.get_session(started["session_id"])
        form = registry.get("test_form")

        once = derive_action_items(form, session)
        twice = derive_action_items(form, session, once)
        assert len(once) == len(twice)


def open_items_from(items: list[Any]) -> list[Any]:
    from sa_forms.models import ActionItemStatus

    return [i for i in items if i.status is ActionItemStatus.OPEN]


# ---------------------------------------------------------------------------
# Grouping by affinity rather than by section
# ---------------------------------------------------------------------------


def _related_form(**overrides: Any) -> FormDefinition:
    """A form whose natural groupings deliberately cut across its sections.

    Two people fields filed a section apart, a guarded follow-up, and a rule
    tying two others together — the three signals topic selection is built on.
    """
    definition = {
        "name": "spanning",
        "version": "1.0.0",
        "title": "Spanning",
        "status": FormStatus.ACTIVE,
        "consistency_rules": [
            ConsistencyRule(
                id="window_vs_outage",
                when="${answered.window and answered.outage}",
                message="checked together",
                fields=["window", "outage"],
            )
        ],
        "sections": [
            FormSection(
                id="what",
                title="What",
                order=0,
                fields=[
                    FormField(id="summary", label="Summary", importance=Importance.MANDATORY),
                    FormField(
                        id="owner",
                        label="Owner",
                        type=FieldType.PERSON,
                        importance=Importance.MANDATORY,
                    ),
                    FormField(
                        id="impacted",
                        label="Customers impacted",
                        type=FieldType.BOOLEAN,
                        importance=Importance.MANDATORY,
                    ),
                ],
            ),
            FormSection(
                id="when",
                title="When",
                order=1,
                fields=[
                    FormField(id="window", label="Window", importance=Importance.MANDATORY),
                    FormField(id="outage", label="Outage", importance=Importance.MANDATORY),
                    FormField(
                        id="comms_owner",
                        label="Comms owner",
                        type=FieldType.PERSON,
                        importance=Importance.MANDATORY,
                        ask_when="${answers.impacted == true}",
                    ),
                ],
            ),
            FormSection(
                id="signoff",
                title="Sign-off",
                order=2,
                fields=[
                    FormField(
                        id="reviewer",
                        label="Reviewer",
                        type=FieldType.PERSON,
                        importance=Importance.MANDATORY,
                    ),
                ],
            ),
        ],
    }
    definition.update(overrides)
    return FormDefinition(**definition)


class TestTopicsByAffinity:
    def test_a_topic_crosses_a_section_boundary_to_group_like_with_like(self) -> None:
        """The owner and the reviewer are two sections and one question.

        This is the whole point of the module: the person answering does not
        hold the author's filing system in their head, and asking "who owns it"
        eight questions before "who reviewed it" is an artefact of the file, not
        of the subject.
        """
        form = _related_form()
        session = FormSession(form_name="spanning", form_version="1.0.0")

        topic, fields = next_topic(form, analyse(form, session))
        assert "reviewer" in [f.id for f in fields]
        assert "owner" in [f.id for f in fields]
        assert topic.spans_sections

    def test_a_guarded_follow_up_jumps_the_declared_order(self) -> None:
        """ "Customers are affected" is followed by "who tells them?".

        Not by whatever the next section happens to hold. The `ask_when` guard
        is the author saying these two belong together, and honouring it late is
        the same as not honouring it.
        """
        form = _related_form()
        session = FormSession(form_name="spanning", form_version="1.0.0")
        for field_id, value in (("summary", "s"), ("owner", "Priya"), ("reviewer", "Sam")):
            answer = session.answer_for(field_id)
            answer.value, answer.state = value, AnswerState.ANSWERED
        impacted = session.answer_for("impacted")
        impacted.value, impacted.state = True, AnswerState.ANSWERED

        _, fields = next_topic(form, analyse(form, session), recently_settled=["impacted"])
        assert "comms_owner" in [f.id for f in fields]

    def test_fields_a_rule_compares_are_asked_together(self) -> None:
        form = _related_form()
        session = FormSession(form_name="spanning", form_version="1.0.0")
        for field_id in ("summary", "owner", "reviewer", "impacted"):
            answer = session.answer_for(field_id)
            answer.value, answer.state = "x", AnswerState.ANSWERED

        _, fields = next_topic(form, analyse(form, session))
        assert {"window", "outage"} <= {f.id for f in fields}

    def test_affinity_can_be_turned_off_for_a_form_whose_order_is_the_rule(self) -> None:
        """Some questionnaires *are* their section order. Say so and get it."""
        form = _related_form(group_by_affinity=False)
        session = FormSession(form_name="spanning", form_version="1.0.0")

        topic, fields = next_topic(form, analyse(form, session))
        assert topic.id == "what"
        assert not topic.spans_sections
        assert {f.id for f in fields} <= {"summary", "owner", "impacted"}

    def test_unrelated_fields_are_not_padded_into_a_question(self) -> None:
        """A fourth unrelated field does not improve the question."""
        form = FormDefinition(
            name="loose",
            version="1.0.0",
            title="Loose",
            sections=[
                FormSection(
                    id="a",
                    title="A",
                    order=0,
                    fields=[FormField(id="alpha", label="Alpha", importance=Importance.MANDATORY)],
                ),
                FormSection(
                    id="b",
                    title="B",
                    order=1,
                    fields=[
                        FormField(
                            id="zulu",
                            label="Zulu",
                            type=FieldType.DATE,
                            importance=Importance.MANDATORY,
                        )
                    ],
                ),
            ],
        )
        session = FormSession(form_name="loose", form_version="1.0.0")
        _, fields = next_topic(form, analyse(form, session))
        assert [f.id for f in fields] == ["alpha"]

    async def test_asking_starts_open_and_gets_specific_only_after_a_miss(
        self, registry: FormRegistry
    ) -> None:
        provider = StubProvider([extraction()])
        service = make_service(registry, provider)
        sid = (await service.start_session("test_form", participant="alice"))["session_id"]

        opening = " ".join(provider.prompts)
        assert "ASKING STYLE: open" in opening

        provider.prompts.clear()
        await service.send(sid, "not sure yet")
        after_a_miss = " ".join(provider.prompts)
        assert "ASKING STYLE: specific" in after_a_miss or "ASKING STYLE: explicit" in after_a_miss

    async def test_the_model_is_told_not_to_read_the_labels_out(
        self, registry: FormRegistry
    ) -> None:
        provider = StubProvider()
        service = make_service(registry, provider)
        await service.start_session("test_form", participant="alice")

        prompt = " ".join(provider.prompts)
        assert "do not" in prompt.lower() and "quote the labels" in prompt.lower()


# ---------------------------------------------------------------------------
# Agreements
# ---------------------------------------------------------------------------


def _agreement_form(**overrides: Any) -> FormDefinition:
    definition: dict[str, Any] = {
        "name": "consented",
        "version": "1.0.0",
        "title": "Consented Form",
        "status": FormStatus.ACTIVE,
        "escalation": [
            EscalationRoute(id="governance", team="Governance", contact="gov@example.com")
        ],
        "agreements": [
            Agreement(
                id="recording",
                title="How this is recorded",
                kind=AgreementKind.SYSTEM,
                stage=AgreementStage.BEFORE_START,
                text="Everything you type is stored against this submission.",
                route="governance",
            ),
            Agreement(
                id="accuracy",
                title="Confirmation of accuracy",
                kind=AgreementKind.CONFIRMATION,
                stage=AgreementStage.BEFORE_REVIEW,
                text="The details above are accurate to the best of my knowledge.",
            ),
        ],
        "sections": [
            FormSection(
                id="basics",
                title="Basics",
                fields=[
                    FormField(
                        id="owner",
                        label="Owner",
                        type=FieldType.PERSON,
                        importance=Importance.MANDATORY,
                    )
                ],
            )
        ],
    }
    definition.update(overrides)
    return FormDefinition(**definition)


@pytest.fixture
def consent_registry() -> FormRegistry:
    reg = FormRegistry()
    reg.create(_agreement_form(), activate=True)
    return reg


class TestAgreements:
    async def test_the_first_message_is_the_terms_and_nothing_else(
        self, consent_registry: FormRegistry
    ) -> None:
        service = make_service(consent_registry, StubProvider())
        started = await service.start_session("consented", participant="alice")

        assert "Everything you type is stored" in started["message"]
        # No question is asked alongside the terms: agreeing and answering in
        # one breath makes it unclear which the reply was to.
        assert "Owner" not in started["message"]

    async def test_nothing_is_recorded_until_the_terms_are_accepted(
        self, consent_registry: FormRegistry
    ) -> None:
        """Consent precedes collection, or the record covers only half of it."""
        provider = StubProvider([extraction(("owner", "Priya Raman", 0.95))])
        service = make_service(consent_registry, provider)
        sid = (await service.start_session("consented", participant="alice"))["session_id"]

        result = await service.send(sid, "Priya Raman owns it")

        session = await service.get_session(sid)
        assert session.answers.get("owner") is None
        assert result.awaiting_agreements == ["recording"]

    async def test_accepting_records_the_words_that_were_shown(
        self, consent_registry: FormRegistry
    ) -> None:
        service = make_service(consent_registry, StubProvider())
        sid = (await service.start_session("consented", participant="alice"))["session_id"]

        await service.send(sid, "I agree", author="alice")

        session = await service.get_session(sid)
        record = session.agreement_record("recording", "1.0.0")
        assert record is not None and record.accepted
        assert record.text == "Everything you type is stored against this submission."
        assert record.text_hash == agreements_digest(record.text)
        assert record.actor == "alice"
        assert record.stated == "I agree"

    async def test_the_conversation_starts_once_the_terms_are_accepted(
        self, consent_registry: FormRegistry
    ) -> None:
        provider = StubProvider([extraction(("owner", "Priya Raman", 0.95))])
        service = make_service(consent_registry, provider)
        sid = (await service.start_session("consented", participant="alice"))["session_id"]

        await service.send(sid, "I agree")
        result = await service.send(sid, "Priya Raman owns it")

        session = await service.get_session(sid)
        assert session.answers["owner"].value == "Priya Raman"
        # The start-stage term is behind them; whatever is being waited on now
        # is not that one.
        assert "recording" not in result.awaiting_agreements

    async def test_i_do_not_agree_is_a_refusal_not_an_acceptance(self) -> None:
        """The two open with the same word and mean the opposite."""
        from sa_forms.agreements import read_decision

        assert read_decision("I agree") is AgreementDecision.ACCEPTED
        assert read_decision("I do not agree") is AgreementDecision.DECLINED
        assert read_decision("no, I can't accept that") is AgreementDecision.DECLINED
        assert read_decision("what does retained mean?") is None

    async def test_a_refusal_is_recorded_and_routed_rather_than_argued_with(
        self, consent_registry: FormRegistry
    ) -> None:
        service = make_service(consent_registry, StubProvider())
        sid = (await service.start_session("consented", participant="alice"))["session_id"]

        result = await service.send(sid, "No, I don't agree to that")

        session = await service.get_session(sid)
        record = session.agreement_record("recording", "1.0.0")
        assert record is not None and not record.accepted
        assert session.open_support_requests()
        assert "Governance" in result.reply

    async def test_a_question_about_the_terms_is_answered_before_they_are_put_again(
        self, consent_registry: FormRegistry
    ) -> None:
        """Answering "please reply 'I agree'" to "what does that mean?" is how
        consent becomes a formality nobody read."""
        provider = StubProvider()
        provider.support_answer = {
            "answer": "It means the text of this conversation is kept with the submission.",
            "answered": True,
            "gap": "",
            "sources": [],
        }
        service = make_service(consent_registry, provider)
        sid = (await service.start_session("consented", participant="alice"))["session_id"]

        result = await service.send(sid, "what does stored against this submission mean?")

        assert "kept with the submission" in result.reply
        # And the terms are still on the table.
        assert result.awaiting_agreements == ["recording"]
        session = await service.get_session(sid)
        assert session.agreement_record("recording", "1.0.0") is None

    async def test_a_question_about_a_term_goes_to_whoever_owns_that_term(
        self, consent_registry: FormRegistry
    ) -> None:
        service = make_service(consent_registry, StubProvider())
        sid = (await service.start_session("consented", participant="alice"))["session_id"]

        result = await service.send(sid, "who can I talk to about this?")

        assert (result.support_request or {})["team"] == "Governance"

    async def test_a_declined_agreement_blocks_the_document(
        self, consent_registry: FormRegistry
    ) -> None:
        """And `allow_incomplete` does not reach it — that flag is about
        completeness, not about consent."""
        service = make_service(consent_registry, StubProvider())
        sid = (await service.start_session("consented", participant="alice"))["session_id"]
        await service.send(sid, "I don't agree")
        await service.set_answer(sid, "owner", "Priya Raman")

        with pytest.raises(ValidationError, match="agreement"):
            await service.generate(sid, ["markdown"], allow_incomplete=True)

    async def test_the_confirmation_is_taken_over_the_finished_submission(
        self, consent_registry: FormRegistry
    ) -> None:
        """A confirmation of accuracy taken before the answers attests to nothing."""
        service = make_service(consent_registry, StubProvider())
        sid = (await service.start_session("consented", participant="alice"))["session_id"]
        await service.send(sid, "I agree")
        await service.set_answer(sid, "owner", "Priya Raman")

        result = await service.send(sid, "that's everything, generate it")

        assert "accurate to the best of my knowledge" in result.reply
        session = await service.get_session(sid)
        assert session.status is not SessionStatus.READY_FOR_REVIEW

        confirmed = await service.send(sid, "confirmed")
        assert confirmed.ready_for_review
        session = await service.get_session(sid)
        assert session.status is SessionStatus.READY_FOR_REVIEW
        assert session.agreement_record("accuracy", "1.0.0") is not None

    async def test_a_confirmation_cannot_be_taken_before_there_is_anything_to_confirm(
        self, consent_registry: FormRegistry
    ) -> None:
        """The conversation gets this right by construction; a checkbox does not.

        "The details above are accurate" is undecided from the first turn, which
        a console offering a button for every undecided agreement would happily
        record — an attestation to a submission that does not exist yet.
        """
        service = make_service(consent_registry, StubProvider())
        sid = (await service.start_session("consented", participant="alice"))["session_id"]

        with pytest.raises(ValidationError, match="has not got there yet"):
            await service.decide_agreement(sid, "accuracy", accept=True, actor="alice")

        listing = await service.agreements(sid)
        by_id = {a["id"]: a for a in listing["outstanding"]}
        assert by_id["recording"]["decidable"] is True
        assert by_id["accuracy"]["decidable"] is False

        # Once the submission exists, it is exactly the right question to ask.
        await service.set_answer(sid, "owner", "Priya Raman")
        listing = await service.agreements(sid)
        assert {a["id"]: a for a in listing["outstanding"]}["accuracy"]["decidable"] is True

    async def test_accepting_outside_the_chat_asks_the_next_question(
        self, consent_registry: FormRegistry
    ) -> None:
        """Otherwise the console ticks a box and both sides sit there waiting."""
        service = make_service(consent_registry, StubProvider())
        sid = (await service.start_session("consented", participant="alice"))["session_id"]

        result = await service.decide_agreement(sid, "recording", accept=True, actor="alice")

        assert result["message"], "the conversation said nothing after being unblocked"
        session = await service.get_session(sid)
        last = [e for e in session.transcript if e.role == "assistant"][-1]
        assert last.targeted_fields == ["owner"]

    async def test_a_reworded_agreement_is_asked_again(self) -> None:
        """Accepting v1 is not accepting v2, and pretending otherwise puts words
        on the record that nobody read."""
        registry = FormRegistry()
        registry.create(_agreement_form(), activate=True)
        service = make_service(registry, StubProvider())
        sid = (await service.start_session("consented", participant="alice"))["session_id"]
        await service.send(sid, "I agree")

        session = await service.get_session(sid)
        reworded = _agreement_form()
        reworded.agreements[0].version = "2.0.0"
        reworded.agreements[0].text = "Everything you type is stored and retained for seven years."

        assert agreements_outstanding(reworded, session, AgreementStage.BEFORE_START)

    async def test_the_document_carries_the_agreement_and_who_accepted_it(
        self, consent_registry: FormRegistry
    ) -> None:
        service = make_service(consent_registry, StubProvider())
        sid = (await service.start_session("consented", participant="bob"))["session_id"]
        await service.send(sid, "I agree", author="bob")
        await service.set_answer(sid, "owner", "Priya Raman")
        await service.send(sid, "confirmed", author="bob")

        session = await service.get_session(sid)
        form = consent_registry.get("consented")
        rendered = render_session(form, session, "markdown")[0].decode("utf-8")

        assert "## Agreements" in rendered
        assert "Everything you type is stored against this submission." in rendered
        assert "bob" in rendered


# ---------------------------------------------------------------------------
# Agreement forms — where the agreements are the content
# ---------------------------------------------------------------------------


def _policy_form(**overrides: Any) -> FormDefinition:
    definition: dict[str, Any] = {
        "name": "policy_pack",
        "version": "1.0.0",
        "title": "Policy Pack",
        "kind": FormKind.AGREEMENT,
        "status": FormStatus.ACTIVE,
        "semantic_consistency_review": False,
        "agreements": [
            Agreement(
                id="acceptable_use",
                title="Acceptable use",
                kind=AgreementKind.USER,
                text="I will use my access only for work I have been asked to do.",
            ),
            Agreement(
                id="credentials",
                title="Credential handling",
                kind=AgreementKind.USER,
                text="I will keep credentials in the approved secret store.",
            ),
            Agreement(
                id="monitoring",
                title="Monitoring notice",
                kind=AgreementKind.SYSTEM,
                text="Platform activity is logged and retained for two years.",
            ),
        ],
    }
    definition.update(overrides)
    return FormDefinition(**definition)


@pytest.fixture
def policy_registry() -> FormRegistry:
    reg = FormRegistry()
    reg.create(_policy_form(), activate=True)
    return reg


class TestAgreementForms:
    def test_an_agreement_form_needs_no_fields(self) -> None:
        """The whole point: a policy pack asks for nothing but decisions."""
        form = _policy_form()
        assert form.is_agreement_form
        assert form.sections == []
        assert len(form.required_agreements()) == 3

    def test_an_intake_form_with_no_sections_is_refused(self) -> None:
        """It would ask nothing, forever, and look like a working form."""
        with pytest.raises(PydanticValidationError, match="declares no sections"):
            FormDefinition(name="empty", version="1.0.0", title="Empty")

    def test_an_agreement_form_with_no_agreements_is_refused(self) -> None:
        with pytest.raises(PydanticValidationError, match="declares no agreements"):
            FormDefinition(name="hollow", version="1.0.0", title="Hollow", kind=FormKind.AGREEMENT)

    async def test_terms_are_put_one_at_a_time(self, policy_registry: FormRegistry) -> None:
        """Five clauses behind a single "I agree" is the record this replaces.

        On an intake form the terms are a preamble and bundling them is
        proportionate. Here each one is the work.
        """
        service = make_service(policy_registry, StubProvider())
        started = await service.start_session("policy_pack", participant="sam")
        sid = started["session_id"]

        assert "Acceptable use" in started["message"]
        assert "Credential handling" not in started["message"]
        assert "1 of 3" in started["message"]

        second = await service.send(sid, "I agree", author="sam")
        assert second.awaiting_agreements == ["credentials"]
        assert "2 of 3" in second.reply

    async def test_it_is_not_complete_until_every_term_is_decided(
        self, policy_registry: FormRegistry
    ) -> None:
        """A form with no fields is complete on turn one under field counting."""
        service = make_service(policy_registry, StubProvider())
        sid = (await service.start_session("policy_pack", participant="sam"))["session_id"]
        form = policy_registry.get("policy_pack")

        session = await service.get_session(sid)
        report = analyse(form, session)
        assert report.mandatory_complete  # no fields — trivially true
        assert not report.finished  # and yet plainly not finished
        assert report.agreements_required == 3

        with pytest.raises(ValidationError, match="agreement"):
            await service.generate(sid, ["markdown"])

    async def test_accepting_every_term_finishes_the_session(
        self, policy_registry: FormRegistry
    ) -> None:
        service = make_service(policy_registry, StubProvider())
        sid = (await service.start_session("policy_pack", participant="sam"))["session_id"]

        for _ in range(3):
            result = await service.send(sid, "I agree", author="sam")

        session = await service.get_session(sid)
        assert len(session.agreements) == 3
        assert result.ready_for_review
        assert session.status is SessionStatus.READY_FOR_REVIEW

        artifacts = await service.generate(sid, ["markdown"])
        content, _ = await service.download(artifacts[0].id)
        rendered = content.decode("utf-8")
        assert "3/3 agreements accepted" in rendered
        assert "I will keep credentials in the approved secret store." in rendered

    async def test_declining_one_term_stops_the_document(
        self, policy_registry: FormRegistry
    ) -> None:
        service = make_service(policy_registry, StubProvider())
        sid = (await service.start_session("policy_pack", participant="sam"))["session_id"]

        await service.send(sid, "I agree", author="sam")
        declined = await service.send(sid, "No, I can't accept that", author="sam")

        assert "Governance" in declined.reply or "form owner" in declined.reply
        session = await service.get_session(sid)
        record = session.agreement_record("credentials", "1.0.0")
        assert record is not None and not record.accepted

        with pytest.raises(ValidationError, match="agreement"):
            await service.generate(sid, ["markdown"], allow_incomplete=True)

    async def test_progress_is_reported_in_agreements_not_fields(
        self, policy_registry: FormRegistry
    ) -> None:
        """ "100% of 0 fields" is the wrong answer about an unsigned policy pack."""
        service = make_service(policy_registry, StubProvider())
        sid = (await service.start_session("policy_pack", participant="sam"))["session_id"]
        await service.send(sid, "I agree", author="sam")

        status = await service.session_status(sid)
        assert status["completeness"]["agreements"] == "1/3"
        assert status["completeness"]["finished"] is False

        form = policy_registry.get("policy_pack")
        session = await service.get_session(sid)
        assert progress_line(analyse(form, session)) == "1 of 3 agreed; 2 left."

    async def test_an_agreement_form_can_still_ask_for_a_detail_or_two(self) -> None:
        """An acceptance nobody can tie to a person is evidence of very little."""
        registry = FormRegistry()
        registry.create(
            _policy_form(
                sections=[
                    FormSection(
                        id="who",
                        title="Who is accepting",
                        fields=[
                            FormField(
                                id="accepting_party",
                                label="Accepting party",
                                type=FieldType.PERSON,
                                importance=Importance.MANDATORY,
                            )
                        ],
                    )
                ]
            ),
            activate=True,
        )
        provider = StubProvider([extraction(("accepting_party", "Sam Whitfield", 0.95))])
        service = make_service(registry, provider)
        sid = (await service.start_session("policy_pack", participant="sam"))["session_id"]

        for _ in range(3):
            await service.send(sid, "I agree", author="sam")
        # Only once the terms are settled does it ask for anything.
        result = await service.send(sid, "Sam Whitfield", author="sam")

        session = await service.get_session(sid)
        assert session.answers["accepting_party"].value == "Sam Whitfield"
        assert result.ready_for_review

    async def test_deciding_from_outside_the_chat_puts_the_next_term(
        self, policy_registry: FormRegistry
    ) -> None:
        """A console ticking boxes must not run the pack off the end.

        The decision is taken out of band, so nothing has presented the term
        *after* it. Without this the consent panel empties while two agreements
        are still outstanding, and the screen looks finished when the session is
        two decisions from starting.
        """
        service = make_service(policy_registry, StubProvider())
        sid = (await service.start_session("policy_pack", participant="sam"))["session_id"]

        first = await service.decide_agreement(sid, "acceptable_use", accept=True, actor="sam")
        assert "Credential handling" in first["message"]

        session = await service.get_session(sid)
        assert session.transcript[-1].awaiting_agreements == ["credentials"]

        await service.decide_agreement(sid, "credentials", accept=True, actor="sam")
        last = await service.decide_agreement(sid, "monitoring", accept=True, actor="sam")
        # Nothing left to agree and no fields on this form: nothing left to say.
        assert last["message"] is None

    async def test_the_shipped_agreement_form_is_valid(self) -> None:
        reg = FormRegistry()
        reg.load_directory("examples/forms")
        form = reg.resolve("platform_access_agreement")

        assert form.kind is FormKind.AGREEMENT
        assert len(form.required_agreements()) == 5
        # Every agreement has somewhere to send a question about it.
        assert all(a.route is None or form.route(a.route) for a in form.agreements)


# ---------------------------------------------------------------------------
# Questions the participant asks
# ---------------------------------------------------------------------------


def _supported_form() -> FormDefinition:
    return FormDefinition(
        name="supported",
        version="1.0.0",
        title="Supported Form",
        status=FormStatus.ACTIVE,
        escalation=[
            EscalationRoute(
                id="default_team",
                team="Change Management",
                contact="cm@example.com",
                sla="one business day",
            ),
            EscalationRoute(
                id="sre", team="SRE On-Call", contact="sre@example.com", covers=["window"]
            ),
        ],
        knowledge=[
            KnowledgeNote(
                id="impact_policy",
                title="What counts as customer impacting",
                text="A change is customer impacting if a customer could notice it.",
                applies_to=["impacted"],
                source="Policy §4.2",
            )
        ],
        sections=[
            FormSection(
                id="basics",
                title="Basics",
                fields=[
                    FormField(
                        id="impacted",
                        label="Customers impacted",
                        type=FieldType.BOOLEAN,
                        importance=Importance.MANDATORY,
                        description="Whether customers will notice.",
                        help_text="Ask whether a customer could notice: an outage, a slower page.",
                    ),
                    FormField(
                        id="window",
                        label="Window",
                        importance=Importance.MANDATORY,
                        # Deliberately bare: nothing to explain it with, which is
                        # what should send it up a tier rather than reading the
                        # label back as though that were an answer.
                    ),
                ],
            )
        ],
    )


@pytest.fixture
def support_registry() -> FormRegistry:
    reg = FormRegistry()
    reg.create(_supported_form(), activate=True)
    return reg


class TestAnsweringQuestions:
    async def test_the_first_answer_comes_from_the_form_itself(
        self, support_registry: FormRegistry
    ) -> None:
        """No model call: the author already wrote this answer."""
        provider = StubProvider()
        service = make_service(support_registry, provider)
        sid = (await service.start_session("supported", participant="alice"))["session_id"]
        provider.prompts.clear()

        result = await service.send(sid, "what do you mean by customers impacted?")

        assert "a customer could notice" in result.reply
        session = await service.get_session(sid)
        assert [r.tier for r in session.support_requests] == ["definition"]

    async def test_asking_again_moves_up_to_the_reference_material(
        self, support_registry: FormRegistry
    ) -> None:
        provider = StubProvider()
        provider.support_answer = {
            "answer": "Only if a customer could notice the change.",
            "answered": True,
            "gap": "",
            "sources": ["impact_policy"],
        }
        service = make_service(support_registry, provider)
        sid = (await service.start_session("supported", participant="alice"))["session_id"]

        await service.send(sid, "what do you mean by customers impacted?")
        result = await service.send(sid, "that doesn't answer it — what counts as impacted?")

        assert "Only if a customer could notice" in result.reply
        # Traceable: an answer about policy that cannot be traced to the policy
        # is an opinion in a confident font.
        assert "Policy §4.2" in result.reply
        session = await service.get_session(sid)
        assert "grounded" in [r.tier for r in session.support_requests]

    async def test_a_question_the_material_cannot_settle_goes_to_a_human(
        self, support_registry: FormRegistry
    ) -> None:
        provider = StubProvider()
        provider.support_answer = {
            "answer": "",
            "answered": False,
            "gap": "the notes say nothing about freeze periods",
            "sources": [],
        }
        service = make_service(support_registry, provider)
        sid = (await service.start_session("supported", participant="alice"))["session_id"]

        result = await service.send(sid, "what do you mean by the window?")

        assert "SRE On-Call" in result.reply
        session = await service.get_session(sid)
        routed = session.open_support_requests()
        assert routed and routed[0].team == "SRE On-Call"
        assert result.support_request is not None

    async def test_asking_for_a_human_is_not_answered_with_another_explanation(
        self, support_registry: FormRegistry
    ) -> None:
        service = make_service(support_registry, StubProvider())
        sid = (await service.start_session("supported", participant="alice"))["session_id"]

        result = await service.send(sid, "who can I ask about this?")

        assert result.intent is Intent.ASK_ESCALATION
        assert "Change Management" in result.reply or "SRE On-Call" in result.reply

    def test_a_question_is_not_filed_against_the_wrong_field(self) -> None:
        """A confident explanation of something they did not ask about is worse
        than admitting you could not tell which field they meant.

        Both halves are real failures. `what` is a perfectly good extraction
        alias and appears in every question ever asked; substring matching files
        "risk" against "asterisk".
        """
        referenced = ConversationEngine._referenced_fields
        form = FormDefinition(
            name="aliased",
            version="1.0.0",
            title="Aliased",
            sections=[
                FormSection(
                    id="s",
                    title="S",
                    fields=[
                        FormField(id="description", label="Description", aliases=["what", "why"]),
                        FormField(id="risk", label="Risk", aliases=["risk level"]),
                        FormField(
                            id="impacted",
                            label="Customers impacted",
                            type=FieldType.BOOLEAN,
                            aliases=["customer impact"],
                        ),
                    ],
                )
            ],
        )

        assert referenced(form, "what do you mean by customers impacted?") == [
            form.field("impacted")
        ]
        assert referenced(form, "why do you need the risk level?") == [form.field("risk")]
        assert referenced(form, "put an asterisk next to it") == []

    async def test_raising_the_change_is_not_mistaken_for_asking_for_help(self) -> None:
        """ "Raise this" is what people call the thing they are filling in."""
        classify = ConversationEngine._classify
        assert classify("I want to raise this change for Friday") is Intent.PROVIDE_INFO
        assert classify("can you raise this with the platform team?") is Intent.ASK_ESCALATION

    async def test_an_escalated_question_does_not_stop_the_form(
        self, support_registry: FormRegistry
    ) -> None:
        """A blocked field must not block every other field."""
        provider = StubProvider()
        provider.support_answer = {"answer": "", "answered": False, "gap": "", "sources": []}
        service = make_service(support_registry, provider)
        sid = (await service.start_session("supported", participant="alice"))["session_id"]

        await service.send(sid, "what do you mean by the window?")
        session = await service.get_session(sid)

        assert session.answers.get("window") is None or not session.answers["window"].is_settled
        assert "window" not in session.skipped_fields

    async def test_an_open_question_travels_onto_the_document(
        self, support_registry: FormRegistry
    ) -> None:
        provider = StubProvider()
        provider.support_answer = {"answer": "", "answered": False, "gap": "", "sources": []}
        service = make_service(support_registry, provider)
        sid = (await service.start_session("supported", participant="alice"))["session_id"]
        await service.send(sid, "who can I ask about the window?")

        session = await service.get_session(sid)
        rendered = render_session(support_registry.get("supported"), session, "markdown")[0].decode(
            "utf-8"
        )

        assert "## Open questions" in rendered
        assert "SRE On-Call" in rendered

    async def test_a_team_answer_closes_the_question(self, support_registry: FormRegistry) -> None:
        provider = StubProvider()
        provider.support_answer = {"answer": "", "answered": False, "gap": "", "sources": []}
        service = make_service(support_registry, provider)
        sid = (await service.start_session("supported", participant="alice"))["session_id"]
        await service.send(sid, "who can I ask about the window?")

        session = await service.get_session(sid)
        request_id = session.open_support_requests()[0].id
        await service.answer_question(sid, request_id, "Use 02:00-04:00 UTC on Saturdays.")

        session = await service.get_session(sid)
        assert not session.open_support_requests()
        assert "02:00-04:00" in session.support_requests[0].resolution

    def test_a_question_about_a_term_is_answered_from_the_term(self) -> None:
        """The gap this class of test exists for.

        In a real session, "what does this mean, exactly?" and "can you explain
        the retention policy?" both came back as "I've put this to Platform
        Governance, they usually come back within two business days" — about
        terms whose own text was on the screen. A two-day wait to be told what a
        sentence in front of you means is worse than the paper form.
        """
        from sa_forms.support import answer_from_agreements

        agreement = Agreement(
            id="recording",
            title="How this is recorded",
            text="What you type is retained for seven years under the change management policy.",
            explanation="Everything you type is kept against this request for seven years.",
            faqs=[
                AgreementFaq(
                    question="Why is it retained for seven years?",
                    aliases=["tell me about the retention policy", "how long is it kept"],
                    answer="Seven years is what the change management policy sets for audit.",
                )
            ],
        )

        # A bare "what does this mean?" has no matchable words at all — every
        # one of them is noise — and it is the commonest question there is.
        bare = answer_from_agreements([agreement], "What does this mean, exactly?")
        assert bare is not None and "kept against this request" in bare[0]

        matched = answer_from_agreements(
            [agreement], "can you explain me more about the retention for change management policy?"
        )
        assert matched is not None and "audit" in matched[0]

        # Something the material genuinely does not cover still goes to a human.
        assert answer_from_agreements([agreement], "who owns the payments gateway?") is None

    async def test_two_different_questions_are_not_treated_as_one_repeated(
        self, consent_registry: FormRegistry
    ) -> None:
        """A counter keyed on "questions about the terms" marks the second
        distinct question as a repeat and fetches a human. What makes something
        a repeat is having already been given the same answer."""
        registry = FormRegistry()
        registry.create(
            _agreement_form(
                agreements=[
                    Agreement(
                        id="recording",
                        title="How this is recorded",
                        text="Everything you type is stored against this submission.",
                        explanation="It is all kept with the submission.",
                        faqs=[
                            AgreementFaq(
                                question="Who can see what I type?",
                                answer="The approver and the auditors, nobody else.",
                            ),
                            AgreementFaq(
                                question="What happens to attachments?",
                                answer="They are read and stored exactly like typed text.",
                            ),
                        ],
                    )
                ]
            ),
            activate=True,
        )
        service = make_service(registry, StubProvider())
        sid = (await service.start_session("consented", participant="alice"))["session_id"]

        first = await service.send(sid, "who can see what I type?")
        second = await service.send(sid, "what happens to attachments?")

        assert "approver and the auditors" in first.reply
        assert "read and stored exactly like typed text" in second.reply
        session = await service.get_session(sid)
        assert [r.tier for r in session.support_requests] == ["definition", "definition"]
        assert not session.open_support_requests()

    async def test_naming_a_term_answers_which_one_cannot_be_accepted(
        self, consent_registry: FormRegistry
    ) -> None:
        """ "Which of these?" — "how recorded". That is an answer.

        In the real session it was met with all the terms again, twice, and the
        refusal was never recorded against anything.
        """
        registry = FormRegistry()
        registry.create(
            _agreement_form(
                agreements=[
                    Agreement(
                        id="recording_notice",
                        title="How this conversation is recorded",
                        text="What you type is stored against this request.",
                    ),
                    Agreement(
                        id="authority_to_raise",
                        title="Authority to raise this change",
                        text="I am authorised to raise this on behalf of the owning team.",
                    ),
                ]
            ),
            activate=True,
        )
        service = make_service(registry, StubProvider())
        sid = (await service.start_session("consented", participant="alice"))["session_id"]

        asked = await service.send(sid, "I can't accept one of these")
        assert "Which of these" in asked.reply

        await service.send(sid, "how recorded")
        session = await service.get_session(sid)
        record = session.agreement_record("recording_notice", "1.0.0")
        assert record is not None and not record.accepted
        # And nothing was recorded against the one they did not name.
        assert session.agreement_record("authority_to_raise", "1.0.0") is None

    def test_the_most_specific_route_wins(self) -> None:
        form = _supported_form()
        assert support_route_for(form, ["window"]).id == "sre"
        assert support_route_for(form, ["impacted"]).id == "default_team"
        assert support_route_for(form, []).id == "default_team"


# ---------------------------------------------------------------------------
# End-to-end
# ---------------------------------------------------------------------------


async def test_full_lifecycle_from_thread_to_baseline(registry: FormRegistry) -> None:
    """JIRA thread → conversation → document → approval → baseline."""
    provider = StubProvider(
        [
            # The ingest pass runs a semantic call of its own; the labelled
            # lines in the ticket are already handled deterministically.
            extraction(),
            # The follow-up turn supplies the one thing the thread lacked.
            extraction(
                ("target_date", "2026-03-15", 0.95),
                actions=[{"description": "Book the change window with ops", "owner": "alice"}],
            ),
        ]
    )
    service = make_service(registry, provider)

    started = await service.start_session("test_form", participant="alice")
    sid = started["session_id"]

    # 1. Mine an existing ticket — no questions asked yet.
    report = await service.ingest(
        sid,
        "jira",
        {
            "key": "OPS-42",
            "fields": {
                "reporter": {"displayName": "alice"},
                "description": "Owner: Priya Raman\nRisk level: low",
                "comment": {"comments": []},
            },
        },
    )
    assert set(report["captured"]) == {"owner", "risk_level"}

    # 2. One conversational turn closes the remaining gap.
    result = await service.send(sid, "we're going on 2026-03-15")
    assert "target_date" in result.captured
    assert result.ready_for_review

    # 3. Render.
    records = await service.generate(sid, ["markdown", "json"])
    assert len(records) == 2

    # 4. Approve — someone who did not contribute.
    approved = await service.approve(records[0].id, approver="bob")
    assert approved.is_baselined

    # 5. The captured commitment survived onto the record.
    session = await service.get_session(sid)
    assert any("change window" in i.description for i in session.action_items)

    # 6. And the baseline verifies.
    assert (await service.verify_baseline(records[0].id))["intact"]


async def test_the_shipped_example_form_is_valid() -> None:
    """The reference definition must load and be internally consistent."""
    reg = FormRegistry()
    forms = reg.load_directory("examples/forms")
    assert forms, "examples/forms should contain at least one definition"

    change_request = reg.resolve("change_request")
    assert change_request.status is FormStatus.ACTIVE
    assert change_request.mandatory_fields()

    # Every mandatory field must be able to answer "why do you need this?".
    missing = [f.id for f in change_request.mandatory_fields() if not f.rationale]
    assert not missing, f"mandatory fields without a rationale: {missing}"

    # Conditional guards must reference fields that exist.
    for field in change_request.fields():
        if field.ask_when:
            assert "answers." in field.ask_when
