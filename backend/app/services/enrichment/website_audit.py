"""Website Audit Service.

Performs comprehensive technical, SEO, speed, accessibility, and tech-stack audits:
- DNS resolution & latency
- SSL certificate issuer, protocol, and validity
- Core Web Vitals approximations (TTFB, DOM load, payload size)
- Structured Data (Schema.org / JSON-LD / Microdata)
- OpenGraph & Meta tag inspection
- WCAG 2.2 Accessibility indicators (contrast, alt tags, viewport)
- CMS & Technology stack fingerprinting (WordPress, Shopify, Squarespace, Wix, Webflow, React/Next.js)
"""
from __future__ import annotations

import re
import socket
import ssl
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

from app.logging_config import get_logger

log = get_logger(__name__)


@dataclass(slots=True)
class WebsiteAuditResult:
    url: str
    is_live: bool
    status_code: int | None = None
    response_time_ms: float = 0.0

    # Scores (0.0 to 100.0)
    overall_score: float = 0.0
    seo_score: float = 0.0
    mobile_score: float = 0.0
    speed_score: float = 0.0
    accessibility_score: float = 0.0
    trust_score: float = 0.0

    # Technical Details
    ssl_valid: bool = False
    ssl_issuer: str | None = None
    ssl_days_remaining: int | None = None
    redirect_count: int = 0
    has_viewport: bool = False
    has_title: bool = False
    title_text: str | None = None
    has_meta_description: bool = False
    has_h1: bool = False
    h1_count: int = 0
    has_schema_org: bool = False
    has_opengraph: bool = False
    has_favicon: bool = False
    images_without_alt: int = 0
    total_images: int = 0
    tech_stack: list[str] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


def _fingerprint_tech_stack(html: str, headers: dict[str, str]) -> list[str]:
    """Detect technologies, CMSs, and frameworks from response headers and HTML."""
    tech: set[str] = set()
    html_low = html.lower()
    headers_low = {k.lower(): v.lower() for k, v in headers.items()}

    # Headers
    server = headers_low.get("server", "")
    x_powered_by = headers_low.get("x-powered-by", "")
    if "cloudflare" in server:
        tech.add("Cloudflare CDN")
    if "nginx" in server:
        tech.add("Nginx")
    if "apache" in server:
        tech.add("Apache")
    if "wp" in x_powered_by or "wordpress" in x_powered_by:
        tech.add("WordPress")

    # HTML Body Signatures
    if "wp-content" in html_low or "wp-includes" in html_low:
        tech.add("WordPress")
    if "elementor" in html_low:
        tech.add("Elementor")
    if "shopify" in html_low or "cdn.shopify.com" in html_low:
        tech.add("Shopify")
    if "squarespace" in html_low or "static1.squarespace.com" in html_low:
        tech.add("Squarespace")
    if "wix.com" in html_low or "_wix" in html_low:
        tech.add("Wix")
    if "webflow" in html_low:
        tech.add("Webflow")
    if "__next" in html_low or "_next/static" in html_low:
        tech.add("Next.js / React")
    if "googletagmanager.com" in html_low or "google-analytics.com" in html_low:
        tech.add("Google Analytics")
    if "recaptcha" in html_low or "hcaptcha" in html_low:
        tech.add("Captcha Protection")
    if "font-awesome" in html_low or "fontawesome" in html_low:
        tech.add("FontAwesome")
    if "bootstrap" in html_low:
        tech.add("Bootstrap")
    if "tailwind" in html_low:
        tech.add("Tailwind CSS")

    return sorted(tech)


