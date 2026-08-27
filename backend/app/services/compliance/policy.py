"""Whether we are allowed to email this lead, right now.

This module is the single gate every outbound message passes through. It exists
because cold B2B email is legal in some jurisdictions and illegal in others, and
because getting that wrong is both a fine and a burned domain.

Rules encoded here:
  * Country gating - jurisdictions requiring prior consent are never auto-mailed.
  * Suppression - opt-outs and hard bounces are permanent, matched per-address
    and per-domain.
  * Terminal states - a lead that said no is never contacted again.
  * Human approval - optional, on by default, so nothing leaves unreviewed.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Lead, LeadStatus, Suppression
from app.utils import domain_of, is_unsafe_address


@dataclass(slots=True)
class Decision:
    allowed: bool
    reason: str = ""

    def __bool__(self) -> bool:  # lets callers write `if decision:`
        return self.allowed


ALLOW = Decision(True, "ok")


def is_suppressed(db: Session, email: str) -> Suppression | None:
    email = (email or "").strip().lower()
    if not email:
        return None
    domain = domain_of(email)
    stmt = select(Suppression).where(
        ((Suppression.kind == "email") & (Suppression.value == email))
        | ((Suppression.kind == "domain") & (Suppression.value == domain))
    )
    return db.execute(stmt).scalars().first()


def suppress(db: Session, value: str, reason: str, kind: str = "email") -> Suppression:
    """Idempotent add to the do-not-contact list."""
    value = (value or "").strip().lower()
    existing = db.execute(
        select(Suppression).where(Suppression.kind == kind, Suppression.value == value)
    ).scalars().first()
    if existing:
        return existing
    entry = Suppression(kind=kind, value=value, reason=reason)
    db.add(entry)
    db.flush()
    return entry


def country_allowed(country_code: str | None) -> Decision:
    if not country_code:
        # Unknown jurisdiction: we cannot prove it is permitted, so we do not send.
        return Decision(False, "unknown country - manual review required")
    if country_code.upper() in settings.blocked_country_set:
        return Decision(False, f"{country_code.upper()} requires prior consent for B2B email")
    return ALLOW


def can_contact(db: Session, lead: Lead, *, ignore_approval: bool = False) -> Decision:
    """The full gate. Called immediately before every send, not just at queue time."""
    if not lead.email:
        return Decision(False, "no email address")
    if is_unsafe_address(lead.email):
        return Decision(False, "unsafe mailbox (noreply/abuse/postmaster)")
    if lead.status in LeadStatus.terminal():
        return Decision(False, f"lead is in terminal state {lead.status.value}")

    entry = is_suppressed(db, lead.email)
    if entry:
        return Decision(False, f"suppressed ({entry.reason})")

    country = lead.business.country_code if lead.business else None
    decision = country_allowed(country)
    if not decision.allowed:
        return decision

    if settings.require_manual_approval and not ignore_approval and not lead.approved:
        return Decision(False, "awaiting manual approval")

    return ALLOW


def enforce(db: Session, lead: Lead) -> Decision:
    """can_contact, but it also records the block on the lead for the dashboard."""
    decision = can_contact(db, lead)
    if not decision.allowed:
        lead.block_reason = decision.reason
        hard_blocks = ("suppressed", "unsafe mailbox", "requires prior consent")
        if any(h in decision.reason for h in hard_blocks):
            lead.status = LeadStatus.DO_NOT_CONTACT
    else:
        lead.block_reason = None
    return decision
