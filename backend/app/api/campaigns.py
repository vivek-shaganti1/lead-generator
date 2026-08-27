from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import Campaign, Lead, User
from app.schemas import CampaignIn, CampaignOut, PreviewRequest, PreviewResponse
from app.security import get_current_user
from app.services.outreach import templates as tpl
from app.services.outreach.dispatcher import presence_of

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


@router.get("", response_model=list[CampaignOut])
def list_campaigns(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return list(db.execute(select(Campaign).order_by(Campaign.id)).scalars().all())


@router.post("", response_model=CampaignOut, status_code=201)
def create_campaign(
    payload: CampaignIn, db: Session = Depends(get_db), _: User = Depends(get_current_user)
):
    if db.execute(select(Campaign).where(Campaign.name == payload.name)).scalars().first():
        raise HTTPException(status_code=409, detail="A campaign with that name already exists")
    _validate_templates(payload)
    campaign = Campaign(**payload.model_dump())
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return campaign


@router.put("/{campaign_id}", response_model=CampaignOut)
def update_campaign(
    campaign_id: int,
    payload: CampaignIn,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    _validate_templates(payload)
    for field, value in payload.model_dump().items():
        setattr(campaign, field, value)
    db.commit()
    db.refresh(campaign)
    return campaign


def _validate_templates(payload: CampaignIn) -> None:
    """Render against a dummy context so a broken template is caught on save."""
    probe = {
        "business_name": "Sample Business", "contact_name": "Alex", "category": "cafe",
        "category_label": "Cafés", "city": "Springfield", "country": "IE",
        "presence": "MISSING", "presence_line": "I couldn't find a website",
        "sender_name": "Sender", "company_name": "Company", "company_website": "https://x.dev",
        "calendar_link": "", "unsubscribe_url": "https://example.com/u/token",
    }
    for name, template in (
        ("subject_template", payload.subject_template),
        ("body_template", payload.body_template),
        ("followup_subject_template", payload.followup_subject_template),
        ("followup_body_template", payload.followup_body_template),
    ):
        if not template:
            continue
        try:
            tpl.render_string(template, probe)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"{name}: {exc}") from exc


@router.post("/preview", response_model=PreviewResponse)
def preview(
    payload: PreviewRequest, db: Session = Depends(get_db), _: User = Depends(get_current_user)
):
    campaign = db.get(Campaign, payload.campaign_id) if payload.campaign_id else None

    if payload.lead_id:
        lead = db.execute(
            select(Lead).options(selectinload(Lead.business)).where(Lead.id == payload.lead_id)
        ).scalars().first()
        if lead is None:
            raise HTTPException(status_code=404, detail="Lead not found")
        business = lead.business
        campaign = campaign or lead.campaign
        context = tpl.build_context(lead, business, presence=presence_of(business))
    else:
        context = _sample_context()

    if payload.step == 0:
        subject = campaign.subject_template if campaign else tpl.DEFAULT_SUBJECT
        body = campaign.body_template if campaign else tpl.DEFAULT_BODY
    else:
        subject = (campaign.followup_subject_template if campaign else None) \
            or tpl.DEFAULT_FOLLOWUP_SUBJECT
        body = (campaign.followup_body_template if campaign else None) or tpl.DEFAULT_FOLLOWUP_BODY

    try:
        rendered = tpl.render_email(subject, body, context)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PreviewResponse(subject=rendered.subject, text=rendered.text, html=rendered.html)


def _sample_context() -> dict:
    from app.config import settings

    return {
        "business_name": "Rossi's Trattoria",
        "contact_name": "",
        "category": "restaurant",
        "category_label": "Restaurants",
        "city": "Cork",
        "country": "IE",
        "presence": "MISSING",
        "presence_line": tpl.presence_line(
            "MISSING", "Rossi's Trattoria", "Restaurants", "Cork"
        ),
        "sender_name": settings.sender_name,
        "company_name": settings.company_name,
        "company_website": settings.company_website,
        "calendar_link": settings.calendar_link,
        "unsubscribe_url": f"{settings.public_base_url.rstrip('/')}/u/sample-token",
    }
