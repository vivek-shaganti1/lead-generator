"""Extreme edge case tests across discovery, enrichment, outreach, IMAP receiving,
reply understanding, and autonomous operation.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.header import Header
from email.message import EmailMessage as MimeMessage
from email.utils import formatdate
import pytest

from app.config import settings
from app.models import (
    Business,
    EmailMessage,
    InboundMessage,
    Lead,
    LeadStatus,
    MessageStatus,
    ReplyClass,
)
from app.services import stats
from app.services.ai import rules
from app.services.discovery.importer import import_reference_sheet
from app.services.inbox.matcher import match_lead
from app.services.inbox.parser import parse_message
from app.services.inbox.processor import process_inbound
from app.services.notify import telegram
from app.services.outreach.dispatcher import approve_lead, due_leads, run_batch, send_lead
from app.services.outreach.sender import RecordingTransport, OutgoingEmail, build_mime
from app.services.outreach.templates import build_context, render_email
from app.services.outreach.throttle import (
    check_send_slot,
    in_send_window,
    local_now,
    warmup_cap,
)
from app.utils import utcnow
from tests.conftest import make_business, make_lead
from tests.test_integration import CapturingTelegram


# =============================================================================
# 1. Extreme MIME & Email Parsing Edge Cases
# =============================================================================

def test_parse_mime_with_rfc2047_encoded_headers():
    """Test non-ASCII / Unicode encoded headers in Subject and From."""
    msg = MimeMessage()
    msg["From"] = str(Header("François Müller <francois@mueller-cafe.ie>", "utf-8"))
    msg["To"] = "hello@studio-example.com"
    msg["Subject"] = str(Header("Re: Question regarding Café de l'Étoile 🥐", "utf-8"))
    msg["Message-ID"] = "<unicode-msg-1@mueller.ie>"
    msg["Date"] = formatdate(usegmt=True)
    msg.set_content("Oui, we are very interested! Please send us a mockup.")

    raw = msg.as_bytes()
    parsed = parse_message(raw)

    assert parsed is not None
    assert "francois@mueller-cafe.ie" in parsed.from_email
    assert "Café de l'Étoile" in parsed.subject
    assert "interested" in parsed.body_text


def test_parse_microsoft_exchange_ndr_bounce():
    """Test Microsoft Exchange NDR bounce format with X-Failed-Recipients."""
    raw_exchange = b"""From: Microsoft Outlook <MicrosoftExchange329e71ec88@company.com>
To: hello@studio-example.com
Subject: Undeliverable: Quick question about business website
Date: Wed, 27 Aug 2026 12:00:00 +0000
Message-ID: <exchange-bounce-99@company.com>
Content-Type: multipart/report; report-type=delivery-status; boundary="Exchange_Boundary"

--Exchange_Boundary
Content-Type: text/plain; charset="utf-8"

Delivery has failed to these recipients or groups:

target-person@invalid-domain-exchange.com
The server has tried to deliver this message, without success, and has stopped trying.

--Exchange_Boundary
Content-Type: message/delivery-status

Recipient: target-person@invalid-domain-exchange.com
Action: failed
Status: 5.4.1
Diagnostic-Code: smtp; 554 5.4.1 Host or domain name not found.

--Exchange_Boundary--
"""
    parsed = parse_message(raw_exchange)
    assert parsed is not None
    assert parsed.is_dsn is True
    assert parsed.failed_recipient == "target-person@invalid-domain-exchange.com"


def test_parse_amazon_ses_sendgrid_bounce_format():
    """Test Amazon SES / SendGrid delivery failure notice."""
    raw_ses = b"""From: MAILER-DAEMON@email.amazonses.com
To: hello@studio-example.com
Subject: Delivery Status Notification (Failure)
Date: Wed, 27 Aug 2026 12:05:00 +0000
Message-ID: <ses-bounce-44@email.amazonses.com>
Content-Type: text/plain; charset="utf-8"

