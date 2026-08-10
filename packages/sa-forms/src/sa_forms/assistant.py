"""A chatbot that can answer about *any* form conversation.

The conversation engine fills one form. This is the other thing people need: a
place to ask "what did we decide about the December release?", "which of my
forms are waiting on me?", "who approved the last change request?" — questions
that span sessions, forms, and artifacts.

Two rules shape the design.

**Retrieval is deterministic; only the prose is generated.** The same choice the
question planner makes. Evidence is selected in code and cited by id, so an
answer can be checked against the session it came from. A model that is
unavailable — or the deterministic profile — degrades to a plainly-worded
summary of the same evidence rather than to an error.

**Nothing is answered without evidence.** Every claim carries a citation to a
session, a form, or an artifact. An assistant over governed records that
paraphrases from memory is worse than useless.
"""

from __future__ import annotations

import math
import re
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from sa_platform.logging import get_logger

from .completeness import analyse
from .models import ArtifactStatus, FormDefinition, FormSession, SessionStatus

logger = get_logger(__name__)

#: Words carrying no retrieval signal. Short list on purpose: an aggressive
#: stoplist removes the words that make a question specific.
_STOPWORDS = frozenset(
    """a an and are as at be by do does for from has have how i in is it its me my of on or
    our that the their there they this to was we were what when where which who why will with
    you your can could would should about""".split()
)

_TOKEN = re.compile(r"[a-z0-9][a-z0-9_.-]*")

#: How much each kind of match counts. A hit in a form's title means more than
#: one buried in a transcript, which is mostly conversational filler.
_FIELD_WEIGHTS = {
    "title": 3.0,
    "identity": 2.5,
    "answers": 2.0,
    "people": 1.5,
    "body": 1.0,
}

#: Sessions touched recently are more likely to be the subject of a question.
_RECENCY_HALF_LIFE_DAYS = 14.0

_MAX_EVIDENCE = 6
_MAX_HISTORY_TURNS = 12


@dataclass(slots=True)
class Hit:
    """One retrieved record, with the reason it matched."""

    kind: str  # session | form | artifact
    id: str
    title: str
    score: float
    summary: str = ""
    matched_terms: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "id": self.id,
            "title": self.title,
            "score": round(self.score, 3),
            "summary": self.summary,
            "matched_terms": self.matched_terms,
            **self.detail,
        }


@dataclass(slots=True)
class AssistantAnswer:
    """What the assistant returns: prose, its evidence, and what to do next."""

    answer: str
    citations: list[Hit] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    conversation_id: str = ""
    grounded: bool = True
    #: True when the wording came from a model rather than the fallback.
    generated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "citations": [c.to_dict() for c in self.citations],
            "actions": self.actions,
            "conversation_id": self.conversation_id,
            "grounded": self.grounded,
            "generated": self.generated,
        }


_ANSWER_SYSTEM = """\
You answer questions about form-filling conversations inside a company.

Rules:
- Answer only from the evidence provided. If it does not contain the answer, say
  so and name what is missing.
- Refer to records the way the evidence labels them, so the reader can find them.
- Be brief. Two or three sentences unless a list is genuinely clearer.
- Never invent a session id, an approver, a date, or a value.
"""

_ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "title": "assistant_answer",
    "properties": {
        "answer": {
            "type": "string",
            "description": "The reply, grounded in the evidence. Empty if the evidence is insufficient.",
        },
        "used_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Ids of the evidence records actually used.",
        },
    },
    "required": ["answer"],
}


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens, minus stopwords, crudely singularised."""
    tokens: list[str] = []
    for match in _TOKEN.findall(text.lower()):
        token = match.rstrip(".-_")
        if len(token) < 2 or token in _STOPWORDS:
            continue
        # Enough to make "forms" match "form"; a real stemmer would be more
        # accurate and would also need a dependency and a language assumption.
        if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
            token = token[:-1]
        tokens.append(token)
    return tokens


@dataclass(slots=True)
class _Document:
    """A searchable record, split into weighted zones."""

    kind: str
    id: str
    title: str
    zones: dict[str, str]
    timestamp: float
    summary: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def term_zones(self) -> dict[str, set[str]]:
        return {zone: set(tokenize(text)) for zone, text in self.zones.items()}


class FormsAssistant:
    """Search and question answering across every form record."""

    def __init__(self, service: Any, *, llm_provider: Any | None = None) -> None:
        self._service = service
        self._llm = llm_provider
        # Conversation memory so follow-ups work ("and the other one?"). In
        # process only: an assistant thread is cheap to lose and expensive to
        # persist correctly, and the records it talks about are already durable.
        self._history: dict[str, deque[tuple[str, str]]] = {}

    def _provider(self) -> Any:
        if self._llm is None:
            from sa_connectors.llm import build_provider

            self._llm = build_provider()
        return self._llm

    # -- indexing ----------------------------------------------------------
    async def _documents(self, *, session_limit: int = 500) -> list[_Document]:
        """Build the searchable set from the stores.

        A linear scan. Correct and fast enough for the thousands of sessions a
        form platform actually holds; the seam for a search backend is here, and
        it is this method alone.
        """
        documents: list[_Document] = []

        for form in self._service.registry.list_forms(include_inactive=True):
            documents.append(self._form_document(form))

        sessions = await self._service.sessions.list_sessions(limit=session_limit)
        for session in sessions:
            documents.append(self._session_document(session))

        artifacts = await self._service.artifacts.list_artifacts(limit=session_limit)
        for record in artifacts:
            documents.append(self._artifact_document(record))

        return documents

    @staticmethod
    def _form_document(form: FormDefinition) -> _Document:
        labels = " ".join(
            f"{f.label} {' '.join(f.aliases)} {f.description}"
            for section in form.sections
            for f in section.fields
        )
        return _Document(
            kind="form",
            id=f"{form.name}@{form.version}",
            title=form.title,
            zones={
                "title": f"{form.title} {form.name}",
                "identity": f"{form.name} {' '.join(form.tags)} {form.owner or ''}",
                "body": f"{form.description} {form.guidance} {labels}",
            },
            timestamp=form.updated_at,
            summary=(
                f"{form.title} v{form.version} ({form.status.value}), "
                # In the units the form is measured in. An agreement form
                # described as "0 required of 0 fields" reads as an empty one.
                + (
                    f"{len(form.required_agreements())} agreement(s) to accept"
                    if form.is_agreement_form
                    else f"{len(form.mandatory_fields())} required of {form.field_count()} fields"
                )
            ),
            detail={"form": form.name, "version": form.version, "status": form.status.value},
        )

    @staticmethod
    def _session_document(session: FormSession) -> _Document:
        answered = {
            fid: answer
            for fid, answer in session.answers.items()
            if answer.value not in (None, "", [])
        }
        answer_text = " ".join(f"{fid} {answer.value}" for fid, answer in answered.items())
        transcript = " ".join(entry.text for entry in session.transcript[-60:])
        return _Document(
            kind="session",
            id=session.id,
            title=session.title or f"{session.form_name} — {', '.join(session.participants)}",
            zones={
                "title": f"{session.title} {session.form_name}",
                "identity": f"{session.form_name} {session.id} {session.status.value}",
                "answers": answer_text,
                "people": " ".join(session.participants),
                "body": transcript,
            },
            timestamp=session.updated_at,
            summary=(
                f"{session.form_name}@{session.form_version} · {session.status.value} · "
                f"{len(answered)} answered · {', '.join(session.participants) or 'no participants'}"
            ),
            detail={
                "form": session.form_name,
                "status": session.status.value,
                "participants": session.participants,
                "answered": len(answered),
                "updated_at": session.updated_at,
            },
        )

    @staticmethod
    def _artifact_document(record: Any) -> _Document:
        approvers = " ".join(a.approver for a in record.approvals)
        return _Document(
            kind="artifact",
            id=record.id,
            title=record.filename or f"{record.form_name} ({record.format})",
            zones={
                "title": f"{record.filename} {record.form_name}",
                "identity": f"{record.form_name} {record.format} {record.status.value}",
                "people": approvers,
                "body": f"revision {record.revision} {record.status.value}",
            },
            timestamp=record.created_at,
            summary=(
                f"{record.form_name}@{record.form_version} · {record.format} · "
                f"{record.status.value} · rev {record.revision}"
            ),
            detail={
                "session_id": record.session_id,
                "format": record.format,
                "status": record.status.value,
                "baselined": record.is_baselined,
            },
        )

    # -- retrieval ---------------------------------------------------------
    async def search(self, query: str, *, limit: int = 10, kind: str | None = None) -> list[Hit]:
        """Rank records against a query."""
        terms = tokenize(query)
        documents = [d for d in await self._documents() if kind is None or d.kind == kind]
        if not terms or not documents:
            # An empty query is a browse, not a search: show what changed last.
            return [
                self._to_hit(d, 0.0, [])
                for d in sorted(documents, key=lambda d: d.timestamp, reverse=True)[:limit]
            ]

        indexed = [(d, d.term_zones()) for d in documents]
        idf = self._inverse_document_frequency(indexed, terms)
        now = time.time()

        scored: list[Hit] = []
        for document, zones in indexed:
            score = 0.0
            matched: list[str] = []
            for term in terms:
                best = 0.0
                for zone, tokens in zones.items():
                    if term in tokens:
                        best = max(best, _FIELD_WEIGHTS.get(zone, 1.0))
                if best:
                    score += best * idf[term]
                    matched.append(term)
            if score <= 0:
                continue
            score *= self._recency_factor(document.timestamp, now)
            scored.append(self._to_hit(document, score, matched))

        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:limit]

    @staticmethod
    def _inverse_document_frequency(
        indexed: list[tuple[_Document, dict[str, set[str]]]], terms: list[str]
    ) -> dict[str, float]:
        """Weight rare terms above common ones.

        Without this, a query mentioning the form name scores every session for
        that form identically and the specific words in the question — the ones
        that actually identify the record — are drowned out.
        """
        total = len(indexed)
        idf: dict[str, float] = {}
        for term in set(terms):
            containing = sum(
                1 for _, zones in indexed if any(term in tokens for tokens in zones.values())
            )
            idf[term] = math.log((total + 1) / (containing + 1)) + 1.0
        return idf

    @staticmethod
    def _recency_factor(timestamp: float, now: float) -> float:
        age_days = max(0.0, (now - timestamp) / 86400.0)
        # Halves every fortnight, floored so an old record still ranks on merit.
        return 0.5 + 0.5 * math.pow(0.5, age_days / _RECENCY_HALF_LIFE_DAYS)

    @staticmethod
    def _to_hit(document: _Document, score: float, matched: list[str]) -> Hit:
        return Hit(
            kind=document.kind,
            id=document.id,
            title=document.title,
            score=score,
            summary=document.summary,
            matched_terms=matched,
            detail=document.detail,
        )

    # -- question answering ------------------------------------------------
    async def ask(
        self,
        question: str,
        *,
        conversation_id: str | None = None,
        participant: str = "user",
    ) -> AssistantAnswer:
        """Answer a question about the form estate, with citations."""
        conversation_id = conversation_id or f"ac_{uuid.uuid4().hex[:10]}"
        history = self._history.setdefault(conversation_id, deque(maxlen=_MAX_HISTORY_TURNS))

        # Follow-ups ("and the other one?") carry no searchable terms of their
        # own; the previous question supplies them.
        retrieval_query = question
        if len(tokenize(question)) < 2 and history:
            retrieval_query = f"{history[-1][0]} {question}"

        hits = await self.search(retrieval_query, limit=_MAX_EVIDENCE)
        overview = await self._overview(participant)
        evidence, details = await self._render_evidence(hits)

        answer = await self._generate(question, evidence, overview, history)
        generated = bool(answer)
        if not answer:
            answer = self._compose(question, hits, overview, details)

        history.append((question, answer))
        return AssistantAnswer(
            answer=answer,
            citations=hits,
            actions=self._actions(hits, overview),
            conversation_id=conversation_id,
            grounded=bool(hits),
            generated=generated,
        )

    async def _overview(self, participant: str) -> dict[str, Any]:
        """Facts worth having for any question, retrieved or not."""
        sessions = await self._service.sessions.list_sessions(limit=200)
        mine = [s for s in sessions if participant in s.participants]
        pending = await self._service.pending_reviews(20)
        return {
            "participant": participant,
            "form_count": len(self._service.registry.list_forms()),
            "open_sessions": [s for s in sessions if s.status is SessionStatus.COLLECTING],
            "my_sessions": mine,
            "pending_reviews": pending,
        }

    async def _render_evidence(self, hits: list[Hit]) -> tuple[str, dict[str, list[str]]]:
        """Turn hits into text a model can cite, expanding sessions with detail.

        Returns the rendered block *and* the per-hit detail lines, so the
        deterministic composer can quote the same facts the model was given
        rather than a thinner summary of them.
        """
        blocks: list[str] = []
        details: dict[str, list[str]] = {}
        for hit in hits:
            lines = [f"[{hit.kind}:{hit.id}] {hit.title}", hit.summary]
            if hit.kind == "session":
                session = await self._service.sessions.try_load(hit.id)
                if session is not None:
                    detail = self._session_detail(session)
                    details[hit.id] = detail
                    lines.extend(detail)
            blocks.append("\n".join(line for line in lines if line))
        return "\n\n".join(blocks), details

    def _session_detail(self, session: FormSession) -> list[str]:
        """Answered values and open gaps for one session.

        Sensitive fields are named but not valued: this assistant is a search
        surface, and a search surface is the wrong place to widen who can read
        a salary or a personal identifier.
        """
        lines: list[str] = []
        try:
            form = self._service.registry.get(session.form_name, session.form_version)
        except Exception:  # noqa: BLE001 - an archived form must not break search
            form = None

        for field_id, answer in session.answers.items():
            if answer.value in (None, "", []):
                continue
            definition = form.try_field(field_id) if form else None
            label = definition.label if definition else field_id
            if definition is not None and definition.sensitive:
                lines.append(f"  {label}: [recorded, not shown]")
            else:
                lines.append(f"  {label}: {answer.value}")

        if form is not None:
            blocking = analyse(form, session).blocking_gaps()
            if blocking:
                missing = ", ".join(gap.field.label for gap in blocking[:5])
                lines.append(f"  still required: {missing}")
        for item in session.action_items:
            lines.append(f"  action: {item.description} ({item.status.value})")
        return lines

    async def _generate(
        self,
        question: str,
        evidence: str,
        overview: dict[str, Any],
        history: deque[tuple[str, str]],
    ) -> str:
        """Ask a model to phrase the answer. Empty string means 'fall back'."""
        if not evidence and not overview["my_sessions"]:
            return ""

        lines: list[str] = []
        if history:
            lines.append("Earlier in this conversation:")
            lines += [f"Q: {q}\nA: {a}" for q, a in list(history)[-3:]]
            lines.append("")
        lines += [
            f"The person asking is '{overview['participant']}'.",
            f"They have {len(overview['my_sessions'])} form session(s) and "
            f"{len(overview['pending_reviews'])} artifact(s) awaiting review.",
            "",
            "Evidence:",
            evidence or "(nothing matched the question)",
            "",
            f"Question: {question}",
        ]

        try:
            from sa_connectors.llm.base import Message

            response = await self._provider().complete_structured(
                [Message.user("\n".join(lines))], _ANSWER_SCHEMA, system=_ANSWER_SYSTEM
            )
            return str(response.get("answer", "")).strip()
        except Exception as exc:  # noqa: BLE001 - fall back rather than fail
            logger.warning(
                "assistant answer generation failed; using the deterministic summary",
                extra={"error": str(exc)},
            )
            return ""

    def _compose(
        self,
        question: str,
        hits: list[Hit],
        overview: dict[str, Any],
        details: dict[str, list[str]] | None = None,
    ) -> str:
        """Answer from the evidence with no model involved.

        This runs whenever the model is unavailable or the deterministic profile
        is selected. It is less fluent and exactly as correct.
        """
        asked = set(tokenize(question))
        parts: list[str] = []

        if asked & {"approve", "approval", "review", "sign", "signoff", "pending", "waiting"}:
            pending = overview["pending_reviews"]
            if pending:
                parts.append(f"{len(pending)} artifact(s) are awaiting review:")
                parts += [
                    f"- {r.form_name}@{r.form_version} ({r.format}, rev {r.revision}) — {r.id}"
                    for r in pending[:5]
                ]
            else:
                parts.append("Nothing is waiting for review right now.")

        elif asked & {"mine", "my", "open", "progress", "outstanding", "incomplete", "resume"}:
            mine = overview["my_sessions"]
            if mine:
                parts.append(f"{overview['participant']} has {len(mine)} session(s):")
                parts += [f"- {s.form_name} ({s.status.value}) — {s.id}" for s in mine[:5]]
            else:
                parts.append(f"{overview['participant']} has no form sessions yet.")

        elif asked & {"form", "available", "catalogue", "catalog", "list"} and not hits:
            forms = self._service.registry.list_forms()
            parts.append(f"{len(forms)} form(s) are published:")
            parts += [f"- {f.title} ({f.name} v{f.version})" for f in forms[:8]]

        if hits:
            if parts:
                parts.append("")
            parts.append("Closest matching records:")
            for hit in hits[:5]:
                parts.append(f"- [{hit.kind}] {hit.title} — {hit.summary}")
                # For the best-matching session, show the values themselves.
                # "Here is a record that matched" is not an answer to "what did
                # we decide"; the decisions are the answer.
                if hit.kind == "session" and hit is hits[0]:
                    parts += [f"  {line.strip()}" for line in (details or {}).get(hit.id, [])]
        elif not parts:
            parts.append(
                "Nothing matched that. Try a form name, a person, or a value you "
                "remember being discussed."
            )
        return "\n".join(parts)

    def _actions(self, hits: list[Hit], overview: dict[str, Any]) -> list[dict[str, Any]]:
        """What the console should offer as a next click.

        Returned as data rather than rendered links so the same answer serves a
        web console, a chat integration, and a CLI.
        """
        actions: list[dict[str, Any]] = []
        for hit in hits[:3]:
            if hit.kind == "session":
                actions.append(
                    {
                        "action": "open_session",
                        "label": f"Open {hit.title}",
                        "session_id": hit.id,
                    }
                )
            elif hit.kind == "form":
                actions.append(
                    {
                        "action": "start_session",
                        "label": f"Start {hit.title}",
                        "form": hit.detail.get("form"),
                    }
                )
            elif hit.kind == "artifact":
                actions.append(
                    {
                        "action": "review_artifact",
                        "label": f"Review {hit.title}",
                        "artifact_id": hit.id,
                    }
                )
        for record in overview["pending_reviews"][:2]:
            if record.status is ArtifactStatus.IN_REVIEW or not record.approvals:
                actions.append(
                    {
                        "action": "review_artifact",
                        "label": f"Review {record.form_name} ({record.format})",
                        "artifact_id": record.id,
                    }
                )
        # Stable order, no duplicates: the console renders these as buttons.
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for action in actions:
            key = f"{action['action']}:{action.get('session_id') or action.get('artifact_id') or action.get('form')}"
            if key not in seen:
                seen.add(key)
                unique.append(action)
        return unique[:5]

    def reset(self, conversation_id: str) -> None:
        self._history.pop(conversation_id, None)


__all__ = ["AssistantAnswer", "FormsAssistant", "Hit", "tokenize"]
