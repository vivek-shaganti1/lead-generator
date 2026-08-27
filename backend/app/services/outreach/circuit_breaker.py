"""Stop sending automatically when the bounce rate says something is wrong.

What this would have prevented
------------------------------
On 27 Aug 2026 the account sent 464 messages in a single day. 42 of the 112
unique addresses hard-bounced — a 37.5% rate against a healthy ceiling of about
2%. Nothing in the pipeline noticed. Every guard that existed was a *volume*
guard (daily cap, per-domain cap, send window); none of them looked at whether
the mail was actually arriving.

Volume limits answer "are we sending too fast". They cannot answer "should we be
sending at all". A pipeline aimed at a bad list will happily send its full daily
allowance into a wall, day after day, until the provider disables the account.

How it works
------------
Before any send, :func:`check` measures the hard-bounce rate over recent
outbound mail. Above ``MAX_BOUNCE_RATE`` the breaker opens and sending stops
until a human clears it. Opening is deliberately sticky: it writes a flag to
``app_settings`` rather than recomputing each time, so a breaker cannot flap
back closed simply because a few good sends diluted the average.

The sample floor matters. Two bounces out of three sends is 67%, but proves
nothing; ``BOUNCE_RATE_MIN_SAMPLE`` stops the breaker firing on noise while a
warmup is still finding its feet.

Reputation damage is slow to accrue and slow to undo, so the breaker is biased
towards stopping early: a false pause costs a day of outreach, while a missed
one costs the sending account.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.logging_config import get_logger
from app.models import AppSetting, EmailMessage, Lead, LeadStatus, MessageStatus
from app.utils import utcnow

log = get_logger(__name__)

BREAKER_KEY = "outreach.circuit_breaker"
LOOKBACK_DAYS = 14


@dataclass(slots=True)
class BreakerState:
    open: bool
    reason: str = ""
    bounce_rate: float = 0.0
    sample: int = 0
    bounced: int = 0

    def __bool__(self) -> bool:
        """Truthy means *safe to send*."""
        return not self.open

    def as_dict(self) -> dict:
        return {
            "open": self.open,
            "reason": self.reason,
            "bounce_rate": round(self.bounce_rate, 4),
            "sample": self.sample,
            "bounced": self.bounced,
            "threshold": settings.max_bounce_rate,
            "min_sample": settings.bounce_rate_min_sample,
        }


def _get_flag(db: Session) -> AppSetting | None:
    return db.scalar(select(AppSetting).where(AppSetting.key == BREAKER_KEY))


def measure(db: Session, *, lookback_days: int = LOOKBACK_DAYS) -> tuple[int, int, float]:
    """Return ``(sample, bounced, rate)`` over recent real sends.

    Dry-run messages are excluded — they never touched a mail server, so they
    can neither bounce nor prove that anything is deliverable. Counting them
    would dilute the rate towards zero exactly when a big dry-run batch precedes
    a live one.
    """
    since = utcnow() - timedelta(days=lookback_days)

    sample = db.scalar(
        select(func.count())
        .select_from(EmailMessage)
        .where(
            EmailMessage.dry_run.is_(False),
            EmailMessage.sent_at.is_not(None),
            EmailMessage.sent_at >= since,
        )
    ) or 0

    if not sample:
        return 0, 0, 0.0

    # A bounce is recorded either on the message or, when the DSN arrived out of
    # band and was reconciled from the mailbox, on the lead.
    bounced_messages = db.scalar(
        select(func.count())
        .select_from(EmailMessage)
        .where(
            EmailMessage.dry_run.is_(False),
            EmailMessage.sent_at >= since,
            EmailMessage.status == MessageStatus.BOUNCED,
        )
    ) or 0

    bounced_leads = db.scalar(
        select(func.count(func.distinct(EmailMessage.lead_id)))
        .select_from(EmailMessage)
        .join(Lead, Lead.id == EmailMessage.lead_id)
        .where(
            EmailMessage.dry_run.is_(False),
            EmailMessage.sent_at >= since,
            Lead.status == LeadStatus.BOUNCED,
        )
    ) or 0

    bounced = max(bounced_messages, bounced_leads)
    return sample, bounced, (bounced / sample if sample else 0.0)


def check(db: Session, *, lookback_days: int = LOOKBACK_DAYS) -> BreakerState:
    """Is it safe to send right now?"""
    flag = _get_flag(db)
    if flag is not None and str(flag.value).startswith("open"):
        return BreakerState(True, str(flag.value), sample=0)

    sample, bounced, rate = measure(db, lookback_days=lookback_days)

    if sample < settings.bounce_rate_min_sample:
        # Too little evidence to judge. Warmup volumes are intentionally tiny.
        return BreakerState(False, "sample below floor", rate, sample, bounced)

    if rate > settings.max_bounce_rate:
        reason = (
            f"open: bounce rate {rate:.1%} over last {sample} sends "
            f"exceeds {settings.max_bounce_rate:.1%}"
        )
        trip(db, reason)
        return BreakerState(True, reason, rate, sample, bounced)

    return BreakerState(False, "healthy", rate, sample, bounced)


def trip(db: Session, reason: str) -> None:
    """Open the breaker and persist it, so it survives a restart."""
    flag = _get_flag(db)
    if flag is None:
        flag = AppSetting(key=BREAKER_KEY, value=reason)
        db.add(flag)
    else:
        flag.value = reason
    db.commit()
    log.error("circuit_breaker.tripped", reason=reason)


def reset(db: Session, note: str = "manual reset") -> None:
    """Close the breaker. Deliberately manual: a human should look first."""
    flag = _get_flag(db)
    if flag is not None:
        db.delete(flag)
        db.commit()
    log.warning("circuit_breaker.reset", note=note)
