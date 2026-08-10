"""Ingestion adapters.

Every channel reduces to a list of :class:`SourceMessage`, so one extraction
pipeline serves chat, JIRA, email, and meeting transcripts. Adding a channel
means writing a parser here — nothing downstream changes.

The parsing is the interesting part. Real ticket comments and email threads are
full of noise that actively harms extraction: quoted replies restating the
question, signature blocks, legal disclaimers, "On Tue, X wrote:" chains. Left
in, a model re-extracts stale values from quoted text and overwrites current
answers with old ones. These adapters strip that before it reaches the model.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any

from sa_platform.logging import get_logger

from .models import SourceChannel, SourceMessage

logger = get_logger(__name__)

# Everything from here down in an email body is quoted history or boilerplate.
_QUOTE_MARKERS = (
    re.compile(r"^\s*on .{0,120}\bwrote:\s*$", re.I | re.M),
    re.compile(r"^\s*-{2,}\s*original message\s*-{2,}\s*$", re.I | re.M),
    re.compile(r"^\s*_{5,}\s*$", re.M),
    re.compile(r"^\s*from:\s*.+\s*$", re.I | re.M),
    re.compile(r"^\s*>{1,}", re.M),
)

_SIGNATURE_MARKERS = (
    re.compile(r"^\s*--\s*$", re.M),
    re.compile(
        r"^\s*(best regards|kind regards|regards|thanks|thank you|cheers|sincerely)[,.]?\s*$",
        re.I | re.M,
    ),
    re.compile(r"^\s*sent from my \w+", re.I | re.M),
    re.compile(r"^\s*(this (e-?mail|message) (and any|is) .{0,80}confidential)", re.I | re.M),
)

# JIRA renders as wiki markup or ADF; strip the markup so the model reads prose.
_JIRA_NOISE = (
    (re.compile(r"\{code(:[^}]*)?\}.*?\{code\}", re.S), " [code block] "),
    (re.compile(r"\{quote\}.*?\{quote\}", re.S), " "),
    (re.compile(r"\{noformat\}.*?\{noformat\}", re.S), " "),
    (re.compile(r"!\S+?\|?[^!]*?!"), " [attachment] "),
    (re.compile(r"\[~accountid:[^\]]+\]"), "@user"),
    (re.compile(r"\[([^|\]]+)\|[^\]]+\]"), r"\1"),
    (re.compile(r"[*_+^~-]{2,}"), " "),
)

_BOT_AUTHORS = frozenset(
    {"jira", "automation for jira", "bot", "github", "jenkins", "bamboo", "webhook", "system"}
)


class ConversationSource(ABC):
    """Turns a channel's payload into normalised messages."""

    channel: SourceChannel = SourceChannel.CHAT

    @abstractmethod
    def parse(self, payload: Any) -> list[SourceMessage]:
        """Convert a raw payload into messages, newest last."""

    @staticmethod
    def _is_noise(text: str, author: str) -> bool:
        """Filter messages that cost tokens and contribute nothing."""
        stripped = text.strip()
        if len(stripped) < 3:
            return True
        if author.lower() in _BOT_AUTHORS:
            return True
        # Pure status transitions: "Status changed from To Do to In Progress".
        if re.fullmatch(r"(?i)\s*status changed .{0,80}", stripped):
            return True
        return False


class ChatSource(ConversationSource):
    """Direct chat turns. The trivial case, included for uniformity."""

    channel = SourceChannel.CHAT

    def parse(self, payload: Any) -> list[SourceMessage]:
        if isinstance(payload, str):
            return [SourceMessage(text=payload, channel=self.channel)]
        if isinstance(payload, dict):
            return [
                SourceMessage(
                    text=str(payload.get("text", "")),
                    author=str(payload.get("author", "user")),
                    channel=self.channel,
                    metadata={k: v for k, v in payload.items() if k not in ("text", "author")},
                )
            ]
        if isinstance(payload, list):
            messages: list[SourceMessage] = []
            for entry in payload:
                messages.extend(self.parse(entry))
            return messages
        raise TypeError(f"ChatSource cannot parse {type(payload).__name__}")


