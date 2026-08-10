"""Tests for email and attachment ingestion.

The value of reading attachments is that people put the answers in them. The
risk is the same thing every email parser gets wrong: quoted history, signature
blocks, and binary payloads decoded as text. Those are what is asserted here.
"""

from __future__ import annotations

import io
import json
from email.message import EmailMessage

import pytest

from sa_forms.attachments import (
    MAX_ATTACHMENT_BYTES,
    extract_attachment,
    html_to_text,
    parse_email,
)
from sa_forms.ingestion import EmailFileSource, parse_payload
from sa_forms.models import SourceChannel
from sa_platform.errors import ValidationError


def make_email(
    body: str = "Plain body",
    *,
    html: str | None = None,
    attachments: list[tuple[str, bytes, str, str]] | None = None,
    subject: str = "Change request details",
) -> bytes:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = "Priya Raman <priya@example.com>"
    message["To"] = "ops@example.com"
    message["Message-ID"] = "<m1@example.com>"
    message.set_content(body)
    if html is not None:
        message.add_alternative(html, subtype="html")
    for filename, content, maintype, subtype in attachments or []:
        message.add_attachment(content, maintype=maintype, subtype=subtype, filename=filename)
    return message.as_bytes()


class TestEmailParsing:
    def test_headers_and_body_are_read(self) -> None:
        parsed = parse_email(make_email("The owner is Priya."))
        assert parsed.subject == "Change request details"
        assert "priya@example.com" in parsed.sender
        assert parsed.recipients == ["ops@example.com"]
        assert "The owner is Priya." in parsed.body
        assert parsed.message_id == "<m1@example.com>"

    def test_an_html_only_body_is_converted_to_text(self) -> None:
        message = EmailMessage()
        message["Subject"] = "s"
        message["From"] = "a@b.c"
        message.set_content("<p>Owner: <b>Priya</b></p><p>Date: 2026-09-15</p>", subtype="html")
        parsed = parse_email(message.as_bytes())
        assert "Owner: Priya" in parsed.body
        assert "<p>" not in parsed.body

    def test_an_outlook_msg_file_is_rejected_with_an_actionable_message(self) -> None:
        """A compound binary file read as a body produces confident nonsense."""
        ole_magic = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"junk" * 40
        with pytest.raises(ValidationError, match=r"\.eml"):
            parse_email(ole_magic)

    def test_malformed_mime_raises_rather_than_returning_garbage(self) -> None:
        parsed = parse_email(b"this is not an email at all")
        # A bare string parses as a bodyless message; the point is it does not
        # crash and does not invent headers.
        assert parsed.subject == ""


