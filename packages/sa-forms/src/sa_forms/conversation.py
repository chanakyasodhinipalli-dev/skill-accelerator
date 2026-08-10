"""The conversation engine.

One turn does this:

    inbound message
      → classify intent (is this an answer, a "why?", a correction, a "skip"?)
      → extract every field the message touches, not just the one we asked about
      → recompute what is still outstanding
      → open the next *topic* and phrase one natural question covering it
      → persist, so the user can walk away and resume days later

Two properties are deliberate and worth stating:

**Questions are never hardcoded.** Gap analysis returns outstanding fields; the
model phrases them. Adding a field to a form changes the conversation with no
code change.

**Nothing is asked twice.** A field answered anywhere — in this turn, ten turns
ago, or in a JIRA comment ingested last week — leaves the outstanding set and
never comes back.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from enum import Enum
from typing import Any

from sa_platform.context import ExecutionContext, current_context
from sa_platform.errors import NotFoundError, ValidationError
from sa_platform.logging import get_logger
from sa_platform.telemetry import get_tracer, metrics

from . import agreements, consistency, normalisation, support, topics
from .actions import derive_action_items
from .coercion import (
    CoercionError,
    coerce_and_validate,
    render_value,
    states_a_time,
    states_a_timezone,
)
from .completeness import (
    Completeness,
    analyse,
    next_topic,
    progress_line,
    unresolved_mandatory,
)
from .extraction import ExtractionEngine, merge_into_session
from .models import (
    ActionItem,
    Agreement,
    AgreementDecision,
    AgreementStage,
    AnswerState,
    ConsistencyFinding,
    FindingState,
    FormDefinition,
    FormField,
    FormSession,
    Provenance,
    SessionStatus,
    SourceChannel,
    SourceMessage,
    TranscriptEntry,
)
from .registry import FormRegistry, form_registry
from .store import InMemorySessionStore, SessionStore

logger = get_logger(__name__)
tracer = get_tracer("sa.forms.conversation")


class Intent(str, Enum):
    """What the participant is doing with this turn."""

    PROVIDE_INFO = "provide_info"
    ASK_RATIONALE = "ask_rationale"  # "why do you need that?"
    ASK_STATUS = "ask_status"  # "how much is left?"
    ASK_CLARIFICATION = "ask_clarification"  # "what do you mean by X?"
    ASK_ASSISTANCE = "ask_assistance"  # "what do you think it should be?"
    ASK_ESCALATION = "ask_escalation"  # "who can I ask about this?"
    ALREADY_ANSWERED = "already_answered"  # "didn't I answer that already?"
    CONFIRM = "confirm"  # "yes, that's right"
    CORRECT = "correct"  # "actually, make that Q3"
    SKIP = "skip"  # "skip that one"
    FINALIZE = "finalize"  # "that's everything, generate it"
    PAUSE = "pause"  # "let me come back to this"
    OTHER = "other"


# Cheap intent detection. These phrasings are stable and unambiguous enough
# that spending a model call on them is waste; anything not matched here falls
# through to PROVIDE_INFO and the extractor sorts it out.
_INTENT_PATTERNS: list[tuple[Intent, re.Pattern[str]]] = [
    (
        # Checked first: "what do you think the risk is?" is a request for help,
        # not a request for justification, and the two read similarly.
        Intent.ASK_ASSISTANCE,
        re.compile(
            r"\b(what (do|would) you (think|reckon|suggest|recommend|say|call)|"
            r"you (tell|decide for) me|your (call|view|read|assessment)|"
            r"can you (suggest|propose|assess|work (that|it) out|figure (that|it) out)|"
            r"(help|assist) me (decide|choose|assess|work (that|it) out)|"
            r"what should (it|that|this) be|any (suggestions?|recommendations?)|"
            r"why (can'?t|don'?t) you (convert|work|figure|get|infer|tell))\b",
            re.I,
        ),
    ),
    (
        # Anchored, so only a standalone affirmation matches. "Yes" as an answer
        # to a yes/no field is handled by the information path, which this
        # handler defers to when nothing is actually awaiting confirmation.
        Intent.CONFIRM,
        re.compile(
            r"^\W*(yes|yep|yeah|yup|correct|right|that'?s (right|correct)|confirm(ed)?|"
            r"looks good|lgtm|sounds good|agreed|exactly|perfect|spot on)"
            r"[\s.!,]*(that'?s right|thanks)?[\s.!]*$",
            re.I,
        ),
    ),
    (
        Intent.ASK_RATIONALE,
        re.compile(
            r"\b(why (do you|are you|is that|would you)|what('s| is) (this|that) for|"
            r"why (does|do) (this|that|it) matter|how does (this|that) help|"
            r"what happens if i (don'?t|do not)|why is (this|that) (needed|required))\b",
            re.I,
        ),
    ),
    (
        Intent.ASK_STATUS,
        re.compile(
            r"\b(how (much|many|far)|what('s| is) (left|remaining|the status)|"
            r"progress|are we done|what do you still need|how many more)\b",
            re.I,
        ),
    ),
    (
        # Ahead of clarification: someone asking to be put in touch with a human
        # has already decided another explanation is not what they want, and
        # producing one anyway is what makes people abandon the form.
        Intent.ASK_ESCALATION,
        support.WANTS_A_HUMAN,
    ),
    (
        # "I already answered that." The correct reply is to show them what was
        # recorded, not to ask a fourth time. Somebody who has to say this has
        # already lost confidence that anything they said landed anywhere, and
        # every further question spends more of it.
        Intent.ALREADY_ANSWERED,
        # `answer\w*` rather than `answered`: somebody typing this is usually
        # typing fast and annoyed, and "I already answerd both of teh questions"
        # is the exact sentence that went unrecognised in a real session.
        re.compile(
            r"\b(i (already |just )?(answer\w*|said|told you|gave you)|"
            r"did\s?n[o']?t i (already )?(answer\w*|say|tell you)|"
            r"i'?ve (already )?(answer\w*|said|told you)|"
            r"as i (said|mentioned|answer\w*)|"
            r"(that|this) (was|is) (already )?answer\w*|"
            r"asked (me )?(that|this) (already|before)|again and again)\b",
            re.I,
        ),
    ),
    (
        Intent.ASK_CLARIFICATION,
        re.compile(
            r"\b(what do you mean|can you (explain|clarify)|i don'?t understand|"
            r"what (is|are) (a |an |the )?\w+ (in this|here)|give me an example|"
            r"what counts as|how do i (know|decide|work out|tell)|"
            r"what'?s the difference between|not sure what|"
            # "What does retained for seven years mean?" — a question about a
            # phrase rather than about a field, and the shape most questions
            # about an agreement's wording take.
            r"what does .{2,60}\bmean|what is meant by|does that mean)\b",
            re.I,
        ),
    ),
    (
        # "That didn't answer my question." Routed through clarification, which
        # reads the same signal and moves a tier up the ladder rather than
        # repeating itself.
        Intent.ASK_CLARIFICATION,
        support.UNSATISFIED,
    ),
    (
        Intent.SKIP,
        re.compile(
            r"\b(skip (that|this|it|the|for now)|let'?s skip|not applicable|n/?a\b|"
            r"leave (that|it) blank|doesn'?t apply|move on|next question|"
            r"i don'?t know that)\b",
            re.I,
        ),
    ),
    (
        Intent.CORRECT,
        re.compile(
            r"\b(actually|correction|i mis(spoke|stated)|scratch that|change (that|it) to|"
            r"that('s| is) wrong|let me correct|instead of that|update that to)\b",
            re.I,
        ),
    ),
    (
        Intent.FINALIZE,
        re.compile(
            # A bare "generate" was not on this list, and the message directly
            # above it says *Say 'generate' to produce the document*. Typing
            # exactly what you were told to type and being handed the same
            # summary again is the worst dead end this conversation has.
            r"^\W*(generate|generate it|go ahead|do it|produce it|proceed)\W*$"
            r"|\b(that('s| is) (it|all|everything)|we'?re done|"
            r"generate (the )?(form|document|report|it|this)|"
            r"produce (the )?(document|form|report|it)|go ahead and generate|"
            r"finali[sz]e|submit (it|this)|create the (pdf|excel|artifact)|ready for review)\b",
            re.I,
        ),
    ),
    (
        Intent.PAUSE,
        re.compile(
            r"\b(come back (to this )?later|pause (this|it)|save (my )?progress|"
            r"i'?ll (finish|continue) later|stop for now|park (this|it))\b",
            re.I,
        ),
    ),
]


#: Single words that appear in almost every question and therefore identify no
#: field on their own, however many forms list them as aliases. An alias exists
#: to help the extractor, which has the rest of the sentence to disambiguate it;
#: a meta-question has only this.
_WEAK_REFERENCES = frozenset(
    {
        "what",
        "when",
        "where",
        "which",
        "why",
        "how",
        "who",
        "whom",
        "value",
        "values",
        "detail",
        "details",
        "info",
        "information",
        "note",
        "notes",
        "context",
        "background",
        "other",
        "name",
        "type",
        "status",
        "this",
        "that",
        "here",
        "form",
        "field",
    }
)

#: An opening that makes a sentence a question even without the mark, which
#: people leave off in chat far more often than they include it.
_OPENS_A_QUESTION = re.compile(
    r"^\W*(what|why|who|whom|whose|when|where|which|how|can|could|do|does|did|"
    r"is|are|was|were|will|would|should|shall|may|might|am i|tell me)\b",
    re.I,
)

#: How many times one discrepancy may be put to the participant. Asked, then
#: followed up once if they answered around it. Beyond that the record says it
#: went unexplained, which is true and is more use than asking a third time.
_MAX_DISCREPANCY_ASKS = 2


#: A message that *opens* with agreement, whatever follows it. Distinct from the
#: CONFIRM intent, which requires the whole message to be agreement and nothing
#: else — real answers are rarely that tidy.
_LEADING_AFFIRMATION = re.compile(
    r"^\W*(yes|yeah|yep|yup|correct|right|confirmed?|agreed|that'?s (right|correct)|"
    r"i (already )?confirmed|i (have|did) confirm)\b",
    re.I,
)


@dataclass(slots=True)
class TurnResult:
    """What one turn produced."""

    session_id: str
    reply: str
    intent: Intent = Intent.PROVIDE_INFO
    targeted_fields: list[str] = dataclass_field(default_factory=list)
    captured: list[str] = dataclass_field(default_factory=list)
    needs_confirmation: list[str] = dataclass_field(default_factory=list)
    conflicts: list[str] = dataclass_field(default_factory=list)
    status: SessionStatus = SessionStatus.COLLECTING
    completeness: dict[str, Any] = dataclass_field(default_factory=dict)
    ready_for_review: bool = False
    #: Agreements this turn is waiting on. A caller rendering its own UI needs
    #: to know the conversation is gated rather than merely chatty.
    awaiting_agreements: list[str] = dataclass_field(default_factory=list)
    #: A question routed to a team on this turn, as data — so a console can
    #: offer to open a ticket and a chat client can @-mention them.
    support_request: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "reply": self.reply,
            "intent": self.intent.value,
            "targeted_fields": self.targeted_fields,
            "captured": self.captured,
            "needs_confirmation": self.needs_confirmation,
            "conflicts": self.conflicts,
            "status": self.status.value,
            "completeness": self.completeness,
            "ready_for_review": self.ready_for_review,
            "awaiting_agreements": self.awaiting_agreements,
            "support_request": self.support_request,
        }


_QUESTION_SYSTEM = """\
You are gathering information through a conversation. You are not reading out a \
questionnaire, and the person you are talking to should not be able to tell \
which form fields are behind your question.

The items below are what you need to LEARN, not what you should SAY. Ask about \
the subject they have in common, in your own plain words, and let one answer \
cover several of them.