class JiraCommentSource(ConversationSource):
    """JIRA issue comments (and the description) as a conversation.

    Accepts the shape returned by ``GET /rest/api/3/issue/{key}?fields=comment``
    as well as a simplified list. The issue description is included as the first
    message because it usually carries the most form-relevant content.
    """

    channel = SourceChannel.JIRA

    def __init__(self, base_url: str | None = None, *, include_description: bool = True) -> None:
        self._base_url = (base_url or "").rstrip("/")
        self._include_description = include_description

    def parse(self, payload: Any) -> list[SourceMessage]:
        if not isinstance(payload, dict):
            if isinstance(payload, list):
                return self._parse_comments(payload, issue_key=None)
            raise TypeError(f"JiraCommentSource cannot parse {type(payload).__name__}")

        issue_key = payload.get("key")
        fields = payload.get("fields", payload)
        messages: list[SourceMessage] = []

        if self._include_description:
            description = self._flatten(fields.get("description"))
            if description.strip():
                reporter = self._author_name(fields.get("reporter"))
                messages.append(
                    SourceMessage(
                        channel=self.channel,
                        author=reporter,
                        text=self._clean(description),
                        external_id=f"{issue_key}:description" if issue_key else None,
                        external_url=self._issue_url(issue_key),
                        metadata={"issue_key": issue_key, "part": "description"},
                    )
                )

        raw_comments = fields.get("comment", {})
        comments = (
            raw_comments.get("comments", []) if isinstance(raw_comments, dict) else raw_comments
        )
        messages.extend(self._parse_comments(comments or [], issue_key=issue_key))
        return messages

    def _parse_comments(self, comments: list[Any], *, issue_key: str | None) -> list[SourceMessage]:
        messages: list[SourceMessage] = []
        for comment in comments:
            if not isinstance(comment, dict):
                continue
            body = self._clean(self._flatten(comment.get("body")))
            author = self._author_name(comment.get("author"))
            if self._is_noise(body, author):
                continue
            messages.append(
                SourceMessage(
                    channel=self.channel,
                    author=author,
                    text=body,
                    external_id=str(comment.get("id", "")) or None,
                    external_url=self._issue_url(issue_key),
                    timestamp=self._epoch(comment.get("created")),
                    metadata={"issue_key": issue_key},
                )
            )
        return messages

    def _issue_url(self, issue_key: str | None) -> str | None:
        if not (self._base_url and issue_key):
            return None
        return f"{self._base_url}/browse/{issue_key}"

    @staticmethod
    def _author_name(author: Any) -> str:
        if isinstance(author, dict):
            return str(author.get("displayName") or author.get("name") or "unknown")
        return str(author or "unknown")

    @classmethod
    def _flatten(cls, body: Any) -> str:
        """Flatten Atlassian Document Format into plain text.

        ADF is a nested node tree; only ``text`` leaves carry content. Walking
        it is simpler and far more robust than trying to render the markup.
        """
        if body is None:
            return ""
        if isinstance(body, str):
            return body
        if isinstance(body, list):
            return " ".join(cls._flatten(node) for node in body)
        if isinstance(body, dict):
            if "text" in body and isinstance(body["text"], str):
                return body["text"]
            content = body.get("content")
            flattened = cls._flatten(content) if content is not None else ""
            # Block-level nodes need a break or sentences run together.
            if body.get("type") in ("paragraph", "listItem", "heading", "blockquote"):
                return f"{flattened}\n"
            return flattened
        return str(body)

    @staticmethod
    def _clean(text: str) -> str:
        for pattern, replacement in _JIRA_NOISE:
            text = pattern.sub(replacement, text)
        return re.sub(r"\n{3,}", "\n\n", text).strip()

    @staticmethod
    def _epoch(value: Any) -> float:
        import time
        from datetime import datetime

        if not value:
            return time.time()
        try:
            # JIRA uses +0000 rather than +00:00.
            normalised = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", str(value))
            return datetime.fromisoformat(normalised).timestamp()
        except (ValueError, TypeError):
            return time.time()