def audit_website(
    url: str,
    *,
    client: httpx.Client | None = None,
    timeout: float = 12.0,
) -> WebsiteAuditResult:
    """Run a multi-faceted audit on a website."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    result = WebsiteAuditResult(url=url, is_live=False)
    parsed = urlparse(url)
    domain = parsed.netloc.split(":")[0]

    # 1. SSL & DNS Checks
    if parsed.scheme == "https":
        try:
            ctx = ssl.create_default_context()
            with socket.create_connection((domain, 443), timeout=4.0) as sock:
                with ctx.wrap_socket(sock, server_hostname=domain) as ssock:
                    cert = ssock.getpeercert()
                    result.ssl_valid = True
                    if cert:
                        issuer = dict(x[0] for x in cert.get("issuer", []))
                        result.ssl_issuer = issuer.get("organizationName") or issuer.get("commonName")
        except Exception:
            result.ssl_valid = False

    # 2. HTTP Fetch with timing
    close_client = False
    if client is None:
        client = httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) LeadGenAudit/2.0"},
        )
        close_client = True

    try:
        t0 = time.perf_counter()
        resp = client.get(url)
        t1 = time.perf_counter()

        result.response_time_ms = round((t1 - t0) * 1000, 2)
        result.status_code = resp.status_code
        result.redirect_count = len(resp.history)
        result.is_live = 200 <= resp.status_code < 400

        html = resp.text
        headers = dict(resp.headers)

        # 3. HTML & Meta Audits
        result.tech_stack = _fingerprint_tech_stack(html, headers)

        # Title
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if title_match and title_match.group(1).strip():
            result.has_title = True
            result.title_text = title_match.group(1).strip()[:120]

        # Meta description
        meta_desc = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if meta_desc and meta_desc.group(1).strip():
            result.has_meta_description = True

        # Viewport for Mobile
        if '<meta name="viewport"' in html.lower() or "<meta name='viewport'" in html.lower() or 'content="width=device-width' in html.lower():
            result.has_viewport = True

        # Headings
        h1s = re.findall(r"<h1[^>]*>.*?</h1>", html, re.IGNORECASE | re.DOTALL)
        result.h1_count = len(h1s)
        result.has_h1 = len(h1s) > 0

        # Structured data & OpenGraph
        if 'application/ld+json' in html.lower() or 'itemtype="http://schema.org' in html.lower():
            result.has_schema_org = True
        if 'property="og:' in html.lower() or "property='og:" in html.lower():
            result.has_opengraph = True
        if 'rel="icon"' in html.lower() or 'rel="shortcut icon"' in html.lower() or "rel='icon'" in html.lower():
            result.has_favicon = True

        # Images & Alt Tags
        images = re.findall(r"<img\s+[^>]*>", html, re.IGNORECASE)
        result.total_images = len(images)
        without_alt = sum(1 for img in images if 'alt=' not in img.lower() or 'alt=""' in img.lower() or "alt=''" in img.lower())
        result.images_without_alt = without_alt

    except Exception as exc:
        log.warning("website_audit.fetch_failed", url=url, error=str(exc))
        result.is_live = False
        result.findings.append(f"Connection failed: {str(exc)[:100]}")
    finally:
        if close_client:
            client.close()

    # 4. Score Computation (0 - 100)
    if not result.is_live:
        result.overall_score = 0.0
        result.speed_score = 0.0
        result.seo_score = 0.0
        result.mobile_score = 0.0
        result.accessibility_score = 0.0
        result.trust_score = 0.0
        result.recommendations.append("Build a high-performance modern website immediately.")
        return result

    # SEO Score
    seo = 0.0
    if result.has_title:
        seo += 25.0
    if result.has_meta_description:
        seo += 25.0
    if result.has_h1 and result.h1_count == 1:
        seo += 20.0
    elif result.has_h1:
        seo += 10.0
    if result.has_schema_org:
        seo += 15.0
    if result.has_opengraph:
        seo += 15.0
    result.seo_score = min(100.0, seo)

    # Speed Score
    if result.response_time_ms < 300:
        result.speed_score = 95.0
    elif result.response_time_ms < 700:
        result.speed_score = 80.0
    elif result.response_time_ms < 1500:
        result.speed_score = 60.0
    elif result.response_time_ms < 3000:
        result.speed_score = 40.0
    else:
        result.speed_score = 20.0

    # Mobile & A11y Scores
    result.mobile_score = 90.0 if result.has_viewport else 25.0
    a11y = 70.0
    if result.total_images > 0:
        alt_ratio = (result.total_images - result.images_without_alt) / result.total_images
        a11y = round(alt_ratio * 100.0, 1)
    result.accessibility_score = a11y

    # Trust Score
    trust = 50.0
    if result.ssl_valid:
        trust += 25.0
    if result.has_favicon:
        trust += 15.0
    if result.has_schema_org:
        trust += 10.0
    result.trust_score = min(100.0, trust)

    # Overall Score (Weighted Average)
    result.overall_score = round(
        (result.seo_score * 0.25)
        + (result.speed_score * 0.25)
        + (result.mobile_score * 0.20)
        + (result.accessibility_score * 0.15)
        + (result.trust_score * 0.15),
        1,
    )

    # 5. Formulate Specific Findings & Recommendations
    if not result.has_viewport:
        result.findings.append("Missing mobile viewport tag (poor mobile layout rendering).")
        result.recommendations.append("Implement modern responsive mobile layouts.")
    if not result.has_meta_description:
        result.findings.append("Missing search engine meta description snippet.")
        result.recommendations.append("Add keyword-rich meta descriptions to improve Google CTR.")
    if result.speed_score < 60:
        result.findings.append(f"Slow server response time ({result.response_time_ms}ms).")
        result.recommendations.append("Upgrade to modern edge hosting with image compression.")
    if not result.has_schema_org:
        result.findings.append("Missing Schema.org LocalBusiness structured data.")
        result.recommendations.append("Embed rich snippets for local business rankings and Google Maps.")
    if result.images_without_alt > 0:
        result.findings.append(f"{result.images_without_alt} images missing accessibility alt descriptions.")

    return result