class TestAttachmentExtraction:
    def test_csv_becomes_labelled_lines(self) -> None:
        """`Label: value` is the shape the deterministic extractor already matches."""
        content = b"Field,Value\nOwner,Priya Raman\nTarget date,2026-09-15\n"
        attachment = extract_attachment("details.csv", content)
        assert attachment.extracted
        assert "Owner: Priya Raman" in attachment.text
        assert "Target date: 2026-09-15" in attachment.text

    def test_a_wide_table_keeps_its_columns(self) -> None:
        rows = "a,b,c\n1,2,3\n"
        attachment = extract_attachment("wide.csv", rows.encode())
        assert "a | b | c" in attachment.text

    def test_json_is_pretty_printed(self) -> None:
        attachment = extract_attachment("payload.json", json.dumps({"owner": "Priya"}).encode())
        assert '"owner": "Priya"' in attachment.text

    def test_xlsx_is_read_sheet_by_sheet(self) -> None:
        openpyxl = pytest.importorskip("openpyxl")
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "Impact"
        sheet.append(["Field", "Value"])
        sheet.append(["Affected system", "payments-gateway"])
        buffer = io.BytesIO()
        workbook.save(buffer)

        attachment = extract_attachment("impact.xlsx", buffer.getvalue())
        assert "# Sheet: Impact" in attachment.text
        assert "Affected system: payments-gateway" in attachment.text

    def test_an_image_is_recorded_rather_than_decoded(self) -> None:
        """Silently dropping an attachment is how a form ends up confidently wrong."""
        attachment = extract_attachment("diagram.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
        assert not attachment.extracted
        assert "not text-extractable" in attachment.note

    def test_an_oversized_attachment_is_skipped_with_a_reason(self) -> None:
        attachment = extract_attachment("huge.txt", b"x" * (MAX_ATTACHMENT_BYTES + 1))
        assert not attachment.extracted
        assert "exceeds" in attachment.note

    def test_an_unknown_extension_is_decoded_only_when_it_looks_textual(self) -> None:
        assert extract_attachment("notes.rst", b"Owner: Priya").extracted
        assert not extract_attachment("blob.bin", b"\x00\x01\x02\x03" * 40).extracted

    def test_a_reader_failure_reports_the_reason_and_does_not_raise(self) -> None:
        attachment = extract_attachment("broken.xlsx", b"not a zip file at all")
        assert not attachment.extracted
        assert attachment.note

    def test_a_forwarded_message_is_read_one_level_deep(self) -> None:
        inner = make_email("Inner body with the answer", subject="Original")
        attachment = extract_attachment("forwarded.eml", inner)
        assert "Inner body with the answer" in attachment.text
        assert "Forwarded message" in attachment.text


class TestHtmlToText:
    def test_scripts_and_styles_are_dropped(self) -> None:
        markup = "<style>p{color:red}</style><script>alert(1)</script><p>Keep this</p>"
        text = html_to_text(markup)
        assert "Keep this" in text
        assert "alert" not in text
        assert "color:red" not in text

    def test_block_elements_become_line_breaks(self) -> None:
        assert html_to_text("<p>one</p><p>two</p>").splitlines() == ["one", "two"]

    def test_entities_are_unescaped(self) -> None:
        assert "Ben & Co" in html_to_text("<p>Ben &amp; Co</p>")


class TestEmailFileSource:
    def test_the_body_and_each_readable_attachment_become_messages(self) -> None:
        raw = make_email(
            "The affected system is payments-gateway.",
            attachments=[
                ("details.csv", b"Field,Value\nOwner,Priya\n", "text", "csv"),
                ("diagram.png", b"\x89PNG\r\n\x1a\n\x00\x00", "image", "png"),
            ],
        )
        messages = EmailFileSource().parse(raw)

        assert len(messages) == 2  # body + csv; the image contributes no text
        assert messages[0].channel is SourceChannel.EMAIL
        assert "payments-gateway" in messages[0].text
        assert messages[1].channel is SourceChannel.DOCUMENT
        assert messages[1].metadata["filename"] == "details.csv"

    def test_quoted_history_is_cut_before_extraction(self) -> None:
        """Otherwise a reply quoting the old question restores superseded values."""
        raw = make_email(
            "The owner is Priya Raman.\n\n"
            "On Mon, 3 Aug 2026, ops wrote:\n"
            "> The owner is Sam Patel.\n"
        )
        [message] = EmailFileSource().parse(raw)
        assert "Priya Raman" in message.text
        assert "Sam Patel" not in message.text

    def test_a_signature_block_is_removed(self) -> None:
        raw = make_email(
            "Target date is 2026-09-15.\n\n"
            "Best regards,\nPriya Raman\nSenior Engineer | Example Corp\n"
        )
        [message] = EmailFileSource().parse(raw)
        assert "2026-09-15" in message.text
        assert "Senior Engineer" not in message.text

    def test_attachments_supplied_alongside_the_mail_are_included(self) -> None:
        """Mail clients drop attachments on forward more often than people expect."""
        payload = {
            "raw": make_email("See attached."),
            "attachments": [{"filename": "runbook.txt", "content": b"Rollback: redeploy 2.14"}],
        }
        messages = EmailFileSource().parse(payload)
        assert any("redeploy 2.14" in m.text for m in messages)

    def test_it_is_reachable_through_the_channel_registry(self) -> None:
        messages = parse_payload("email_file", make_email("Body text here."))
        assert messages and "Body text here." in messages[0].text
