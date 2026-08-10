"""Tests for the operator console.

The console's job is to be a faithful client: it must serve the app, reach the
platform API through one origin, and — in remote mode — proxy without leaking
the upstream credential to the browser or corrupting the response.

The end-to-end case here is the one the console exists for: an email with an
attachment arrives, and the answers inside it end up in the form.
"""

from __future__ import annotations

import json
from email.message import EmailMessage
from typing import Any

import pytest
from fastapi.testclient import TestClient

from sa_console.app import create_console
from sa_console.config import ConsoleSettings


@pytest.fixture
def console() -> Any:
    with TestClient(create_console(ConsoleSettings(title="Test Console"))) as client:
        yield client


class TestShell:
    def test_the_app_is_served_from_the_root(self, console: Any) -> None:
        response = console.get("/")
        assert response.status_code == 200
        assert "<title>" in response.text

    def test_assets_are_served(self, console: Any) -> None:
        assert console.get("/assets/styles.css").status_code == 200
        assert console.get("/assets/js/app.js").status_code == 200

    def test_the_browser_config_carries_no_credential(self) -> None:
        settings = ConsoleSettings(api_key="super-secret", api_base_url="https://api.internal")
        assert "super-secret" not in json.dumps(settings.public_config())
        assert settings.mode == "remote"

    def test_embedded_mode_mounts_the_platform_api(self, console: Any) -> None:
        """Mounted, not re-declared: the console must hit the real routes."""
        assert console.get("/api/health/ready").status_code == 200
        assert console.get("/api/forms").status_code == 200

    def test_the_mounted_api_is_bootstrapped(self, console: Any) -> None:
        """Starlette does not forward lifespan to a mounted app; the console must."""
        assert console.get("/api/forms").json()["count"] >= 1
        assert console.get("/api/tools").json()["count"] > 0


class TestRemoteMode:
    """Remote mode proxies to a separately deployed API."""

    def test_the_upstream_credential_is_attached_server_side(self) -> None:
        """The console is the trust boundary; the browser never holds the key."""
        settings = ConsoleSettings(
            api_base_url="https://platform.internal", api_key="upstream-secret"
        )
        assert settings.api_key is not None
        assert settings.api_key.get_secret_value() == "upstream-secret"
        assert "upstream-secret" not in json.dumps(settings.public_config())

    def test_hop_by_hop_headers_are_not_copied_through(self) -> None:
        """Forwarding content-encoding on an already-decoded body corrupts it."""
        from sa_console.app import _HOP_BY_HOP

        assert "content-encoding" in _HOP_BY_HOP
        assert "content-length" in _HOP_BY_HOP
        assert "transfer-encoding" in _HOP_BY_HOP

    def test_an_unreachable_upstream_becomes_a_502_not_a_crash(self) -> None:
        settings = ConsoleSettings(api_base_url="http://127.0.0.1:9", request_timeout_seconds=1.0)
        with TestClient(create_console(settings)) as client:
            response = client.get("/api/forms")
            assert response.status_code == 502
            assert "could not reach" in response.json()["error"]["message"]


class TestProfileHeader:
    def test_a_pinned_profile_is_honoured_per_request(self, console: Any) -> None:
        """`X-LLM-Profile` selects the model for one request without changing the default."""
        before = console.get("/api/providers").json()["active"]
        response = console.post(
            "/api/providers/complete",
            json={"prompt": "hello"},
            headers={"X-LLM-Profile": "stub"},
        )
        assert response.status_code == 200
        assert response.json()["served_by"] == "stub"
        assert console.get("/api/providers").json()["active"] == before

    def test_an_unknown_profile_header_does_not_fail_the_request(self, console: Any) -> None:
        """Choosing a model is not the caller's business to get right."""
        response = console.get("/api/forms", headers={"X-LLM-Profile": "retired-profile"})
        assert response.status_code == 200


def build_email() -> bytes:
    message = EmailMessage()
    message["Subject"] = "Change request: payments gateway"
    message["From"] = "Priya Raman <priya@example.com>"
    message["To"] = "ops@example.com"
    message.set_content("Details below.\n\n" "Best regards,\nPriya\n")
    message.add_attachment(
        b"Field,Value\n"
        b"Change title,Payments gateway TLS upgrade\n"
        b"Affected system,payments-gateway\n"
        b"Change owner,Priya Raman\n",
        maintype="text",
        subtype="csv",
        filename="details.csv",
    )
    return message.as_bytes()