An error occurred while trying to deliver the mail to the following recipients:
Final-Recipient: rfc822; nonexistent-user@clientdomain.com
Action: failed
Status: 5.1.1
Diagnostic-Code: smtp; 550 5.1.1 User does not exist
"""
    parsed = parse_message(raw_ses)
    assert parsed is not None
    assert parsed.is_dsn is True
    assert parsed.failed_recipient == "nonexistent-user@clientdomain.com"


def test_parse_corrupt_zero_byte_body_and_attachments():
    """Test parser resilience against zero-byte bodies and attachments."""
    msg = MimeMessage()
    msg["From"] = "sender@domain.com"
    msg["To"] = "hello@studio-example.com"
    msg["Subject"] = "Empty or attachment only"
    msg["Message-ID"] = "<empty-1@domain.com>"
    msg.add_attachment(b"dummy pdf bytes", maintype="application", subtype="pdf", filename="doc.pdf")

    parsed = parse_message(msg.as_bytes())
    assert parsed is not None
    assert parsed.from_email == "sender@domain.com"
    assert parsed.body_text == ""


# =============================================================================
# 2. Extreme Reply Understanding & Classification Edge Cases
# =============================================================================

@pytest.mark.parametrize(
    "subject,body,expected_class",
    [
        # Multi-language Auto Replies / Out of Office
        ("Abwesenheitsnotiz", "Ich bin bis zum 05.09 nicht im Büro.", ReplyClass.AUTO_REPLY),
        ("Réponse automatique", "Je suis actuellement en congé maternité.", ReplyClass.AUTO_REPLY),
        ("Fuera de la oficina", "Estaré fuera de la oficina por vacaciones.", ReplyClass.AUTO_REPLY),
        # High buying intent / Positive replies
        ("Re: website", "Sounds great! What are your prices?", ReplyClass.POSITIVE),
        ("Re: website", "Send over the mockup please, would love to see it.", ReplyClass.POSITIVE),
        ("Re: website", "Give us a call on +353 21 555 1234 to discuss.", ReplyClass.POSITIVE),
        ("Re: website", "Yes please, definitely interested in seeing samples.", ReplyClass.POSITIVE),
        # Polite or hard declines / Negative replies
        ("Re: website", "We already have an agency managing our site, please stop.", ReplyClass.NEGATIVE),
        ("Re: website", "We're all set, no interest at this time.", ReplyClass.NEGATIVE),
        ("Re: website", "Wrong person, not looking for a website.", ReplyClass.NEGATIVE),
        # Explicit GDPR / Unsubscribe requests
        ("Unsubscribe", "Please remove our company from your records immediately (GDPR).", ReplyClass.UNSUBSCRIBE),
        ("Re: website", "Stop sending emails to this address. Unsubscribe me.", ReplyClass.UNSUBSCRIBE),
        ("Re: website", "Do not contact us ever again.", ReplyClass.UNSUBSCRIBE),
        # Questions & Mixed Intent
        ("Re: website", "How does this work and what is included in the price?", ReplyClass.QUESTION),
        ("Re: website", "Not interested right now, but how much do you charge?", ReplyClass.QUESTION),
    ],
)
def test_rules_classification_edge_cases(subject, body, expected_class):
    cls, conf, reason = rules.classify(subject, body)
    assert cls == expected_class
    assert conf > 0.0


def test_quote_stripping_with_multilingual_and_outlook_headers():
    body = """Yes please send a mockup!

From: Vivek <hello@yourstudio.com>
Sent: Tuesday, August 26, 2026 10:00 AM
To: owner@irishbakery.ie
Subject: Quick question about Irish Bakery's website

