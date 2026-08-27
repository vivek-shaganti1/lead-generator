"""Analytics.

Two shapes of number:
  * DailyStat rows - recomputed from the raw tables, so a re-run always converges
    on the truth even if a worker died mid-day.
  * live queries   - funnel and breakdowns, cheap enough to compute on demand.

The dashboard splits everything into OUTBOUND (what we sent) and INBOUND
(what came back), because they answer different questions.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Business,
    DailyStat,
    EmailMessage,
    InboundMessage,
    Lead,
    LeadStatus,
    MessageStatus,
    ReplyClass,
)
from app.utils import parse_day, utcnow


def _day_bounds(day: str) -> tuple[datetime, datetime]:
    d = parse_day(day)
    start = datetime.combine(d, time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def compute_day(db: Session, day: str) -> dict:
    """Recompute one UTC day's counters from source tables."""
    start, end = _day_bounds(day)

    def count(model, *conditions):
        return int(db.execute(select(func.count(model.id)).where(*conditions)).scalar() or 0)

    sent_window = (EmailMessage.sent_at >= start, EmailMessage.sent_at < end)
    inbound_window = (InboundMessage.received_at >= start, InboundMessage.received_at < end)

    emails_sent = count(EmailMessage, EmailMessage.status == MessageStatus.SENT,
                        EmailMessage.step == 0, *sent_window)
    followups = count(EmailMessage, EmailMessage.status == MessageStatus.SENT,
                      EmailMessage.step > 0, *sent_window)
    failed = count(EmailMessage, EmailMessage.status == MessageStatus.FAILED,
                   EmailMessage.updated_at >= start, EmailMessage.updated_at < end)
    opened = count(EmailMessage, EmailMessage.opened_at >= start, EmailMessage.opened_at < end)

    def inbound_count(*conditions):
        return count(InboundMessage, *inbound_window, *conditions)

    # "Replies" means a human wrote back: auto-responders and bounces don't count.
    replies = inbound_count(
        InboundMessage.classification.notin_([ReplyClass.BOUNCE, ReplyClass.AUTO_REPLY])
    )

    return {
        "day": day,
        "discovered": count(Business, Business.created_at >= start, Business.created_at < end),
        "leads_created": count(Lead, Lead.created_at >= start, Lead.created_at < end),
        "emails_sent": emails_sent,
        "followups_sent": followups,
        "failed": failed,
        "opened": opened,
        "replies": replies,
        "positive": inbound_count(InboundMessage.classification == ReplyClass.POSITIVE),
        "negative": inbound_count(InboundMessage.classification == ReplyClass.NEGATIVE),
        "neutral": inbound_count(
            InboundMessage.classification.in_(
                [ReplyClass.NEUTRAL, ReplyClass.QUESTION, ReplyClass.UNKNOWN]
            )
        ),
        "unsubscribes": inbound_count(InboundMessage.classification == ReplyClass.UNSUBSCRIBE),
        "bounces": inbound_count(InboundMessage.classification == ReplyClass.BOUNCE),
    }


def rollup_day(db: Session, day: str | None = None) -> DailyStat:
    day = day or utcnow().date().isoformat()
    values = compute_day(db, day)
    row = db.execute(select(DailyStat).where(DailyStat.day == day)).scalars().first()
    if row is None:
        row = DailyStat(day=day)
        db.add(row)
    for key, value in values.items():
        if key != "day":
            setattr(row, key, value)
    db.flush()
    return row


def rollup_range(db: Session, days: int = 30) -> list[DailyStat]:
    today = utcnow().date()
    return [rollup_day(db, (today - timedelta(days=offset)).isoformat())
            for offset in range(days)]


def timeseries(db: Session, days: int = 30) -> list[dict]:
    """Dense series (zero-filled) for charting, oldest first."""
    today = utcnow().date()
    start = today - timedelta(days=days - 1)
    rows = {
        r.day: r
        for r in db.execute(
            select(DailyStat).where(DailyStat.day >= start.isoformat())
        ).scalars().all()
    }
    out = []
    for offset in range(days):
        day = (start + timedelta(days=offset)).isoformat()
        row = rows.get(day)
        out.append(
            {
                "day": day,
                "emails_sent": row.emails_sent if row else 0,
                "followups_sent": row.followups_sent if row else 0,
                "opened": row.opened if row else 0,
                "replies": row.replies if row else 0,
                "positive": row.positive if row else 0,
                "negative": row.negative if row else 0,
                "neutral": row.neutral if row else 0,
                "bounces": row.bounces if row else 0,
                "unsubscribes": row.unsubscribes if row else 0,
                "leads_created": row.leads_created if row else 0,
                "discovered": row.discovered if row else 0,
            }
        )
    return out


def _pct(numerator: int, denominator: int) -> float:
    return round((numerator / denominator) * 100, 2) if denominator else 0.0