How to write your reply:
- Acknowledge briefly what you just captured, if anything. One short clause.
- Then ask ONE question. Not a list, not a numbered set, not "I need the \
following". One question a person can answer in a sentence or two.
- Ask about the topic, not the fields. Do not read the item labels back — \
"what's the affected system and the change owner?" is the questionnaire you are \
replacing. "Which system is this on, and who's driving it?" is the question.
- Do not mention fields, forms, sections, or anything else about the mechanism.
- Never ask about anything not in the provided list. Those are already known or \
not relevant.
- Never re-ask something already captured.
- Use the participant's own vocabulary back to them.
- Follow the ASKING STYLE given below. Getting more specific is something you \
do when an open question has already failed, not something you start with.
- If a value failed validation, say plainly what was wrong and what shape you \
need — do not just repeat the question.
- One to three sentences. No preamble, no headers, no bullet lists.\
"""

#: How pointed the question should be. Deterministic: it is driven by how many
#: times these fields have already been asked about, not by the model's read of
#: the mood. An open question first, because it gets a fuller answer and often
#: settles several items at once; specificity is what you spend when that fails,
#: and spending it up front is how a conversation becomes an interrogation.
_ASK_STYLES = {
    "invitation": (
        "ASKING STYLE: opening invitation. This is the first thing you say to "
        "them about the substance, so do not ask for particular items at all. "
        "Invite them to describe the whole thing in their own words — what "
        "they are doing, and anything they think matters about it — and say "
        "you will pick up whatever they cover and come back for the rest. "
        "Someone who has the whole change in their head should be able to type "
        "it in one go and have it land."
    ),
    "open": (
        "ASKING STYLE: open. Ask broadly about the subject and let them tell it "
        "their way. Do not enumerate the individual things you need — a good "
        "open question gets most of them in one answer, and whatever it misses "
        "you can come back to."
    ),
    "specific": (
        "ASKING STYLE: specific. The open question did not get everything, so "
        "name the one or two things still missing — still as a single natural "
        "question, still in your own words."
    ),
    "explicit": (
        "ASKING STYLE: explicit. This has been asked before without an answer. "
        "Do not rephrase it again. Acknowledge you are coming back to it, say "
        "concretely what would settle it — the exact options, or the shape of "
        "the value — and offer to leave it out if they would rather move on."
    ),
}

_QUESTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "reply": {"type": "string", "description": "The message to send to the participant."}
    },
    "required": ["reply"],
    "additionalProperties": False,
}

_SUGGESTION_SYSTEM = """\
The participant has asked you to propose a value rather than supply one \
themselves. You are drafting a proposal for them to accept or overrule — you \
are not deciding.

