"""Attach an inbound message to the lead it belongs to.

Three strategies, strongest first:
  1. In-Reply-To / References against our own outbound Message-IDs (exact)
  2. the DSN's failed recipient (bounces come from a mail daemon, not the lead)
  3. sender address against lead emails, newest contacted first (fuzzy but common,
     because plenty of clients reply from a different mailbox than we wrote to)
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EmailMessage, Lead
from app.services.inbox.parser import ParsedInbound


def _by_message_ids(db: Session, ids: list[str]) -> Lead | None:
    ids = [i for i in ids if i]
    if not ids:
        return None
    message = db.execute(
        select(EmailMessage)
        .where(EmailMessage.message_id.in_(ids))
        .order_by(EmailMessage.sent_at.desc())
    ).scalars().first()
    return message.lead if message else None


def _by_email(db: Session, email: str) -> Lead | None:
    if not email:
        return None
    return db.execute(
        select(Lead)
        .where(Lead.email == email.strip().lower())
        .order_by(Lead.last_contacted_at.desc().nullslast(), Lead.id.desc())
    ).scalars().first()


def match_lead(db: Session, inbound: ParsedInbound) -> tuple[Lead | None, str]:
    """Return (lead, how_we_matched)."""
    candidate_ids = []
    if inbound.in_reply_to:
        candidate_ids.append(inbound.in_reply_to.strip())
    candidate_ids.extend(inbound.references or [])

    lead = _by_message_ids(db, candidate_ids)
    if lead:
        return lead, "threading_headers"

    if inbound.is_dsn and inbound.failed_recipient:
        lead = _by_email(db, inbound.failed_recipient)
        if lead:
            return lead, "dsn_recipient"

    lead = _by_email(db, inbound.from_email)
    if lead:
        return lead, "sender_address"

    return None, "unmatched"
