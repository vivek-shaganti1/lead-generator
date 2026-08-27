"""Sending pace and timing.

Deliverability is mostly a function of restraint. Five independent limits:
  1. warmup ramp   - a new domain that sends 500 on day one goes straight to spam
  2. daily cap     - hard ceiling regardless of ramp
  3. campaign cap  - the optional per-campaign ceiling set from the dashboard
  4. per-domain    - never blast several mailboxes at one company on one day
  5. send window   - business hours in the *lead's* timezone, weekdays only
Plus a minimum gap between individual sends so the pattern doesn't look robotic.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import EmailMessage, Lead, MessageStatus
from app.utils import coerce_aware, domain_of, today_str, utcnow


@dataclass(slots=True)
class SendSlot:
    allowed: bool
    reason: str = ""
    retry_after: datetime | None = None

    def __bool__(self) -> bool:
        return self.allowed


# --------------------------------------------------------------------- warmup
def warmup_cap(day_index: int) -> int:
    """Volume allowed on day `day_index` (0-based) of the ramp."""
    if not settings.warmup_enabled:
        return settings.daily_send_cap
    if day_index < 0:
        day_index = 0
    ramped = settings.warmup_start + settings.warmup_increment * day_index
    return max(1, min(ramped, settings.daily_send_cap))


def sending_days_elapsed(db: Session) -> int:
    """Distinct UTC days on which we have actually delivered mail."""
    first = db.execute(
        select(func.min(EmailMessage.sent_at)).where(
            EmailMessage.status == MessageStatus.SENT,
            EmailMessage.dry_run.is_(False),
        )
    ).scalar()
    if first is None:
        return 0
    first = coerce_aware(first)
    return max(0, (utcnow().date() - first.date()).days)


def todays_cap(db: Session) -> int:
    return warmup_cap(sending_days_elapsed(db))


def sent_today(db: Session, now: datetime | None = None) -> int:
    now = now or utcnow()
    start = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(
        db.execute(
            select(func.count(EmailMessage.id)).where(
                EmailMessage.status == MessageStatus.SENT,
                EmailMessage.sent_at >= start,
            )
        ).scalar()
        or 0
    )


def sent_to_domain_today(
    db: Session, email: str, now: datetime | None = None, exclude_lead_id: int | None = None
) -> int:
    """How many *distinct leads* at this domain we have mailed today.

    Counting leads rather than messages is deliberate: the cap exists to stop us
    hitting several mailboxes at one company on one day. A follow-up to a lead we
    already contacted is a continuation of one conversation, not a second knock
    on the door, so `exclude_lead_id` keeps it out of the count.
    """
    domain = domain_of(email)
    if not domain:
        return 0
    now = now or utcnow()
    start = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = select(func.count(func.distinct(EmailMessage.lead_id))).where(
        EmailMessage.status == MessageStatus.SENT,
        EmailMessage.sent_at >= start,
        EmailMessage.to_email.like(f"%@{domain}"),
    )
    if exclude_lead_id is not None:
        stmt = stmt.where(EmailMessage.lead_id != exclude_lead_id)
    return int(db.execute(stmt).scalar() or 0)


def sent_for_campaign_today(
    db: Session, campaign_id: int, now: datetime | None = None
) -> int:
    """Messages delivered today on behalf of one campaign, follow-ups included."""
    now = now or utcnow()
    start = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(
        db.execute(
            select(func.count(EmailMessage.id))
            .join(Lead, Lead.id == EmailMessage.lead_id)
            .where(
                EmailMessage.status == MessageStatus.SENT,
                EmailMessage.sent_at >= start,
                Lead.campaign_id == campaign_id,
            )
        ).scalar()
        or 0
    )


def last_send_at(db: Session) -> datetime | None:
    return coerce_aware(
        db.execute(
            select(func.max(EmailMessage.sent_at)).where(EmailMessage.status == MessageStatus.SENT)
        ).scalar()
    )


# ---------------------------------------------------------------- send window
@lru_cache(maxsize=1)
def _tz_finder():
    from timezonefinder import TimezoneFinder

    return TimezoneFinder()


def timezone_for(lat: float | None, lon: float | None, fallback: str = "UTC") -> str:
    if lat is None or lon is None:
        return fallback
    try:
        return _tz_finder().timezone_at(lat=lat, lng=lon) or fallback
    except Exception:  # pragma: no cover - depends on optional data files
        return fallback


def local_now(tz_name: str, now: datetime | None = None) -> datetime:
    import pytz

    now = now or utcnow()
    try:
        tz = pytz.timezone(tz_name)
    except Exception:
        tz = pytz.UTC
    return now.astimezone(tz)


def in_send_window(tz_name: str, now: datetime | None = None) -> SendSlot:
    """Business hours where the recipient actually lives."""
    local = local_now(tz_name, now)
    if not settings.send_on_weekends and local.weekday() >= 5:
        days_ahead = 7 - local.weekday()
        nxt = (local + timedelta(days=days_ahead)).replace(
            hour=settings.send_window_start_hour, minute=0, second=0, microsecond=0
        )
        return SendSlot(False, "weekend in recipient timezone", nxt.astimezone(timezone.utc))
    if local.hour < settings.send_window_start_hour:
        nxt = local.replace(
            hour=settings.send_window_start_hour, minute=0, second=0, microsecond=0
        )
        return SendSlot(False, "before local business hours", nxt.astimezone(timezone.utc))
    if local.hour >= settings.send_window_end_hour:
        nxt = (local + timedelta(days=1)).replace(
            hour=settings.send_window_start_hour, minute=0, second=0, microsecond=0
        )
        return SendSlot(False, "after local business hours", nxt.astimezone(timezone.utc))
    return SendSlot(True)


# ------------------------------------------------------------------ combined
def check_send_slot(db: Session, lead, now: datetime | None = None) -> SendSlot:
    now = now or utcnow()

    # Deliverability comes first. Every other check below is about pacing; this
    # one is about whether we should be sending at all. A list that is bouncing
    # does not become safe by being sent more slowly.
    from app.services.outreach import circuit_breaker

    breaker = circuit_breaker.check(db)
    if breaker.open:
        return SendSlot(False, f"circuit breaker open — {breaker.reason}")

    cap = todays_cap(db)
    used = sent_today(db, now)
    if used >= cap:
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=1, second=0, microsecond=0)
        return SendSlot(False, f"daily cap reached ({used}/{cap})", tomorrow)

    campaign = getattr(lead, "campaign", None)
    campaign_cap = campaign.daily_cap if campaign else None
    if campaign_cap:
        campaign_used = sent_for_campaign_today(db, campaign.id, now)
        if campaign_used >= campaign_cap:
            tomorrow = (now + timedelta(days=1)).replace(
                hour=0, minute=1, second=0, microsecond=0
            )
            return SendSlot(
                False,
                f"campaign daily limit reached ({campaign_used}/{campaign_cap})",
                tomorrow,
            )

    domain_leads = sent_to_domain_today(db, lead.email, now, exclude_lead_id=lead.id)
    if domain_leads >= settings.max_per_domain_per_day:
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=1, second=0, microsecond=0)
        return SendSlot(False, "per-domain daily cap reached", tomorrow)

    last = last_send_at(db)
    if last is not None:
        gap = (now - last).total_seconds()
        if gap < settings.min_seconds_between_sends:
            return SendSlot(
                False, "minimum gap between sends",
                now + timedelta(seconds=settings.min_seconds_between_sends - gap),
            )

    business = getattr(lead, "business", None)
    tz_name = (business.timezone_name if business else None) or "UTC"
    return in_send_window(tz_name, now)


def capacity_remaining(db: Session, now: datetime | None = None) -> int:
    return max(0, todays_cap(db) - sent_today(db, now))


def usage_snapshot(db: Session) -> dict:
    cap = todays_cap(db)
    used = sent_today(db)
    return {
        "day": today_str(),
        "cap": cap,
        "sent": used,
        "remaining": max(0, cap - used),
        "warmup_day": sending_days_elapsed(db),
        "warmup_enabled": settings.warmup_enabled,
        "dry_run": settings.dry_run,
    }