Hi, I couldn't find a website for Irish Bakery...
"""
    stripped = rules.strip_quoted(body)
    assert stripped == "Yes please send a mockup!"


# =============================================================================
# 3. Extreme Outreach & Throttling Edge Cases
# =============================================================================

def test_template_rendering_with_unicode_and_missing_attributes(db):
    """Verify template handles missing city/region/category and emojis gracefully."""
    biz = make_business(db, name="Boulangerie L'Étoile 🥐", city=None, region=None, category=None)
    lead = make_lead(db, business=biz, email="test@unicode-company.ie", contact_name="René")

    ctx = build_context(lead, biz, presence="MISSING")
    assert ctx["business_name"] == "Boulangerie L'Étoile 🥐"
    assert ctx["city"] == "your area"
    assert ctx["category_label"] == "local"

    rendered = render_email(
        "Website for {{ business_name }}",
        "Hi {{ contact_name }}, we noticed your {{ category_label }} in {{ city }}.",
        ctx,
    )
    assert "Boulangerie L'Étoile 🥐" in rendered.subject
    assert "René" in rendered.text
    assert "your area" in rendered.text
    assert "Unsubscribe" in rendered.text


def test_warmup_curve_progression():
    """Test daily warmup curve calculations."""
    settings.warmup_enabled = True
    settings.warmup_start = 20
    settings.warmup_increment = 15
    settings.daily_send_cap = 200

    assert warmup_cap(0) == 20
    assert warmup_cap(1) == 35
    assert warmup_cap(2) == 50
    assert warmup_cap(10) == 170
    assert warmup_cap(15) == 200  # Capped at daily_send_cap
    assert warmup_cap(100) == 200


def test_send_window_across_timezones_and_weekends(monkeypatch):
    """Test timezone window calculations for various global regions."""
    monkeypatch.setattr(settings, "send_window_start_hour", 9)
    monkeypatch.setattr(settings, "send_window_end_hour", 17)
    monkeypatch.setattr(settings, "send_on_weekends", False)

    # Tuesday 14:00 Dublin -> In window
    tue_noon_utc = datetime(2026, 8, 25, 13, 0, tzinfo=timezone.utc)
    slot_dublin = in_send_window("Europe/Dublin", now=tue_noon_utc)
    assert slot_dublin.allowed is True

    # Tuesday 02:00 New York (06:00 UTC) -> Before business hours
    tue_early_utc = datetime(2026, 8, 25, 6, 0, tzinfo=timezone.utc)
    slot_ny = in_send_window("America/New_York", now=tue_early_utc)
    assert slot_ny.allowed is False
    assert "before local business hours" in slot_ny.reason

    # Saturday UTC -> Weekend
    sat_utc = datetime(2026, 8, 29, 14, 0, tzinfo=timezone.utc)
    slot_weekend = in_send_window("Europe/Dublin", now=sat_utc)
    assert slot_weekend.allowed is False
    assert "weekend in recipient timezone" in slot_weekend.reason


# =============================================================================
# 4. Autonomous End-to-End Workflow Test (Zero-Intervention)
# =============================================================================

def test_zero_intervention_autonomous_flow(db, transport):
    """Simulate 100% automated workflow:
    1. Import reference spreadsheet with custom leads
    2. System auto-qualifies and auto-approves
    3. Throttled dispatcher sends Step 0
    4. Recipient replies positively
    5. IMAP processor parses and matches reply
    6. System auto-classifies as POSITIVE, marks lead POSITIVE, updates stats
    7. System stops further automated follow-ups
    """
    capturing_tg = CapturingTelegram()
    telegram.set_client(capturing_tg)

    # 1. Ingest Reference Sheet
    csv_data = """Business Name,Email,Website,Phone,City,Country,Category,Contact Person
Emerald Roofing,info@emeraldroofing.ie,,+353 21 555 7788,Cork,IE,roofing,Liam Byrne
"""
    import_res = import_reference_sheet(
        db,
        csv_data,
        auto_qualify=True,
        auto_approve=True,  # zero intervention mode
    )
    assert import_res["leads_created"] == 1
    assert import_res["leads_approved"] == 1

    # Verify lead is immediately READY
    lead = db.query(Lead).filter(Lead.email == "info@emeraldroofing.ie").one()
    assert lead.status == LeadStatus.READY
    assert lead.approved is True

    # 2. Automated outreach batch fires
    batch_res = run_batch(db, limit=10)
    assert batch_res["sent"] == 1
    assert len(transport.sent) == 1

    db.refresh(lead)
    assert lead.status == LeadStatus.CONTACTED
    assert lead.last_contacted_at is not None
    original_msg = lead.messages[0]
    assert original_msg.status == MessageStatus.SENT

    # 3. Inbound reply arrives via IMAP
    reply_msg = MimeMessage()
    reply_msg["From"] = "Liam Byrne <info@emeraldroofing.ie>"
    reply_msg["To"] = "hello@yourstudio.com"
    reply_msg["Subject"] = "Re: Quick question about Emerald Roofing's website"
    reply_msg["In-Reply-To"] = original_msg.message_id
    reply_msg["References"] = original_msg.message_id
    reply_msg["Message-ID"] = "<reply-liam-999@emeraldroofing.ie>"
    reply_msg["Date"] = formatdate(usegmt=True)
    reply_msg.set_content("Hi Vivek,\n\nYes please, send over the mockup and pricing details!\n\nBest,\nLiam")

    parsed_reply = parse_message(reply_msg.as_bytes())
    process_res = process_inbound(db, parsed_reply)
    db.commit()

    # 4. Verification of understanding and state update
    assert process_res.stored is True
    assert process_res.classification == ReplyClass.POSITIVE
    assert process_res.notified is True

    db.refresh(lead)
    assert lead.status == LeadStatus.POSITIVE
    assert lead.reply_class == ReplyClass.POSITIVE
    assert lead.next_action_at is None  # automated followups stopped

    # 5. Telegram notification verified
    assert len(capturing_tg.messages) == 1
    assert "POSITIVE REPLY" in capturing_tg.messages[0]
    assert "Emerald Roofing" in capturing_tg.messages[0]
    assert "info@emeraldroofing.ie" in capturing_tg.messages[0]

    # 6. Daily stats rollup verified
    stats.rollup_day(db)
    dash = stats.dashboard(db, days=1)
    assert dash["totals"]["outbound"]["emails_sent"] == 1
    assert dash["totals"]["inbound"]["positive"] == 1

    telegram.set_client(None)
