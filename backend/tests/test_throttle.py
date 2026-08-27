from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.config import settings
from app.models import EmailMessage, MessageStatus
from app.services.discovery.overpass import _Throttle
from app.services.outreach.throttle import (
    capacity_remaining,
    check_send_slot,
    in_send_window,
    sending_days_elapsed,
    sent_today,
    sent_to_domain_today,
    todays_cap,
    usage_snapshot,
    warmup_cap,
)
from app.utils import utcnow
from tests.conftest import make_business, make_lead


def _sent_message(db, lead, when=None, step=0, to=None):
    message = EmailMessage(
        lead_id=lead.id, step=step, to_email=to or lead.email,
        from_email=settings.sender_email, subject="s", body_text="b",
        status=MessageStatus.SENT, sent_at=when or utcnow(),
        message_id=f"<m{lead.id}-{step}-{when}@x>",
    )
    db.add(message)
    db.commit()
    return message


# --------------------------------------------------------------------- warmup
def test_warmup_ramps_then_plateaus(monkeypatch):
    monkeypatch.setattr(settings, "warmup_enabled", True)
    monkeypatch.setattr(settings, "warmup_start", 20)
    monkeypatch.setattr(settings, "warmup_increment", 15)
    monkeypatch.setattr(settings, "daily_send_cap", 100)
    assert warmup_cap(0) == 20
    assert warmup_cap(1) == 35
    assert warmup_cap(2) == 50
    assert warmup_cap(20) == 100      # never exceeds the hard cap
    assert warmup_cap(-5) == 20       # defensive


def test_warmup_disabled_uses_full_cap(monkeypatch):
    monkeypatch.setattr(settings, "warmup_enabled", False)
    monkeypatch.setattr(settings, "daily_send_cap", 250)
    assert warmup_cap(0) == 250


def test_sending_days_elapsed_counts_from_first_real_send(db, campaign, monkeypatch):
    lead = make_lead(db, campaign=campaign)
    assert sending_days_elapsed(db) == 0
    message = _sent_message(db, lead, when=utcnow() - timedelta(days=3))
    message.dry_run = False
    db.commit()
    assert sending_days_elapsed(db) == 3


def test_dry_run_sends_do_not_advance_the_warmup(db, campaign):
    lead = make_lead(db, campaign=campaign)
    message = _sent_message(db, lead, when=utcnow() - timedelta(days=5))
    message.dry_run = True
    db.commit()
    assert sending_days_elapsed(db) == 0


# ---------------------------------------------------------------------- caps
def test_sent_today_counts_only_today(db, campaign):
    lead = make_lead(db, campaign=campaign)
    _sent_message(db, lead, when=utcnow())
    _sent_message(db, lead, when=utcnow() - timedelta(days=2), step=1)
    assert sent_today(db) == 1


def test_per_domain_counter_counts_distinct_leads(db, campaign):
    first = make_lead(db, campaign=campaign, email="a@shop.ie")
    second = make_lead(db, business=make_business(db, source_id="n2"),
                       campaign=campaign, email="b@shop.ie")
    third = make_lead(db, business=make_business(db, source_id="n3"),
                      campaign=campaign, email="c@other.ie")
    _sent_message(db, first, to="a@shop.ie")
    _sent_message(db, second, to="b@shop.ie")
    _sent_message(db, third, to="c@other.ie")
    assert sent_to_domain_today(db, "d@shop.ie") == 2
    assert sent_to_domain_today(db, "d@other.ie") == 1


def test_per_domain_counter_ignores_the_leads_own_followups(db, campaign):
    """Follow-ups continue one conversation; they must not consume the cap."""
    lead = make_lead(db, campaign=campaign, email="a@shop.ie")
    _sent_message(db, lead, to="a@shop.ie")
    _sent_message(db, lead, to="a@shop.ie", step=1)
    assert sent_to_domain_today(db, lead.email, exclude_lead_id=lead.id) == 0


def test_daily_cap_blocks_further_sends(db, campaign, monkeypatch):
    monkeypatch.setattr(settings, "warmup_enabled", False)
    monkeypatch.setattr(settings, "daily_send_cap", 1)
    lead = make_lead(db, campaign=campaign)
    _sent_message(db, lead)
    slot = check_send_slot(db, lead)
    assert slot.allowed is False
    assert "daily cap" in slot.reason
    assert capacity_remaining(db) == 0


def test_campaign_daily_cap_blocks(db, campaign):
    """Campaign.daily_cap is editable from the dashboard, so it has to bite."""
    campaign.daily_cap = 1
    db.commit()
    lead = make_lead(db, campaign=campaign)
    other = make_lead(db, business=make_business(db, source_id="node/2"),
                      campaign=campaign, email="b@shop.ie")
    _sent_message(db, lead)

    slot = check_send_slot(db, other)
    assert slot.allowed is False
    assert "campaign daily limit" in slot.reason