Rules:
- Ground every proposal in what the participant has already said in this \
conversation. Quote the words that support it.
- Do not reason from what is typical for changes of this kind. If the \
conversation does not support a value, set `confident` to false and say what \
you would need to hear.
- For an enum field, `value` must be exactly one of the declared options.
- `reasoning` is one sentence, addressed to the participant, naming the \
evidence. Not a justification of the form's existence.
- Never propose a value for a field the participant would be signing their name \
to — an approver, a reviewer, an owner. Those name a person and you cannot \
know who. Set `confident` to false for them.\
"""

_SUGGESTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field_id": {"type": "string"},
                    "value": {"type": "string"},
                    "reasoning": {
                        "type": "string",
                        "description": "One sentence citing what the participant said.",
                    },
                    "confident": {
                        "type": "boolean",
                        "description": "False when the conversation does not support a value.",
                    },
                },
                "required": ["field_id", "value", "reasoning", "confident"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["suggestions"],
    "additionalProperties": False,
}


class ConversationEngine:
    """Drives a form-filling conversation across turns, channels, and sessions."""

    def __init__(
        self,
        *,
        registry: FormRegistry | None = None,
        session_store: SessionStore | None = None,
        extractor: ExtractionEngine | None = None,
        llm_provider: Any | None = None,
    ) -> None:
        self._registry = registry if registry is not None else form_registry
        self._sessions = session_store if session_store is not None else InMemorySessionStore()
        self._extractor = extractor if extractor is not None else ExtractionEngine(llm_provider)
        self._llm = llm_provider

    @property
    def sessions(self) -> SessionStore:
        return self._sessions

    @property
    def registry(self) -> FormRegistry:
        return self._registry

    def _provider(self) -> Any:
        if self._llm is None:
            from sa_connectors.llm import build_provider

            self._llm = build_provider()
        return self._llm

    # -- session lifecycle ------------------------------------------------
    async def start(
        self,
        form_name: str,
        *,
        version: str | None = None,
        participant: str = "user",
        title: str = "",
        ctx: ExecutionContext | None = None,
        resume_existing: bool = True,
    ) -> tuple[FormSession, str]:
        """Open a session, or resume this participant's in-flight one.

        Resumption is the default. A user who returns two days later says
        "let's carry on with the change request" and gets their own session
        back, not a blank one.
        """
        ctx = ctx or current_context()

        if resume_existing:
            existing = await self._sessions.find_resumable(form_name, participant)
            if existing is not None:
                form = self._registry.get(existing.form_name, existing.form_version)
                greeting = await self._resume_greeting(form, existing)
                return existing, greeting

        # A *new* session always binds to the latest active version.
        form = self._registry.resolve(form_name, version)
        session = FormSession(
            form_name=form.name,
            form_version=form.version,
            title=title or form.title,
            tenant_id=ctx.tenant_id,
            correlation_id=ctx.correlation_id,
            created_by=participant,
            participants=[participant],
        )
        await self._sessions.save(session)

        opening, awaiting, asked = await self._opening_message(form, session)
        session.record(
            TranscriptEntry(
                role="assistant",
                text=opening,
                author="assistant",
                targeted_fields=asked,
                awaiting_agreements=awaiting,
            )
        )
        session.note_asked(asked)
        await self._sessions.save(session)

        logger.info(
            "started form session",
            extra={
                "session": session.id,
                "form": form.qualified_name,
                "participant": participant,
            },
        )
        return session, opening

    async def _opening_message(
        self, form: FormDefinition, session: FormSession
    ) -> tuple[str, list[str], list[str]]:
        """The first message, what it waits on, and what it asked about.

        All three are returned because the caller records all three: an opening
        question never counted as asked gets asked again in the same words, and
        the second time reads as not listening.

        Terms come first, questions after. An agreement taken halfway through
        covers only the half that follows it, and the participant has already
        told you things by then.
        """
        due = agreements.next_batch(form, session, AgreementStage.BEFORE_START)
        if due:
            return (
                f"{self._agreement_preface(form, session, due)}\n\n"
                f"{agreements.present_all(due)}",
                [a.id for a in due],
                [],
            )

        completeness = analyse(form, session)
        topic = next_topic(form, completeness)
        if topic is None:
            return (
                f"{form.title} has no outstanding fields. Say 'generate' when you're ready.",
                [],
                [],
            )

        section, fields = topic
        self._note_topic(session, section)
        if section.opening_prompt:
            return section.opening_prompt, [], [f.id for f in fields]

        opening = await self._phrase_question(
            form,
            session,
            section=section,
            fields=fields,
            captured=[],
            problems=[],
            preamble=(
                f"This is the opening message of a conversation to complete "
                f"'{form.title}'. Introduce it in one short sentence, then open the "
                f"subject below."
            ),
        )
        return opening, [], [f.id for f in fields]

    @staticmethod
    def _agreement_preface(form: FormDefinition, session: FormSession, due: list[Agreement]) -> str:
        """How to introduce the terms — which depends on what the form is.

        On an intake form the terms are the throat-clearing before the work. On
        an agreement form they are the work, and saying "before we start" about
        the only thing there is to do reads as though something else is coming.
        """
        if form.is_agreement_form:
            completeness = analyse(form, session)
            done = completeness.agreements_accepted
            total = completeness.agreements_required
            if total > 1:
                return (
                    f"{form.title}. There {'is' if total == 1 else 'are'} {total} to go "
                    f"through, one at a time — this is {done + 1} of {total}."
                )
            return f"{form.title}. Here it is in full:"

        return f"Let's get your {form.title.lower()} together. Before we start, " + (
            "there's something to agree to:"
            if len(due) == 1
            else "there are a couple of things to agree to:"
        )

    async def _resume_greeting(self, form: FormDefinition, session: FormSession) -> str:
        due = agreements.next_batch(form, session, AgreementStage.BEFORE_START)
        if due:
            return (
                "Welcome back. This is still waiting on you before we can start:\n\n"
                f"{agreements.present_all(due)}"
            )

        completeness = analyse(form, session)
        status = progress_line(completeness)
        topic = next_topic(
            form,
            completeness,
            stalled=session.stalled_fields(),
            max_fields=self._batch_size(session),
            recently_settled=self._recently_settled(session),
        )
        if topic is None:
            return (
                f"Welcome back. {status} Say 'generate' when you'd like the document, "
                "or tell me anything you'd like to change."
            )
        section, fields = topic
        self._note_topic(session, section)
        question = await self._phrase_question(
            form,
            session,
            section=section,
            fields=fields,
            captured=[],
            problems=[],
            preamble="The participant is returning to a paused session. Welcome them back in "
            "one short clause, then continue with the topic below.",
        )
        return f"{status} {question}"

    async def prompt_next(self, session_id: str) -> str | None:
        """Say the next thing, when the conversation was unblocked from outside.

        A decision taken somewhere other than the chat window — a console
        checkbox, an integration — changes what the conversation should be
        doing, and nothing in the chat window knows it. Without this the
        participant accepts the terms, the gate opens, and the screen sits there
        having said nothing: the conversation is waiting for a message and the
        person is waiting for a question.

        Returns the message, or ``None`` when there is genuinely nothing to say.
        It is recorded on the transcript like any other assistant turn, so the
        next inbound message is read against it.
        """
        session = await self._sessions.load(session_id)
        form = self._registry.get(session.form_name, session.form_version)
        if not session.status.is_editable:
            return None

        # More terms to go: put the next one. Doing nothing here is what left a
        # console showing an empty consent panel with four agreements still
        # outstanding — the decision was taken out of band, so nobody had
        # presented the one after it, and the screen looked finished when the
        # session was four decisions from starting.
        due = agreements.next_batch(form, session, AgreementStage.BEFORE_START)
        if due:
            message = (
                f"{self._agreement_preface(form, session, due)}\n\n"
                f"{agreements.present_all(due)}"
            )
            session.record(
                TranscriptEntry(
                    role="assistant",
                    text=message,
                    author="assistant",
                    awaiting_agreements=[a.id for a in due],
                )
            )
            await self._sessions.save(session)
            return message

        if self._last_targeted(session):
            return None  # a question is already on the table

        completeness = analyse(form, session)
        topic = next_topic(
            form,
            completeness,
            stalled=session.stalled_fields(),
            max_fields=self._batch_size(session),
            recently_settled=self._recently_settled(session),
        )
        if topic is None:
            return None

        section, fields = topic
        self._note_topic(session, section)
        message = section.opening_prompt or await self._phrase_question(
            form,
            session,
            section=section,
            fields=fields,
            captured=[],
            problems=[],
            preamble="The participant has just accepted the terms. Open the subject below "
            "with one short question — no more preamble than a clause.",
        )
        session.record(
            TranscriptEntry(
                role="assistant",
                text=message,
                author="assistant",
                targeted_fields=[f.id for f in fields],
            )
        )
        session.note_asked([f.id for f in fields])
        await self._sessions.save(session)
        return message

    # -- the main turn ----------------------------------------------------
    async def turn(
        self,
        session_id: str,
        message: str | SourceMessage,
        *,
        author: str = "user",
        channel: SourceChannel = SourceChannel.CHAT,
        ctx: ExecutionContext | None = None,
    ) -> TurnResult:
        """Process one inbound message and produce the reply."""
        ctx = ctx or current_context()
        session = await self._sessions.load(session_id)
        form = self._registry.get(session.form_name, session.form_version)

        inbound = (
            message
            if isinstance(message, SourceMessage)
            else SourceMessage(text=message, author=author, channel=channel)
        )

        if not session.status.is_editable:
            return TurnResult(
                session_id=session.id,
                reply=(
                    f"This submission is {session.status.value.replace('_', ' ')} and can no "
                    "longer be edited. Start a new session to capture changes."
                ),
                status=session.status,
                completeness=analyse(form, session).summary(),
            )

        with tracer.span("forms.turn", form=form.name, session=session.id) as span:
            session.record(
                TranscriptEntry(
                    role="user",
                    text=inbound.text,
                    author=inbound.author,
                    channel=inbound.channel,
                    message_id=inbound.id,
                )
            )

            intent = self._classify(inbound.text)
            span.set_attribute("intent", intent.value)
            metrics.increment("forms.turn", form=form.name, intent=intent.value)

            # Consent comes before collection. Anything the participant says
            # while a start-stage agreement is outstanding is either a decision
            # on it, a question about it, or a reason to put it again.
            gated = await self._agreement_turn(form, session, inbound, intent)
            if gated is not None:
                result = gated
            else:
                handler = {
                    Intent.ASK_RATIONALE: self._handle_rationale,
                    Intent.ASK_STATUS: self._handle_status,
                    Intent.ASK_CLARIFICATION: self._handle_clarification,
                    Intent.ASK_ESCALATION: self._handle_escalation,
                    Intent.ALREADY_ANSWERED: self._handle_already_answered,
                    Intent.ASK_ASSISTANCE: self._handle_assistance,
                    Intent.CONFIRM: self._handle_confirm,
                    Intent.SKIP: self._handle_skip,
                    Intent.FINALIZE: self._handle_finalize,
                    Intent.PAUSE: self._handle_pause,
                }.get(intent, self._handle_information)

                result = await handler(form, session, inbound, intent)

            session.record(
                TranscriptEntry(
                    role="assistant",
                    text=result.reply,
                    author="assistant",
                    targeted_fields=result.targeted_fields,
                    awaiting_agreements=result.awaiting_agreements,
                )
            )
            session.note_asked(result.targeted_fields)
            await self._sessions.save(session)
            return result

    # -- intent handlers ---------------------------------------------------
    async def _handle_information(
        self,
        form: FormDefinition,
        session: FormSession,
        message: SourceMessage,
        intent: Intent,
    ) -> TurnResult:
        """The normal path: mine the message, then ask about what remains."""
        before = analyse(form, session)

        # Target everything still open, plus anything awaiting confirmation, so
        # a volunteered detail about a later topic is captured now rather than
        # asked about again in ten turns.
        targets = [g.field.id for g in before.gaps] + [c.field.id for c in before.confirmations]

        # Settled fields are normally excluded — that is what stops a
        # conversational echo overwriting a real answer. But a field named in an
        # outstanding contradiction has just been put back to the participant
        # with "correct whichever one is wrong", and an invitation you cannot
        # act on is worse than no invitation. Listen for the correction.
        contested = [fid for f in consistency.outstanding(session) for fid in f.fields]
        targets = list(dict.fromkeys(targets + contested))

        extraction = await self._extractor.extract(
            form,
            message,
            target_fields=targets or None,
            known_values=session.settled_values(),
            context=self._recent_context(session),
        )
        changed = merge_into_session(session, form, extraction, message)
        changed["accepted"].extend(self._apply_timezone(form, session, message))
        changed["accepted"].extend(self._apply_leading_affirmation(form, session, message, changed))
        changed["accepted"].extend(
            await self._catch_up_on_unlocked_fields(form, session, message, before)
        )

        for item in extraction.action_items:
            self._add_action_item(session, item)

        after = analyse(form, session)
        problems = [
            {
                "field": form.field(e.field_id).label,
                "problem": e.error or "could not be interpreted",
            }
            for e in extraction.rejected()
            if form.try_field(e.field_id)
        ]

        # Newly announced completion of the mandatory set is worth calling out
        # explicitly — it is the moment the user can stop if they want to.
        just_completed = after.mandatory_complete and not session.mandatory_complete_announced
        if just_completed:
            session.mandatory_complete_announced = True

        topic = next_topic(
            form,
            after,
            stalled=session.stalled_fields(),
            max_fields=self._batch_size(session),
            # What they just answered decides what follows it, wherever in the
            # form that lives: "customers are affected" is followed by "who
            # tells them?", not by whatever the next section happens to hold.
            recently_settled=changed["accepted"] or self._recently_settled(session),
        )
        confirmations = [c.field for c in after.confirmations]

        if topic is None and not confirmations:
            return await self._wrap_up(form, session, after, intent, changed, message=message)

        # The review does NOT run here. It runs at wrap-up, once the questions
        # are exhausted, and at finalize. Running it the moment the mandatory
        # set closed put it ahead of every recommended and optional field —
        # and because a raised finding kept the floor, those fields were never
        # asked at all. A submission went to review with no ticket, no window,
        # no blast radius and no monitoring plan, and the participant's summary
        # was raw chat text because the wording pass runs at wrap-up too.
        #
        # Mandatory-complete means "you may stop here", not "we are finished
        # asking".

        if confirmations:
            # A confirmation is a closed question and gets the turn to itself.
            # Bundling the next question with it asks someone to say yes to one
            # thing and answer another in the same breath: the "yes" then reads
            # as an answer to whichever the extractor liked better, and the
            # participant is left unsure which of the two was heard.
            pending = confirmations[:2]
            return await self._ask_to_confirm(
                form, session, pending, intent, changed, after, problems
            )

        assert topic is not None  # the branch above returned when it was
        section, fields = topic
        self._note_topic(session, section)
        reply = await self._phrase_question(
            form,
            session,
            section=section,
            fields=fields,
            captured=changed["accepted"],
            problems=problems,
            note=(
                "All required fields are now captured. Mention that they can generate the "
                "document now, then optionally ask about the remaining nice-to-have items."
                if just_completed
                else ""
            ),
        )
        return self._result(
            session,
            reply,
            intent,
            [f.id for f in fields],
            changed,
            after,
            ready=after.mandatory_complete,
        )

    async def _ask_to_confirm(
        self,
        form: FormDefinition,
        session: FormSession,
        pending: list[FormField],
        intent: Intent,
        changed: dict[str, list[str]],
        completeness: Completeness,
        problems: list[dict[str, str]],
    ) -> TurnResult:
        """Put a value back for confirmation, and ask nothing else.

        The answer to this turn is yes, no, "skip it", or "later" — all of which
        the intent handlers already understand, and all of which move the
        conversation on by themselves. Adding a fresh question here is what
        makes a confirmation feel like an interrogation.
        """
        reply = await self._phrase_question(
            form,
            session,
            section=topics.topic_of(form, [f.id for f in pending]),
            fields=[],
            captured=changed.get("accepted", []),
            problems=problems,
            confirmations=[(f, session.answer_for(f.id).value) for f in pending],
            preamble="Confirm the value(s) below and nothing else. Do not ask a new "
            "question in this message — the next topic comes after they answer.",
        )
        return self._result(
            session,
            reply,
            intent,
            [f.id for f in pending],
            changed,
            completeness,
            ready=completeness.mandatory_complete,
        )

    async def _handle_rationale(
        self,
        form: FormDefinition,
        session: FormSession,
        message: SourceMessage,
        intent: Intent,
    ) -> TurnResult:
        """Answer "why are you asking me this?" from the form's own rationale.

        Sourced from the definition rather than generated, so the explanation is
        the one the form's owner wrote and stays consistent between users.
        """
        completeness = analyse(form, session)
        fields = self._referenced_fields(form, message.text)
        if not fields:
            topic = next_topic(
                form,
                completeness,
                stalled=session.stalled_fields(),
                max_fields=self._batch_size(session),
            )
            fields = list(topic[1]) if topic else []

        if not fields:
            return self._result(
                session,
                "There's nothing outstanding right now, so nothing left to justify.",
                intent,
                [],
                {},
                completeness,
            )

        explanations: list[str] = []
        for field in fields[:3]:
            rationale = field.rationale or field.description
            if rationale:
                explanations.append(f"**{field.label}** — {rationale}")
            else:
                explanations.append(
                    f"**{field.label}** — required by the {form.title} form; "
                    "the submission can't be baselined without it."
                )

        # The explanation is followed by the question again, so answering
        # "why?" never costs the user their place in the flow.
        follow_up = await self._phrase_question(
            form,
            session,
            section=topics.topic_of(form, [f.id for f in fields]),
            fields=fields,
            captured=[],
            problems=[],
            preamble="Re-ask the question briefly after an explanation was given. One sentence.",
        )
        reply = "\n".join(explanations) + f"\n\n{follow_up}"
        return self._result(session, reply, intent, [f.id for f in fields], {}, completeness)

    async def _handle_status(
        self,
        form: FormDefinition,
        session: FormSession,
        message: SourceMessage,
        intent: Intent,
    ) -> TurnResult:
        completeness = analyse(form, session)
        lines = [progress_line(completeness)]

        blocking = completeness.blocking_gaps()
        if blocking:
            labels = ", ".join(g.field.label for g in blocking[:6])
            more = f" (+{len(blocking) - 6} more)" if len(blocking) > 6 else ""
            lines.append(f"Still needed: {labels}{more}.")
        if completeness.confirmations:
            labels = ", ".join(c.field.label for c in completeness.confirmations[:4])
            lines.append(f"Awaiting your confirmation: {labels}.")
        if completeness.mandatory_complete:
            lines.append("You can say 'generate' whenever you're ready.")

        return self._result(session, " ".join(lines), intent, [], {}, completeness)

    async def _handle_clarification(
        self,
        form: FormDefinition,
        session: FormSession,
        message: SourceMessage,
        intent: Intent,
    ) -> TurnResult:
        """Answer their question, escalating a tier each time an answer misses.

        The ladder is in :mod:`sa_forms.support`; what lives here is where each
        tier is chosen:

        1. **The definition.** What the form's author wrote. Free, exact, and
           right for most questions.
        2. **The reference notes.** A grounded answer, or an explicit "the
           material doesn't settle this" — which is a correct answer, and the
           reason nothing here invents a threshold or a policy.
        3. **A human.** The team that owns that part of the form.

        Which tier is chosen is arithmetic on how many times they have asked,
        not a read of their tone. A second question about the same field means
        the first answer did not land; repeating it more slowly is not a plan.
        An explicit "that didn't answer it" skips a tier outright.
        """
        completeness = analyse(form, session)
        fields = self._question_fields(form, session, message, completeness)

        if not fields and not form.knowledge:
            return await self._handle_status(form, session, message, intent)

        depth = session.note_help_asked([f.id for f in fields])
        if support.UNSATISFIED.search(message.text):
            # "That didn't answer it" skips the tier that just missed. It
            # accelerates the ladder; it does not double-count, or someone who
            # says it on their second try is sent to a human without the
            # reference material ever having been read.
            depth = max(depth, 2)

        if depth <= 1:
            explanation = support.explain(form, fields)
            if explanation:
                support.record_answer(
                    session,
                    message.text,
                    asked_by=message.author,
                    fields=fields,
                    tier="definition",
                    answer=explanation,
                )
                reply = (
                    f"{explanation}\n\nDoes that cover it? If not, say so and I'll "
                    "dig further or put it to the team who owns this."
                )
                return self._result(
                    session, reply, intent, [f.id for f in fields], {}, completeness
                )
            # Nothing authored to explain it with. Reading the label back would
            # be worse than useless, so go a tier up rather than pretending.

        if depth <= 2:
            grounded = await support.answer_from_knowledge(
                form, session, message.text, fields, llm_provider=self._llm
            )
            if grounded["answered"]:
                support.record_answer(
                    session,
                    message.text,
                    asked_by=message.author,
                    fields=fields,
                    tier="grounded",
                    answer=grounded["answer"],
                    sources=grounded["sources"],
                )
                cited = self._cite(form, grounded["sources"])
                follow_up = await self._reask(form, session, fields)
                reply = f"{grounded['answer']}{cited}" + (f"\n\n{follow_up}" if follow_up else "")
                return self._result(
                    session, reply, intent, [f.id for f in fields], {}, completeness
                )
            return self._route_question(
                form, session, message, fields, intent, completeness, reason=str(grounded["gap"])
            )

        return self._route_question(
            form,
            session,
            message,
            fields,
            intent,
            completeness,
            reason="asked more than twice without a settled answer",
        )

    @staticmethod
    def _cite(form: FormDefinition, sources: list[str]) -> str:
        """Name where a grounded answer came from, when the note says.

        An answer about policy that cannot be traced to the policy is an opinion
        in a confident font, and the person acting on it has no way to check.
        """
        named = [n for n in form.knowledge if n.id in set(sources) and n.source]
        if not named:
            return ""
        return " (" + "; ".join(sorted({n.source for n in named})) + ")"

    async def _reask(
        self, form: FormDefinition, session: FormSession, fields: list[FormField]
    ) -> str:
        """Put the question again after an explanation, so answering costs nothing."""
        if not fields:
            return ""
        return await self._phrase_question(
            form,
            session,
            section=topics.topic_of(form, [f.id for f in fields]),
            fields=fields,
            captured=[],
            problems=[],
            preamble="An explanation was just given. Ask the question again briefly — "
            "one sentence, no repetition of the explanation.",
        )

    async def _handle_assistance(
        self,
        form: FormDefinition,
        session: FormSession,
        message: SourceMessage,
        intent: Intent,
    ) -> TurnResult:
        """ "What do you think it should be?" — propose a value, don't decide it.

        The old behaviour was to decline: risk and rollback are the owner's
        judgement, and a form that quietly fills them in is worse than useless.
        That reasoning is sound but the conclusion was wrong. Refusing to
        engage with what the participant has *already told you* — four to six
        hours of full downtime on a shared platform — makes them restate their
        own words to satisfy a field, which is the interrogation this design
        exists to avoid.

        So: propose, ground the proposal in verbatim evidence, and record it as
        PROPOSED. It is never counted as answered until the participant says so,
        which keeps the judgement theirs while doing the reading for them.
        """
        completeness = analyse(form, session)
        fields = [
            f for f in self._referenced_fields(form, message.text) if not self._settled(session, f)
        ]
        if not fields:
            topic = next_topic(
                form,
                completeness,
                stalled=session.stalled_fields(),
                max_fields=self._batch_size(session),
            )
            fields = list(topic[1]) if topic else []
        fields = fields[:3]

        if not fields:
            return await self._handle_status(form, session, message, intent)

        suggestions = await self._suggest_values(form, session, fields)
        proposed: list[str] = []
        lines: list[str] = []

        for field in fields:
            suggestion = suggestions.get(field.id)
            if suggestion is None or not suggestion.get("confident"):
                reason = (suggestion or {}).get("reasoning", "")
                lines.append(
                    f"**{field.label}** — I can't call this one from what's been said"
                    + (f": {reason}" if reason else ".")
                )
                continue
            try:
                value = coerce_and_validate(field, str(suggestion.get("value", "")))
            except CoercionError as exc:
                logger.debug(
                    "suggested value failed coercion",
                    extra={"field": field.id, "error": exc.message},
                )
                lines.append(f"**{field.label}** — I couldn't put a value to that one.")
                continue
            if value is None:
                continue

            session.answer_for(field.id).supersede_with(
                value,
                raw_value=str(suggestion.get("value", "")),
                state=AnswerState.PROPOSED,
                # Deliberately below every threshold: a proposal is a question
                # with a default, and must never settle on its own.
                confidence=0.4,
                provenance=Provenance(
                    channel=message.channel,
                    author="assistant",
                    evidence=str(suggestion.get("reasoning", ""))[:300],
                    method="assistant_proposed",
                ),
                note="proposed by the assistant; awaiting confirmation",
            )
            proposed.append(field.id)
            lines.append(
                f"**{field.label}** — I'd put this at **{render_value(field, value)}**. "
                f"{suggestion.get('reasoning', '')}".strip()
            )

        after = analyse(form, session)
        closing = (
            "Confirm and I'll record it, or give me the value you want."
            if proposed
            else "Tell me what it should be and I'll take it from there."
        )
        reply = "\n".join(lines) + f"\n\n{closing}"
        return self._result(
            session,
            reply,
            intent,
            [f.id for f in fields],
            {"proposed": proposed},
            after,
        )

    async def _handle_confirm(
        self,
        form: FormDefinition,
        session: FormSession,
        message: SourceMessage,
        intent: Intent,
    ) -> TurnResult:
        """ "Yes" — promote whatever was awaiting confirmation.

        Without this a proposed value has no way to become an answer: extraction
        finds nothing in a bare "yes", so the field would be re-proposed every
        turn forever. When nothing is pending, "yes" is just an answer to a
        yes/no question, and the information path handles it as before.
        """
        pending = [
            form.field(fid)
            for fid in self._last_targeted(session)
            if form.try_field(fid) and session.answer_for(fid).needs_confirmation
        ]
        if not pending:
            pending = [
                form.field(fid)
                for fid, answer in session.answers.items()
                if answer.needs_confirmation and form.try_field(fid)
            ]
        if not pending:
            return await self._handle_information(form, session, message, Intent.PROVIDE_INFO)

        for field in pending:
            answer = session.answer_for(field.id)
            answer.state = AnswerState.CONFIRMED
            answer.confidence = 1.0
            answer.note = ""
            answer.updated_at = time.time()

        after = analyse(form, session)
        confirmed = ", ".join(
            f"{f.label} as {render_value(f, session.answer_for(f.id).value)}" for f in pending
        )
        topic = next_topic(
            form,
            after,
            stalled=session.stalled_fields(),
            max_fields=self._batch_size(session),
            recently_settled=[f.id for f in pending],
        )

        if topic is None:
            result = await self._wrap_up(
                form,
                session,
                after,
                intent,
                {"accepted": [f.id for f in pending]},
                message=message,
            )
            result.reply = f"Recorded {confirmed}.\n\n{result.reply}"
            return result

        section, fields = topic
        self._note_topic(session, section)
        question = await self._phrase_question(
            form, session, section=section, fields=fields, captured=[], problems=[]
        )
        return self._result(
            session,
            f"Recorded {confirmed}. {question}",
            intent,
            [f.id for f in fields],
            {"accepted": [f.id for f in pending]},
            after,
        )

    async def _handle_skip(
        self,
        form: FormDefinition,
        session: FormSession,
        message: SourceMessage,
        intent: Intent,
    ) -> TurnResult:
        """Mark the fields just asked about as skipped and move on.

        A skipped *mandatory* field is not silently dropped — it becomes an
        action item when the session is finalised.
        """
        # Prefer fields the user named ("skip the owner"); otherwise fall back
        # to whatever the previous question asked about.
        targets = self._referenced_fields(form, message.text)
        if not targets:
            targets = [
                form.field(fid) for fid in self._last_targeted(session) if form.try_field(fid)
            ]

        skipped_labels: list[str] = []
        for field in targets:
            answer = session.answer_for(field.id)
            if answer.is_settled:
                continue
            answer.state = AnswerState.SKIPPED
            answer.note = "skipped at the participant's request"
            if field.id not in session.skipped_fields:
                session.skipped_fields.append(field.id)
            skipped_labels.append(field.label)

        after = analyse(form, session)
        topic = next_topic(
            form,
            after,
            stalled=session.stalled_fields(),
            max_fields=self._batch_size(session),
            recently_settled=self._recently_settled(session),
        )

        acknowledgement = (
            f"Noted — leaving {', '.join(skipped_labels)} blank."
            if skipped_labels
            else "Understood, moving on."
        )
        mandatory_skipped = [
            f for f in targets if f.is_mandatory and f.id in session.skipped_fields
        ]
        if mandatory_skipped:
            acknowledgement += (
                f" {', '.join(f.label for f in mandatory_skipped)} is required, so I'll flag it "
                "as an open action item on the final document."
            )

        if topic is None:
            # Same rule as the information path: skipping the last open question
            # ends the asking, not the requirement.
            result = await self._wrap_up(form, session, after, intent, {}, message=message)
            result.reply = f"{acknowledgement} {result.reply}"
            return result

        section, fields = topic
        self._note_topic(session, section)
        question = await self._phrase_question(
            form, session, section=section, fields=fields, captured=[], problems=[]
        )
        return self._result(
            session, f"{acknowledgement} {question}", intent, [f.id for f in fields], {}, after
        )

    async def _handle_finalize(
        self,
        form: FormDefinition,
        session: FormSession,
        message: SourceMessage,
        intent: Intent,
    ) -> TurnResult:
        """Move to review — but refuse if mandatory fields are genuinely open."""
        completeness = analyse(form, session)

        if not completeness.mandatory_complete:
            blocking = completeness.blocking_gaps()
            labels = ", ".join(g.field.label for g in blocking[:5])
            reply = (
                f"Not quite — {len(blocking)} required field(s) are still open: {labels}. "
                "Give me those and I'll generate it, or say 'skip' on any that genuinely "
                "don't apply and I'll record them as open items."
            )
            return self._result(
                session, reply, intent, [g.field.id for g in blocking[:5]], {}, completeness
            )

        # Complete is not the same as coherent. Contradictions are put here,
        # where the participant can answer them, rather than at the render call
        # where they would arrive as a failed button press. The same handler as
        # the conversational path, so saying "generate" cannot skip the review
        # or get stuck in it: anything already put to them and left standing is
        # recorded as accepted and stops being raised.
        raised = await self._consistency_turn(form, session, completeness, intent, {}, message)
        if raised is not None:
            return raised

        polished = await self._polish(form, session)
        session.action_items = derive_action_items(form, session, session.action_items)

        summary = self._render_summary(form, session)
        open_items = [a for a in session.action_items if a.status.value == "open"]
        noted = [
            f
            for f in session.consistency_findings
            if f.state is FindingState.ACKNOWLEDGED and f.resolution
        ]
        body = (
            f"Here's the complete submission for review:\n\n{summary}\n\n"
            + (f"{len(open_items)} open action item(s) recorded.\n\n" if open_items else "")
            + (
                f"{len(noted)} noted discrepancy(ies) carried with your reasons.\n\n"
                if noted
                else ""
            )
            + (f"{polished}\n\n" if polished else "")
        )

        # A confirmation is a statement about *this* submission and can only be
        # taken once the submission exists — which is here, with the summary in
        # front of them. Taken any earlier it attests to nothing.
        due = agreements.next_batch(form, session, AgreementStage.BEFORE_REVIEW)
        if due:
            return self._present_agreements(
                form, session, due, intent, completeness, preface=body.rstrip()
            )

        session.status = SessionStatus.READY_FOR_REVIEW
        reply = body + (
            "Tell me anything you'd like changed, or confirm and I'll produce the document."
        )
        return self._result(session, reply, intent, [], {}, completeness, ready=True)

    async def _polish(self, form: FormDefinition, session: FormSession) -> str:
        """Write up the free-text answers. Returns a line about it, or "".

        Run from both completion paths — saying "generate" must not produce a
        different document from letting the conversation finish.
        """
        rewrites = await normalisation.normalise(form, session, llm_provider=self._llm)
        applied = [r for r in rewrites if r.applied]
        if not applied:
            return ""
        return (
            f"I've written up the wording on {len(applied)} field(s) so they read properly in "
            "the document — the exact text you typed is kept on the record. Read them over and "
            "tell me if I've changed your meaning anywhere."
        )

    async def _handle_pause(
        self,
        form: FormDefinition,
        session: FormSession,
        message: SourceMessage,
        intent: Intent,
    ) -> TurnResult:
        completeness = analyse(form, session)
        reply = (
            f"Saved. {progress_line(completeness)} "
            f"Come back any time and mention this form — I'll pick up exactly here. "
            f"(Session `{session.id}`.)"
        )
        return self._result(session, reply, intent, [], {}, completeness)

    # -- agreements --------------------------------------------------------
    async def _agreement_turn(
        self,
        form: FormDefinition,
        session: FormSession,
        message: SourceMessage,
        intent: Intent,
    ) -> TurnResult | None:
        """Handle a turn that an outstanding agreement owns.

        Returns ``None`` when nothing is gated and the normal handlers should
        run. Two things are gated: agreements due before the conversation starts
        — always, because consent precedes collection — and any agreement the
        previous turn actually put to them, which is what makes their reply
        readable as a decision rather than as an answer to a question.

        Nothing is extracted while a start-stage agreement stands. That is the
        cost of taking consent seriously: someone who volunteers their whole
        change before accepting the terms has to say it again. It is a small
        cost, it happens once, and the alternative is a record that stored
        somebody's words under terms they had not agreed to.
        """
        pending = agreements.next_batch(form, session, AgreementStage.BEFORE_START)
        if not pending:
            asked = self._last_agreements_asked(session)
            pending = [
                a
                for a in form.agreements
                if a.id in asked and session.agreement_record(a.id, a.version) is None
            ]
        if not pending:
            return None

        completeness = analyse(form, session)

        if intent is Intent.PAUSE:
            return await self._handle_pause(form, session, message, intent)

        if intent in (Intent.ASK_RATIONALE, Intent.ASK_CLARIFICATION, Intent.ASK_ESCALATION):
            return await self._explain_agreement(form, session, message, pending, intent)

        decision = agreements.read_decision(message.text)

        if decision is AgreementDecision.ACCEPTED:
            for agreement in pending:
                agreements.record(
                    session,
                    agreement,
                    decision=AgreementDecision.ACCEPTED,
                    actor=message.author,
                    stated=message.text,
                )
            return await self._resume_after_agreement(form, session, intent, message, pending)

        if decision is AgreementDecision.DECLINED:
            return self._handle_decline(form, session, pending, message, intent, completeness)

        # "Which one can't you accept?" — "how recorded". A reply that names one
        # of them is an answer to the question just asked, and putting all the
        # terms again because it was not the word "no" reads as not listening.
        # It is also how a refusal gets lost: they said which one, twice, and
        # the record still shows nothing decided.
        if self._asked_which_agreement(session):
            named = agreements.identify(pending, message.text)
            if named is not None:
                return self._handle_decline(form, session, [named], message, intent, completeness)

        # Anything else that is *shaped* like a question is one. While terms are
        # on the screen the only things a person says are: I accept, I don't, or
        # a question about them — and the intent patterns will never cover every
        # way of asking. "Who can see what I type here?" matched none of them and
        # got the terms read back at it, which is the behaviour of something that
        # is not listening.
        if self._looks_like_a_question(message.text):
            return await self._explain_agreement(
                form, session, message, pending, Intent.ASK_CLARIFICATION
            )

        # Neither. Put them again — once, with the reason they are being asked
        # rather than the same words a second time.
        return self._present_agreements(
            form,
            session,
            pending,
            intent,
            completeness,
            preface=(
                "Before I record anything, I need this settled — it's the basis "
                "the rest of the submission is kept under."
            ),
        )

    @staticmethod
    def _looks_like_a_question(text: str) -> bool:
        """Shaped like a question: it ends in one, or it opens with one."""
        stripped = text.strip()
        if not stripped:
            return False
        return bool(stripped.endswith("?") or _OPENS_A_QUESTION.match(stripped))

    @staticmethod
    def _already_said(session: FormSession, answer: str) -> bool:
        """Have we given this exact answer before?

        This is what "asked twice" actually means. Repeating an answer that
        already failed to land is the behaviour the ladder exists to prevent,
        and it is the only thing that should push a question up a tier — not
        the number of questions asked before it, which are usually about
        something else entirely.
        """
        normalised = " ".join(answer.lower().split())
        return any(
            " ".join(request.answer.lower().split()) == normalised
            for request in session.support_requests
            if request.answer
        )

    @staticmethod
    def _asked_which_agreement(session: FormSession) -> bool:
        """True when the previous turn asked them to name one of the terms."""
        for entry in reversed(session.transcript):
            if entry.role == "assistant":
                return "which of these" in entry.text.lower()
        return False

    def _present_agreements(
        self,
        form: FormDefinition,
        session: FormSession,
        pending: list[Agreement],
        intent: Intent,
        completeness: Completeness,
        *,
        preface: str = "",
        ready: bool = False,
    ) -> TurnResult:
        """Put the agreements to the participant, verbatim.

        The text is never handed to the model. Everything around it is phrasing;
        the words being agreed to are the words the form declares, or the record
        of acceptance means nothing.

        On an agreement form each turn carries its own place in the sequence.
        Being handed clause after clause with no sense of how many are left is
        what makes people stop reading and start clicking.
        """
        if not preface and form.is_agreement_form:
            preface = self._agreement_preface(form, session, pending)
        body = agreements.present_all(pending)
        reply = f"{preface}\n\n{body}" if preface else body
        result = self._result(session, reply, intent, [], {}, completeness, ready=ready)
        result.awaiting_agreements = [a.id for a in pending]
        return result

    def _handle_decline(
        self,
        form: FormDefinition,
        session: FormSession,
        pending: list[Agreement],
        message: SourceMessage,
        intent: Intent,
        completeness: Completeness,
    ) -> TurnResult:
        """A refusal is recorded and respected, not argued with.

        With one agreement outstanding the refusal is unambiguous and is
        recorded against it. With several, it is not — and attributing a refusal
        to the wrong term would put a false statement on the record, so it is
        asked about instead.
        """
        if len(pending) > 1:
            titles = "\n".join(f"- **{a.title}**" for a in pending)
            reply = (
                "Which of these can't you accept? I don't want to record a refusal "
                f"against the wrong one.\n\n{titles}"
            )
            result = self._result(session, reply, intent, [], {}, completeness)
            result.awaiting_agreements = [a.id for a in pending]
            return result

        agreement = pending[0]
        agreements.record(
            session,
            agreement,
            decision=AgreementDecision.DECLINED,
            actor=message.author,
            stated=message.text,
        )

        route = form.route(agreement.route) if agreement.route else form.default_route()
        request = support.escalate(
            form,
            session,
            f"Declined '{agreement.title}': {message.text.strip()}",
            [],
            asked_by=message.author,
            reason="agreement declined",
            route=route,
        )
        explanation = agreement.on_decline or (
            "That's recorded. This one is required, so the submission can't go "
            "forward without it."
            if agreement.required
            else "That's recorded, and it doesn't stop anything — we can carry on."
        )
        reply = (
            f"{explanation}\n\n"
            + support.describe_route(request, sla=route.sla if route else "")
            + " Tell me if anything changes and I'll pick it straight back up."
        )
        result = self._result(session, reply, intent, [], {}, completeness)
        result.support_request = request.model_dump(mode="json")
        return result

    async def _explain_agreement(
        self,
        form: FormDefinition,
        session: FormSession,
        message: SourceMessage,
        pending: list[Agreement],
        intent: Intent,
    ) -> TurnResult:
        """Answer a question about the terms, then put them again.

        Somebody who asks what a term means before accepting it is doing exactly
        the right thing, and answering "please reply 'I agree'" to that is how
        consent becomes a formality nobody read.
        """
        completeness = analyse(form, session)
        context = "\n\n".join(f"{a.title}:\n{a.text}" for a in pending)
        # A question about the wording of a term belongs to whoever owns that
        # term, not to the form's default queue.
        owner = next(
            (form.route(a.route) for a in pending if a.route and form.route(a.route)), None
        )

        if intent is Intent.ASK_ESCALATION:
            return self._route_question(
                form, session, message, [], intent, completeness, route=owner
            )

        unsatisfied = bool(support.UNSATISFIED.search(message.text))

        # Tier 1 always gets a go. The terms never change while they are
        # pending, so counting "questions about the agreements" the way field
        # help is counted marks the *second distinct question* as a repeat and
        # sends it to a human — which is exactly what happened: two different
        # questions, two tickets, no answers. What makes something a repeat is
        # having already been given the same answer, so that is what is checked.
        if not unsatisfied:
            authored = support.answer_from_agreements(pending, message.text)
            if authored is not None and not self._already_said(session, authored[0]):
                answer, agreement_id = authored
                support.record_answer(
                    session,
                    message.text,
                    asked_by=message.author,
                    fields=[],
                    tier="definition",
                    answer=answer,
                    sources=[agreement_id],
                )
                return self._present_agreements(
                    form, session, pending, intent, completeness, preface=answer
                )

        # Only a question the authored material could not settle counts towards
        # the ladder.
        depth = session.note_help_asked([f"agreement:{a.id}" for a in pending])
        if unsatisfied:
            depth = max(depth, 2)

        # Tier 2: the model, grounded in the clause itself and the form's notes.
        # The text is right there — a question about "retained for seven years"
        # is answerable from the sentence it appears in.
        if depth <= 2:
            grounded = await support.answer_from_knowledge(
                form,
                session,
                message.text,
                [],
                llm_provider=self._llm,
                extra_context=(
                    "The participant is being asked to accept these terms and is "
                    f"asking about them:\n\n{context}"
                ),
                scope=[a.id for a in pending],
            )
            if grounded["answered"]:
                support.record_answer(
                    session,
                    message.text,
                    asked_by=message.author,
                    fields=[],
                    tier="grounded",
                    answer=grounded["answer"],
                    sources=grounded["sources"],
                )
                return self._present_agreements(
                    form, session, pending, intent, completeness, preface=grounded["answer"]
                )
            gap = str(grounded["gap"])
        else:
            gap = "asked more than twice without a settled answer"

        return self._route_question(
            form, session, message, [], intent, completeness, reason=gap, route=owner
        )

    async def _resume_after_agreement(
        self,
        form: FormDefinition,
        session: FormSession,
        intent: Intent,
        message: SourceMessage,
        accepted: list[Agreement],
    ) -> TurnResult:
        """Acceptance recorded — carry straight on rather than announcing it.

        Where the conversation resumes depends on which gate was just passed: a
        start-stage term is followed by the first question, a review-stage
        confirmation by the close it was holding up.
        """
        completeness = analyse(form, session)
        if agreements.blocking(form, session, AgreementStage.BEFORE_START):
            pending = agreements.next_batch(form, session, AgreementStage.BEFORE_START)
            return self._present_agreements(form, session, pending, intent, completeness)

        # A review-stage confirmation is the last thing between a finished
        # submission and the document. Accepting it closes the session rather
        # than reopening the review that produced it — the summary they just
        # confirmed is the summary, and showing it again reads as a system that
        # did not hear them.
        if (
            any(a.stage is AgreementStage.BEFORE_REVIEW for a in accepted)
            and completeness.mandatory_complete
            and not unresolved_mandatory(form, session)
            and not agreements.blocking_up_to(form, session, AgreementStage.BEFORE_REVIEW)
        ):
            session.status = SessionStatus.READY_FOR_REVIEW
            return self._result(
                session,
                "Recorded, with your confirmation against it. Say 'generate' and I'll "
                "produce the document, or tell me what to change.",
                intent,
                [],
                {},
                completeness,
                ready=True,
            )

        topic = next_topic(
            form,
            completeness,
            stalled=session.stalled_fields(),
            max_fields=self._batch_size(session),
            recently_settled=self._recently_settled(session),
        )
        if topic is None:
            result = await self._wrap_up(form, session, completeness, intent, {}, message=message)
            result.reply = f"Thank you — that's recorded. {result.reply}"
            return result

        section, fields = topic
        self._note_topic(session, section)
        question = await self._phrase_question(
            form,
            session,
            section=section,
            fields=fields,
            captured=[],
            problems=[],
            preamble="The participant has just accepted the terms. Thank them in one short "
            "clause — no more than that — and open the subject below.",
        )
        self._note_topic(session, section)
        return self._result(session, question, intent, [f.id for f in fields], {}, completeness)

    @staticmethod
    def _last_agreements_asked(session: FormSession) -> list[str]:
        for entry in reversed(session.transcript):
            if entry.role == "assistant" and entry.awaiting_agreements:
                return entry.awaiting_agreements
            if entry.role == "assistant" and entry.targeted_fields:
                return []  # a later question superseded the agreement turn
        return []

    # -- questions the participant asks ------------------------------------
    async def _handle_already_answered(
        self,
        form: FormDefinition,
        session: FormSession,
        message: SourceMessage,
        intent: Intent,
    ) -> TurnResult:
        """ "I already answered that" — show them what was recorded.

        Asking a fourth time is not the answer, and neither is an apology on its
        own. What restores confidence is the value: reading back what is on the
        record for the thing they are talking about proves it landed, and turns
        a complaint into either a confirmation or a correction.

        Where the value genuinely is missing — the extractor did not take it,
        which is the usual reason someone says this — saying so plainly is the
        honest move. "I have nothing recorded for the maintenance window" is a
        useful sentence; asking the same question again is not.

        The message is **extracted first, like any other**. "Didn't I answer
        that — the changes are reviewed by Haja" is a complaint *and* an answer,
        and the version of this that skipped extraction threw the answer away
        and asked for it again on the next turn. Somebody who has to say the
        same name three times has been told plainly that nothing they say is
        being listened to.
        """
        before = analyse(form, session)
        extraction = await self._extractor.extract(
            form,
            message,
            target_fields=[g.field.id for g in before.gaps] or None,
            known_values=session.settled_values(),
            context=self._recent_context(session),
        )
        captured = merge_into_session(session, form, extraction, message)["accepted"]

        completeness = analyse(form, session)
        named = self._referenced_fields(form, message.text)
        asked = [form.field(f) for f in self._last_targeted(session) if form.try_field(f)]
        subjects = named or asked

        recorded: list[str] = []
        missing: list[FormField] = []
        for field in subjects[:4]:
            answer = session.answers.get(field.id)
            if answer is not None and answer.is_settled and answer.value is not None:
                recorded.append(f"- **{field.label}**: {render_value(field, answer.value)}")
            else:
                missing.append(field)

        # Anything the protest itself carried takes precedence over everything
        # else: they said it again, it landed this time, and showing them that
        # is the whole answer.
        just_captured = [
            f"- **{form.field(fid).label}**: "
            f"{render_value(form.field(fid), session.answers[fid].value)}"
            for fid in captured
            if form.try_field(fid) and session.answers.get(fid) is not None
        ]
        missing = [f for f in missing if f.id not in set(captured)]

        # Nothing recorded for what was just asked does not mean nothing landed.
        # Showing the answers that did is what settles a protest — then the
        # statement about what is genuinely still missing reads as information
        # rather than as another demand.
        if not recorded and not just_captured:
            for field_id in self._recently_settled(session, limit=3):
                settled = form.try_field(field_id)
                answer = session.answers.get(field_id)
                if settled is None or answer is None or answer.value is None:
                    continue
                recorded.append(f"- **{settled.label}**: {render_value(settled, answer.value)}")

        lines: list[str] = []
        if just_captured:
            lines.append("You did, and it's landed now:\n" + "\n".join(just_captured))
        elif recorded:
            lines.append("You did — here's what I have:\n" + "\n".join(recorded))
            lines.append("Tell me if any of that is wrong and I'll change it.")
        if missing:
            labels = ", ".join(f.label.lower() for f in missing)
            lines.append(
                ("I don't have anything recorded for " if recorded else "You may well have, but ")
                + f"{labels} — it didn't reach the record, which is my fault rather than yours. "
                "Say it once more and I'll make sure it sticks."
            )
        if not lines:
            return await self._handle_status(form, session, message, intent)

        return self._result(
            session,
            "\n\n".join(lines),
            intent,
            [f.id for f in missing],
            {},
            completeness,
            ready=completeness.mandatory_complete,
        )

    async def _handle_escalation(
        self,
        form: FormDefinition,
        session: FormSession,
        message: SourceMessage,
        intent: Intent,
    ) -> TurnResult:
        """ "Who can I ask about this?" — route it, and say who has it."""
        completeness = analyse(form, session)
        fields = self._question_fields(form, session, message, completeness)
        return self._route_question(form, session, message, fields, intent, completeness)

    def _route_question(
        self,
        form: FormDefinition,
        session: FormSession,
        message: SourceMessage,
        fields: list[FormField],
        intent: Intent,
        completeness: Completeness,
        *,
        reason: str = "",
        route: Any = None,
    ) -> TurnResult:
        """Hand a question to the team that owns it and carry on.

        The question does not stop the form. Whatever it was about is left open
        — not skipped, which would be a decision the participant has not made —
        and the conversation moves to something they *can* answer while the team
        comes back. A blocked field that also blocks every other field is how a
        form gets abandoned over one question.
        """
        request = support.escalate(
            form,
            session,
            message.text,
            fields,
            asked_by=message.author,
            reason=reason,
            route=route,
        )
        route = form.route(request.route_id) if request.route_id else None
        lines = [support.describe_route(request, sla=route.sla if route else "")]
        if route and route.note:
            lines.append(route.note)
        if fields:
            labels = ", ".join(f.label for f in fields)
            lines.append(
                f"I've left {labels} open rather than guessing at it. Come back to me "
                "when you hear, and we'll keep going with the rest meanwhile."
            )

        result = self._result(
            session, " ".join(lines), intent, [f.id for f in fields], {}, completeness
        )
        result.support_request = request.model_dump(mode="json")
        return result

    def _question_fields(
        self,
        form: FormDefinition,
        session: FormSession,
        message: SourceMessage,
        completeness: Completeness,
    ) -> list[FormField]:
        """What a meta-question is about: what they named, else what was asked."""
        named = self._referenced_fields(form, message.text)
        if named:
            return named[:2]
        asked = [form.field(f) for f in self._last_targeted(session) if form.try_field(f)]
        if asked:
            return asked[:2]
        topic = next_topic(
            form,
            completeness,
            stalled=session.stalled_fields(),
            max_fields=self._batch_size(session),
        )
        return list(topic[1])[:2] if topic else []

    # -- question generation ----------------------------------------------
    async def _phrase_question(
        self,
        form: FormDefinition,
        session: FormSession,
        *,
        section: Any,
        fields: list[FormField],
        captured: list[str],
        problems: list[dict[str, str]],
        confirmations: list[tuple[FormField, Any]] | None = None,
        note: str = "",
        preamble: str = "",
    ) -> str:
        """Ask the model to phrase a question covering the given fields.

        The *selection* is deterministic — gap analysis says what may be asked,
        affinity says what belongs together, ask counts say how pointed to be.
        Only the wording is generated. That keeps control in code while the
        conversation still reads like one.

        What the model is given is deliberately not a list of labels to read
        out. It is told what needs to be *learned*, and asked for the question a
        colleague would ask to learn it.
        """
        if not fields and not confirmations:
            return "Anything else you'd like to add?"

        lines: list[str] = []
        if preamble:
            lines += [preamble, ""]
        if form.guidance:
            lines += [f"Form context: {form.guidance}", ""]

        lines += [f"Subject of this question: {section.title}"]
        if section.description:
            lines.append(section.description)
        if getattr(section, "spans_sections", False):
            # Worth saying: these were filed apart by the author and are being
            # asked together because they belong together to the person
            # answering. The model should find the thread, not apologise for it.
            lines.append(
                "These come from different parts of the form and are being asked "
                "together because they are the same subject to the person answering. "
                "Find what they have in common and ask about that."
            )

        if captured:
            labels = [form.field(f).label for f in captured if form.try_field(f)]
            if labels:
                lines += ["", f"Just captured: {', '.join(labels)}."]

        if problems:
            lines += ["", "These values could not be accepted — explain and re-ask:"]
            lines += [f"- {p['field']}: {p['problem']}" for p in problems]

        if confirmations:
            lines += ["", "Confirm these low-confidence values with the participant:"]
            lines += [
                f"- {f.label}: currently recorded as '{render_value(f, v)}'"
                for f, v in confirmations
            ]

        if fields:
            lines += [
                "",
                "What you need to learn (describe these in your own words — do not "
                "quote the labels, and do not list them):",
            ]
            for field in fields:
                marker = "required" if field.is_mandatory else "optional"
                lines.append(f"- {field.prompt_descriptor()} [{marker}]")

            # Naming what is already settled, with its value, is what stops the
            # single most damaging failure this conversation has: asking again
            # for something the participant has already given you. Telling the
            # model what *not* to ask is weaker than showing it the answer — it
            # cannot re-ask for a date it can see.
            settled = self._settled_summary(form, session)
            if settled:
                lines += [
                    "",
                    "Already answered. Do not ask about any of these again, in any "
                    "form, and do not ask them to confirm one unless it is listed "
                    "above as needing confirmation:",
                    *settled,
                ]

            lines += ["", _ASK_STYLES[self._ask_style(session, fields)]]

        if note:
            lines += ["", note]

        recent = self._recent_context(session, limit=6)
        if recent:
            lines += ["", "Recent conversation:", recent]

        try:
            from sa_connectors.llm.base import Message

            response = await self._provider().complete_structured(
                [Message.user("\n".join(lines))], _QUESTION_SCHEMA, system=_QUESTION_SYSTEM
            )
            reply = str(response.get("reply", "")).strip()
            if reply:
                return reply
        except Exception as exc:  # noqa: BLE001 - fall back rather than fail the turn
            logger.error(
                "question generation failed; using the deterministic fallback",
                extra={"form": form.name, "error": str(exc)},
            )

        return self._fallback_question(section, fields, confirmations, problems)

    @staticmethod
    def _settled_summary(form: FormDefinition, session: FormSession, limit: int = 24) -> list[str]:
        """Every answer already on the record, as `- Label: value` lines.

        Sensitive fields are named without their value: the question planner has
        no need of a salary, and the prompt is one more place it could leak.
        """
        lines: list[str] = []
        for field in form.fields():
            answer = session.answers.get(field.id)
            if answer is None or not answer.is_settled or answer.value is None:
                continue
            shown = "(recorded)" if field.sensitive else render_value(field, answer.value)
            lines.append(f"- {field.label}: {shown}")
            if len(lines) >= limit:
                break
        return lines

    @staticmethod
    def _ask_style(session: FormSession, fields: list[FormField]) -> str:
        """How pointed this question should be, from how often it has been asked.

        Read off the highest count in the batch, because that is the item
        holding the conversation up. Nobody minds a broad question the first
        time; everybody minds the same broad question a third time.

        The first substantive turn is an *invitation*, not a question: somebody
        who arrives with the whole change in their head should be able to type
        it out in one go. Opening with "what's changing, which system, and who
        owns it?" tells them the shape of the answer you want, and they give you
        three things instead of twelve.
        """
        asked = max((session.ask_counts.get(f.id, 0) for f in fields), default=0)
        if asked >= 2:
            return "explicit"
        if asked >= 1:
            return "specific"
        if not any(a.is_settled for a in session.answers.values()):
            return "invitation"
        return "open"

    @staticmethod
    def _batch_size(session: FormSession, default: int = 4) -> int:
        """How many things to ask about at once, from how this person answers.

        Not a constant, and not read off the form. Somebody answering in
        paragraphs has more in their head than one question can carry, and
        capping them at three items means three round trips to get what they
        would have typed in one. Somebody answering in three words is telling
        you the opposite, and handing them four things at once is how two of
        them get missed.

        Measured on what they have actually done in this conversation — the
        words per turn and how much each turn settled — rather than on a guess
        about the kind of person they are.
        """
        replies = [e for e in session.transcript if e.role == "user"][-4:]
        if not replies:
            return default
        words = sum(len(e.text.split()) for e in replies) / len(replies)
        settled = sum(1 for a in session.answers.values() if a.is_settled)

        # A long opening answer that settled several fields at once: they are
        # willing to talk, so ask for more ground at a time.
        if words >= 40 or (settled >= 4 and words >= 20):
            return 6
        if words <= 6:
            return 2
        return default

    @staticmethod
    def _fallback_question(
        section: Any,
        fields: list[FormField],
        confirmations: list[tuple[FormField, Any]] | None,
        problems: list[dict[str, str]],
    ) -> str:
        """Plain-language question used when the model is unavailable.

        Less fluent, but the conversation keeps working during an LLM outage
        instead of dead-ending. It leads with the topic rather than the labels,
        so an outage degrades the phrasing without reverting to reading the form
        out loud — and it still names the items, because being unmistakable
        matters more than being smooth when there is no model to be smooth with.
        """
        parts: list[str] = []
        for problem in problems:
            parts.append(f"I couldn't use the value for {problem['field']}: {problem['problem']}.")
        for field, value in confirmations or []:
            parts.append(f"Can you confirm {field.label} is '{value}'?")
        if fields:
            subject = (getattr(section, "title", "") or "this").lower()
            labels = [f.label.lower() for f in fields]
            joined = labels[0] if len(labels) == 1 else f"{', '.join(labels[:-1])} and {labels[-1]}"
            parts.append(f"Tell me about {subject} — I still need the {joined}.")
        return " ".join(parts) or "Anything else to add?"

    async def _suggest_values(
        self,
        form: FormDefinition,
        session: FormSession,
        fields: list[FormField],
    ) -> dict[str, dict[str, Any]]:
        """Ask the model to propose values for the given fields.

        Returns proposals keyed by field id. A model failure returns nothing
        rather than raising: the handler then says it cannot call it, which is
        the same thing the old refusal said but without pretending it was a
        policy rather than an outage.
        """
        lines: list[str] = []
        if form.guidance:
            lines += [f"Form context: {form.guidance}", ""]
        lines += ["Propose a value for each of these fields:"]
        for field in fields:
            marker = "required" if field.is_mandatory else "optional"
            lines.append(f"- `{field.id}` — {field.prompt_descriptor()} [{marker}]")

        known = session.settled_values()
        if known:
            labels = {form.field(k).label: v for k, v in known.items() if form.try_field(k)}
            lines += [
                "",
                "Already established in this conversation:",
                *[f"- {label}: {value}" for label, value in labels.items()],
            ]

        lines += ["", "Full conversation so far:", self._recent_context(session, limit=20)]

        try:
            from sa_connectors.llm.base import Message

            response = await self._provider().complete_structured(
                [Message.user("\n".join(lines))], _SUGGESTION_SCHEMA, system=_SUGGESTION_SYSTEM
            )
        except Exception as exc:  # noqa: BLE001 - a proposal is best-effort
            logger.error(
                "value suggestion failed",
                extra={"form": form.name, "error": str(exc)},
            )
            return {}

        wanted = {f.id for f in fields}
        return {
            str(item.get("field_id")): item
            for item in (response.get("suggestions") or [])
            if item.get("field_id") in wanted
        }

    async def _catch_up_on_unlocked_fields(
        self,
        form: FormDefinition,
        session: FormSession,
        message: SourceMessage,
        before: Completeness,
    ) -> list[str]:
        """Re-read this message for fields its own answers have just unlocked.

        A conditional field is not a gap while its guard is undecided, so it is
        not in the target set, so anything the participant said about it is
        thrown away. One message that says both "the application will be down"
        *and* "the platform support team will tell users" settles customer
        impact — which activates the comms owner — and loses the comms owner in
        the same breath. Two turns later the engine asks who tells the
        customers, and the honest answer is "I already told you", because they
        had.

        Only the newly-unlocked fields are re-read, and only when a guard
        actually flipped, so the usual turn costs nothing extra.
        """
        after = analyse(form, session)
        unlocked = [
            gap.field.id
            for gap in after.gaps
            if gap.field.id in set(before.inactive) and gap.reason == "unanswered"
        ]
        if not unlocked:
            return []

        extraction = await self._extractor.extract(
            form,
            message,
            target_fields=unlocked,
            known_values=session.settled_values(),
            context=self._recent_context(session),
        )
        caught = merge_into_session(session, form, extraction, message)["accepted"]
        if caught:
            logger.info(
                "recovered answers for fields the same message unlocked",
                extra={"session": session.id, "fields": caught},
            )
            metrics.increment("forms.unlocked_recovered", form=form.name)
        return caught

    @staticmethod
    def _apply_timezone(
        form: FormDefinition,
        session: FormSession,
        message: SourceMessage,
    ) -> list[str]:
        """ "IST" completes the window they already gave.

        A value refused only for a missing timezone is kept as raw text, so the
        answer to "which zone?" is a two-letter reply rather than a request to
        retype the whole window. Deterministic on purpose: joining a time to its
        zone is string concatenation, and a model has no business in it.
        """
        if not states_a_timezone(message.text) or states_a_time(message.text):
            # A message carrying its own clock time is a fresh answer, not a
            # zone for the previous one; extraction handles it normally.
            return []

        zone = message.text.strip().strip(".,!")
        repaired: list[str] = []
        for field in form.fields():
            if not field.requires_timezone:
                continue
            answer = session.answers.get(field.id)
            if answer is None or answer.is_settled or not answer.raw_value:
                continue
            if "timezone" not in answer.note.lower():
                continue
            try:
                value = coerce_and_validate(field, f"{answer.raw_value} {zone}")
            except CoercionError:
                continue
            answer.supersede_with(
                value,
                raw_value=f"{answer.raw_value} {zone}",
                state=AnswerState.ANSWERED,
                confidence=0.9,
                provenance=Provenance(
                    channel=message.channel,
                    author=message.author,
                    message_id=message.id,
                    evidence=f"{answer.raw_value} + {zone}",
                    method="timezone_repair",
                ),
            )
            repaired.append(field.id)
        return repaired

    @staticmethod
    def _apply_leading_affirmation(
        form: FormDefinition,
        session: FormSession,
        message: SourceMessage,
        changed: dict[str, list[str]],
    ) -> list[str]:
        """ "Yes that's correct for the date, and …" confirms the date.

        The bare-affirmation path only fires on a message that is *nothing but*
        agreement, which is not how anyone talks. Someone who answers "yes
        that's right for the date — and didn't I already tell you the risk?" has
        confirmed the date, and asking them again reads as not listening. It is
        what produced "again and again am saying" in a real session.

        Run after extraction, and only for fields this turn did not otherwise
        touch, so "yes, but make it the 23rd" is a correction rather than a
        confirmation of the value being corrected.
        """
        if not _LEADING_AFFIRMATION.match(message.text.strip()):
            return []

        touched = {fid for key in ("accepted", "proposed", "conflicts") for fid in changed[key]}
        confirmed: list[str] = []
        for field_id in ConversationEngine._last_targeted(session):
            if field_id in touched or form.try_field(field_id) is None:
                continue
            answer = session.answers.get(field_id)
            if answer is None or not answer.needs_confirmation:
                continue
            answer.state = AnswerState.CONFIRMED
            answer.confidence = 1.0
            answer.note = ""
            answer.updated_at = time.time()
            confirmed.append(field_id)
        return confirmed

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _recently_settled(session: FormSession, limit: int = 4) -> list[str]:
        """The fields answered most recently, newest first.

        Feeds topic selection, which uses them to keep the conversation moving
        along the thread the participant is already on rather than restarting on
        whatever the form declares next.
        """
        settled = [
            (answer.updated_at, field_id)
            for field_id, answer in session.answers.items()
            if answer.is_settled
        ]
        return [field_id for _, field_id in sorted(settled, reverse=True)[:limit]]

    @staticmethod
    def _note_topic(session: FormSession, topic: Any) -> None:
        """Record which topic was opened, for progress and for debugging selection."""
        topic_id = getattr(topic, "id", "")
        if topic_id and (not session.topics_opened or session.topics_opened[-1] != topic_id):
            session.topics_opened.append(topic_id)

    @staticmethod
    def _settled(session: FormSession, field: FormField) -> bool:
        answer = session.answers.get(field.id)
        return answer is not None and answer.is_settled

    @staticmethod
    def _classify(text: str) -> Intent:
        stripped = text.strip()
        if not stripped:
            return Intent.OTHER
        for intent, pattern in _INTENT_PATTERNS:
            if pattern.search(stripped):
                # A long message that merely opens with "actually" is still
                # substantive: treat it as information carrying a correction.
                if intent is Intent.CORRECT and len(stripped.split()) > 8:
                    return Intent.PROVIDE_INFO
                return intent
        return Intent.PROVIDE_INFO

    @staticmethod
    def _referenced_fields(form: FormDefinition, text: str) -> list[FormField]:
        """Find which fields a meta-question is about ("why do you need the owner?").

        Two rules stop a question being filed against the wrong field, which is
        worse than not identifying one at all — the participant gets a confident
        explanation of something they did not ask about:

        * **Whole words only.** Substring matching files "risk" against
          "asterisk" and "date" against "candidate".
        * **A single common word never identifies a field.** Aliases are written
          for the extractor, where surrounding context disambiguates them, and
          they routinely include words like `what` and `why`. Every question
          contains those, so "what do you mean by customers impacted?" was
          matching whichever field happened to list `what`. Multi-word aliases
          are unaffected: "what else breaks" identifies exactly one field.
        """
        lowered = text.lower()
        matched: list[FormField] = []
        for field in form.fields():
            names = [field.label, field.id.replace("_", " "), *field.aliases]
            for name in names:
                candidate = name.lower().strip()
                if len(candidate) <= 3 or candidate in _WEAK_REFERENCES:
                    continue
                if re.search(rf"\b{re.escape(candidate)}\b", lowered):
                    matched.append(field)
                    break
        return matched

    @staticmethod
    def _last_targeted(session: FormSession) -> list[str]:
        for entry in reversed(session.transcript):
            if entry.role == "assistant" and entry.targeted_fields:
                return entry.targeted_fields
        return []

    @staticmethod
    def _recent_context(session: FormSession, limit: int = 10) -> str:
        return "\n".join(f"{e.role}: {e.text[:400]}" for e in session.recent_transcript(limit))

    @staticmethod
    def _add_action_item(session: FormSession, item: dict[str, str]) -> None:
        description = item.get("description", "").strip()
        if not description:
            return
        # Cheap dedupe: the same commitment restated across turns is common.
        normalised = " ".join(description.lower().split())
        if any(" ".join(a.description.lower().split()) == normalised for a in session.action_items):
            return
        session.action_items.append(
            ActionItem(
                description=description,
                owner=item.get("owner") or None,
                due_date=item.get("due_date") or None,
                evidence=item.get("evidence", ""),
                origin="conversation",
            )
        )

    async def _wrap_up(
        self,
        form: FormDefinition,
        session: FormSession,
        completeness: Completeness,
        intent: Intent,
        changed: dict[str, list[str]],
        *,
        message: SourceMessage | None = None,
    ) -> TurnResult:
        """Nothing left to ask. Say so — accurately.

        "Nothing left to ask" and "nothing left to answer" are different states,
        and conflating them is how a submission reaches an approver with a
        required field reading ``_(not provided)_`` under a heading that says
        the form is complete. A mandatory field that was skipped or declined
        leaves no gap to ask about, but it absolutely leaves the form
        incomplete, and only :meth:`_handle_finalize` used to notice.

        Having every field is also not the same as having a coherent
        submission, so this is where the consistency review runs — once, at the
        point the answers stop moving.
        """
        session.action_items = derive_action_items(form, session, session.action_items)
        outstanding = unresolved_mandatory(form, session)

        if outstanding:
            summary = self._render_summary(form, session)
            labels = ", ".join(f.label for f in outstanding)
            reply = (
                f"Here's everything captured so far:\n\n{summary}\n\n"
                f"{len(outstanding)} required field(s) are still open — {labels}. "
                "Give me those and it's complete; leave them and they go on the document "
                "as open action items, which is what the approver will see."
            )
            return self._result(
                session,
                reply,
                intent,
                [f.id for f in outstanding],
                changed,
                completeness,
                ready=False,
            )

        return await self._review_and_close(form, session, completeness, intent, changed, message)

    async def _consistency_turn(
        self,
        form: FormDefinition,
        session: FormSession,
        completeness: Completeness,
        intent: Intent,
        changed: dict[str, list[str]],
        message: SourceMessage | None,
    ) -> TurnResult | None:
        """Check the submission against itself.

        Returns a turn when something needs putting to the participant, and
        ``None`` when the answers cohere and the caller should carry on.

        Their next message either changes an answer — the finding resolves
        itself on re-evaluation — or explains why both are true, which is
        recorded against *that* finding and travels onto the document.

        When several were raised together, the reply is attributed to the ones
        it actually answers. Filing one explanation against all of them was the
        earlier behaviour and it produced records where the owner's reason for
        reviewing their own change was a sentence about the maintenance window:
        worse than recording nothing, because it reads like a considered answer.
        Whatever the reply did not cover is asked again, once.
        """
        previously_raised = {
            f.id for f in session.consistency_findings if f.state is FindingState.RAISED
        }

        # Re-evaluate first. A participant who answered by *correcting* an
        # answer has resolved the finding, and recording their correction as a
        # justification for the thing they just fixed would be exactly backwards.
        understanding, findings = await consistency.review(form, session, llm_provider=self._llm)

        if message is not None and previously_raised:
            standing = [f for f in findings if f.id in previously_raised]
            answered = await self._attribute(session, standing, message, intent)
            findings = [f for f in findings if f.id not in answered]

        if not findings:
            return None

        # A follow-up is not a repeat. Someone who answered one of three and
        # got all three back would rightly conclude nobody was reading.
        following_up = all(f.times_raised for f in findings)
        consistency.mark_raised(findings)

        if following_up:
            plural = "one thing" if len(findings) == 1 else f"{len(findings)} things"
            reply = (
                f"That's noted. {plural.capitalize()} from before still needs an answer:\n\n"
                f"{consistency.describe(findings)}\n\n"
                "Correct the answer, or tell me why it stands and I'll record that. If you'd "
                "rather leave it, say so and the document will show it was raised and not "
                "explained."
            )
        else:
            # Written up before it is read back. A summary of raw chat text
            # invites "you have exact words from my chat rather than beautified
            # versions", and rightly so — this is the first full look the
            # participant gets at what the document will say.
            await self._polish(form, session)
            summary = self._render_summary(form, session)
            lead = understanding or "Here's what I have."
            plural = "this doesn't" if len(findings) == 1 else "these don't"
            reply = (
                f"{lead}\n\n{summary}\n\n"
                f"Before I call this done — {plural} line up:\n\n"
                f"{consistency.describe(findings)}\n\n"
                "Which is right? Correct whichever one is wrong, or tell me why both hold and "
                "I'll record your reason on the document for the approver."
            )
        return self._result(
            session,
            reply,
            intent,
            sorted({fid for f in findings for fid in f.fields}),
            changed,
            completeness,
            # A warning does not stop the document; a blocking finding does.
            ready=not any(f.severity.blocks for f in findings),
        )

    async def _attribute(
        self,
        session: FormSession,
        standing: list[ConsistencyFinding],
        message: SourceMessage,
        intent: Intent,
    ) -> set[str]:
        """Acknowledge the findings this reply actually answers.

        Returns the ids that are now settled. A finding the reply did not touch
        stays raised and is put again — but only once more. Somebody who has
        been asked twice and answered neither time has told you something, and
        the honest record is "raised twice, not explained" rather than either an
        invented reason or an endless loop.
        """
        if not standing:
            return set()

        # An instruction is not an explanation. "Generate it" accepts everything
        # outstanding without saying why, and is recorded as exactly that.
        if intent in (Intent.FINALIZE, Intent.CONFIRM):
            consistency.acknowledge(session, standing, self._acknowledgement(message, intent))
            return {f.id for f in standing}

        answered = await consistency.attribute(
            standing,
            message.text,
            llm_provider=self._llm,
            # Once something has been followed up, taking the next reply as its
            # answer is the assumption that produced the wrong record in the
            # first place. Make the attribution earn it.
            assume_single=not any(f.times_raised >= _MAX_DISCREPANCY_ASKS for f in standing),
        )
        settled: set[str] = set()

        for finding in standing:
            explanation = answered.get(finding.id)
            if explanation:
                consistency.acknowledge(session, [finding], explanation)
                settled.add(finding.id)
            elif finding.times_raised >= _MAX_DISCREPANCY_ASKS:
                consistency.acknowledge(
                    session,
                    [finding],
                    f"Raised {finding.times_raised} times and not explained; "
                    f"accepted as stated by {message.author}.",
                )
                settled.add(finding.id)
        return settled

    @staticmethod
    def _acknowledgement(message: SourceMessage, intent: Intent) -> str:
        """What to record against a finding the participant stood by.

        Usually their own words. But "generate it" and "yes" are instructions,
        not explanations, and putting them on the document under "the owner's
        answer" would misrepresent what they said — so those become a plain
        statement of what actually happened.
        """
        note = message.text.strip()
        if intent in (Intent.FINALIZE, Intent.CONFIRM) or len(note.split()) <= 3:
            return f"Reviewed and accepted without change by {message.author}."
        return note

    async def _review_and_close(
        self,
        form: FormDefinition,
        session: FormSession,
        completeness: Completeness,
        intent: Intent,
        changed: dict[str, list[str]],
        message: SourceMessage | None,
    ) -> TurnResult:
        """Nothing left to ask and nothing left unanswered. Review, then close."""
        raised = await self._consistency_turn(form, session, completeness, intent, changed, message)
        if raised is not None:
            return raised

        # Written up only once the answers have stopped moving, so nothing is
        # polished and then superseded — and so the summary the participant
        # reads below is the text that will appear on the document.
        polished = await self._polish(form, session)

        acknowledged = [
            f
            for f in session.consistency_findings
            if f.state is FindingState.ACKNOWLEDGED and f.resolution
        ]
        footnotes: list[str] = []
        if acknowledged:
            footnotes.append(
                f"Noted on the document: {len(acknowledged)} point(s) you confirmed were "
                "deliberate, with your reasons."
            )
        if polished:
            footnotes.append(polished)
        open_questions = session.open_support_requests()
        if open_questions:
            teams = ", ".join(sorted({r.team for r in open_questions if r.team}))
            footnotes.append(
                f"{len(open_questions)} question(s) still with {teams or 'the owning team'}; "
                "they're recorded on the document so the approver sees them too."
            )
        body = (
            "That's everything, and it hangs together. Here's the full submission:\n\n"
            f"{self._render_summary(form, session)}\n"
            + ("\n" + "\n".join(footnotes) + "\n" if footnotes else "")
        )

        due = agreements.next_batch(form, session, AgreementStage.BEFORE_REVIEW)
        if due:
            return self._present_agreements(
                form, session, due, intent, completeness, preface=body.rstrip()
            )

        session.status = SessionStatus.READY_FOR_REVIEW
        reply = body + "\nSay 'generate' to produce the document, or tell me what to change."
        return self._result(session, reply, intent, [], changed, completeness, ready=True)

    def _render_summary(self, form: FormDefinition, session: FormSession) -> str:
        """A readable recap, grouped by topic, for the review step."""
        lines: list[str] = []
        for section in form.ordered_sections():
            rows: list[str] = []
            for field in section.fields:
                answer = session.answers.get(field.id)
                if answer is None or answer.state is AnswerState.EMPTY:
                    continue
                if answer.state in (AnswerState.SKIPPED, AnswerState.NOT_APPLICABLE):
                    rows.append(f"  - {field.label}: _(not provided)_")
                    continue
                shown = "••••••" if field.sensitive else render_value(field, answer.value)
                flag = " _(unconfirmed)_" if answer.state is AnswerState.PROPOSED else ""
                rows.append(f"  - {field.label}: {shown}{flag}")
            if rows:
                lines.append(f"**{section.title}**")
                lines.extend(rows)

        # What was agreed is part of the recap, and for an agreement form it is
        # the whole of it — a summary that said "nothing captured yet" about a
        # completed policy acceptance would be both wrong and insulting.
        decisions: list[str] = []
        for record in session.agreements:
            agreement = form.try_agreement(record.agreement_id)
            title = agreement.title if agreement else record.agreement_id
            verdict = "Accepted" if record.accepted else "**Declined**"
            decisions.append(f"  - {title}: {verdict} by {record.actor}")
        if decisions:
            lines.append("**Agreed**")
            lines.extend(decisions)

        return "\n".join(lines) if lines else "_Nothing captured yet._"

    @staticmethod
    def _result(
        session: FormSession,
        reply: str,
        intent: Intent,
        targeted: list[str],
        changed: dict[str, list[str]],
        completeness: Completeness,
        *,
        ready: bool = False,
    ) -> TurnResult:
        return TurnResult(
            session_id=session.id,
            reply=reply,
            intent=intent,
            targeted_fields=targeted,
            captured=changed.get("accepted", []),
            needs_confirmation=changed.get("proposed", []),
            conflicts=changed.get("conflicts", []),
            status=session.status,
            completeness=completeness.summary(),
            ready_for_review=ready,
        )

    # -- bulk ingestion ----------------------------------------------------
    async def ingest(
        self,
        session_id: str,
        messages: list[SourceMessage],
        *,
        summarise: bool = True,
    ) -> dict[str, Any]:
        """Mine a batch of messages without conversing.

        This is the JIRA-thread and email-thread path: pull in months of
        back-and-forth at once, extract everything it supports, and only then
        ask the user about whatever is genuinely still missing. It is what
        turns "a lot of to-and-fro" into a single short conversation.

        Messages are processed oldest-first so later corrections supersede
        earlier statements rather than being rejected as lower-confidence
        conflicts.
        """
        session = await self._sessions.load(session_id)
        form = self._registry.get(session.form_name, session.form_version)

        if not session.status.is_editable:
            raise ValidationError(
                f"session '{session_id}' is {session.status.value} and cannot accept new input",
                details={"session_id": session_id, "status": session.status.value},
            )

        # The same gate the conversation applies, for the same reason. Mining a
        # thread stores the participant's words exactly as typing them would,
        # and a terms-of-recording agreement that the ingest path walks around
        # is not a gate — it is a notice. An integration that cannot show the
        # terms to anybody has no business storing their words either.
        unagreed = agreements.blocking(form, session, AgreementStage.BEFORE_START)
        if unagreed:
            raise ValidationError(
                f"{len(unagreed)} agreement(s) must be accepted before this session "
                "can take any content",
                details={
                    "session_id": session_id,
                    "agreements": [{"id": a.id, "title": a.title} for a in unagreed],
                },
            )

        ordered = sorted(messages, key=lambda m: m.timestamp)
        captured: list[str] = []
        proposed: list[str] = []
        conflicts: list[str] = []

        with tracer.span("forms.ingest", form=form.name, session=session.id, messages=len(ordered)):
            for message in ordered:
                current = analyse(form, session)
                targets = [g.field.id for g in current.gaps] + [
                    c.field.id for c in current.confirmations
                ]
                if not targets:
                    break  # nothing left to look for; stop spending calls

                extraction = await self._extractor.extract(
                    form,
                    message,
                    target_fields=targets,
                    known_values=session.settled_values(),
                )
                changed = merge_into_session(session, form, extraction, message)
                captured.extend(changed["accepted"])
                proposed.extend(changed["proposed"])
                conflicts.extend(changed["conflicts"])

                for item in extraction.action_items:
                    self._add_action_item(session, item)

                session.record(
                    TranscriptEntry(
                        role="user",
                        text=message.text,
                        author=message.author,
                        channel=message.channel,
                        message_id=message.id,
                    )
                )

        after = analyse(form, session)
        if after.mandatory_complete and not session.mandatory_complete_announced:
            session.mandatory_complete_announced = True
            session.status = SessionStatus.READY_FOR_REVIEW

        report: dict[str, Any] = {
            "session_id": session.id,
            "messages_processed": len(ordered),
            "captured": sorted(set(captured)),
            "needs_confirmation": sorted(set(proposed)),
            "conflicts": sorted(set(conflicts)),
            "completeness": after.summary(),
        }

        if summarise:
            topic = next_topic(
                form,
                after,
                stalled=session.stalled_fields(),
                max_fields=self._batch_size(session),
                recently_settled=sorted(set(captured)),
            )
            if topic is None:
                report["next_message"] = (
                    f"I pulled {len(captured)} field(s) from that thread and everything "
                    "required is covered. Say 'generate' when you'd like the document."
                )
            else:
                section, fields = topic
                self._note_topic(session, section)
                report["next_message"] = await self._phrase_question(
                    form,
                    session,
                    section=section,
                    fields=fields,
                    captured=sorted(set(captured)),
                    problems=[],
                    preamble=(
                        "You have just read an existing thread and extracted what it "
                        "contained. Summarise in one clause what you picked up, then ask "
                        "only about what is still missing."
                    ),
                )
                report["targeted_fields"] = [f.id for f in fields]
            session.record(
                TranscriptEntry(
                    role="assistant",
                    text=report["next_message"],
                    author="assistant",
                    targeted_fields=report.get("targeted_fields", []),
                )
            )

        await self._sessions.save(session)
        logger.info(
            "ingested external thread",
            extra={
                "session": session.id,
                "messages": len(ordered),
                "captured": len(set(captured)),
            },
        )
        return report

    # -- direct manipulation ----------------------------------------------
    async def set_answer(
        self,
        session_id: str,
        field_id: str,
        value: Any,
        *,
        author: str = "user",
        confirm: bool = True,
    ) -> FormSession:
        """Set a field directly, bypassing extraction.

        Used by a form UI, an import, or a reviewer correcting a value. A
        directly-set answer is ``CONFIRMED``, so later extraction cannot
        overwrite it.
        """
        session = await self._sessions.load(session_id)
        form = self._registry.get(session.form_name, session.form_version)
        field = form.try_field(field_id)
        if field is None:
            raise NotFoundError(
                f"form '{form.name}' has no field '{field_id}'",
                details={"form": form.name, "field": field_id},
            )
        if not session.status.is_editable:
            raise ValidationError(
                f"session '{session_id}' is {session.status.value} and cannot be edited",
                details={"session_id": session_id, "status": session.status.value},
            )

        try:
            coerced = coerce_and_validate(field, value)
        except CoercionError:
            raise

        session.answer_for(field_id).supersede_with(
            coerced,
            raw_value=str(value),
            state=AnswerState.CONFIRMED if confirm else AnswerState.ANSWERED,
            confidence=1.0,
            provenance=Provenance(
                channel=SourceChannel.FORM_UI,
                author=author,
                evidence="" if field.sensitive else str(value)[:200],
                method="user_confirmed",
            ),
        )
        await self._sessions.save(session)
        return session

    async def get_session(self, session_id: str) -> FormSession:
        return await self._sessions.load(session_id)

    async def status(self, session_id: str) -> dict[str, Any]:
        """Full status report for a session."""
        session = await self._sessions.load(session_id)
        form = self._registry.get(session.form_name, session.form_version)
        completeness = analyse(form, session)
        return {
            "session_id": session.id,
            "form": form.qualified_name,
            "status": session.status.value,
            "participants": session.participants,
            "completeness": completeness.summary(),
            "summary": self._render_summary(form, session),
            "topics_opened": session.topics_opened,
            "agreements": {
                "decided": [a.model_dump(mode="json") for a in session.agreements],
                # What the conversation is *actually* waiting on right now, as
                # opposed to what is merely undecided. A confirmation due before
                # review is undecided from the first turn, and a caller that
                # cannot tell the two apart shows a gate that is not there yet.
                "awaiting": [
                    a
                    for a in self._last_agreements_asked(session)
                    if (agreement := form.try_agreement(a)) is not None
                    and session.agreement_record(a, agreement.version) is None
                ],
                "outstanding": [
                    {
                        "id": a.id,
                        "title": a.title,
                        "stage": a.stage.value,
                        "kind": a.kind.value,
                        "decidable": agreements.reachable(form, session, a.stage),
                    }
                    for stage in AgreementStage
                    for a in agreements.outstanding(form, session, stage)
                ],
                "blocking": [
                    a.id
                    for a in agreements.blocking_up_to(
                        form, session, AgreementStage.BEFORE_GENERATE
                    )
                ],
            },
            "questions": {
                "open": [r.model_dump(mode="json") for r in session.open_support_requests()],
                "answered": [
                    r.model_dump(mode="json") for r in session.support_requests if not r.is_open
                ],
            },
            "action_items": [
                a.model_dump(mode="json") for a in session.action_items if a.status.value == "open"
            ],
            "consistency": {
                "outstanding": [
                    f.model_dump(mode="json") for f in consistency.outstanding(session)
                ],
                "blocking": [f.id for f in consistency.blocking(session)],
                "noted": [
                    f.model_dump(mode="json")
                    for f in session.consistency_findings
                    if f.state is FindingState.ACKNOWLEDGED
                ],
            },
            "closed_action_items": [
                a.model_dump(mode="json") for a in session.action_items if a.status.value != "open"
            ],
            "created_at": session.created_at,
            "updated_at": session.updated_at,
        }


__all__ = ["ConversationEngine", "Intent", "TurnResult"]
