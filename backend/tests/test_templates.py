from __future__ import annotations

import pytest

from app.services.outreach.templates import (
    DEFAULT_BODY,
    DEFAULT_FOLLOWUP_BODY,
    DEFAULT_FOLLOWUP_SUBJECT,
    DEFAULT_SUBJECT,
    build_context,
    presence_line,
    render_email,
    render_string,
)
from app.services.outreach.tracking import inject_pixel, make_token, parse_token, pixel_url
from tests.conftest import make_lead


def test_presence_lines_differ_by_situation():
    missing = presence_line("MISSING", "Rossi's", "Restaurants", "Cork")
    social = presence_line("SOCIAL", "Rossi's", "Restaurants", "Cork")
    broken = presence_line("BROKEN", "Rossi's", "Restaurants", "Cork")
    assert len({missing, social, broken}) == 3
    assert "social media" in social
    assert "didn't load" in broken


def test_build_context_fills_business_fields(db, campaign):
    lead = make_lead(db, campaign=campaign)
    context = build_context(lead, lead.business, presence="MISSING")
    assert context["business_name"] == "Rossi's Trattoria"
    assert context["category_label"] == "Restaurants"
    assert context["city"] == "Cork"
    assert lead.unsubscribe_token in context["unsubscribe_url"]


def test_render_default_email_end_to_end(db, campaign):
    lead = make_lead(db, campaign=campaign)
    context = build_context(lead, lead.business, presence="SOCIAL")
    rendered = render_email(DEFAULT_SUBJECT, DEFAULT_BODY, context)

    assert "Rossi's Trattoria" in rendered.subject
    assert "social media" in rendered.text
    assert "Unsubscribe" in rendered.text
    assert "Test Studio" in rendered.text
    assert "1 Test Street" in rendered.text          # CAN-SPAM postal address
    assert lead.unsubscribe_token in rendered.text
    assert "<p" in rendered.html and "</div>" in rendered.html


def test_followup_template_renders(db, campaign):
    lead = make_lead(db, campaign=campaign)
    context = build_context(lead, lead.business)
    rendered = render_email(DEFAULT_FOLLOWUP_SUBJECT, DEFAULT_FOLLOWUP_BODY, context)
    assert rendered.subject.startswith("Re:")
    assert "not now" in rendered.text


def test_render_escapes_html_in_business_name(db, campaign):
    business_html = "<script>alert(1)</script>"
    lead = make_lead(db, campaign=campaign)
    lead.business.name = business_html
    context = build_context(lead, lead.business)
    rendered = render_email(DEFAULT_SUBJECT, DEFAULT_BODY, context)
    assert "<script>" not in rendered.html
    assert "&lt;script&gt;" in rendered.html


def test_render_string_rejects_undefined_variable():
    with pytest.raises(ValueError, match="template error"):
        render_string("Hello {{ missing_variable }}", {})


def test_render_string_blocks_sandbox_escape():
    with pytest.raises(ValueError):
        render_string("{{ ''.__class__.__mro__ }}", {})


def test_footer_can_be_omitted(db, campaign):
    lead = make_lead(db, campaign=campaign)
    context = build_context(lead, lead.business)
    rendered = render_email("S", "Body", context, include_footer=False)
    assert "Unsubscribe" not in rendered.text


# ------------------------------------------------------------------- tracking
def test_tracking_token_roundtrip():
    token = make_token(42)
    assert parse_token(token) == 42


def test_tracking_token_rejects_tampering():
    token = make_token(42)
    forged = token.replace("42.", "43.")
    assert parse_token(forged) is None
    assert parse_token("nonsense") is None
    assert parse_token("") is None


def test_tracking_token_is_kind_specific():
    assert parse_token(make_token(7, kind="o"), kind="c") is None


def test_inject_pixel_places_image_inside_body():
    html = '<div style="x"><p>hello</p></div>'
    out = inject_pixel(html, 5)
    assert pixel_url(5) in out
    assert out.endswith("</div>")