def accept_terms(console: Any, session_id: str, actor: str) -> None:
    """Accept whatever the form requires before it will hold any content.

    Mining a thread stores the participant's words exactly as typing them would,
    so the ingest path is behind the same consent gate the conversation is. This
    is the flow, not test scaffolding: a real intake accepts the terms and then
    uploads the mail.
    """
    outstanding = console.get(f"/api/forms/sessions/{session_id}/agreements").json()["outstanding"]
    for agreement in outstanding:
        # Only the ones the submission has actually reached. A confirmation of
        # accuracy is undecided from the first turn and refused until there is
        # something to confirm.
        if not agreement["decidable"]:
            continue
        console.post(
            f"/api/forms/sessions/{session_id}/agreements/{agreement['id']}",
            json={"accept": True, "actor": actor, "stated": "I agree"},
        )


class TestEmailIntakeEndToEnd:
    def test_answers_inside_an_attachment_reach_the_form(self, console: Any) -> None:
        """The whole point: nobody retypes the spreadsheet that was attached.

        The attachment is a two-column sheet, which the deterministic extractor
        reads directly — so this passes with no model configured.
        """
        console.post("/api/providers/stub/activate")

        started = console.post(
            "/api/forms/change_request/sessions",
            json={"participant": "priya", "resume": False},
        ).json()
        session_id = started["session_id"]
        accept_terms(console, session_id, "priya")

        response = console.post(
            f"/api/forms/sessions/{session_id}/ingest/email",
            files=[("email", ("thread.eml", build_email(), "message/rfc822"))],
        )
        assert response.status_code == 200, response.text
        report = response.json()

        assert "change_owner" in report["captured"]
        assert "affected_system" in report["captured"]

        session = console.get(f"/api/forms/sessions/{session_id}").json()
        assert session["answers"]["change_owner"]["value"] == "Priya Raman"
        # Provenance names the file, not just "an email".
        provenance = session["answers"]["change_owner"]["provenance"]
        assert provenance["channel"] == "document"

    def test_the_console_can_take_consent_and_close_a_routed_question(self, console: Any) -> None:
        """The endpoints the session view drives, in the order it drives them.

        A checkbox in a console and a typed "I agree" have to produce the same
        record, so this asserts on what was stored rather than on the response:
        the exact wording, who decided, and the hash over it.
        """
        console.post("/api/providers/stub/activate")
        session_id = console.post(
            "/api/forms/change_request/sessions",
            json={"participant": "priya", "resume": False},
        ).json()["session_id"]

        # 1. The view asks what it is waiting on, and shows the declared text.
        pending = console.get(f"/api/forms/sessions/{session_id}/agreements").json()
        assert {a["id"] for a in pending["outstanding"]} >= {"recording_notice"}
        assert "retained for seven years" in "".join(a["text"] for a in pending["outstanding"])

        # 2. Accepting from the console records the wording, not a tick.
        recorded = console.post(
            f"/api/forms/sessions/{session_id}/agreements/recording_notice",
            json={"accept": True, "actor": "priya", "stated": "Accepted in the console."},
        ).json()
        assert recorded["decision"] == "accepted"
        assert "retained for seven years" in recorded["text"]
        assert len(recorded["text_hash"]) == 64
        accept_terms(console, session_id, "priya")  # the rest of the start-stage terms

        # 3. A question the assistant cannot settle is routed and shows up as
        #    open, with the team that owns it named.
        console.post(
            f"/api/forms/sessions/{session_id}/messages",
            json={"message": "who can I ask about the maintenance window?", "author": "priya"},
        )
        open_questions = console.get(
            f"/api/forms/sessions/{session_id}/questions", params={"open_only": True}
        ).json()["questions"]
        assert open_questions and open_questions[0]["team"] == "SRE On-Call"

        # 4. And the console can close it with what the team came back with.
        closed = console.post(
            f"/api/forms/sessions/{session_id}/questions/{open_questions[0]['id']}",
            json={"resolution": "Use 02:00-04:00 UTC on Saturdays."},
        ).json()
        assert closed["status"] == "closed"

        status = console.get(f"/api/forms/sessions/{session_id}/status").json()
        assert status["questions"]["open"] == []
        assert "recording_notice" not in status["agreements"]["blocking"]

    def test_the_session_view_gets_everything_it_renders(self, console: Any) -> None:
        """The contract between the API and the session view, asserted here.

        The console builds three things from data the engine has only recently
        started returning: the consent panel, the agreements card, and the
        "asking about now" highlight. Each reads a specific key, and a rename on
        the server side would leave the browser silently rendering nothing —
        which on a consent gate means the participant sees an idle screen and no
        reason for it.
        """
        console.post("/api/providers/stub/activate")
        session_id = console.post(
            "/api/forms/change_request/sessions",
            json={"participant": "sam", "resume": False},
        ).json()["session_id"]

        # The consent panel: `awaiting` says what is being waited on *now*, and
        # the wording comes from the definition, not from the chat bubble.
        status = console.get(f"/api/forms/sessions/{session_id}/status").json()
        assert status["agreements"]["awaiting"] == ["recording_notice", "authority_to_raise"]
        definition = console.get("/api/forms/change_request").json()
        declared = {a["id"]: a for a in definition["agreements"]}
        assert set(status["agreements"]["awaiting"]) <= declared.keys()
        assert all(declared[a]["text"] for a in status["agreements"]["awaiting"])

        # A confirmation due later is undecided but not yet awaited: showing it
        # as a gate would be showing a gate that is not there.
        assert "submission_is_accurate" not in status["agreements"]["awaiting"]
        assert "submission_is_accurate" in {a["id"] for a in status["agreements"]["outstanding"]}

        accept_terms(console, session_id, "sam")

        # The "asking about now" highlight reads the last assistant turn. It is
        # what makes a topic spanning two sections legible instead of looking
        # like the assistant wandering.
        session = console.get(f"/api/forms/sessions/{session_id}").json()
        asked = [e for e in session["transcript"] if e["role"] == "assistant"][-1]
        assert asked["targeted_fields"], "the view has nothing to highlight"
        sections = {
            section["title"]
            for section in definition["sections"]
            for field in section["fields"]
            if field["id"] in asked["targeted_fields"]
        }
        assert len(sections) > 1, "expected this form's opening topic to cross a section"

        # And the agreements card reads the stored record, not the definition.
        status = console.get(f"/api/forms/sessions/{session_id}/status").json()
        decided = status["agreements"]["decided"]
        assert {r["agreement_id"] for r in decided} == {"recording_notice", "authority_to_raise"}
        assert all(r["text"] and r["text_hash"] and r["actor"] == "sam" for r in decided)
        assert status["agreements"]["awaiting"] == []

    def test_an_agreement_form_walks_the_pack_one_term_at_a_time(self, console: Any) -> None:
        """What the session view drives when the form *is* the agreements.

        The failure this guards against is the panel emptying after the first
        acceptance: the decision is taken out of band, so unless the engine puts
        the next term, the screen shows nothing with four still outstanding.
        """
        console.post("/api/providers/stub/activate")
        definition = console.get("/api/forms/platform_access_agreement").json()
        assert definition["kind"] == "agreement"

        catalogue = console.get("/api/forms").json()["forms"]
        listed = next(f for f in catalogue if f["name"] == "platform_access_agreement")
        # The catalogue measures it in agreements; "0 required / 0 fields" would
        # read as an empty form.
        assert listed["required_agreements"] == 5

        session_id = console.post(
            "/api/forms/platform_access_agreement/sessions",
            json={"participant": "sam", "resume": False},
        ).json()["session_id"]

        seen: list[str] = []
        for _ in range(6):
            status = console.get(f"/api/forms/sessions/{session_id}/status").json()
            awaiting = status["agreements"]["awaiting"]
            if not awaiting:
                break
            # One at a time, never bundled.
            assert len(awaiting) == 1
            seen.append(awaiting[0])
            console.post(
                f"/api/forms/sessions/{session_id}/agreements/{awaiting[0]}",
                json={"accept": True, "actor": "sam", "stated": "Accepted in the console."},
            )

        assert seen == [a["id"] for a in definition["agreements"]]

        status = console.get(f"/api/forms/sessions/{session_id}/status").json()
        assert status["completeness"]["agreements"] == "5/5"
        assert status["agreements"]["blocking"] == []
        # And it has moved on to the two identifying details it also asks for.
        assert status["completeness"]["outstanding_mandatory"] == [
            "accepting_party",
            "sponsoring_team",
        ]

    def test_an_unreadable_attachment_is_reported_rather_than_dropped(self, console: Any) -> None:
        console.post("/api/providers/stub/activate")
        started = console.post(
            "/api/forms/change_request/sessions",
            json={"participant": "ben", "resume": False},
        ).json()
        accept_terms(console, started["session_id"], "ben")

        message = EmailMessage()
        message["Subject"] = "diagram"
        message["From"] = "ben@example.com"
        message.set_content("See the diagram.")
        message.add_attachment(
            b"\x89PNG\r\n\x1a\n" + b"\x00" * 32,
            maintype="image",
            subtype="png",
            filename="topology.png",
        )

        report = console.post(
            f"/api/forms/sessions/{started['session_id']}/ingest/email",
            files=[("email", ("d.eml", message.as_bytes(), "message/rfc822"))],
        ).json()

        [attachment] = report["email"]["attachments"]
        assert attachment["extracted"] is False
        assert "not text-extractable" in attachment["note"]
