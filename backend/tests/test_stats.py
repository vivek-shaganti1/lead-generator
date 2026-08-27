from __future__ import annotations

from datetime import timedelta

from app.config import settings
from app.models import (
    DailyStat,
    EmailMessage,
    InboundMessage,
    LeadStatus,
    MessageStatus,
    ReplyClass,
)
from app.services import stats
from app.utils import today_str, utcnow
from tests.conftest import make_business, make_lead


def _message(db, lead, *, step=0, when=None, status=MessageStatus.SENT, opened=None):
    record = EmailMessage(
        lead_id=lead.id, step=step, to_email=lead.email,
        from_email=settings.sender_email, subject="s", body_text="b",
        status=status, sent_at=when or utcnow(), opened_at=opened,
        message_id=f"<m{lead.id}-{step}-{when}@x>",
    )
    db.add(record)
    db.commit()
    return record


def _inbound(db, lead, classification, when=None, mid=None):
    row = InboundMessage(
        lead_id=lead.id, message_id=mid or f"<in-{lead.id}-{classification.value}-{when}@x>",
        from_email=lead.email, subject="Re:", body_text="body",
        received_at=when or utcnow(), classification=classification, confidence=0.9,
    )
    db.add(row)
    db.commit()
    return row


# ----------------------------------------------------------------- daily math
def test_compute_day_counts_each_bucket(db, campaign):
    lead = make_lead(db, campaign=campaign)
    _message(db, lead, step=0)
    _message(db, lead, step=1)
    _message(db, lead, step=2, status=MessageStatus.FAILED)
    _inbound(db, lead, ReplyClass.POSITIVE)
    _inbound(db, lead, ReplyClass.NEGATIVE)
    _inbound(db, lead, ReplyClass.BOUNCE)
    _inbound(db, lead, ReplyClass.UNSUBSCRIBE)
    _inbound(db, lead, ReplyClass.AUTO_REPLY)

    day = stats.compute_day(db, today_str())
    assert day["emails_sent"] == 1
    assert day["followups_sent"] == 1
    assert day["failed"] == 1
    assert day["positive"] == 1
    assert day["negative"] == 1
    assert day["bounces"] == 1
    assert day["unsubscribes"] == 1
    # Bounces and auto-replies are not replies from a human.
    assert day["replies"] == 3


def test_compute_day_ignores_other_days(db, campaign):
    lead = make_lead(db, campaign=campaign)
    _message(db, lead, when=utcnow() - timedelta(days=3))
    assert stats.compute_day(db, today_str())["emails_sent"] == 0


def test_rollup_is_idempotent(db, campaign):
    lead = make_lead(db, campaign=campaign)
    _message(db, lead)
    stats.rollup_day(db)
    db.commit()
    stats.rollup_day(db)
    db.commit()
    assert db.query(DailyStat).count() == 1
    assert db.query(DailyStat).one().emails_sent == 1


def test_rollup_corrects_itself_after_new_data(db, campaign):
    lead = make_lead(db, campaign=campaign)
    stats.rollup_day(db)
    db.commit()
    _message(db, lead)
    stats.rollup_day(db)
    db.commit()
    assert db.query(DailyStat).one().emails_sent == 1


def test_timeseries_is_dense_and_ordered(db):
    series = stats.timeseries(db, days=7)
    assert len(series) == 7
    assert series[-1]["day"] == today_str()
    assert series == sorted(series, key=lambda row: row["day"])
    assert all(row["emails_sent"] == 0 for row in series)


# --------------------------------------------------------------------- totals
def test_totals_split_outbound_and_inbound(db, campaign):
    lead = make_lead(db, campaign=campaign)
    _message(db, lead, opened=utcnow())
    _inbound(db, lead, ReplyClass.POSITIVE)

    result = stats.totals(db)
    assert result["outbound"]["emails_sent"] == 1
    assert result["outbound"]["unique_contacted"] == 1
    assert result["outbound"]["opened"] == 1
    assert result["outbound"]["open_rate"] == 100.0
    assert result["inbound"]["positive"] == 1
    assert result["inbound"]["reply_rate"] == 100.0
    assert result["inbound"]["positive_rate"] == 100.0


def test_totals_handle_empty_database(db):
    result = stats.totals(db)
    assert result["outbound"]["emails_sent"] == 0
    assert result["inbound"]["reply_rate"] == 0.0   # no division by zero


def test_bounce_and_unsubscribe_rates(db, campaign):
    lead = make_lead(db, campaign=campaign)
    for i in range(4):
        _message(db, lead, step=i)
    _inbound(db, lead, ReplyClass.BOUNCE)
    result = stats.totals(db)
    assert result["inbound"]["bounce_rate"] == 25.0


# --------------------------------------------------------------------- funnel
def test_funnel_stages_descend(db, campaign):
    for i in range(3):
        make_business(db, source_id=f"n{i}")
    lead = make_lead(db, business=make_business(db, source_id="lead"), campaign=campaign)
    _message(db, lead)
    lead.replied_at = utcnow()
    lead.status = LeadStatus.POSITIVE
    db.commit()

    funnel = {row["stage"]: row["count"] for row in stats.funnel(db)}
    assert funnel["Discovered"] == 4
    assert funnel["Emailed"] == 1
    assert funnel["Replied"] == 1
    assert funnel["Positive"] == 1
    assert funnel["Won"] == 0


def test_funnel_percentages_present(db):
    make_business(db)
    rows = stats.funnel(db)
    assert rows[0]["pct_of_top"] == 100.0


# ---------------------------------------------------------------- breakdowns
def test_country_and_category_breakdown(db):
    make_business(db, source_id="n1", country_code="IE", category="restaurant")
    make_business(db, source_id="n2", country_code="IE", category="cafe",
                  phone="+353 21 555 0999")
    make_business(db, source_id="n3", country_code="IN", category="restaurant",
                  phone="+91 98765 43210")

    countries = {row["key"]: row["count"] for row in stats.country_breakdown(db)}
    categories = {row["key"]: row["count"] for row in stats.category_breakdown(db)}
    assert countries == {"IE": 2, "IN": 1}
    assert categories["restaurant"] == 2


def test_status_breakdown(db, campaign):
    make_lead(db, campaign=campaign, status=LeadStatus.READY)
    make_lead(db, business=make_business(db, source_id="n2"), campaign=campaign,
              status=LeadStatus.POSITIVE)
    breakdown = {row["status"]: row["count"] for row in stats.status_breakdown(db)}
    assert breakdown == {"READY": 1, "POSITIVE": 1}


# ------------------------------------------------------------------ dashboard
def test_dashboard_shape(db):
    payload = stats.dashboard(db, days=7)
    assert set(payload) == {
        "generated_at", "totals", "today", "sending", "funnel",
        "timeseries", "by_status", "by_country", "by_category",
    }
    assert len(payload["timeseries"]) == 7
    assert "outbound" in payload["totals"] and "inbound" in payload["totals"]


def test_digest_matches_compute_day(db):
    assert stats.digest_for(db) == stats.compute_day(db, today_str())
