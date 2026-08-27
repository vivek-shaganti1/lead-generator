"""CRM Deal & Pipeline Management Service.

Handles:
- Deal / Opportunity lifecycle across Kanban stages (PROSPECT, CONTACTED, QUALIFIED, PROPOSAL_SENT, NEGOTIATION, WON, LOST)
- Pipeline valuation and revenue forecasting
- Automated conversion from Positive Leads to CRM Deals
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models import Deal, DealStage, Lead
from app.schemas import DealIn, DealUpdate, KanbanStageOut, PipelineOut
from app.utils import utcnow

log = get_logger(__name__)

STAGE_PROBABILITIES = {
    DealStage.PROSPECT: 10.0,
    DealStage.CONTACTED: 20.0,
    DealStage.QUALIFIED: 40.0,
    DealStage.PROPOSAL_SENT: 65.0,
    DealStage.NEGOTIATION: 85.0,
    DealStage.WON: 100.0,
    DealStage.LOST: 0.0,
}


def create_deal(db: Session, deal_in: DealIn) -> Deal:
    """Create a new CRM opportunity."""
    prob = deal_in.probability if deal_in.probability is not None else STAGE_PROBABILITIES.get(deal_in.stage, 20.0)

    deal = Deal(
        lead_id=deal_in.lead_id,
        business_id=deal_in.business_id,
        title=deal_in.title,
        company_name=deal_in.company_name,
        contact_name=deal_in.contact_name,
        contact_email=str(deal_in.contact_email) if deal_in.contact_email else None,
        stage=deal_in.stage,
        value=deal_in.value,
        probability=prob,
        expected_close_at=deal_in.expected_close_at,
        notes=deal_in.notes,
    )
    db.add(deal)
    db.commit()
    db.refresh(deal)
    log.info("crm.deal_created", deal_id=deal.id, company=deal.company_name, stage=deal.stage.value)
    return deal


def create_deal_from_positive_lead(db: Session, lead: Lead) -> Deal:
    """Automatically convert a high-intent positive lead into a qualified CRM deal."""
    biz = lead.business
    company = biz.name if biz else "New Prospect"
    title = f"Web Design Contract — {company}"

    deal = Deal(
        lead_id=lead.id,
        business_id=biz.id if biz else None,
        title=title,
        company_name=company,
        contact_name=lead.contact_name,
        contact_email=lead.email,
        stage=DealStage.QUALIFIED,
        value=2500.0,
        probability=40.0,
        notes=f"Auto-created from positive reply. AI Summary: {lead.ai_summary or 'Prospect requested details'}",
    )
    db.add(deal)
    db.commit()
    db.refresh(deal)
    log.info("crm.deal_auto_converted", deal_id=deal.id, lead_id=lead.id)
    return deal


def update_deal(db: Session, deal_id: int, update: DealUpdate) -> Deal | None:
    """Update deal properties or transition stages."""
    deal = db.query(Deal).filter(Deal.id == deal_id).first()
    if not deal:
        return None

    if update.title is not None:
        deal.title = update.title
    if update.company_name is not None:
        deal.company_name = update.company_name
    if update.contact_name is not None:
        deal.contact_name = update.contact_name
    if update.contact_email is not None:
        deal.contact_email = str(update.contact_email)
    if update.stage is not None:
        deal.stage = update.stage
        if update.probability is None:
            deal.probability = STAGE_PROBABILITIES.get(update.stage, deal.probability)
    if update.value is not None:
        deal.value = update.value
    if update.probability is not None:
        deal.probability = update.probability
    if update.expected_close_at is not None:
        deal.expected_close_at = update.expected_close_at
    if update.win_loss_reason is not None:
        deal.win_loss_reason = update.win_loss_reason
    if update.notes is not None:
        deal.notes = update.notes

    db.commit()
    db.refresh(deal)
    return deal


def get_pipeline_summary(db: Session) -> PipelineOut:
    """Aggregate Kanban stages, pipeline values, and weighted revenue forecasts."""
    deals = db.query(Deal).order_by(Deal.id.desc()).all()

    stage_buckets: dict[DealStage, list[Deal]] = {s: [] for s in DealStage}
    total_val = 0.0
    forecast_val = 0.0

    for d in deals:
        stage_buckets[d.stage].append(d)
        if d.stage != DealStage.LOST:
            total_val += d.value
            forecast_val += d.value * (d.probability / 100.0)

    stages_out: list[KanbanStageOut] = []
    for stage_enum in DealStage:
        stage_deals = stage_buckets[stage_enum]
        s_val = sum(d.value for d in stage_deals)
        stages_out.append(
            KanbanStageOut(
                stage=stage_enum,
                total_value=round(s_val, 2),
                deals_count=len(stage_deals),
                deals=stage_deals,  # SQLAlchemy models match DealOut with from_attributes
            )
        )

    return PipelineOut(
        total_pipeline_value=round(total_val, 2),
        forecasted_value=round(forecast_val, 2),
        total_deals=len(deals),
        stages=stages_out,
    )
