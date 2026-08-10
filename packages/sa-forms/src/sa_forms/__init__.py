"""sa-forms — conversational form intake.

Replaces manual form filling and the email/ticket back-and-forth around it with
one resumable conversation that can also mine existing threads.

The flow::

    forms_service.start_session("change_request", participant="alice")
    forms_service.ingest(sid, "jira", jira_payload)   # mine what already exists
    forms_service.send(sid, "we're targeting 15 March, Priya owns it")
    forms_service.generate(sid, ["xlsx", "pdf"])      # render for review
    forms_service.approve(artifact_id, approver="bob")  # -> baselined

What makes it generic rather than per-form:

* **Questions are computed, not written.** Gap analysis reads the definition and
  the session; the model only phrases the result. A new field changes the
  conversation with no code change.
* **One extraction pipeline, many channels.** Chat, JIRA, email, and meeting
  transcripts all normalise to :class:`SourceMessage`.
* **Forms are data.** Upload the spreadsheet you fill in today and
  :class:`FormAuthor` infers the definition, including the "why do you need
  this?" rationale for each field.
* **Everything is versioned.** New sessions always bind to the latest *active*
  form version; in-flight sessions keep the version they started on.
"""

from __future__ import annotations

from .actions import derive_action_items, open_items
from .approval import ApprovalService, FormsEvents
from .authoring import ColumnProfile, FormAuthor, InferenceReport, read_tabular
from .coercion import CoercionError, coerce_and_validate, render_value
from .completeness import Completeness, analyse, next_topic, progress_line
from .conversation import ConversationEngine, Intent, TurnResult
from .extraction import Extraction, ExtractionEngine, ExtractionResult
from .ingestion import (
    ChatSource,
    ConversationSource,
    EmailThreadSource,
    JiraCommentSource,
    MeetingTranscriptSource,
    parse_payload,
)
from .models import (
    ActionItem,
    AnswerState,
    ArtifactRecord,
    ArtifactStatus,
    FieldAnswer,
    FieldType,
    FormDefinition,
    FormField,
    FormSection,
    FormSession,
    FormStatus,
    Importance,
    Provenance,
    SessionStatus,
    SourceChannel,
    SourceMessage,
)
from .registry import FormRegistry, form_registry
from .rendering import available_formats, render_session
from .service import FormsService, forms_service
from .store import (
    ArtifactStore,
    FileArtifactStore,
    FileSessionStore,
    InMemoryArtifactStore,
    InMemorySessionStore,
    SessionStore,
)
from .tools import register_form_tools

__version__ = "0.1.0"

__all__ = [
    "ActionItem",
    "AnswerState",
    "ApprovalService",
    "ArtifactRecord",
    "ArtifactStatus",
    "ArtifactStore",
    "ChatSource",
    "CoercionError",
    "ColumnProfile",
    "Completeness",
    "ConversationEngine",
    "ConversationSource",
    "EmailThreadSource",
    "Extraction",
    "ExtractionEngine",
    "ExtractionResult",
    "FieldAnswer",
    "FieldType",
    "FileArtifactStore",
    "FileSessionStore",
    "FormAuthor",
    "FormDefinition",
    "FormField",
    "FormRegistry",
    "FormSection",
    "FormSession",
    "FormStatus",
    "FormsEvents",
    "FormsService",
    "Importance",
    "InMemoryArtifactStore",
    "InMemorySessionStore",
    "InferenceReport",
    "Intent",
    "JiraCommentSource",
    "MeetingTranscriptSource",
    "Provenance",
    "SessionStatus",
    "SessionStore",
    "SourceChannel",
    "SourceMessage",
    "TurnResult",
    "__version__",
    "analyse",
    "available_formats",
    "coerce_and_validate",
    "derive_action_items",
    "form_registry",
    "forms_service",
    "next_topic",
    "open_items",
    "parse_payload",
    "progress_line",
    "read_tabular",
    "register_form_tools",
    "render_session",
    "render_value",
]