def test_campaign_without_a_cap_is_unlimited(db, campaign):
    lead = make_lead(db, campaign=campaign)
    other = make_lead(db, business=make_business(db, source_id="node/3"),
                      campaign=campaign, email="c@shop.ie")
    _sent_message(db, lead)
    assert campaign.daily_cap is None
    assert check_send_slot(db, other).allowed is True


def test_campaign_cap_counts_only_its_own_campaign(db, campaign):
    from app.models import Campaign

    campaign.daily_cap = 1
    other_campaign = Campaign(name="Second", subject_template="s", body_template="b")
    db.add(other_campaign)
    db.commit()

    lead = make_lead(db, campaign=campaign)
    _sent_message(db, lead)
    elsewhere = make_lead(db, business=make_business(db, source_id="node/4"),
                          campaign=other_campaign, email="d@shop.ie")
    assert check_send_slot(db, elsewhere).allowed is True


def test_per_domain_cap_blocks(db, campaign, monkeypatch):
    monkeypatch.setattr(settings, "max_per_domain_per_day", 1)
    lead = make_lead(db, campaign=campaign, email="a@shop.ie")
    other = make_lead(db, business=make_business(db, source_id="node/2"),
                      campaign=campaign, email="b@shop.ie")
    _sent_message(db, lead)
    slot = check_send_slot(db, other)
    assert slot.allowed is False
    assert "per-domain" in slot.reason


def test_minimum_gap_between_sends(db, campaign, monkeypatch):
    monkeypatch.setattr(settings, "min_seconds_between_sends", 600)
    lead = make_lead(db, campaign=campaign)
    _sent_message(db, lead)
    slot = check_send_slot(db, lead)
    assert slot.allowed is False
    assert "minimum gap" in slot.reason
    assert slot.retry_after > utcnow()


# -------------------------------------------------------------- send windows
@pytest.mark.parametrize("hour,allowed", [(6, False), (9, True), (12, True), (17, False),
                                          (23, False)])
def test_send_window_respects_local_business_hours(monkeypatch, hour, allowed):
    monkeypatch.setattr(settings, "send_window_start_hour", 9)
    monkeypatch.setattr(settings, "send_window_end_hour", 17)
    monkeypatch.setattr(settings, "send_on_weekends", True)
    now = datetime(2026, 8, 26, hour, 0, tzinfo=timezone.utc)  # a Wednesday
    assert in_send_window("UTC", now).allowed is allowed


def test_send_window_uses_recipient_timezone(monkeypatch):
    monkeypatch.setattr(settings, "send_window_start_hour", 9)
    monkeypatch.setattr(settings, "send_window_end_hour", 17)
    monkeypatch.setattr(settings, "send_on_weekends", True)
    # 05:00 UTC is 10:30 in Kolkata - fine there, too early in London.
    now = datetime(2026, 8, 26, 5, 0, tzinfo=timezone.utc)
    assert in_send_window("Asia/Kolkata", now).allowed is True
    assert in_send_window("Europe/London", now).allowed is False


def test_weekend_is_skipped(monkeypatch):
    monkeypatch.setattr(settings, "send_on_weekends", False)
    saturday = datetime(2026, 8, 29, 11, 0, tzinfo=timezone.utc)
    slot = in_send_window("UTC", saturday)
    assert slot.allowed is False
    assert "weekend" in slot.reason
    assert slot.retry_after.weekday() == 0   # next Monday


def test_out_of_window_retry_time_is_next_open(monkeypatch):
    monkeypatch.setattr(settings, "send_window_start_hour", 9)
    monkeypatch.setattr(settings, "send_window_end_hour", 17)
    monkeypatch.setattr(settings, "send_on_weekends", True)
    evening = datetime(2026, 8, 26, 20, 0, tzinfo=timezone.utc)
    slot = in_send_window("UTC", evening)
    assert slot.retry_after.day == 27 and slot.retry_after.hour == 9


def test_unknown_timezone_falls_back_to_utc(monkeypatch):
    monkeypatch.setattr(settings, "send_on_weekends", True)
    monkeypatch.setattr(settings, "send_window_start_hour", 0)
    monkeypatch.setattr(settings, "send_window_end_hour", 24)
    assert in_send_window("Not/AZone").allowed is True


# ------------------------------------------------------------------ throttle
def test_process_throttle_waits_the_minimum_interval():
    slept = []
    clock = {"t": 0.0}
    throttle = _Throttle(min_interval=5.0)

    def sleeper(seconds):
        slept.append(seconds)
        clock["t"] += seconds

    def now():
        return clock["t"]

    throttle.wait(sleeper, now)      # first call never waits
    assert slept == []
    clock["t"] += 1.0
    throttle.wait(sleeper, now)
    assert slept and pytest.approx(slept[0], abs=0.01) == 4.0


def test_usage_snapshot_shape(db):
    snapshot = usage_snapshot(db)
    assert set(snapshot) == {"day", "cap", "sent", "remaining", "warmup_day",
                             "warmup_enabled", "dry_run"}
    assert snapshot["cap"] == todays_cap(db)
