from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import Business, InboundMessage, Lead, LeadStatus, User
from app.schemas import (
    BulkAction,
    InboundOut,
    LeadDetail,
    LeadImportOut,
    LeadImportRequest,
    LeadOut,
    LeadUpdate,
    PaginatedLeads,
)
from app.security import get_current_user
from app.services.compliance.policy import suppress
from app.services.discovery.importer import import_reference_sheet
from app.services.outreach.dispatcher import approve_lead, send_lead

router = APIRouter(prefix="/api/leads", tags=["leads"])


def _base_query():
    return select(Lead).options(selectinload(Lead.business))


@router.get("", response_model=PaginatedLeads)
def list_leads(
    status: LeadStatus | None = None,
    country: str | None = Query(default=None, min_length=2, max_length=2),
    category: str | None = None,
    approved: bool | None = None,
    search: str | None = Query(default=None, max_length=120),
    min_score: float | None = Query(default=None, ge=0, le=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    sort: str = Query(default="score", pattern="^(score|created_at|last_contacted_at)$"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = _base_query().join(Business, Lead.business_id == Business.id)
    count_query = select(func.count(Lead.id)).join(Business, Lead.business_id == Business.id)

    filters = []
    if status is not None:
        filters.append(Lead.status == status)
    if country:
        filters.append(Business.country_code == country.upper())
    if category:
        filters.append(Business.category == category)
    if approved is not None:
        filters.append(Lead.approved.is_(approved))
    if min_score is not None:
        filters.append(Lead.score >= min_score)
    if search:
        pattern = f"%{search.lower()}%"
        filters.append(
            or_(
                func.lower(Business.name).like(pattern),
                func.lower(Lead.email).like(pattern),
                func.lower(func.coalesce(Business.city, "")).like(pattern),
            )
        )
    if filters:
        query = query.where(*filters)
        count_query = count_query.where(*filters)

    order = {
        "score": Lead.score.desc(),
        "created_at": Lead.created_at.desc(),
        "last_contacted_at": Lead.last_contacted_at.desc(),
    }[sort]

    total = int(db.execute(count_query).scalar() or 0)
    items = db.execute(
        query.order_by(order, Lead.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).scalars().all()

    return PaginatedLeads(
        items=[LeadOut.model_validate(item) for item in items],
        total=total, page=page, page_size=page_size,
    )


def _get_lead(db: Session, lead_id: int) -> Lead:
    lead = db.execute(
        _base_query().options(selectinload(Lead.messages)).where(Lead.id == lead_id)
    ).scalars().first()
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


@router.get("/{lead_id}", response_model=LeadDetail)
def get_lead(lead_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return _get_lead(db, lead_id)


@router.get("/{lead_id}/replies", response_model=list[InboundOut])
def lead_replies(
    lead_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
):
    _get_lead(db, lead_id)
    return list(
        db.execute(
            select(InboundMessage)
            .where(InboundMessage.lead_id == lead_id)
            .order_by(InboundMessage.received_at.desc())
        ).scalars().all()
    )


@router.patch("/{lead_id}", response_model=LeadDetail)
def update_lead(
    lead_id: int,
    payload: LeadUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    lead = _get_lead(db, lead_id)
    data = payload.model_dump(exclude_unset=True)

    if "approved" in data:
        approve_lead(db, lead, bool(data.pop("approved")))
    for field, value in data.items():
        setattr(lead, field, value)
    db.commit()
    db.refresh(lead)
    return lead


@router.post("/{lead_id}/send")
def send_now(
    lead_id: int,
    force: bool = Query(default=False, description="bypass pacing, never compliance"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    lead = _get_lead(db, lead_id)
    outcome = send_lead(db, lead, force=force)
    db.commit()
    if not outcome.sent:
        raise HTTPException(status_code=409, detail=outcome.reason)
    return {"sent": True, "step": outcome.step, "message_id": outcome.message_id}


@router.post("/bulk")
def bulk_action(
    payload: BulkAction, db: Session = Depends(get_db), _: User = Depends(get_current_user)
):
    leads = list(
        db.execute(_base_query().where(Lead.id.in_(payload.lead_ids))).scalars().all()
    )
    if not leads:
        raise HTTPException(status_code=404, detail="No matching leads")

    affected = 0
    for lead in leads:
        if payload.action == "approve":
            approve_lead(db, lead, True)
        elif payload.action == "unapprove":
            approve_lead(db, lead, False)
        elif payload.action == "suppress":
            suppress(db, lead.email, reason="manual suppression")
            lead.status = LeadStatus.DO_NOT_CONTACT
            lead.next_action_at = None
        elif payload.action == "delete":
            db.delete(lead)
        elif payload.action == "send_now":
            from app.workers.tasks import send_lead_now

            send_lead_now.delay(lead.id)
        affected += 1
    db.commit()
    return {"action": payload.action, "affected": affected}


@router.post("/import", response_model=LeadImportOut)
def import_leads(
    payload: LeadImportRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Import reference sheets, CSVs, or tabular lead data."""
    try:
        result = import_reference_sheet(
            db,
            payload.csv_data,
            campaign_id=payload.campaign_id,
            auto_qualify=payload.auto_qualify,
            auto_approve=payload.auto_approve,
            auto_dispatch=payload.auto_dispatch,
            default_category=payload.default_category,
            default_country=payload.default_country,
        )
        return result
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Import failed: {exc}") from exc

