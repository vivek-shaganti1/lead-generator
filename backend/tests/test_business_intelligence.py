from __future__ import annotations

import pytest

from app.models import Business
from app.services.ai.business_profile import generate_business_profile, generate_deterministic_profile
from app.services.enrichment.website_audit import WebsiteAuditResult
from tests.conftest import make_business


def test_generate_business_profile_no_website(db):
    biz = make_business(
        db,
        name="Rossi Pizza",
        category="restaurant",
        city="Cork",
        country_code="IE",
        has_website=False,
    )
    biz.rating = 4.7
    biz.review_count = 85
    biz.facebook = "https://facebook.com/rossipizza"
    db.commit()

    profile = generate_business_profile(biz, audit=None)

    assert profile.digital_presence_score > 0
    assert profile.website_quality_score == 0.0
    assert "strengths" in profile.swot
    assert "weaknesses" in profile.swot
    assert profile.buying_intent_score > 70.0  # High intent because social active + no web
    assert "Rossi Pizza" in profile.summary
    assert "inquiries" in profile.suggested_pitch


def test_generate_business_profile_with_live_audit(db):
    biz = make_business(
        db,
        name="Cork Law Associates",
        category="lawyer",
        city="Cork",
        country_code="IE",
        has_website=True,
    )

    audit = WebsiteAuditResult(
        url="https://corklaw.ie",
        is_live=True,
        status_code=200,
        overall_score=85.0,
        seo_score=90.0,
        mobile_score=80.0,
        accessibility_score=80.0,
        speed_score=85.0,
        trust_score=90.0,
    )

    profile = generate_deterministic_profile(biz, audit=audit)
    assert profile.website_quality_score == 85.0
    assert profile.seo_score == 90.0
    assert "corklaw.ie" in profile.summary or "Cork Law Associates" in profile.summary
