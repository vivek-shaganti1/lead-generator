"""Business Intelligence & Competitor Analysis API router."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Business, BusinessAudit, Competitor, User
from app.schemas import (
    BusinessAuditOut,
    CompetitorOut,
    PitchGenerationRequest,
    PitchGenerationResponse,
)
from app.security import get_current_user
from app.services.ai.business_profile import generate_business_profile
from app.services.ai.competitor_intel import discover_and_benchmark_competitors, sync_competitors_to_db
from app.services.ai.copywriter import generate_multichannel_pitch
from app.services.enrichment.website_audit import audit_website

router = APIRouter(prefix="/api/intelligence", tags=["intelligence"])


@router.get("/{business_id}/audit", response_model=BusinessAuditOut)
def get_or_run_business_audit(
    business_id: int,
    force_refresh: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Retrieve existing 360° business audit or trigger a fresh technical & SWOT scan."""
    biz = db.query(Business).filter(Business.id == business_id).first()
    if not biz:
        raise HTTPException(status_code=404, detail="Business not found")

    existing = (
        db.query(BusinessAudit)
        .filter(BusinessAudit.business_id == business_id)
        .order_by(BusinessAudit.id.desc())
        .first()
    )

    if existing and not force_refresh:
        return existing

    # Run fresh technical audit
    web_audit = None
    if biz.has_website and biz.website:
        web_audit = audit_website(biz.website)

    profile = generate_business_profile(biz, web_audit)

    audit_rec = BusinessAudit(
        business_id=biz.id,
        digital_presence_score=profile.digital_presence_score,
        website_quality_score=profile.website_quality_score,
        seo_score=profile.seo_score,
        mobile_score=profile.mobile_score,
        accessibility_score=profile.accessibility_score,
        speed_score=profile.speed_score,
        trust_score=profile.trust_score,
        swot_analysis=profile.swot,
        audit_details=profile.audit_details,
        suggested_pitch=profile.suggested_pitch,
        buying_intent_score=profile.buying_intent_score,
        buying_intent_rationale=profile.buying_intent_rationale,
    )
    db.add(audit_rec)
    db.commit()
    db.refresh(audit_rec)
    return audit_rec


@router.get("/{business_id}/competitors", response_model=list[CompetitorOut])
def get_business_competitors(
    business_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Retrieve local competitor comparison and benchmarking matrix."""
    biz = db.query(Business).filter(Business.id == business_id).first()
    if not biz:
        raise HTTPException(status_code=404, detail="Business not found")

    comps = db.query(Competitor).filter(Competitor.business_id == business_id).all()
    if not comps:
        comps = sync_competitors_to_db(db, biz)

    return comps


@router.post("/generate-pitch", response_model=PitchGenerationResponse)
def generate_pitch(
    req: PitchGenerationRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Generate high-converting multi-channel copy grounded in business & competitor audit data."""
    biz = db.query(Business).filter(Business.id == req.business_id).first()
    if not biz:
        raise HTTPException(status_code=404, detail="Business not found")

    competitors = discover_and_benchmark_competitors(db, biz)
    pitch = generate_multichannel_pitch(
        biz,
        channel=req.channel,
        hook_style=req.hook_style,
        competitors=competitors,
    )

    return PitchGenerationResponse(
        business_id=biz.id,
        channel=req.channel,
        hook_style=req.hook_style,
        subject_line=pitch.subject,
        message_content=pitch.content,
        rationale=pitch.rationale,
        competitors_referenced=pitch.competitors_referenced,
    )
