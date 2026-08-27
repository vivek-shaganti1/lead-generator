from __future__ import annotations

import httpx
import pytest

from app.services.enrichment.website_audit import (
    _fingerprint_tech_stack,
    audit_website,
)


def test_fingerprint_tech_stack():
    html = """
    <html>
        <head>
            <link rel="stylesheet" href="/wp-content/themes/sample/style.css">
            <script src="https://cdn.shopify.com/s/files/1/0000/0000/t/1/assets/app.js"></script>
        </head>
        <body>
            <div class="elementor-section">Content</div>
            <script src="https://www.googletagmanager.com/gtm.js"></script>
        </body>
    </html>
    """
    headers = {"server": "cloudflare", "x-powered-by": "WordPress"}
    tech = _fingerprint_tech_stack(html, headers)
    assert "Cloudflare CDN" in tech
    assert "WordPress" in tech
    assert "Elementor" in tech
    assert "Shopify" in tech
    assert "Google Analytics" in tech


def test_audit_website_mock_transport():
    sample_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Apex Dental Clinic | Cork</title>
        <meta name="description" content="Leading dental clinic in Cork.">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <link rel="icon" href="/favicon.ico">
        <script type="application/ld+json">{"@context": "http://schema.org", "@type": "Dentist"}</script>
    </head>
    <body>
        <h1>Apex Dental Services</h1>
        <img src="/logo.png" alt="Apex Logo">
    </body>
    </html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=sample_html, headers={"Content-Type": "text/html"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    res = audit_website("https://apexdental.ie", client=client)

    assert res.is_live is True
    assert res.status_code == 200
    assert res.has_title is True
    assert res.title_text == "Apex Dental Clinic | Cork"
    assert res.has_meta_description is True
    assert res.has_viewport is True
    assert res.has_h1 is True
    assert res.has_schema_org is True
    assert res.seo_score >= 80.0
    assert res.mobile_score >= 80.0
    assert res.overall_score >= 70.0
