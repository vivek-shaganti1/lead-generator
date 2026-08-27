from __future__ import annotations

import httpx
import pytest

from app.services.enrichment.email_finder import (
    emails_from_html,
    find_email,
    from_map_tags,
    from_website,
)
from app.services.enrichment.scoring import score_lead
from app.services.enrichment.validator import pick_best, validate
from app.services.enrichment.website_check import (
    WebPresence,
    check_website,
    classify_static,
)


# ------------------------------------------------------------------ validator
@pytest.mark.parametrize(
    "email,valid,reason",
    [
        ("info@shop.ie", True, "ok"),
        ("Maria@Shop.IE", True, "ok"),
        ("not-an-email", False, "syntax"),
        ("", False, "empty"),
        ("noreply@shop.ie", False, "unsafe-mailbox"),
        ("postmaster@shop.ie", False, "unsafe-mailbox"),
        ("test@mailinator.com", False, "disposable-domain"),
        ("you@example.com", False, "placeholder"),
        ("youremail@shop.ie", False, "placeholder"),
    ],
)
def test_validate(email, valid, reason):
    result = validate(email, check_mx=False)
    assert result.valid is valid
    assert reason in result.reason


def test_validate_normalises_case():
    assert validate("Maria@Shop.IE", check_mx=False).email == "maria@shop.ie"


def test_validate_scores_branded_named_mailbox_highest():
    branded = validate("maria@rossis.ie", check_mx=False)
    role = validate("info@rossis.ie", check_mx=False)
    free = validate("maria@gmail.com", check_mx=False)
    assert branded.confidence > role.confidence > free.confidence


def test_validate_rejects_overlong_localpart():
    assert validate("a" * 65 + "@shop.ie", check_mx=False).valid is False


def test_pick_best_prefers_own_domain():
    best = pick_best(
        ["someone@gmail.com", "info@rossistrattoria.ie"],
        business_name="Rossis Trattoria",
        check_mx=False,
    )
    assert best.email == "info@rossistrattoria.ie"


def test_pick_best_returns_none_when_all_invalid():
    assert pick_best(["noreply@x.ie", "bad"], check_mx=False) is None


# --------------------------------------------------------------- email finder
def test_from_map_tags_handles_semicolon_lists():
    finding = from_map_tags("noreply@shop.ie;maria@shop.ie")
    assert finding.email == "maria@shop.ie"
    assert finding.source == "map_tag"


def test_from_map_tags_none_when_empty():
    assert from_map_tags(None) is None
    assert from_map_tags("garbage") is None


def test_emails_from_html_reads_mailto_and_text():
    html = """
    <html><body>
      <a href="mailto:hello@shop.ie?subject=hi">Mail us</a>
      <p>Or write to sales@shop.ie</p>
      <script>var x = "tracker@sentry.io";</script>
    </body></html>
    """
    found = emails_from_html(html)
    assert "hello@shop.ie" in found
    assert "sales@shop.ie" in found
    assert "tracker@sentry.io" not in found


def test_emails_from_html_decodes_obfuscation():
    assert "info@shop.ie" in emails_from_html("<p>info&#64;shop.ie</p>")


def test_from_website_scrapes_contact_page(monkeypatch):
    monkeypatch.setattr("app.services.enrichment.email_finder.settings.enable_website_email_scrape",
                        True)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text='<a href="mailto:info@rossis.ie">mail</a>',
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    finding = from_website("http://rossis.ie", "Rossis", client=client)
    assert finding.email == "info@rossis.ie"
    assert finding.source == "website_scrape"


def test_from_website_returns_none_on_404(monkeypatch):
    monkeypatch.setattr("app.services.enrichment.email_finder.settings.enable_website_email_scrape",
                        True)
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    assert from_website("http://gone.ie", "Gone", client=client) is None


def test_find_email_prefers_map_tag_over_scrape():
    finding = find_email(
        map_email="maria@shop.ie", website="http://shop.ie", business_name="Shop"
    )
    assert finding.source == "map_tag"


def test_find_email_returns_none_when_nothing_found():
    assert find_email(map_email=None, website=None, business_name="Shop") is None


# -------------------------------------------------------------- website check
def test_classify_static_missing_and_social():
    assert classify_static(None).presence == WebPresence.MISSING
    assert classify_static("").presence == WebPresence.MISSING
    assert classify_static("https://facebook.com/shop").presence == WebPresence.SOCIAL
    assert classify_static("https://shop.ie") is None


def test_check_website_detects_parked_page():
    client = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, text="<html>This domain is parked</html>")
    ))
    result = check_website("http://shop.ie", client=client)
    assert result.presence == WebPresence.BROKEN
    assert result.is_prospect


def test_check_website_detects_thin_page():
    client = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, text="<html><body>hi</body></html>")
    ))
    assert check_website("http://shop.ie", client=client).presence == WebPresence.BROKEN


def test_check_website_detects_live_site():
    body = "<html><body>" + ("Real restaurant content. " * 60) + "</body></html>"
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=body)))
    result = check_website("http://shop.ie", client=client)
    assert result.presence == WebPresence.LIVE
    assert result.is_prospect is False


def test_check_website_handles_connection_error():
    def handler(request):
        raise httpx.ConnectError("dns failure")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = check_website("http://gone.ie", client=client)
    assert result.presence == WebPresence.BROKEN
    assert "unreachable" in result.detail


def test_check_website_500_is_broken():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert check_website("http://shop.ie", client=client).presence == WebPresence.BROKEN


# -------------------------------------------------------------------- scoring
def test_score_prefers_social_only_high_intent_business():
    social, _ = score_lead(
        presence=WebPresence.SOCIAL, category="restaurant", email_confidence=0.9,
        is_role_account=False, has_phone=True, has_address=True, has_social=True,
    )
    missing, _ = score_lead(
        presence=WebPresence.MISSING, category="hardware", email_confidence=0.5,
        is_role_account=True, has_phone=False, has_address=False, has_social=False,
    )
    assert social > missing


def test_score_live_website_scores_low():
    score, breakdown = score_lead(
        presence=WebPresence.LIVE, category="restaurant", email_confidence=0.9,
        is_role_account=False, has_phone=True, has_address=True, has_social=True,
    )
    assert breakdown["web_presence"] == 0
    assert score < 70


def test_score_is_capped_at_100():
    score, _ = score_lead(
        presence=WebPresence.SOCIAL, category="hotel", email_confidence=1.0,
        is_role_account=False, has_phone=True, has_address=True, has_social=True,
    )
    assert score <= 100
