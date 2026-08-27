from __future__ import annotations

import smtplib

import pytest

from app.config import settings
from app.services.outreach.sender import (
    OutgoingEmail,
    RecordingTransport,
    SMTPTransport,
    build_mime,
)


def _email(**kw) -> OutgoingEmail:
    base = dict(to_email="owner@shop.ie", subject="Hello", text="Body text",
                html="<p>Body text</p>")
    base.update(kw)
    return OutgoingEmail(**base)


def test_build_mime_headers():
    msg = build_mime(_email(headers={"List-Unsubscribe": "<https://x/u/1>"}))
    assert msg["To"] == "owner@shop.ie"
    assert settings.sender_name in msg["From"]
    assert msg["Message-ID"].endswith(f"@{settings.sender_email.split('@')[-1]}>")
    assert msg["Reply-To"] == settings.effective_reply_to
    assert msg["Precedence"] == "bulk"
    assert msg["List-Unsubscribe"] == "<https://x/u/1>"


def test_build_mime_is_multipart_alternative():
    msg = build_mime(_email())
    assert msg.get_content_type() == "multipart/alternative"
    assert msg.get_body(preferencelist=("plain",)).get_content().strip() == "Body text"
    assert "<p>" in msg.get_body(preferencelist=("html",)).get_content()


def test_build_mime_text_only_when_no_html():
    msg = build_mime(_email(html=None))
    assert msg.get_content_type() == "text/plain"


def test_build_mime_threading_headers():
    msg = build_mime(_email(in_reply_to="<orig@x>"))
    assert msg["In-Reply-To"] == "<orig@x>"
    assert msg["References"] == "<orig@x>"


def test_custom_header_replaces_rather_than_duplicates():
    msg = build_mime(_email(headers={"Reply-To": "other@shop.ie"}))
    assert msg.get_all("Reply-To") == ["other@shop.ie"]


def test_recording_transport_captures():
    transport = RecordingTransport()
    result = transport.send(_email())
    assert result.ok and result.dry_run
    assert len(transport.sent) == 1
    transport.clear()
    assert transport.sent == []


def test_smtp_transport_without_host_fails_cleanly():
    result = SMTPTransport(host="").send(_email())
    assert result.ok is False
    assert "SMTP_HOST" in result.error


def test_smtp_transport_reports_connection_failure(monkeypatch):
    transport = SMTPTransport(host="smtp.invalid", port=587)
    monkeypatch.setattr(
        transport, "_connect",
        lambda: (_ for _ in ()).throw(OSError("connection refused")),
    )
    result = transport.send(_email())
    assert result.ok is False
    assert "connect" in result.error


def test_smtp_transport_reports_refused_recipient(monkeypatch):
    class FakeSMTP:
        def login(self, *a):
            pass

        def send_message(self, msg):
            raise smtplib.SMTPRecipientsRefused({"owner@shop.ie": (550, b"no such user")})

        def quit(self):
            pass

    transport = SMTPTransport(host="smtp.example.com", user="", password="")
    monkeypatch.setattr(transport, "_connect", lambda: FakeSMTP())
    result = transport.send(_email())
    assert result.ok is False
    assert "recipient refused" in result.error


def test_smtp_transport_success(monkeypatch):
    sent = []

    class FakeSMTP:
        def login(self, *a):
            sent.append("login")

        def send_message(self, msg):
            sent.append(msg)

        def quit(self):
            pass

    transport = SMTPTransport(host="smtp.example.com", user="u", password="p")
    monkeypatch.setattr(transport, "_connect", lambda: FakeSMTP())
    result = transport.send(_email())
    assert result.ok is True
    assert result.dry_run is False
    assert result.message_id
    assert "login" in sent


@pytest.mark.parametrize("dry_run", [True, False])
def test_get_transport_honours_dry_run(monkeypatch, dry_run):
    from app.services.outreach import sender

    monkeypatch.setattr(settings, "dry_run", dry_run)
    sender.set_transport(None)
    transport = sender.get_transport()
    assert isinstance(transport, RecordingTransport) is dry_run
    sender.set_transport(None)
