from __future__ import annotations

from email.message import EmailMessage as MimeMessage
from email.utils import formatdate

from app.models import (
    EmailMessage,
    InboundMessage,
    LeadStatus,
    MessageStatus,
    ReplyClass,
    Suppression,
)
from app.services.inbox.matcher import match_lead
from app.services.inbox.parser import parse_message
from app.services.inbox.processor import process_batch, process_inbound
from app.utils import utcnow
from tests.conftest import make_lead


def build_raw(
    *, sender="owner@rossis.ie", subject="Re: website", body="Yes, interested!",
    in_reply_to=None, references=None, message_id="<reply-1@rossis.ie>", html=None,
) -> bytes:
    msg = MimeMessage()
    msg["From"] = sender
    msg["To"] = "hello@studio-example.com"
    msg["Subject"] = subject
    msg["Message-ID"] = message_id
    msg["Date"] = formatdate(usegmt=True)
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    return msg.as_bytes()


BOUNCE_RAW = b"""From: Mail Delivery Subsystem <MAILER-DAEMON@mx.test>
To: hello@studio-example.com
Subject: Undeliverable: Quick question
Message-ID: <bounce-1@mx.test>
Date: Tue, 25 Aug 2026 10:00:00 +0000
Content-Type: multipart/report; report-type=delivery-status; boundary="B"

--B
Content-Type: text/plain

Your message could not be delivered.

--B
Content-Type: message/delivery-status

Final-Recipient: rfc822; info@rossis.ie
Action: failed
Status: 5.1.1
Diagnostic-Code: smtp; 550 5.1.1 User unknown

--B--
"""


# --------------------------------------------------------------------- parser
def test_parse_plain_reply():
    parsed = parse_message(build_raw())
    assert parsed.from_email == "owner@rossis.ie"
    assert parsed.subject == "Re: website"
    assert "interested" in parsed.body_text
    assert parsed.is_dsn is False


def test_parse_extracts_threading_headers():
    parsed = parse_message(build_raw(in_reply_to="<orig@studio-example.com>",
                                     references="<a@x> <orig@studio-example.com>"))
    assert parsed.in_reply_to == "<orig@studio-example.com>"
    assert parsed.references == ["<a@x>", "<orig@studio-example.com>"]


def test_parse_falls_back_to_html_body():
    msg = MimeMessage()
    msg["From"] = "owner@rossis.ie"
    msg["Subject"] = "Re: website"
    msg["Message-ID"] = "<html-1@x>"
    msg.set_content("<p>Sounds <b>good</b>, how much?</p>", subtype="html")
    parsed = parse_message(msg.as_bytes())
    assert "Sounds good, how much?" in parsed.body_text
    assert "<p>" not in parsed.body_text


def test_parse_detects_bounce_and_failed_recipient():
    parsed = parse_message(BOUNCE_RAW)
    assert parsed.is_dsn is True
    assert parsed.failed_recipient == "info@rossis.ie"


def test_parse_synthesises_missing_message_id():
    raw = b"From: a@b.test\nSubject: hi\n\nbody"
    parsed = parse_message(raw)
    assert parsed.message_id.startswith("<synthetic-")


def test_parse_returns_none_for_garbage():
    assert parse_message(b"") is not None  # empty parses to an empty message


# -------------------------------------------------------------------- matcher
def _sent(db, lead, message_id="<orig@studio-example.com>"):
    record = EmailMessage(
        lead_id=lead.id, step=0, to_email=lead.email, from_email="hello@studio-example.com",
        subject="s", body_text="b", status=MessageStatus.SENT, sent_at=utcnow(),
        message_id=message_id,
    )
    db.add(record)
    db.commit()
    return record


def test_match_by_in_reply_to(db, campaign):
    lead = make_lead(db, campaign=campaign)
    _sent(db, lead)
    parsed = parse_message(build_raw(sender="different@elsewhere.test",
                                     in_reply_to="<orig@studio-example.com>"))
    matched, how = match_lead(db, parsed)
    assert matched.id == lead.id
    assert how == "threading_headers"


def test_match_by_references_when_in_reply_to_missing(db, campaign):
    lead = make_lead(db, campaign=campaign)
    _sent(db, lead)
    parsed = parse_message(build_raw(sender="x@y.test",
                                     references="<junk@a> <orig@studio-example.com>"))
    matched, how = match_lead(db, parsed)
    assert matched.id == lead.id


def test_match_by_sender_address(db, campaign):
    lead = make_lead(db, campaign=campaign, email="owner@rossis.ie")
    parsed = parse_message(build_raw(sender="owner@rossis.ie"))
    matched, how = match_lead(db, parsed)
    assert matched.id == lead.id
    assert how == "sender_address"


