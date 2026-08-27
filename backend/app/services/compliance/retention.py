"""Data retention.

Two obligations meet here:
  * Google Maps Platform terms cap how long non-place-id Places content may be
    cached (currently 30 days).
  * GDPR/DPDP data minimisation: we should not sit on personal data for
    businesses we never contacted and never will.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models import Business, Event, InboundMessage, Lead, LeadStatus
from app.utils import utcnow

log = get_logger(__name__)

GOOGLE_CACHE_DAYS = 30
STALE_UNCONTACTED_DAYS = 180
EVENT_RETENTION_DAYS = 365


def purge_stale_google_content(db: Session, days: int = GOOGLE_CACHE_DAYS) -> int:
    """Blank Google-sourced detail fields older than the cache window, keeping place ids."""
    cutoff = utcnow() - timedelta(days=days)
    stale = db.execute(
        select(Business).where(
            Business.source == "google",
            Business.updated_at < cutoff,
        )
    ).scalars().all()
    for business in stale:
        # Retaining the place id is permitted; everything else must be refreshed.
        business.phone = None
        business.address = None
        business.raw = {"google_place_id": (business.raw or {}).get("google_place_id")}
    log.info("retention.google_purged", count=len(stale))
    return len(stale)


def purge_uncontacted(db: Session, days: int = STALE_UNCONTACTED_DAYS) -> int:
    """Drop businesses we discovered but never turned into contacted leads."""
    cutoff = utcnow() - timedelta(days=days)
    contacted_business_ids = select(Lead.business_id).where(
        Lead.status.notin_([LeadStatus.NEW, LeadStatus.NEEDS_APPROVAL])
    )
    result = db.execute(
        delete(Business).where(
            Business.created_at < cutoff,
            Business.id.notin_(contacted_business_ids),
        )
    )
    log.info("retention.uncontacted_purged", count=result.rowcount or 0)
    return result.rowcount or 0


def purge_old_events(db: Session, days: int = EVENT_RETENTION_DAYS) -> int:
    cutoff = utcnow() - timedelta(days=days)
    result = db.execute(delete(Event).where(Event.created_at < cutoff))
    return result.rowcount or 0


def redact_inbound_bodies(db: Session, days: int = 90) -> int:
    """Reply bodies are personal data; keep the classification, drop the text."""
    cutoff = utcnow() - timedelta(days=days)
    result = db.execute(
        update(InboundMessage)
        .where(InboundMessage.received_at < cutoff, InboundMessage.body_text != "")
        .values(body_text="")
    )
    return result.rowcount or 0


def run_all(db: Session) -> dict[str, int]:
    return {
        "google_purged": purge_stale_google_content(db),
        "uncontacted_purged": purge_uncontacted(db),
        "events_purged": purge_old_events(db),
        "inbound_redacted": redact_inbound_bodies(db),
    }