class EmailThreadSource(ConversationSource):
    """Email messages, with quoted history and signatures stripped.

    Stripping quotes is not cosmetic. A reply that quotes the original question
    would otherwise let the extractor re-read superseded values and overwrite
    current answers with stale ones.
    """

    channel = SourceChannel.EMAIL

    def parse(self, payload: Any) -> list[SourceMessage]:
        entries = payload if isinstance(payload, list) else [payload]
        messages: list[SourceMessage] = []

        for entry in entries:
            if isinstance(entry, str):
                body, author, subject, message_id = entry, "unknown", "", None
            elif isinstance(entry, dict):
                body = str(entry.get("body") or entry.get("text") or "")
                author = str(entry.get("from") or entry.get("author") or "unknown")
                subject = str(entry.get("subject") or "")
                message_id = entry.get("message_id") or entry.get("id")
            else:
                continue

            cleaned = self.strip_quoted(body)
            cleaned = self.strip_signature(cleaned)
            if self._is_noise(cleaned, author):
                continue

            # The subject often carries the topic and sometimes a value; keep it
            # as a labelled line so the extractor can use it.
            text = f"Subject: {subject}\n\n{cleaned}" if subject else cleaned
            messages.append(
                SourceMessage(
                    channel=self.channel,
                    author=self._display_name(author),
                    text=text,
                    external_id=str(message_id) if message_id else None,
                    metadata={"subject": subject},
                )
            )
        return messages

    @staticmethod
    def strip_quoted(body: str) -> str:
        """Cut the body at the first quoted-history marker."""
        earliest = len(body)
        for pattern in _QUOTE_MARKERS:
            match = pattern.search(body)
            if match and match.start() < earliest:
                earliest = match.start()
        return body[:earliest].strip()

    #: A sign-off block is short. Anything longer than this after the marker is
    #: body text that happens to start with "Thanks", not a signature.
    MAX_SIGNATURE_CHARS = 400

    @staticmethod
    def strip_signature(body: str) -> str:
        earliest = len(body)
        for pattern in _SIGNATURE_MARKERS:
            match = pattern.search(body)
            # Judge by what follows, not by position as a fraction of length:
            # a two-line email has its sign-off near the top by that measure.
            if (
                match
                and match.start() < earliest
                and match.start() > 0
                and len(body) - match.start() <= EmailThreadSource.MAX_SIGNATURE_CHARS
            ):
                earliest = match.start()
        return body[:earliest].strip()

    @staticmethod
    def _display_name(address: str) -> str:
        match = re.match(r"\s*\"?([^\"<]+?)\"?\s*<", address)
        if match:
            return match.group(1).strip()
        return address.strip()


class EmailFileSource(ConversationSource):
    """An uploaded ``.eml`` file, including its attachments.

    Produces the mail body as one message and each readable attachment as
    another, so a spreadsheet of impacted systems attached to a change request
    is mined the same way the covering note is.

    Attachments that could not be read are still reported — as a message the
    extractor ignores but the user sees — because a form that silently omits
    what was in an unreadable attachment is worse than one that says so.
    """

    channel = SourceChannel.EMAIL_FILE

    def __init__(self, *, include_attachments: bool = True) -> None:
        self._include_attachments = include_attachments

    def parse(self, payload: Any) -> list[SourceMessage]:
        from .attachments import Attachment, ParsedEmail, extract_attachment, parse_email

        extra: list[Attachment] = []
        if isinstance(payload, ParsedEmail):
            parsed = payload
        elif isinstance(payload, (bytes, bytearray, str)):
            parsed = parse_email(bytes(payload) if not isinstance(payload, str) else payload)
        elif isinstance(payload, dict):
            parsed = parse_email(payload["raw"])
            # Attachments sent alongside the mail rather than inside it. Mail
            # clients drop attachments on forward far more often than users
            # expect, so uploading them separately has to work.
            for entry in payload.get("attachments") or []:
                extra.append(
                    extract_attachment(
                        str(entry.get("filename", "attachment")),
                        entry["content"],
                        content_type=str(entry.get("content_type", "")),
                    )
                )
        else:
            raise TypeError(f"EmailFileSource cannot parse {type(payload).__name__}")

        body = EmailThreadSource.strip_signature(EmailThreadSource.strip_quoted(parsed.body))
        messages: list[SourceMessage] = []
        author = EmailThreadSource._display_name(parsed.sender) or "unknown"

        if body.strip():
            text = f"Subject: {parsed.subject}\n\n{body}" if parsed.subject else body
            messages.append(
                SourceMessage(
                    channel=SourceChannel.EMAIL,
                    author=author,
                    text=text,
                    external_id=parsed.message_id,
                    metadata={
                        "subject": parsed.subject,
                        "date": parsed.date,
                        "recipients": parsed.recipients,
                    },
                )
            )

        if self._include_attachments:
            for attachment in [*parsed.attachments, *extra]:
                if not attachment.extracted:
                    continue
                messages.append(
                    SourceMessage(
                        # Tagged as a document: it is one, and provenance should
                        # name the file rather than the mail that carried it.
                        channel=SourceChannel.DOCUMENT,
                        author=author,
                        text=f"Attachment '{attachment.filename}':\n{attachment.text}",
                        metadata={
                            "filename": attachment.filename,
                            "content_type": attachment.content_type,
                            "attachment_of": parsed.subject,
                        },
                    )
                )
        return messages


