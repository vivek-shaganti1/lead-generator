"""Opt-out plumbing.

Every message carries a List-Unsubscribe header (RFC 2369) *and* RFC 8058
one-click support, plus a visible link in the body. Gmail and Yahoo require the
former for bulk senders; the latter is what an actual human clicks.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Event, Lead, LeadStatus
from app.services.compliance.policy import suppress


def unsubscribe_url(token: str) -> str:
    return f"{settings.public_base_url.rstrip('/')}/u/{token}"


def list_unsubscribe_headers(token: str) -> dict[str, str]:
    url = unsubscribe_url(token)
    return {
        "List-Unsubscribe": f"<{url}>, <mailto:{settings.effective_reply_to}?subject=unsubscribe>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }


def apply_unsubscribe(db: Session, lead: Lead, reason: str = "user opt-out") -> None:
    """Terminal and irreversible: mark the lead and suppress the address forever."""
    lead.status = LeadStatus.UNSUBSCRIBED
    lead.next_action_at = None
    lead.block_reason = reason
    suppress(db, lead.email, reason=reason, kind="email")
    db.add(Event(type="lead.unsubscribed", lead_id=lead.id, payload={"reason": reason}))
