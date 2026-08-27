from __future__ import annotations

from datetime import timedelta

from app.config import settings
from app.models import EmailMessage, Event, LeadStatus, MessageStatus
from app.services.compliance.policy import suppress
from app.services.outreach.dispatcher import (
    approve_lead,
    due_leads,
    presence_of,
    run_batch,
    send_lead,
)
from app.services.outreach.sender import SendResult
from app.utils import utcnow
from tests.conftest import make_business, make_lead


# ------------------------------------------------------------------- presence
def test_presence_of_each_case(db):
    missing = make_business(db, source_id="n1", website=None)
    social = make_business(db, source_id="n2", website="https://facebook.com/x")
    broken = make_business(db, source_id="n3", website="https://x.ie", website_alive=False)
    live = make_business(db, source_id="n4", website="https://x.ie",
                         website_alive=True, has_website=True)
    assert presence_of(missing) == "MISSING"
    assert presence_of(social) == "SOCIAL"
    assert presence_of(broken) == "BROKEN"
    assert presence_of(live) == "LIVE"


# ----------------------------------------------------------------- first send
def test_send_lead_delivers_and_updates_state(db, campaign, transport):
    lead = make_lead(db, campaign=campaign)
    outcome = send_lead(db, lead)
    db.commit()

    assert outcome.sent is True
    assert len(transport.sent) == 1

    message = transport.sent[0]
    assert message["To"] == lead.email
    assert "Rossi's Trattoria" in message["Subject"]
    assert message["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert lead.unsubscribe_token in message["List-Unsubscribe"]
    assert message["Reply-To"]

    assert lead.status == LeadStatus.CONTACTED
    assert lead.last_contacted_at is not None
    assert lead.next_action_at is not None      # follow-up scheduled

    record = db.query(EmailMessage).one()
    assert record.status == MessageStatus.SENT
    assert record.step == 0
    assert record.dry_run is True
    assert record.message_id


def test_send_includes_tracking_pixel(db, campaign, transport):
    lead = make_lead(db, campaign=campaign)
    send_lead(db, lead)
    db.commit()
    html = transport.sent[0].get_body(preferencelist=("html",)).get_content()
    assert "/t/o/" in html


def test_track_opens_false_omits_the_pixel(db, campaign, transport, monkeypatch):
    """TRACK_OPENS is documented as a kill switch; it has to actually reach the send."""
    monkeypatch.setattr(settings, "track_opens", False)
    lead = make_lead(db, campaign=campaign)
    send_lead(db, lead)
    db.commit()
    html = transport.sent[0].get_body(preferencelist=("html",)).get_content()
    assert "/t/o/" not in html


def test_send_is_idempotent_for_the_same_step(db, campaign, transport):
    lead = make_lead(db, campaign=campaign)
    assert send_lead(db, lead).sent is True
    db.commit()
    # A second call must not fire the follow-up early...
    second = send_lead(db, lead)
    db.commit()
    assert second.sent is False
    assert "not due yet" in second.reason

    # ...and re-attempting step 0 itself must not double-send.
    lead.status = LeadStatus.READY
    db.commit()
    third = send_lead(db, lead)
    db.commit()
    assert third.sent is False
    assert "already sent" in third.reason
    assert len(transport.sent) == 1


def test_send_blocked_by_compliance(db, campaign, transport):
    lead = make_lead(db, campaign=campaign)
    suppress(db, lead.email, reason="hard bounce")
    db.commit()
    outcome = send_lead(db, lead)
    db.commit()
    assert outcome.sent is False
    assert transport.sent == []
    assert lead.status == LeadStatus.DO_NOT_CONTACT


def test_send_blocked_for_unapproved_lead(db, campaign, transport):
    lead = make_lead(db, campaign=campaign, approved=False,
                     status=LeadStatus.NEEDS_APPROVAL)
    outcome = send_lead(db, lead)
    assert outcome.sent is False
    assert "approval" in outcome.reason
    assert transport.sent == []


def test_send_records_failure(db, campaign, monkeypatch, transport):
    monkeypatch.setattr(
        transport, "send",
        lambda email: SendResult(ok=False, error="connect: refused"),
    )
    lead = make_lead(db, campaign=campaign)
    outcome = send_lead(db, lead)
    db.commit()
    assert outcome.sent is False
    record = db.query(EmailMessage).one()
    assert record.status == MessageStatus.FAILED
    assert record.error == "connect: refused"
    assert lead.status == LeadStatus.READY   # stays eligible for a retry


def test_refused_recipient_marks_lead_bounced(db, campaign, monkeypatch, transport):
    monkeypatch.setattr(
        transport, "send",
        lambda email: SendResult(ok=False, error="recipient refused: no such user"),
    )
    lead = make_lead(db, campaign=campaign)
    send_lead(db, lead)
    db.commit()
    assert lead.status == LeadStatus.BOUNCED


def test_render_failure_marks_lead_failed(db, campaign, transport):
    campaign.body_template = "Hello {{ nonexistent_variable }}"
    db.commit()
    lead = make_lead(db, campaign=campaign)
    outcome = send_lead(db, lead)
    db.commit()
    assert outcome.sent is False
    assert lead.status == LeadStatus.FAILED
    assert transport.sent == []


# ------------------------------------------------------------------ follow-ups
def test_followup_threads_onto_the_original_message(db, campaign, transport, monkeypatch):
    monkeypatch.setattr(settings, "followup_delays_days", "3,7")
    monkeypatch.setattr(settings, "max_followups", 2)
    lead = make_lead(db, campaign=campaign)

    send_lead(db, lead)
    db.commit()
    first_id = transport.sent[0]["Message-ID"]

    lead.next_action_at = utcnow() - timedelta(seconds=1)
    db.commit()
    outcome = send_lead(db, lead)
    db.commit()

    assert outcome.sent and outcome.step == 1
    followup = transport.sent[1]
    assert followup["In-Reply-To"] == first_id
    assert followup["References"] == first_id
    assert followup["Subject"].startswith("Re:")
    assert lead.status == LeadStatus.FOLLOWED_UP
    assert lead.followups_sent == 1


def test_followup_sequence_stops_at_max(db, campaign, transport, monkeypatch):
    monkeypatch.setattr(settings, "followup_delays_days", "1,2")
    monkeypatch.setattr(settings, "max_followups", 2)
    lead = make_lead(db, campaign=campaign)

    for _ in range(3):
        lead.next_action_at = utcnow() - timedelta(seconds=1)
        db.commit()
        send_lead(db, lead)
        db.commit()

    assert lead.followups_sent == 2
    assert lead.next_action_at is None
    assert len(transport.sent) == 3   # initial + 2 follow-ups


def test_followup_delay_schedule(db, campaign, transport, monkeypatch):
    monkeypatch.setattr(settings, "followup_delays_days", "3,7")
    lead = make_lead(db, campaign=campaign)
    send_lead(db, lead)
    db.commit()
    delta = lead.next_action_at - utcnow()
    assert timedelta(days=2, hours=23) < delta < timedelta(days=3, minutes=1)


# ------------------------------------------------------------------ selection
def test_due_leads_orders_by_score(db, campaign):
    low = make_lead(db, business=make_business(db, source_id="n1"),
                    campaign=campaign, score=10)
    high = make_lead(db, business=make_business(db, source_id="n2"),
                     campaign=campaign, score=95)
    assert [lead.id for lead in due_leads(db)] == [high.id, low.id]


def test_due_leads_excludes_unapproved(db, campaign):
    make_lead(db, campaign=campaign, approved=False, status=LeadStatus.NEEDS_APPROVAL)
    assert due_leads(db) == []


def test_due_leads_excludes_future_followups(db, campaign):
    make_lead(db, campaign=campaign, status=LeadStatus.CONTACTED,
              next_action_at=utcnow() + timedelta(days=2))
    assert due_leads(db) == []


def test_due_leads_includes_overdue_followups(db, campaign):
    lead = make_lead(db, campaign=campaign, status=LeadStatus.CONTACTED,
                     next_action_at=utcnow() - timedelta(days=1))
    assert [item.id for item in due_leads(db)] == [lead.id]


def test_due_leads_excludes_replied(db, campaign):
    make_lead(db, campaign=campaign, status=LeadStatus.POSITIVE,
              next_action_at=utcnow() - timedelta(days=1))
    assert due_leads(db) == []


# ---------------------------------------------------------------------- batch
def test_run_batch_sends_everything_eligible(db, campaign, transport):
    for i in range(3):
        make_lead(db, business=make_business(db, source_id=f"n{i}"), campaign=campaign,
                  email=f"a{i}@shop{i}.ie")
    result = run_batch(db, limit=10)
    assert result["sent"] == 3
    assert len(transport.sent) == 3


def test_run_batch_stops_when_cap_hit(db, campaign, transport, monkeypatch):
    monkeypatch.setattr(settings, "warmup_enabled", False)
    monkeypatch.setattr(settings, "daily_send_cap", 2)
    for i in range(5):
        make_lead(db, business=make_business(db, source_id=f"n{i}"), campaign=campaign,
                  email=f"a{i}@shop{i}.ie")
    result = run_batch(db, limit=10)
    assert result["sent"] == 2
    assert len(transport.sent) == 2


def test_run_batch_respects_per_domain_cap(db, campaign, transport, monkeypatch):
    monkeypatch.setattr(settings, "max_per_domain_per_day", 1)
    for i in range(3):
        make_lead(db, business=make_business(db, source_id=f"n{i}"), campaign=campaign,
                  email=f"a{i}@sameshop.ie")
    result = run_batch(db, limit=10)
    assert result["sent"] == 1


def test_run_batch_counts_campaign_limit_as_blocked_not_failed(db, campaign, transport):
    """A campaign limit pauses that campaign; it is not a send failure."""
    campaign.daily_cap = 1
    db.commit()
    for i in range(3):
        make_lead(db, business=make_business(db, source_id=f"n{i}"), campaign=campaign,
                  email=f"a{i}@shop{i}.ie")
    result = run_batch(db, limit=10)
    assert result["sent"] == 1
    assert result["blocked"] == 2
    assert result["failed"] == 0


# -------------------------------------------------------------------- approval
def test_approve_lead_moves_to_ready(db, campaign):
    lead = make_lead(db, campaign=campaign, approved=False,
                     status=LeadStatus.NEEDS_APPROVAL)
    approve_lead(db, lead, True)
    db.commit()
    assert lead.status == LeadStatus.READY
    assert lead.approved is True
    assert lead.next_action_at is not None


def test_unapprove_lead_moves_back(db, campaign):
    lead = make_lead(db, campaign=campaign, approved=True, status=LeadStatus.READY)
    approve_lead(db, lead, False)
    db.commit()
    assert lead.status == LeadStatus.NEEDS_APPROVAL


def test_events_are_written_for_audit(db, campaign, transport):
    lead = make_lead(db, campaign=campaign)
    send_lead(db, lead)
    db.commit()
    types = {event.type for event in db.query(Event).all()}
    assert "outreach.sent" in types
