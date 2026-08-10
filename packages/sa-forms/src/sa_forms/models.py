"""Form, session, and artifact models.

The design separates three things that are easy to conflate:

* **What the form needs** — :class:`FormDefinition`, a versioned contract.
* **What we have learned so far** — :class:`FormSession`, an append-only record
  of answers with provenance, resumable across days and channels.
* **What we produced** — :class:`ArtifactRecord`, a rendered, reviewable,
  baselineable document.

Nothing here is specific to any particular form. A form is data.
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

_ID_PATTERN = r"^[a-z][a-z0-9_]*$"


# ---------------------------------------------------------------------------
# Field-level vocabulary
# ---------------------------------------------------------------------------


class FieldType(str, Enum):
    """The value shape a field holds. Drives coercion, validation, and rendering."""

    STRING = "string"
    TEXT = "text"  # multi-line prose
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"  # ISO-8601 date
    DATETIME = "datetime"
    ENUM = "enum"  # one of `options`
    MULTI_ENUM = "multi_enum"  # any of `options`
    LIST = "list"  # free-form list of strings
    OBJECT = "object"  # nested JSON
    EMAIL = "email"
    URL = "url"
    PERSON = "person"  # a named human; kept distinct so we can resolve directories
    CURRENCY = "currency"
    DURATION = "duration"


class Importance(str, Enum):
    """How badly the form needs this field.

    ``MANDATORY`` blocks completion. ``RECOMMENDED`` is the "good to have"
    tier — the conversation probes for it once the mandatory set is closed, but
    never blocks on it.
    """

    MANDATORY = "mandatory"
    RECOMMENDED = "recommended"
    OPTIONAL = "optional"

    @property
    def rank(self) -> int:
        return {"mandatory": 0, "recommended": 1, "optional": 2}[self.value]


class AnswerState(str, Enum):
    """Lifecycle of a single field's answer."""

    EMPTY = "empty"
    PROPOSED = "proposed"  # extracted, but below the confidence bar
    ANSWERED = "answered"  # accepted
    CONFIRMED = "confirmed"  # explicitly confirmed by a human
    SKIPPED = "skipped"  # deliberately declined
    NOT_APPLICABLE = "not_applicable"

    @property
    def is_settled(self) -> bool:
        """True when the field no longer needs to be asked about."""
        return self in (
            AnswerState.ANSWERED,
            AnswerState.CONFIRMED,
            AnswerState.SKIPPED,
            AnswerState.NOT_APPLICABLE,
        )


class FieldValidation(BaseModel):
    """Declarative constraints, checked after coercion."""

    model_config = ConfigDict(extra="forbid")

    pattern: str | None = None
    min_length: int | None = Field(default=None, ge=0)
    max_length: int | None = Field(default=None, ge=1)
    minimum: float | None = None
    maximum: float | None = None
    min_items: int | None = Field(default=None, ge=0)
    max_items: int | None = Field(default=None, ge=1)