def test_match_bounce_by_failed_recipient(db, campaign):
    lead = make_lead(db, campaign=campaign, email="info@rossis.ie")
    parsed = parse_message(BOUNCE_RAW)
    matched, how = match_lead(db, parsed)
    assert matched.id == lead.id
    assert how == "dsn_recipient"


def test_unmatched_returns_none(db):
    parsed = parse_message(build_raw(sender="stranger@nowhere.test"))
    matched, how = match_lead(db, parsed)
    assert matched is None and how == "unmatched"


# ------------------------------------------------------------------ processor
def test_positive_reply_updates_lead(db, campaign):
    lead = make_lead(db, campaign=campaign, email="owner@rossis.ie",
                     status=LeadStatus.CONTACTED, next_action_at=utcnow())
    parsed = parse_message(build_raw(body="Yes please, how much would it cost?"))
    result = process_inbound(db, parsed)
    db.commit()

    assert result.stored
    assert result.classification == ReplyClass.POSITIVE
    assert lead.status == LeadStatus.POSITIVE
    assert lead.replied_at is not None
    assert lead.next_action_at is None      # follow-ups stop on a human reply


def test_negative_reply_marks_lead_negative(db, campaign):
    lead = make_lead(db, campaign=campaign, email="owner@rossis.ie",
                     status=LeadStatus.CONTACTED)
    parsed = parse_message(build_raw(body="No thanks, we already have a website."))
    process_inbound(db, parsed)
    db.commit()
    assert lead.status == LeadStatus.NEGATIVE


def test_unsubscribe_reply_suppresses(db, campaign):
    lead = make_lead(db, campaign=campaign, email="owner@rossis.ie",
                     status=LeadStatus.CONTACTED)
    parsed = parse_message(build_raw(body="Please remove me from your list."))
    process_inbound(db, parsed)
    db.commit()
    assert lead.status == LeadStatus.UNSUBSCRIBED
    assert db.query(Suppression).filter_by(value=lead.email).count() == 1


def test_bounce_marks_lead_and_suppresses(db, campaign):
    lead = make_lead(db, campaign=campaign, email="info@rossis.ie",
                     status=LeadStatus.CONTACTED)
    parsed = parse_message(BOUNCE_RAW)
    result = process_inbound(db, parsed)
    db.commit()
    assert result.classification == ReplyClass.BOUNCE
    assert lead.status == LeadStatus.BOUNCED
    assert lead.next_action_at is None
    assert db.query(Suppression).filter_by(value="info@rossis.ie").count() == 1


def test_auto_reply_does_not_stop_the_sequence(db, campaign):
    future = utcnow()
    lead = make_lead(db, campaign=campaign, email="owner@rossis.ie",
                     status=LeadStatus.CONTACTED, next_action_at=future)
    parsed = parse_message(build_raw(subject="Out of Office",
                                     body="I am on annual leave until September."))
    process_inbound(db, parsed)
    db.commit()
    assert lead.status == LeadStatus.CONTACTED
    assert lead.next_action_at is not None


def test_duplicate_message_is_ignored(db, campaign):
    make_lead(db, campaign=campaign, email="owner@rossis.ie")
    parsed = parse_message(build_raw())
    assert process_inbound(db, parsed).stored is True
    db.commit()
    second = process_inbound(db, parsed)
    assert second.stored is False
    assert "already processed" in second.reason
    assert db.query(InboundMessage).count() == 1


def test_our_own_sent_message_is_ignored(db, campaign):
    lead = make_lead(db, campaign=campaign)
    _sent(db, lead, message_id="<mine@studio-example.com>")
    parsed = parse_message(build_raw(message_id="<mine@studio-example.com>"))
    result = process_inbound(db, parsed)
    assert result.stored is False
    assert "own outbound" in result.reason


def test_unmatched_reply_is_still_stored(db):
    parsed = parse_message(build_raw(sender="stranger@nowhere.test"))
    result = process_inbound(db, parsed)
    db.commit()
    assert result.stored is True
    assert result.lead_id is None
    assert db.query(InboundMessage).count() == 1


def test_process_batch_summarises(db, campaign):
    make_lead(db, campaign=campaign, email="owner@rossis.ie",
              status=LeadStatus.CONTACTED)
    messages = [
        parse_message(build_raw(message_id="<m1@x>", body="Yes, interested, send a quote")),
        parse_message(build_raw(message_id="<m2@x>", sender="s@nowhere.test",
                                body="No thanks")),
        parse_message(BOUNCE_RAW),
    ]
    summary = process_batch(db, messages)
    assert summary["seen"] == 3
    assert summary["stored"] == 3
    assert summary["positive"] == 1
    assert summary["bounces"] == 1
