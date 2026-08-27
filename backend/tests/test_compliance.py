from __future__ import annotations

from app.config import settings
from app.models import LeadStatus, Suppression
from app.services.compliance.policy import (
    can_contact,
    country_allowed,
    enforce,
    is_suppressed,
    suppress,
)
from app.services.compliance.unsubscribe import (
    apply_unsubscribe,
    list_unsubscribe_headers,
    unsubscribe_url,
)
from tests.conftest import make_business, make_lead


# ------------------------------------------------------------------- country
def test_blocked_countries_are_rejected():
    assert country_allowed("DE").allowed is False
    assert "prior consent" in country_allowed("DE").reason
    assert country_allowed("de").allowed is False


def test_allowed_country_passes():
    assert country_allowed("IE").allowed is True
    assert country_allowed("IN").allowed is True


def test_unknown_country_is_rejected():
    decision = country_allowed(None)
    assert decision.allowed is False
    assert "manual review" in decision.reason


# --------------------------------------------------------------- suppression
def test_suppress_is_idempotent(db):
    first = suppress(db, "a@shop.ie", reason="bounce")
    second = suppress(db, "A@SHOP.IE", reason="bounce")
    db.commit()
    assert first.id == second.id
    assert db.query(Suppression).count() == 1


def test_domain_suppression_blocks_every_mailbox(db):
    suppress(db, "shop.ie", reason="asked us to stop", kind="domain")
    db.commit()
    assert is_suppressed(db, "anyone@shop.ie") is not None
    assert is_suppressed(db, "anyone@other.ie") is None


# ------------------------------------------------------------------ can_contact
def test_can_contact_allows_approved_lead(db, campaign):
    lead = make_lead(db, campaign=campaign, approved=True)
    assert can_contact(db, lead).allowed is True


def test_can_contact_requires_approval(db, campaign):
    lead = make_lead(db, campaign=campaign, approved=False,
                     status=LeadStatus.NEEDS_APPROVAL)
    decision = can_contact(db, lead)
    assert decision.allowed is False
    assert "approval" in decision.reason


def test_can_contact_blocks_suppressed_address(db, campaign):
    lead = make_lead(db, campaign=campaign)
    suppress(db, lead.email, reason="hard bounce")
    db.commit()
    assert can_contact(db, lead).allowed is False


def test_can_contact_blocks_terminal_states(db, campaign):
    lead = make_lead(db, campaign=campaign, status=LeadStatus.UNSUBSCRIBED)
    assert can_contact(db, lead).allowed is False


def test_can_contact_blocks_blocked_country(db, campaign):
    business = make_business(db, country_code="DE", source_id="node/de")
    lead = make_lead(db, business=business, campaign=campaign)
    assert can_contact(db, lead).allowed is False


def test_can_contact_blocks_unsafe_mailbox(db, campaign):
    lead = make_lead(db, campaign=campaign, email="noreply@shop.ie")
    assert can_contact(db, lead).allowed is False


def test_enforce_marks_lead_do_not_contact_on_hard_block(db, campaign):
    lead = make_lead(db, campaign=campaign)
    suppress(db, lead.email, reason="hard bounce")
    db.commit()
    enforce(db, lead)
    db.commit()
    assert lead.status == LeadStatus.DO_NOT_CONTACT
    assert "suppressed" in lead.block_reason


def test_enforce_clears_block_reason_when_allowed(db, campaign):
    lead = make_lead(db, campaign=campaign, block_reason="stale reason")
    enforce(db, lead)
    assert lead.block_reason is None


# ----------------------------------------------------------------- unsubscribe
def test_unsubscribe_url_and_headers():
    headers = list_unsubscribe_headers("tok123")
    assert unsubscribe_url("tok123") in headers["List-Unsubscribe"]
    assert headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert "mailto:" in headers["List-Unsubscribe"]


def test_apply_unsubscribe_suppresses_and_stops_sequence(db, campaign):
    lead = make_lead(db, campaign=campaign, next_action_at=None)
    apply_unsubscribe(db, lead)
    db.commit()
    assert lead.status == LeadStatus.UNSUBSCRIBED
    assert lead.next_action_at is None
    assert is_suppressed(db, lead.email) is not None


# ------------------------------------------------------------------ retention
def test_retention_redacts_old_inbound(db, campaign):
    from datetime import timedelta

    from app.models import InboundMessage, ReplyClass
    from app.services.compliance.retention import redact_inbound_bodies
    from app.utils import utcnow

    lead = make_lead(db, campaign=campaign)
    db.add(InboundMessage(
        lead_id=lead.id, message_id="<old@x>", from_email="a@b.ie",
        subject="hi", body_text="personal data here",
        received_at=utcnow() - timedelta(days=200),
        classification=ReplyClass.NEUTRAL,
    ))
    db.commit()
    assert redact_inbound_bodies(db, days=90) == 1
    db.commit()
    assert db.query(InboundMessage).one().body_text == ""


def test_retention_purges_uncontacted_businesses(db):
    from datetime import timedelta

    from app.models import Business
    from app.services.compliance.retention import purge_uncontacted
    from app.utils import utcnow

    stale = make_business(db, source_id="node/stale")
    stale.created_at = utcnow() - timedelta(days=400)
    db.commit()
    assert purge_uncontacted(db, days=180) == 1
    db.commit()
    assert db.query(Business).count() == 0


def test_blocked_country_list_covers_key_eu_states():
    assert {"DE", "IT", "ES", "PL"} <= settings.blocked_country_set