class MeetingTranscriptSource(ConversationSource):
    """Meeting transcripts, one message per speaker turn.

    Consecutive lines from the same speaker are merged, because a transcript
    splits a single spoken thought across many short lines and extracting from
    each in isolation loses the sentence that spans them.
    """

    channel = SourceChannel.MEETING

    #: "Alice Chen:", "[00:14:02] Alice:", "Alice (Product):"
    SPEAKER = re.compile(
        r"^\s*(?:\[?\d{1,2}:\d{2}(?::\d{2})?\]?\s*)?([A-Z][\w .'-]{1,40})(?:\s*\([^)]*\))?\s*:\s*(.*)$"
    )

    def parse(self, payload: Any) -> list[SourceMessage]:
        text = payload if isinstance(payload, str) else str(payload.get("transcript", ""))
        turns: list[tuple[str, list[str]]] = []

        for line in text.splitlines():
            if not line.strip():
                continue
            match = self.SPEAKER.match(line)
            if match:
                speaker, utterance = match.group(1).strip(), match.group(2).strip()
                if turns and turns[-1][0] == speaker:
                    turns[-1][1].append(utterance)
                else:
                    turns.append((speaker, [utterance]))
            elif turns:
                turns[-1][1].append(line.strip())
            else:
                turns.append(("unknown", [line.strip()]))

        messages: list[SourceMessage] = []
        for speaker, lines in turns:
            body = " ".join(lines).strip()
            if self._is_noise(body, speaker):
                continue
            messages.append(SourceMessage(channel=self.channel, author=speaker, text=body))
        return messages


class DocumentSource(ConversationSource):
    """A pasted or uploaded document treated as a single message."""

    channel = SourceChannel.DOCUMENT

    def parse(self, payload: Any) -> list[SourceMessage]:
        if isinstance(payload, dict):
            text = str(payload.get("text", ""))
            name = str(payload.get("name", "document"))
        else:
            text, name = str(payload), "document"
        return [
            SourceMessage(
                channel=self.channel,
                author="document",
                text=text,
                metadata={"name": name},
            )
        ]


_SOURCES: dict[SourceChannel, type[ConversationSource]] = {
    SourceChannel.CHAT: ChatSource,
    SourceChannel.JIRA: JiraCommentSource,
    SourceChannel.EMAIL: EmailThreadSource,
    SourceChannel.EMAIL_FILE: EmailFileSource,
    SourceChannel.MEETING: MeetingTranscriptSource,
    SourceChannel.DOCUMENT: DocumentSource,
}


def get_source(channel: SourceChannel | str, **kwargs: Any) -> ConversationSource:
    """Construct the adapter for a channel."""
    resolved = SourceChannel(channel) if isinstance(channel, str) else channel
    factory = _SOURCES.get(resolved)
    if factory is None:
        from sa_platform.errors import ConfigurationError

        raise ConfigurationError(
            f"no ingestion adapter for channel '{resolved.value}'",
            details={"channel": resolved.value, "supported": [c.value for c in _SOURCES]},
        )
    import inspect

    accepted = inspect.signature(factory).parameters
    return factory(**{k: v for k, v in kwargs.items() if k in accepted})  # type: ignore[arg-type]


def parse_payload(channel: SourceChannel | str, payload: Any, **kwargs: Any) -> list[SourceMessage]:
    """Parse a channel payload into normalised messages."""
    messages = get_source(channel, **kwargs).parse(payload)
    logger.info(
        "parsed inbound payload",
        extra={
            "channel": str(channel),
            "messages": len(messages),
            "characters": sum(len(m.text) for m in messages),
        },
    )
    return messages


__all__ = [
    "ChatSource",
    "ConversationSource",
    "DocumentSource",
    "EmailFileSource",
    "EmailThreadSource",
    "JiraCommentSource",
    "MeetingTranscriptSource",
    "get_source",
    "parse_payload",
]
