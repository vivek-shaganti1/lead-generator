"""AI Business Intelligence Engine.

Generates comprehensive, explainable business intelligence profiles:
- Executive Summary
- SWOT Analysis (Strengths, Weaknesses, Opportunities, Threats)
- Buying Intent Score & Strategic Pitch Angle
- Value Estimation (Estimated revenue tier, web project value)
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from app.config import settings
from app.logging_config import get_logger
from app.models import Business
from app.services.enrichment.website_audit import WebsiteAuditResult

log = get_logger(__name__)


@dataclass(slots=True)
class BusinessProfile:
    summary: str
    digital_presence_score: float
    website_quality_score: float
    seo_score: float
    mobile_score: float
    accessibility_score: float
    speed_score: float
    trust_score: float
    swot: dict[str, list[str]] = field(default_factory=dict)
    audit_details: dict[str, Any] = field(default_factory=dict)
    suggested_pitch: str = ""
    buying_intent_score: float = 0.0
    buying_intent_rationale: str = ""
    estimated_revenue: str = "$100k - $300k"
    estimated_project_value: str = "$1,500 - $3,500"


def generate_deterministic_profile(
    business: Business,
    audit: WebsiteAuditResult | None = None,
) -> BusinessProfile:
    """Deterministic fallback for generating rich business profiles."""
    name = business.name or "The business"
    category = (business.category or "local business").replace("_", " ")
    city = business.city or "the local area"
    rating = business.rating or 0.0
    reviews = business.review_count or 0
    has_web = business.has_website and (audit is None or audit.is_live)

    # 1. Base Scores
    if audit:
        web_q = audit.overall_score
        seo_s = audit.seo_score
        mob_s = audit.mobile_score
        spd_s = audit.speed_score
        a11y_s = audit.accessibility_score
        tru_s = audit.trust_score
    else:
        web_q = 75.0 if has_web else 0.0
        seo_s = 60.0 if has_web else 0.0
        mob_s = 70.0 if has_web else 0.0
        spd_s = 70.0 if has_web else 0.0
        a11y_s = 65.0 if has_web else 0.0
        tru_s = 60.0 if has_web else 20.0

    # Digital presence score calculation
    presence = 0.0
    if has_web:
        presence += 40.0
    if business.facebook:
        presence += 20.0
    if business.instagram:
        presence += 20.0
    if reviews > 20:
        presence += 20.0
    elif reviews > 5:
        presence += 10.0
    digital_presence = min(100.0, presence)

    # 2. SWOT Matrix
    strengths = []
    weaknesses = []
    opportunities = []
    threats = []

    if rating >= 4.5 and reviews > 10:
        strengths.append(f"Strong local reputation ({rating}★ across {reviews} Google reviews).")
    if business.phone:
        strengths.append("Direct phone contact established for rapid customer response.")
    if business.facebook or business.instagram:
        strengths.append("Active social media brand footprint in local community.")
    if not strengths:
        strengths.append("Established local presence and trade specialization.")

    if not has_web:
        weaknesses.append("Zero owned website presence—relies entirely on word of mouth or social.")
        weaknesses.append("Losing high-intent organic Google Search traffic to digital-first competitors.")
    elif audit and not audit.has_viewport:
        weaknesses.append("Non-responsive mobile design degrades smartphone conversions.")
    elif audit and audit.speed_score < 60:
        weaknesses.append(f"Slow page loading speeds ({audit.response_time_ms}ms) cause user bounce.")

    opportunities.append("Deploy a modern conversion-optimized landing page with instant booking.")
    opportunities.append("Capture local search queries (e.g. 'best " + category + " in " + city + "').")
    if not business.booking_url:
        opportunities.append("Integrate 24/7 automated appointment booking and inquiry capture.")

    threats.append("Local competitors with modern websites ranking higher on Google Maps & Search.")
    threats.append("Social platform algorithm changes reducing organic reach to customers.")

    swot = {
        "strengths": strengths,
        "weaknesses": weaknesses,
        "opportunities": opportunities,
        "threats": threats,
    }

    # 3. Buying Intent Score & Pitch Angle
    buying_intent = 50.0
    reasons = []
    if not has_web and (business.facebook or business.instagram):
        buying_intent += 30.0
        reasons.append("Active social marketer without an owned domain (ideal prospect)")
    elif not has_web:
        buying_intent += 20.0
        reasons.append("No website listed on local directories")
    elif audit and audit.overall_score < 50:
        buying_intent += 20.0
        reasons.append("Severe technical website deficit identified")

    if reviews > 30:
        buying_intent += 10.0
        reasons.append("Proven customer volume and commercial cash flow")

    buying_intent = min(98.0, buying_intent)
    buying_rationale = "; ".join(reasons) or "Standard commercial opportunity."

    # 4. Tailored Pitch
    if not has_web:
        suggested_pitch = (
            f"Show {name} a bespoke interactive demo site showing how they can capture 20-30 more "
            f"{category} inquiries every month in {city} with 24/7 direct booking."
        )
    else:
        suggested_pitch = (
            f"Offer {name} a complimentary Core Web Vitals and mobile conversion revamp to boost their "
            f"Google Search rankings and turn more website visitors into booked clients."
        )

    # 5. Executive Summary
    summary = (
        f"{name} is an active {category} in {city} with a digital presence score of {digital_presence:.0f}/100. "
        + (f"They hold {reviews} reviews with a {rating}★ rating. " if reviews else "")
        + ("They currently lack a standalone website, representing an immediate high-value web design opportunity."
           if not has_web else f"Their current website scores {web_q:.0f}/100 with clear modernization upside.")
    )

    rev_est = business.estimated_revenue or "$150k - $400k"
    proj_val = "$2,500 - $5,000" if "M" in rev_est or reviews > 100 else "$1,200 - $3,000"

    return BusinessProfile(
        summary=summary,
        digital_presence_score=digital_presence,
        website_quality_score=web_q,
        seo_score=seo_s,
        mobile_score=mob_s,
        accessibility_score=a11y_s,
        speed_score=spd_s,
        trust_score=tru_s,
        swot=swot,
        audit_details=asdict(audit) if audit else {},
        suggested_pitch=suggested_pitch,
        buying_intent_score=buying_intent,
        buying_intent_rationale=buying_rationale,
        estimated_revenue=rev_est,
        estimated_project_value=proj_val,
    )


def generate_business_profile(
    business: Business,
    audit: WebsiteAuditResult | None = None,
) -> BusinessProfile:
    """Generate business intelligence profile with LLM enhancement when configured."""
    profile = generate_deterministic_profile(business, audit)

    if not settings.groq_api_key:
        return profile

    # Optional Groq LLM refinement if API key is present
    try:
        from app.services.ai.groq import GroqClient
        client = GroqClient()
        prompt = (
            f"Business: {business.name}\n"
            f"Category: {business.category}\n"
            f"Location: {business.city}, {business.country_code}\n"
            f"Has Website: {business.has_website}\n"
            f"Rating: {business.rating} ({business.review_count} reviews)\n\n"
            f"Refine the executive summary in 2 sentences."
        )
        resp = client.client.post(
            "/chat/completions",
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": "You are a senior B2B sales intelligence analyst. Be concise and factual."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 150,
            },
            timeout=8.0,
        )
        if resp.status_code == 200:
            content = resp.json()["choices"][0]["message"]["content"].strip()
            if len(content) > 20:
                profile.summary = content
    except Exception as exc:
        log.warning("business_profile.llm_refinement_skipped", error=str(exc))

    return profile