class FormField(BaseModel):
    """One question the form needs answered."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Stable snake_case identifier, unique within the form")
    label: str = Field(description="Human-readable name, e.g. 'Target go-live date'")
    type: FieldType = FieldType.STRING
    importance: Importance = Importance.OPTIONAL

    description: str = Field(
        default="",
        description="What this field means. Shown to users and given to the extractor.",
    )
    #: Why the form needs it. Answers the user's "why are you asking me this?"
    #: without a model having to invent a justification.
    rationale: str = Field(
        default="",
        description="Why this matters and what it unblocks downstream.",
    )
    #: Alternate phrasings a speaker might use. Materially improves recall when
    #: mining unstructured JIRA comments and email threads.
    aliases: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)

    options: list[str] = Field(default_factory=list, description="Allowed values for enum types")
    validation: FieldValidation | None = None
    default: Any = None
    unit: str | None = Field(default=None, description="e.g. 'USD', 'days'")

    #: Only ask when this expression is true, evaluated against collected
    #: answers — e.g. ``${answers.needs_dr == true}``.
    ask_when: str | None = None
    #: Fields whose answers give this one useful context when asking.
    related_fields: list[str] = Field(default_factory=list)

    #: Extraction below this confidence is held as PROPOSED and confirmed with
    #: the user rather than silently accepted.
    confidence_threshold: float = Field(default=0.65, ge=0.0, le=1.0)
    #: Never infer this from surrounding text; require an explicit statement.
    require_explicit: bool = Field(
        default=False,
        description="Set for fields where a wrong guess is costly (dates, money, owners).",
    )
    sensitive: bool = Field(
        default=False, description="Redact from logs and from the provenance appendix"
    )
    #: Responsibility rests with a *named* party: a person, or a team with a
    #: name. What is refused is anything that names nobody — "me", "my scrum
    #: team", "the developer of iDocs" — because the artifact outlives the
    #: conversation, and none of those can be resolved back to anyone from it.
    requires_named_party: bool = Field(
        default=False,
        description="Person fields only: require a named individual or a named team.",
    )
    #: Keep exactly what was typed. Set where the wording itself is the record —
    #: a quoted commitment, a command to run, a legal form of words.
    preserve_verbatim: bool = Field(
        default=False,
        description="Exclude from the wording pass; store the text exactly as stated.",
    )
    #: A clock time with no zone is only unambiguous to the person who typed it.
    #: Everyone downstream — on-call in another region, the approver, the person
    #: reading the change calendar — has to guess, and "8AM to 11PM" is eight
    #: hours out between London and Bangalore.
    requires_timezone: bool = Field(
        default=False,
        description="Refuse a value that states a clock time without a timezone.",
    )
    #: Extra explanation for "what do you mean by this?", beyond `description`.
    #: `description` says what the field holds; this says how to decide it.
    help_text: str = Field(
        default="",
        description="How to work out the answer. Used when the participant asks for help.",
    )
    #: Who to put an unanswerable question about this field to. References an
    #: :class:`EscalationRoute` id on the form.
    route: str | None = Field(
        default=None,
        description="Escalation route id for questions this field attracts.",
    )

    @field_validator("id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        import re

        if not re.match(_ID_PATTERN, v):
            raise ValueError(f"field id '{v}' must be lowercase snake_case")
        return v

    @model_validator(mode="after")
    def _validate_options(self) -> FormField:
        if self.type in (FieldType.ENUM, FieldType.MULTI_ENUM) and not self.options:
            raise ValueError(f"field '{self.id}' is an enum type but declares no options")
        return self

    @property
    def is_mandatory(self) -> bool:
        return self.importance is Importance.MANDATORY

    def prompt_descriptor(self) -> str:
        """A compact description handed to the extractor and the question planner."""
        parts = [f"{self.label} ({self.type.value})"]
        if self.description:
            parts.append(self.description)
        if self.options:
            parts.append(f"One of: {', '.join(self.options)}.")
        if self.aliases:
            parts.append(f"Also called: {', '.join(self.aliases)}.")
        if self.unit:
            parts.append(f"Unit: {self.unit}.")
        if self.examples:
            parts.append(f"Examples: {'; '.join(str(e) for e in self.examples[:3])}.")
        return " ".join(parts)


class FormSection(BaseModel):
    """A group of fields as the author thinks of them.

    Sections are the author's grouping, and they still shape the document and
    the order the conversation broadly moves in. They are no longer the unit the
    conversation asks in: :mod:`sa_forms.topics` computes that from how the
    fields actually relate to each other, which regularly crosses a section
    boundary. Two fields an author filed apart — the change owner under
    "overview" and the reviewer under "sign-off" — are one question to the
    person answering.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    description: str = ""
    #: Opening line for this topic. When absent the engine generates one.
    opening_prompt: str = ""
    fields: list[FormField] = Field(min_length=1)
    order: int = 0
    #: Explanation covering the whole section, for "what is this part about?".
    help_text: str = ""
    #: Default escalation route for questions about anything in this section.
    route: str | None = None

    @field_validator("id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        import re

        if not re.match(_ID_PATTERN, v):
            raise ValueError(f"section id '{v}' must be lowercase snake_case")
        return v


# ---------------------------------------------------------------------------
# Form definition
# ---------------------------------------------------------------------------


class FormStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


class FormKind(str, Enum):
    """What a form is for, which decides what "finished" means.

    ``INTAKE`` — the usual thing: fields to gather. Agreements may hang off it
    as terms the gathering happens under.

    ``AGREEMENT`` — the agreements *are* the form. A policy acknowledgement, a
    terms-of-use acceptance, a joiner's declarations pack. It may carry a field
    or two for identification, and it may carry none at all; what makes it
    complete is that every required agreement has been decided, not that a
    field count has been reached.

    The distinction is not cosmetic. A form with no fields is complete the
    moment it starts under intake rules, which is the wrong answer for a
    document whose entire content is what somebody agreed to — and the two need
    different conversations: terms grouped as a preamble in one case, put one at
    a time in the other, because in an agreement form each one is the work
    rather than the throat-clearing before it.
    """

    INTAKE = "intake"
    AGREEMENT = "agreement"


class ApprovalPolicy(BaseModel):
    """How a completed submission becomes a baseline."""

    model_config = ConfigDict(extra="forbid")

    required_approvals: int = Field(default=1, ge=0)
    approver_roles: list[str] = Field(default_factory=list)
    #: Anyone who contributed answers may not also approve them.
    allow_self_approval: bool = False
    #: Re-open for edits after rejection rather than terminating the session.
    reopen_on_rejection: bool = True


class ConsistencySeverity(str, Enum):
    """How much a contradiction matters.

    ``BLOCKING`` stops the artifact until it is resolved or the participant
    explicitly stands by it. ``WARNING`` is raised once and travels onto the
    document with whatever the participant said about it. ``INFO`` is noted and
    never interrupts.
    """

    INFO = "info"
    WARNING = "warning"
    BLOCKING = "blocking"

    @property
    def blocks(self) -> bool:
        return self is ConsistencySeverity.BLOCKING


class ConsistencyRule(BaseModel):
    """One cross-field check, authored as data alongside the fields it relates.

    Individually valid answers can still contradict each other — a change with
    no customer impact that takes the platform down for six hours, a reviewer
    who is also the owner. Field-level validation cannot see any of that,
    because it only ever looks at one value.

    ``when`` is true when something is **wrong**. Deterministic rules carry no
    false positives, which is why they are worth authoring even though the
    semantic reviewer covers more ground.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Stable snake_case identifier, unique within the form")
    when: str = Field(description="Expression over the consistency scope. True means inconsistent.")
    message: str = Field(description="What looks wrong, addressed to the participant")
    question: str = Field(
        default="",
        description="What to ask about it. The message is used when this is blank.",
    )
    fields: list[str] = Field(
        default_factory=list,
        description="Fields involved. Used to target the question and to detect "
        "when the participant has answered by changing one of them.",
    )
    severity: ConsistencySeverity = ConsistencySeverity.WARNING

    @field_validator("id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        import re

        if not re.match(_ID_PATTERN, v):
            raise ValueError(f"consistency rule id '{v}' must be lowercase snake_case")
        return v


class FindingState(str, Enum):
    OPEN = "open"
    #: Put to the participant, awaiting their response.
    RAISED = "raised"
    #: They stand by it and said why. The reason goes on the document.
    ACKNOWLEDGED = "acknowledged"
    #: No longer true — they changed an answer.
    RESOLVED = "resolved"


class ConsistencyFinding(BaseModel):
    """One contradiction found in a session, and what became of it."""

    model_config = ConfigDict(extra="forbid")

    id: str
    message: str
    question: str = ""
    fields: list[str] = Field(default_factory=list)
    severity: ConsistencySeverity = ConsistencySeverity.WARNING
    #: `rule` for a deterministic check, `model` for the semantic review.
    source: str = "rule"
    #: Verbatim support from the conversation. Required of the semantic pass, so
    #: a finding can always be traced back to something actually said.
    evidence: str = ""
    state: FindingState = FindingState.OPEN
    #: How many times this has been put to the participant. Bounded, so an
    #: unanswered discrepancy is followed up once and then recorded as
    #: unexplained rather than asked forever.
    times_raised: int = 0
    #: What the participant said about *this* finding, when it was put to them.
    resolution: str = ""
    raised_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    @property
    def is_outstanding(self) -> bool:
        return self.state in (FindingState.OPEN, FindingState.RAISED)


# ---------------------------------------------------------------------------
# Agreements
# ---------------------------------------------------------------------------


class AgreementKind(str, Enum):
    """Whose statement it is.

    The distinction is not decorative: it decides who is bound by what, and an
    auditor reading the record needs to see which is which.

    ``SYSTEM`` — the platform's terms. How the conversation works, what is
    recorded, what happens to the text afterwards. The participant is agreeing
    to *our* statement.

    ``USER`` — a declaration the participant makes about themselves. "I am
    authorised to raise this." Nobody but them can make it.

    ``CONFIRMATION`` — a statement about *this* submission, made once it exists.
    "Everything above is accurate." It is worthless taken before the answers,
    which is why stage and kind are separate.
    """

    SYSTEM = "system"
    USER = "user"
    CONFIRMATION = "confirmation"


class AgreementStage(str, Enum):
    """When the agreement is put to the participant.

    ``BEFORE_START`` gates the first question, ``BEFORE_REVIEW`` gates the
    submission being called finished, ``BEFORE_GENERATE`` gates the document.
    """

    BEFORE_START = "before_start"
    BEFORE_REVIEW = "before_review"
    BEFORE_GENERATE = "before_generate"


class AgreementFaq(BaseModel):
    """A question this agreement reliably provokes, and its answer.

    Authored beside the clause it is about, because that is where the person
    who wrote the clause knows the answer. Matched deterministically against
    what the participant asked, so the common questions are answered instantly,
    identically every time, and without a model — which is what "some basic
    questions" has to mean if the answer is going to be trustworthy.
    """

    model_config = ConfigDict(extra="forbid")

    question: str = Field(description="How people actually ask it")
    answer: str = Field(description="The answer, in the participant's terms")
    #: Other ways the same question gets asked. Matching is on words, so these
    #: matter as much as the question itself.
    aliases: list[str] = Field(default_factory=list)


class Agreement(BaseModel):
    """Something the participant must accept before the flow continues.

    The ``text`` is the record. It is presented verbatim, stored verbatim, and
    hashed — an agreement whose wording is paraphrased on the way to the
    participant is not an agreement, and one whose stored wording can drift from
    what was shown proves nothing later.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Stable snake_case identifier, unique within the form")
    title: str
    text: str = Field(description="The exact words shown to the participant and recorded")
    kind: AgreementKind = AgreementKind.SYSTEM
    stage: AgreementStage = AgreementStage.BEFORE_START
    #: A required agreement blocks. An optional one is offered and recorded
    #: either way — a marketing opt-in, an invitation to be named on the record.
    required: bool = True
    #: Bumped when the wording changes. A session that accepted 1.0.0 has
    #: accepted 1.0.0, and re-asking is the *only* honest way to get 2.0.0.
    version: str = "1.0.0"
    #: How to ask for acceptance. Generated when blank.
    prompt: str = ""
    #: What to say if they decline. The route below is offered alongside it.
    on_decline: str = ""
    #: What this clause means, in plainer words than the clause itself. The
    #: first thing offered when someone asks — and the reason "what does this
    #: mean?" does not have to become a ticket. It never replaces `text`: the
    #: clause is what they accept, this is what helps them decide.
    explanation: str = ""
    #: The questions this clause reliably provokes, answered by whoever wrote it.
    faqs: list[AgreementFaq] = Field(default_factory=list)
    #: Who answers questions about this agreement, and who hears about a refusal.
    route: str | None = None
    #: Only put this agreement when the expression is true.
    ask_when: str | None = None

    @field_validator("id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        import re

        if not re.match(_ID_PATTERN, v):
            raise ValueError(f"agreement id '{v}' must be lowercase snake_case")
        return v


class AgreementDecision(str, Enum):
    ACCEPTED = "accepted"
    DECLINED = "declined"


class AgreementRecord(BaseModel):
    """One decision on one agreement, as it will be read back years later.

    Both the text and its hash are stored. The text so the record is legible
    without the form definition it came from; the hash so a definition edited
    after the fact cannot quietly change what somebody agreed to.
    """

    model_config = ConfigDict(extra="forbid")

    agreement_id: str
    version: str
    decision: AgreementDecision
    actor: str
    #: Verbatim text as presented.
    text: str = ""
    #: SHA-256 of that text.
    text_hash: str = ""
    #: What the participant actually typed to accept or decline it.
    stated: str = ""
    decided_at: float = Field(default_factory=time.time)

    @property
    def accepted(self) -> bool:
        return self.decision is AgreementDecision.ACCEPTED


# ---------------------------------------------------------------------------
# Help: reference material, and who to ask when it runs out
# ---------------------------------------------------------------------------


class KnowledgeNote(BaseModel):
    """Reference material the assistant may answer questions from.

    This is what makes "answer it properly" different from "make something up
    that sounds like policy". A question the notes cannot support is escalated
    rather than answered — a confident wrong answer about which approval path
    applies is worse than "let me find out".
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str = ""
    text: str
    #: Field or section ids this note bears on. Empty means the whole form.
    applies_to: list[str] = Field(default_factory=list)
    #: Where it came from — a policy document, a wiki page. Cited when used.
    source: str = ""

    @field_validator("id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        import re

        if not re.match(_ID_PATTERN, v):
            raise ValueError(f"knowledge note id '{v}' must be lowercase snake_case")
        return v


class EscalationRoute(BaseModel):
    """A team that answers what the form cannot.

    Every form needs one. A participant blocked on a question nobody in the
    conversation can answer will otherwise either guess — which puts a wrong
    value on an approved record — or abandon the form, and neither outcome is
    visible to anyone afterwards.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    team: str = Field(description="The team as people refer to it")
    contact: str = Field(default="", description="Email, channel, or queue")
    channel: str = Field(default="email", description="email | chat | ticket | phone")
    #: Field or section ids this route covers. Empty makes it the form default.
    covers: list[str] = Field(default_factory=list)
    #: What this team is for, in the participant's terms.
    note: str = ""
    #: What to promise about the response — "one business day".
    sla: str = ""

    @field_validator("id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        import re

        if not re.match(_ID_PATTERN, v):
            raise ValueError(f"escalation route id '{v}' must be lowercase snake_case")
        return v


class SupportStatus(str, Enum):
    ANSWERED = "answered"  # settled inside the conversation
    ROUTED = "routed"  # handed to a team; awaiting them
    CLOSED = "closed"  # the team came back, or it stopped mattering


class SupportRequest(BaseModel):
    """A question the participant asked, and what became of it.

    Recorded whether or not it was answered. The questions a form provokes are
    the cheapest available evidence of where its wording is wrong, and they are
    invisible today because they happen in a chat window nobody reads back.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: f"sq_{uuid.uuid4().hex[:10]}")
    question: str
    asked_by: str = "unknown"
    #: Fields the question was about, as far as could be told.
    fields: list[str] = Field(default_factory=list)
    #: How far up the ladder it got: definition | grounded | routed.
    tier: str = "definition"
    answer: str = ""
    #: Set when the answer came from knowledge notes, so it can be traced.
    sources: list[str] = Field(default_factory=list)
    status: SupportStatus = SupportStatus.ANSWERED
    route_id: str | None = None
    team: str = ""
    contact: str = ""
    channel: str = ""
    resolution: str = ""
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    @property
    def is_open(self) -> bool:
        return self.status is SupportStatus.ROUTED


class FormDefinition(BaseModel):
    """A versioned, self-describing form.

    This is the whole contract: the conversation, the extraction schema, the
    rendered artifact, and the approval rules are all derived from it.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Stable snake_case identifier, e.g. 'change_request'")
    version: str = Field(default="1.0.0")
    title: str = Field(description="Human-readable form name")
    description: str = ""
    status: FormStatus = FormStatus.DRAFT
    kind: FormKind = FormKind.INTAKE
    owner: str | None = None
    tags: list[str] = Field(default_factory=list)

    #: Required for an intake form and optional for an agreement one, which may
    #: legitimately ask for nothing at all beyond the decisions themselves.
    sections: list[FormSection] = Field(default_factory=list)

    #: Prepended to every conversation. Domain framing, tone, house rules.
    guidance: str = Field(
        default="",
        description="Context the assistant should hold while gathering this form.",
    )
    #: Formats offered when the submission is rendered.
    output_formats: list[str] = Field(default_factory=lambda: ["xlsx", "pdf", "markdown"])
    approval: ApprovalPolicy = Field(default_factory=ApprovalPolicy)
    #: Extract follow-up tasks from the conversation when it completes.
    collect_action_items: bool = True

    #: Tidy the wording of free-text answers before the document is produced.
    #: What people type into a chat box is not what belongs in a record an
    #: approver reads — "8AM ro 11PM" and "from the serivces start log for any
    #: issues" are answers, but they are not writing. The original text is kept
    #: on every answer regardless, so the record stays faithful.
    normalise_wording: bool = True

    #: Terms, declarations, and confirmations gathered as part of the flow.
    #: Gathering consent conversationally is the point: a checkbox on a screen
    #: nobody read is the thing this replaces.
    agreements: list[Agreement] = Field(default_factory=list)
    #: Teams that answer questions this form provokes. The first with no
    #: `covers` entries is the form's default route.
    escalation: list[EscalationRoute] = Field(default_factory=list)
    #: Material the assistant may answer questions from. Nothing outside it is
    #: invented — an unsupported question is escalated instead.
    knowledge: list[KnowledgeNote] = Field(default_factory=list)

    #: Group the conversation by how fields relate to each other rather than by
    #: the section they were authored in. Off falls back to section-at-a-time.
    group_by_affinity: bool = True

    #: Cross-field checks run before the submission is called complete.
    consistency_rules: list[ConsistencyRule] = Field(default_factory=list)
    #: Also have the model look for contradictions the rules cannot express —
    #: a downtime that does not fit its own maintenance window, a risk level at
    #: odds with the description. Off makes the check purely deterministic.
    semantic_consistency_review: bool = True

    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    created_by: str | None = None
    #: Set when the definition was inferred from an uploaded sample.
    derived_from: str | None = None
    change_note: str = ""

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        import re

        if not re.match(_ID_PATTERN, v):
            raise ValueError(f"form name '{v}' must be lowercase snake_case")
        return v

    @field_validator("version")
    @classmethod
    def _validate_version(cls, v: str) -> str:
        parts = v.split("-")[0].split(".")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            raise ValueError(f"version '{v}' must be MAJOR.MINOR.PATCH")
        return v

    @model_validator(mode="after")
    def _validate_kind(self) -> FormDefinition:
        """Each kind has to be able to do its job.

        An intake form with no fields asks nothing; an agreement form with no
        agreements records nothing. Both are almost certainly an authoring
        mistake, and both fail silently at the far end — one as a conversation
        that ends before it starts, the other as a document with nothing on it.
        """
        if self.kind is FormKind.INTAKE and not self.sections:
            raise ValueError(
                f"form '{self.name}' is an intake form and declares no sections; "
                "set `kind: agreement` for a form whose content is its agreements"
            )
        if self.kind is FormKind.AGREEMENT and not self.agreements:
            raise ValueError(f"form '{self.name}' is an agreement form and declares no agreements")
        return self

    @model_validator(mode="after")
    def _validate_unique_ids(self) -> FormDefinition:
        section_ids = [s.id for s in self.sections]
        if len(set(section_ids)) != len(section_ids):
            raise ValueError("section ids must be unique within a form")

        field_ids = [f.id for s in self.sections for f in s.fields]
        duplicates = {i for i in field_ids if field_ids.count(i) > 1}
        if duplicates:
            raise ValueError(f"duplicate field id(s): {', '.join(sorted(duplicates))}")

        known = set(field_ids)
        for field in self.fields():
            unknown = [r for r in field.related_fields if r not in known]
            if unknown:
                raise ValueError(
                    f"field '{field.id}' references unknown related field(s): {', '.join(unknown)}"
                )

        for collection, label in (
            ([a.id for a in self.agreements], "agreement"),
            ([r.id for r in self.escalation], "escalation route"),
            ([k.id for k in self.knowledge], "knowledge note"),
        ):
            duplicated = {i for i in collection if collection.count(i) > 1}
            if duplicated:
                raise ValueError(f"duplicate {label} id(s): {', '.join(sorted(duplicated))}")

        # A route id that points nowhere fails silently at exactly the wrong
        # moment: someone is stuck, asks for help, and the escalation lands in
        # the default queue instead of with the team who could answer it.
        routes = {r.id for r in self.escalation}
        referenced = [
            (owner, route)
            for owner, route in (
                *[(f"field '{f.id}'", f.route) for f in self.fields()],
                *[(f"section '{s.id}'", s.route) for s in self.sections],
                *[(f"agreement '{a.id}'", a.route) for a in self.agreements],
            )
            if route is not None
        ]
        missing = [f"{owner} → '{route}'" for owner, route in referenced if route not in routes]
        if missing:
            raise ValueError(f"unknown escalation route(s): {'; '.join(missing)}")
        return self

    # -- accessors --------------------------------------------------------
    @property
    def qualified_name(self) -> str:
        return f"{self.name}@{self.version}"

    def fields(self) -> list[FormField]:
        return [f for s in self.ordered_sections() for f in s.fields]

    def ordered_sections(self) -> list[FormSection]:
        return sorted(self.sections, key=lambda s: (s.order, s.id))

    def field(self, field_id: str) -> FormField:
        for candidate in self.fields():
            if candidate.id == field_id:
                return candidate
        raise KeyError(field_id)

    def try_field(self, field_id: str) -> FormField | None:
        try:
            return self.field(field_id)
        except KeyError:
            return None

    def section_of(self, field_id: str) -> FormSection:
        for section in self.sections:
            if any(f.id == field_id for f in section.fields):
                return section
        raise KeyError(field_id)

    def mandatory_fields(self) -> list[FormField]:
        return [f for f in self.fields() if f.is_mandatory]

    def field_count(self) -> int:
        return len(self.fields())

    @property
    def is_agreement_form(self) -> bool:
        return self.kind is FormKind.AGREEMENT

    def required_agreements(self) -> list[Agreement]:
        return [a for a in self.agreements if a.required]

    def try_agreement(self, agreement_id: str) -> Agreement | None:
        for agreement in self.agreements:
            if agreement.id == agreement_id:
                return agreement
        return None

    def route(self, route_id: str) -> EscalationRoute | None:
        for candidate in self.escalation:
            if candidate.id == route_id:
                return candidate
        return None

    def default_route(self) -> EscalationRoute | None:
        """The route for a question no field or section claims.

        The first route declaring no `covers` list, falling back to the first
        declared at all — a form with one team named has named its default,
        whether or not the author thought of it that way.
        """
        for candidate in self.escalation:
            if not candidate.covers:
                return candidate
        return self.escalation[0] if self.escalation else None


# ---------------------------------------------------------------------------
# Provenance and answers
# ---------------------------------------------------------------------------


class SourceChannel(str, Enum):
    CHAT = "chat"
    JIRA = "jira"
    EMAIL = "email"
    #: An uploaded .eml file. Distinct from EMAIL because the adapter differs —
    #: the messages it produces are still tagged EMAIL or DOCUMENT.
    EMAIL_FILE = "email_file"
    MEETING = "meeting"
    DOCUMENT = "document"
    FORM_UI = "form_ui"
    IMPORT = "import"
    SYSTEM = "system"


class SourceMessage(BaseModel):
    """One normalised inbound message, whatever channel it came from.

    Chat turns, JIRA comments, email bodies, and meeting transcript segments
    all reduce to this, which is why one extraction pipeline serves all of them.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    channel: SourceChannel = SourceChannel.CHAT
    author: str = "unknown"
    author_role: str | None = None
    text: str = ""
    timestamp: float = Field(default_factory=time.time)
    external_id: str | None = Field(
        default=None, description="e.g. JIRA comment id, email Message-ID"
    )
    external_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def excerpt(self, limit: int = 200) -> str:
        collapsed = " ".join(self.text.split())
        return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


class Provenance(BaseModel):
    """Where an answer came from. This is what makes the artifact auditable."""

    model_config = ConfigDict(extra="forbid")

    channel: SourceChannel = SourceChannel.CHAT
    author: str = "unknown"
    message_id: str | None = None
    external_url: str | None = None
    #: Verbatim supporting text. Redacted for sensitive fields.
    evidence: str = ""
    extracted_at: float = Field(default_factory=time.time)
    method: str = Field(default="llm", description="llm | pattern | user_confirmed | imported")


class FieldAnswer(BaseModel):
    """The current answer for one field, plus how we came to believe it."""

    model_config = ConfigDict(extra="forbid")

    field_id: str
    value: Any = None
    raw_value: str | None = Field(default=None, description="Pre-coercion text as stated")
    state: AnswerState = AnswerState.EMPTY
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    provenance: Provenance | None = None
    #: Superseded answers, newest last. Corrections never destroy history.
    history: list[dict[str, Any]] = Field(default_factory=list)
    note: str = ""
    #: The wording pass rewrote this value. `raw_value` still holds what was
    #: typed, so the record stays faithful while the document reads properly.
    polished: bool = False
    updated_at: float = Field(default_factory=time.time)

    @property
    def is_settled(self) -> bool:
        return self.state.is_settled

    @property
    def needs_confirmation(self) -> bool:
        return self.state is AnswerState.PROPOSED

    def supersede_with(
        self,
        value: Any,
        *,
        raw_value: str | None,
        state: AnswerState,
        confidence: float,
        provenance: Provenance | None,
        note: str = "",
    ) -> None:
        """Replace the value, preserving the previous one in history."""
        if self.state is not AnswerState.EMPTY:
            self.history.append(
                {
                    "value": self.value,
                    "state": self.state.value,
                    "confidence": self.confidence,
                    "provenance": self.provenance.model_dump() if self.provenance else None,
                    "superseded_at": time.time(),
                }
            )
        self.value = value
        self.raw_value = raw_value
        self.state = state
        self.confidence = confidence
        self.provenance = provenance
        self.note = note
        # A new value has not been written up, whatever was true of the old one.
        # Leaving the flag set makes the record claim this text was polished
        # when it is raw — and a correction made late in the conversation is
        # exactly the text most likely to reach the document as typed.
        self.polished = False
        self.updated_at = time.time()


# ---------------------------------------------------------------------------
# Action items
# ---------------------------------------------------------------------------


class ActionItemStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


class ActionItem(BaseModel):
    """A follow-up task surfaced by the conversation.

    These come from two places: things the participants explicitly committed to,
    and gaps the form could not close (a mandatory field nobody could answer).
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: f"ai_{uuid.uuid4().hex[:10]}")
    description: str
    owner: str | None = None
    due_date: str | None = None
    status: ActionItemStatus = ActionItemStatus.OPEN
    source_field_id: str | None = None
    origin: str = Field(default="conversation", description="conversation | unresolved_field")
    evidence: str = ""
    created_at: float = Field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


class SessionStatus(str, Enum):
    COLLECTING = "collecting"
    READY_FOR_REVIEW = "ready_for_review"
    IN_REVIEW = "in_review"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    BASELINED = "baselined"
    ABANDONED = "abandoned"

    @property
    def is_editable(self) -> bool:
        return self in (
            SessionStatus.COLLECTING,
            SessionStatus.READY_FOR_REVIEW,
            SessionStatus.CHANGES_REQUESTED,
        )


class TranscriptEntry(BaseModel):
    """One line of the conversation record, inbound or outbound."""

    model_config = ConfigDict(extra="forbid")

    role: str = Field(description="user | assistant | system")
    text: str
    author: str = "unknown"
    channel: SourceChannel = SourceChannel.CHAT
    timestamp: float = Field(default_factory=time.time)
    #: Fields this turn was about, for debugging the question planner.
    targeted_fields: list[str] = Field(default_factory=list)
    #: Agreements this turn put to the participant. What makes the next message
    #: readable as a decision on them rather than as an answer to a question —
    #: and it survives a restart, unlike anything held in the engine.
    awaiting_agreements: list[str] = Field(default_factory=list)
    message_id: str | None = None


class FormSession(BaseModel):
    """An in-progress (or finished) attempt to fill one form.

    Fully serialisable: a session can be parked for a week, picked up on a
    different channel by a different person, and continue where it left off.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: f"fs_{uuid.uuid4().hex[:12]}")
    form_name: str
    form_version: str
    title: str = ""
    status: SessionStatus = SessionStatus.COLLECTING

    answers: dict[str, FieldAnswer] = Field(default_factory=dict)
    transcript: list[TranscriptEntry] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)

    participants: list[str] = Field(default_factory=list)
    tenant_id: str | None = None
    correlation_id: str | None = None

    #: Contradictions found across fields, and what the participant said about
    #: each. Carried on the session rather than recomputed at render time so an
    #: acknowledgement survives — the reason a "low risk, six-hour outage" is
    #: deliberate is exactly what the approver needs and would otherwise be lost.
    consistency_findings: list[ConsistencyFinding] = Field(default_factory=list)

    #: Every agreement decision taken in this session, accepted or declined.
    agreements: list[AgreementRecord] = Field(default_factory=list)
    #: Questions the participant asked, and what became of each.
    support_requests: list[SupportRequest] = Field(default_factory=list)

    #: Fields the user explicitly declined; never asked again.
    skipped_fields: list[str] = Field(default_factory=list)
    #: How many times each field has been put to the participant. Asking a third
    #: time in three different phrasings is not persistence, it is not listening.
    ask_counts: dict[str, int] = Field(default_factory=dict)
    #: How many times the participant has asked for help on each field. A second
    #: ask means the first answer did not land, and repeating it more slowly is
    #: not a strategy — this is what drives the escalation ladder.
    help_counts: dict[str, int] = Field(default_factory=dict)
    #: Topic ids already opened, most recent last. Used to keep the conversation
    #: moving forward rather than circling a group it has already covered.
    topics_opened: list[str] = Field(default_factory=list)
    #: Set once the mandatory set closes, so we only announce completion once.
    mandatory_complete_announced: bool = False

    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    created_by: str | None = None
    artifacts: list[str] = Field(default_factory=list, description="ArtifactRecord ids")
    metadata: dict[str, Any] = Field(default_factory=dict)

    # -- answers ----------------------------------------------------------
    def answer_for(self, field_id: str) -> FieldAnswer:
        """Return the answer slot, creating an empty one on first access."""
        existing = self.answers.get(field_id)
        if existing is None:
            existing = FieldAnswer(field_id=field_id)
            self.answers[field_id] = existing
        return existing

    def settled_values(self) -> dict[str, Any]:
        """Accepted answers only — what the artifact renders from."""
        return {
            fid: answer.value
            for fid, answer in self.answers.items()
            if answer.is_settled and answer.value is not None
        }

    def all_values(self) -> dict[str, Any]:
        """Every value including unconfirmed proposals, for expression evaluation."""
        return {fid: a.value for fid, a in self.answers.items() if a.value is not None}

    @computed_field  # type: ignore[prop-decorator]
    @property
    def editable(self) -> bool:
        """Whether this session still accepts input.

        Serialised deliberately. The console used to re-derive it as
        ``status === "collecting"``, which disabled every control — including
        the Generate button — the moment the mandatory set closed and the
        engine moved the session to ``ready_for_review`` while saying "say
        'generate' when you're ready". Backend and UI disagreed about the same
        state and the user was left with an invitation they could not accept.
        One source of truth, on the object that owns the state.
        """
        return self.status.is_editable

    # -- asking -----------------------------------------------------------
    def note_asked(self, field_ids: list[str]) -> None:
        for field_id in field_ids:
            self.ask_counts[field_id] = self.ask_counts.get(field_id, 0) + 1

    def note_help_asked(self, field_ids: list[str]) -> int:
        """Count a request for help, and return how deep this one is.

        One is the first time they asked about these fields; two is the time
        after the first answer failed to land. The number, not a guess about
        tone, is what decides whether to explain harder or fetch a human.
        """
        depth = 1
        for field_id in field_ids or ["_general"]:
            self.help_counts[field_id] = self.help_counts.get(field_id, 0) + 1
            depth = max(depth, self.help_counts[field_id])
        return depth

    def agreement_record(self, agreement_id: str, version: str) -> AgreementRecord | None:
        """The decision on this exact version, if one was taken.

        Version-specific on purpose. A session that accepted v1 of a term has
        not accepted v2, and treating the two as the same acceptance is how a
        record ends up attesting to words nobody read.
        """
        for record in reversed(self.agreements):
            if record.agreement_id == agreement_id and record.version == version:
                return record
        return None

    def open_support_requests(self) -> list[SupportRequest]:
        return [r for r in self.support_requests if r.is_open]

    def stalled_fields(self, threshold: int = 2) -> set[str]:
        """Fields asked repeatedly that still have no settled answer.

        They stop driving topic selection, so one field nobody wants to answer
        cannot hold the whole conversation hostage. Nothing is dropped: an
        unanswered mandatory field still blocks completion and still becomes an
        action item.
        """
        stalled: set[str] = set()
        for field_id, count in self.ask_counts.items():
            if count < threshold:
                continue
            answer = self.answers.get(field_id)
            if answer is None or not answer.is_settled:
                stalled.add(field_id)
        return stalled

    # -- transcript -------------------------------------------------------
    def record(self, entry: TranscriptEntry) -> None:
        self.transcript.append(entry)
        if entry.role == "user" and entry.author not in self.participants:
            self.participants.append(entry.author)
        self.updated_at = time.time()

    def recent_transcript(self, limit: int = 12) -> list[TranscriptEntry]:
        return self.transcript[-limit:]

    def touch(self) -> None:
        self.updated_at = time.time()


# ---------------------------------------------------------------------------
# Artifacts and approval
# ---------------------------------------------------------------------------


class ArtifactStatus(str, Enum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    BASELINED = "baselined"
    SUPERSEDED = "superseded"


class Approval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approver: str
    decision: str = Field(description="approved | rejected")
    comment: str = ""
    decided_at: float = Field(default_factory=time.time)


class ArtifactRecord(BaseModel):
    """A rendered document produced from a session."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: f"art_{uuid.uuid4().hex[:12]}")
    session_id: str
    form_name: str
    form_version: str
    format: str = Field(description="xlsx | pdf | docx | markdown | json | csv")
    filename: str = ""
    location: str = Field(default="", description="Path or URI in the artifact store")
    size_bytes: int = 0
    #: SHA-256 of the bytes. A baseline whose checksum no longer matches has
    #: been tampered with.
    checksum: str = ""
    status: ArtifactStatus = ArtifactStatus.DRAFT
    approvals: list[Approval] = Field(default_factory=list)
    revision: int = Field(default=1, ge=1)
    baselined_at: float | None = None
    created_at: float = Field(default_factory=time.time)
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_baselined(self) -> bool:
        return self.status is ArtifactStatus.BASELINED

    def approval_count(self) -> int:
        return sum(1 for a in self.approvals if a.decision == "approved")


__all__ = [
    "ActionItem",
    "ActionItemStatus",
    "Agreement",
    "AgreementDecision",
    "AgreementFaq",
    "AgreementKind",
    "AgreementRecord",
    "AgreementStage",
    "AnswerState",
    "Approval",
    "ApprovalPolicy",
    "ArtifactRecord",
    "ArtifactStatus",
    "EscalationRoute",
    "FieldAnswer",
    "FieldType",
    "FieldValidation",
    "FormDefinition",
    "FormField",
    "FormKind",
    "FormSection",
    "FormSession",
    "FormStatus",
    "Importance",
    "KnowledgeNote",
    "Provenance",
    "SessionStatus",
    "SourceChannel",
    "SourceMessage",
    "SupportRequest",
    "SupportStatus",
    "TranscriptEntry",
]
