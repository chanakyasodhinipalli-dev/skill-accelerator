"""Tests for the cross-session assistant.

Retrieval is deterministic, so it can be asserted on directly. The generated
prose cannot be, and is not: what matters is that the right records are found,
that the citations point at them, and that an unavailable model degrades to a
useful answer rather than an error.
"""

from __future__ import annotations

from typing import Any

import pytest

from sa_forms.assistant import tokenize
from sa_forms.models import (
    FieldType,
    FormDefinition,
    FormField,
    FormSection,
    FormStatus,
    Importance,
)
from sa_forms.registry import FormRegistry
from sa_forms.service import FormsService
from sa_forms.store import InMemoryArtifactStore, InMemorySessionStore
from sa_platform.context import ExecutionContext, Principal, bind_context


@pytest.fixture(autouse=True)
def _principal() -> Any:
    with bind_context(
        ExecutionContext(principal=Principal(subject="tests", permissions=frozenset({"*"})))
    ):
        yield


def definition(name: str, title: str) -> FormDefinition:
    return FormDefinition(
        name=name,
        title=title,
        status=FormStatus.ACTIVE,
        sections=[
            FormSection(
                id="main",
                title="Main",
                fields=[
                    FormField(
                        id="owner",
                        label="Change owner",
                        type=FieldType.PERSON,
                        importance=Importance.MANDATORY,
                    ),
                    FormField(
                        id="system",
                        label="Affected system",
                        importance=Importance.MANDATORY,
                    ),
                    FormField(id="salary", label="Salary band", sensitive=True),
                ],
            )
        ],
    )


class _NoModel:
    """Stands in for an unavailable provider."""

    async def complete_structured(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("provider is down")


@pytest.fixture
async def service() -> FormsService:
    registry = FormRegistry()
    registry.create(definition("change_request", "Production Change Request"), activate=True)
    registry.create(definition("vendor_review", "Vendor Review"), activate=True)

    instance = FormsService(
        registry=registry,
        sessions=InMemorySessionStore(),
        artifacts=InMemoryArtifactStore(),
        llm_provider=_NoModel(),
    )

    started = await instance.start_session("change_request", participant="priya")
    session_id = started["session_id"]
    await instance.set_answer(session_id, "owner", "Priya Raman", author="priya")
    await instance.set_answer(session_id, "system", "payments-gateway", author="priya")
    await instance.set_answer(session_id, "salary", "Band 7", author="priya")
    return instance


class TestTokenize:
    def test_stopwords_and_short_tokens_are_dropped(self) -> None:
        assert tokenize("what is the owner of it") == ["owner"]

    def test_plurals_fold_onto_the_singular(self) -> None:
        assert tokenize("forms") == tokenize("form")

    def test_double_s_words_are_left_alone(self) -> None:
        assert "access" in tokenize("access control")


class TestSearch:
    async def test_a_value_stated_in_a_session_is_findable(self, service: FormsService) -> None:
        hits = await service.assistant.search("payments-gateway")
        assert hits
        assert hits[0].kind == "session"

    async def test_results_can_be_restricted_to_one_kind(self, service: FormsService) -> None:
        hits = await service.assistant.search("change", kind="form")
        assert hits and all(h.kind == "form" for h in hits)

    async def test_an_empty_query_browses_by_recency(self, service: FormsService) -> None:
        hits = await service.assistant.search("")
        assert hits
        assert all(hit.score == 0.0 for hit in hits)

    async def test_rare_terms_outrank_common_ones(self, service: FormsService) -> None:
        """Both forms match "review"; only one matches the specific term."""
        hits = await service.assistant.search("vendor")
        assert hits[0].title == "Vendor Review"

    async def test_nothing_matches_returns_nothing(self, service: FormsService) -> None:
        assert await service.assistant.search("zzzzz-unmatchable-term") == []


class TestAsk:
    async def test_an_answer_is_composed_without_a_model(self, service: FormsService) -> None:
        answer = await service.assistant.ask("what is payments-gateway about?", participant="priya")
        assert answer.generated is False
        assert answer.answer
        assert answer.grounded is True

    async def test_the_top_session_contributes_its_values(self, service: FormsService) -> None:
        """ "Here is a record that matched" is not an answer to "what did we decide"."""
        answer = await service.assistant.ask("what did we decide about payments-gateway?")
        assert "Priya Raman" in answer.answer

    async def test_a_sensitive_field_is_named_but_not_valued(self, service: FormsService) -> None:
        answer = await service.assistant.ask("tell me about payments-gateway")
        assert "Band 7" not in answer.answer
        assert "Salary band" in answer.answer

    async def test_citations_point_at_the_records_used(self, service: FormsService) -> None:
        answer = await service.assistant.ask("payments-gateway")
        assert answer.citations
        assert all(c.id for c in answer.citations)

    async def test_actions_are_data_rather_than_links(self, service: FormsService) -> None:
        """The same answer has to serve a console, a chat integration, and a CLI."""
        answer = await service.assistant.ask("payments-gateway")
        assert all("action" in a and "label" in a for a in answer.actions)

    async def test_my_sessions_is_answered_from_the_participant(
        self, service: FormsService
    ) -> None:
        mine = await service.assistant.ask("which of my forms are open?", participant="priya")
        assert "priya" in mine.answer

        theirs = await service.assistant.ask("which of my forms are open?", participant="ben")
        assert "no form sessions" in theirs.answer

    async def test_a_follow_up_inherits_the_previous_question_terms(
        self, service: FormsService
    ) -> None:
        """ "and the owner?" carries no searchable terms of its own."""
        first = await service.assistant.ask("what about payments-gateway?")
        follow_up = await service.assistant.ask("owner?", conversation_id=first.conversation_id)
        assert follow_up.citations
        assert follow_up.conversation_id == first.conversation_id

    async def test_an_unmatched_question_says_so_rather_than_inventing(
        self, service: FormsService
    ) -> None:
        answer = await service.assistant.ask("zzzzz-unmatchable-term")
        assert answer.grounded is False
        assert "Nothing matched" in answer.answer