def totals(db: Session) -> dict:
    sent = int(db.execute(
        select(func.count(EmailMessage.id)).where(EmailMessage.status == MessageStatus.SENT)
    ).scalar() or 0)
    unique_contacted = int(db.execute(
        select(func.count(func.distinct(EmailMessage.lead_id)))
        .where(EmailMessage.status == MessageStatus.SENT)
    ).scalar() or 0)
    opened = int(db.execute(
        select(func.count(EmailMessage.id)).where(EmailMessage.opened_at.isnot(None))
    ).scalar() or 0)

    def inbound(*conditions):
        return int(db.execute(
            select(func.count(InboundMessage.id)).where(*conditions)
        ).scalar() or 0)

    replies = inbound(
        InboundMessage.classification.notin_([ReplyClass.BOUNCE, ReplyClass.AUTO_REPLY])
    )
    positive = inbound(InboundMessage.classification == ReplyClass.POSITIVE)
    negative = inbound(InboundMessage.classification == ReplyClass.NEGATIVE)
    bounces = inbound(InboundMessage.classification == ReplyClass.BOUNCE)
    unsubs = inbound(InboundMessage.classification == ReplyClass.UNSUBSCRIBE)

    businesses = int(db.execute(select(func.count(Business.id))).scalar() or 0)
    without_site = int(db.execute(
        select(func.count(Business.id)).where(Business.has_website.is_(False))
    ).scalar() or 0)
    leads = int(db.execute(select(func.count(Lead.id))).scalar() or 0)
    won = int(db.execute(
        select(func.count(Lead.id)).where(Lead.status == LeadStatus.WON)
    ).scalar() or 0)

    return {
        "outbound": {
            "businesses_discovered": businesses,
            "without_website": without_site,
            "leads": leads,
            "emails_sent": sent,
            "unique_contacted": unique_contacted,
            "opened": opened,
            "open_rate": _pct(opened, sent),
        },
        "inbound": {
            "replies": replies,
            "positive": positive,
            "negative": negative,
            "neutral": max(0, replies - positive - negative),
            "bounces": bounces,
            "unsubscribes": unsubs,
            "reply_rate": _pct(replies, unique_contacted),
            "positive_rate": _pct(positive, replies),
            "bounce_rate": _pct(bounces, sent),
            "unsubscribe_rate": _pct(unsubs, sent),
            "won": won,
        },
    }


def funnel(db: Session) -> list[dict]:
    businesses = int(db.execute(select(func.count(Business.id))).scalar() or 0)
    no_site = int(db.execute(
        select(func.count(Business.id)).where(Business.has_website.is_(False))
    ).scalar() or 0)
    leads = int(db.execute(select(func.count(Lead.id))).scalar() or 0)
    contacted = int(db.execute(
        select(func.count(func.distinct(EmailMessage.lead_id)))
        .where(EmailMessage.status == MessageStatus.SENT)
    ).scalar() or 0)
    replied = int(db.execute(
        select(func.count(Lead.id)).where(Lead.replied_at.isnot(None))
    ).scalar() or 0)
    positive = int(db.execute(
        select(func.count(Lead.id)).where(Lead.status.in_([LeadStatus.POSITIVE, LeadStatus.WON]))
    ).scalar() or 0)
    won = int(db.execute(
        select(func.count(Lead.id)).where(Lead.status == LeadStatus.WON)
    ).scalar() or 0)

    stages = [
        ("Discovered", businesses),
        ("No usable website", no_site),
        ("Contactable leads", leads),
        ("Emailed", contacted),
        ("Replied", replied),
        ("Positive", positive),
        ("Won", won),
    ]
    top = stages[0][1] or 1
    return [
        {"stage": name, "count": value, "pct_of_top": _pct(value, top)}
        for name, value in stages
    ]


def status_breakdown(db: Session) -> list[dict]:
    rows = db.execute(
        select(Lead.status, func.count(Lead.id)).group_by(Lead.status)
    ).all()
    return [{"status": s.value if hasattr(s, "value") else str(s), "count": c} for s, c in rows]


def _group_breakdown(db: Session, column, limit: int = 15) -> list[dict]:
    rows = db.execute(
        select(column, func.count(Business.id))
        .where(column.isnot(None))
        .group_by(column)
        .order_by(func.count(Business.id).desc())
        .limit(limit)
    ).all()
    return [{"key": key, "count": count} for key, count in rows]


def country_breakdown(db: Session, limit: int = 15) -> list[dict]:
    return _group_breakdown(db, Business.country_code, limit)


def category_breakdown(db: Session, limit: int = 15) -> list[dict]:
    return _group_breakdown(db, Business.category, limit)


def today_snapshot(db: Session) -> dict:
    return compute_day(db, utcnow().date().isoformat())


def dashboard(db: Session, days: int = 30) -> dict:
    from app.services.outreach.throttle import usage_snapshot

    return {
        "generated_at": utcnow().isoformat(),
        "totals": totals(db),
        "today": today_snapshot(db),
        "sending": usage_snapshot(db),
        "funnel": funnel(db),
        "timeseries": timeseries(db, days),
        "by_status": status_breakdown(db),
        "by_country": country_breakdown(db),
        "by_category": category_breakdown(db),
    }


def digest_for(db: Session, day: str | None = None) -> dict:
    day = day or utcnow().date().isoformat()
    return compute_day(db, day)
