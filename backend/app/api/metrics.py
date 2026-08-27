"""Observability & AI Learning Insights API router."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Business, Deal, EmailMessage, InboundMessage, Lead, LeadStatus, User
from app.security import get_current_user
from app.services.ai.learning import generate_learning_insights

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/metrics")
def get_prometheus_metrics(db: Session = Depends(get_db)):
    """Export Prometheus-compatible telemetry for system monitoring."""
    total_businesses = db.query(Business).count()
    total_leads = db.query(Lead).count()
    ready_leads = db.query(Lead).filter(Lead.status == LeadStatus.READY).count()
    contacted_leads = db.query(Lead).filter(Lead.status == LeadStatus.CONTACTED).count()
    positive_leads = db.query(Lead).filter(Lead.status == LeadStatus.POSITIVE).count()
    total_emails = db.query(EmailMessage).count()
    total_inbound = db.query(InboundMessage).count()
    total_deals = db.query(Deal).count()

    lines = [
        "# HELP leadgen_businesses_total Total discovered businesses",
        "# TYPE leadgen_businesses_total gauge",
        f"leadgen_businesses_total {total_businesses}",
        "# HELP leadgen_leads_total Total leads in database",
        "# TYPE leadgen_leads_total gauge",
        f"leadgen_leads_total {total_leads}",
        "# HELP leadgen_leads_ready Ready leads awaiting delivery",
        "# TYPE leadgen_leads_ready gauge",
        f"leadgen_leads_ready {ready_leads}",
        "# HELP leadgen_leads_contacted Contacted leads",
        "# TYPE leadgen_leads_contacted gauge",
        f"leadgen_leads_contacted {contacted_leads}",
        "# HELP leadgen_leads_positive Positive buying intent leads",
        "# TYPE leadgen_leads_positive gauge",
        f"leadgen_leads_positive {positive_leads}",
        "# HELP leadgen_emails_sent_total Outbound emails sent",
        "# TYPE leadgen_emails_sent_total gauge",
        f"leadgen_emails_sent_total {total_emails}",
        "# HELP leadgen_inbound_messages_total Inbound messages ingested",
        "# TYPE leadgen_inbound_messages_total gauge",
        f"leadgen_inbound_messages_total {total_inbound}",
        "# HELP leadgen_crm_deals_total CRM opportunities created",
        "# TYPE leadgen_crm_deals_total gauge",
        f"leadgen_crm_deals_total {total_deals}",
    ]

    return Response(content="\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


@router.get("/learning-insights")
def get_learning_insights_endpoint(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Retrieve AI-derived insights and conversion optimizations."""
    insights = generate_learning_insights(db)
    return [
        {
            "category": i.category,
            "headline": i.headline,
            "description": i.description,
            "impact_level": i.impact_level,
            "recommended_action": i.recommended_action,
        }
        for i in insights
    ]
