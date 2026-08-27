"""Deliverability & Sender Reputation API router."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import DeliverabilityHealth, User
from app.schemas import DeliverabilityHealthOut
from app.security import get_current_user
from app.services.outreach.deliverability import audit_and_save_deliverability
from app.utils import parse_domain

router = APIRouter(prefix="/api/deliverability", tags=["deliverability"])


@router.get("/health", response_model=DeliverabilityHealthOut)
def get_deliverability_health(
    domain: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Retrieve sender domain DNS, SPF, DKIM, DMARC, BIMI and blacklist safety metrics."""
    target_domain = domain or parse_domain(settings.sender_email) or "yourdomain.com"
    existing = (
        db.query(DeliverabilityHealth)
        .filter(DeliverabilityHealth.domain == target_domain)
        .first()
    )
    if existing:
        return existing
    return audit_and_save_deliverability(db, target_domain)


@router.post("/verify", response_model=DeliverabilityHealthOut)
def verify_deliverability(
    domain: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Run an instant live DNS & reputation scan on the sender domain."""
    target_domain = domain or parse_domain(settings.sender_email) or "yourdomain.com"
    return audit_and_save_deliverability(db, target_domain)
