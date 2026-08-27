"""Find a contact address for a discovered business.

Sources, in the order we trust them:
  1. the map data itself (OSM contact:email) - explicitly published by the owner
  2. a contact page on whatever web presence they do have (dead/parked/social sites
     still often carry an address)
  3. an optional external enrichment provider (Hunter/Snov/Apollo) if you plug one in

We never guess addresses (info@theirdomain.com when nothing confirms it exists).
Guessed addresses bounce, and bounces are what kill a sending domain.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.logging_config import get_logger
from app.services.enrichment.validator import ValidationResult, pick_best, validate
from app.utils import extract_emails

log = get_logger(__name__)

CONTACT_PATHS = ("", "/contact", "/contact-us", "/contacts", "/about", "/about-us",
                 "/impressum", "/kontakt", "/contatti", "/contacto", "/reach-us")
MAX_PAGES_PER_SITE = 4
MAX_HTML_BYTES = 1_500_000


@dataclass(slots=True)
class EmailFinding:
    email: str
    source: str
    confidence: float
    is_role: bool = False

    @classmethod
    def from_validation(cls, result: ValidationResult, source: str) -> "EmailFinding":
        return cls(result.email, source, result.confidence, result.is_role)


def from_map_tags(email: str | None) -> EmailFinding | None:
    """The owner put the address on the map themselves - the strongest signal we get."""
    if not email:
        return None
    # OSM sometimes stores several, semicolon separated
    for part in str(email).replace(",", ";").split(";"):
        result = validate(part.strip())
        if result.valid:
            result.confidence = min(result.confidence + 0.15, 1.0)
            return EmailFinding.from_validation(result, "map_tag")
    return None


def _fetch(client: httpx.Client, url: str) -> str | None:
    try:
        response = client.get(url, follow_redirects=True)
    except httpx.HTTPError as exc:
        log.debug("scrape.fetch_failed", url=url, error=str(exc))
        return None
    if response.status_code >= 400:
        return None
    ctype = response.headers.get("content-type", "")
    if "html" not in ctype and "text" not in ctype:
        return None
    return response.text[:MAX_HTML_BYTES]


def emails_from_html(html: str) -> list[str]:
    """Pull addresses from mailto: links first, then from the visible text."""
    found: list[str] = []
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:  # pragma: no cover - parser fallback
        soup = BeautifulSoup(html, "html.parser")

    for anchor in soup.select('a[href^="mailto:"]'):
        href = anchor.get("href", "")
        address = href[7:].split("?")[0].strip()
        if address:
            found.append(address.lower())

    for script in soup(["script", "style", "noscript"]):
        script.decompose()
    visible = soup.get_text(" ")
    found.extend(extract_emails(visible))

    # Entity-escaped and lightly obfuscated forms. Run this over the *stripped*
    # markup only - scanning raw HTML drags in analytics keys from <script>.
    deobfuscated = (
        str(soup).replace("&#64;", "@").replace("&#x40;", "@")
        .replace("[at]", "@").replace(" (at) ", "@")
    )
    found.extend(extract_emails(deobfuscated))
    return list(dict.fromkeys(found))


def from_website(
    url: str, business_name: str = "", client: httpx.Client | None = None
) -> EmailFinding | None:
    """Crawl a handful of likely contact pages on the given site."""
    if not settings.enable_website_email_scrape or not url:
        return None
    base = url if "://" in url else f"http://{url}"
    base = base.rstrip("/")

    owns_client = client is None
    client = client or httpx.Client(
        timeout=settings.scrape_timeout,
        headers={"User-Agent": settings.user_agent},
        follow_redirects=True,
    )
    try:
        collected: list[str] = []
        for path in CONTACT_PATHS[:MAX_PAGES_PER_SITE]:
            html = _fetch(client, base + path)
            if not html:
                continue
            collected.extend(emails_from_html(html))
            if collected:
                break  # first page that yields anything is good enough
        if not collected:
            return None
        best = pick_best(collected, business_name)
        return EmailFinding.from_validation(best, "website_scrape") if best else None
    finally:
        if owns_client:
            client.close()


class ExternalEnrichmentProvider:
    """Seam for a paid provider (Hunter.io, Snov, Apollo).

    Left unconfigured by default: those APIs cost money and their terms differ,
    so enabling one is a deliberate choice. Implement `lookup` and register it.
    """

    name = "external"

    def lookup(self, business_name: str, domain: str | None, country: str | None):
        return None


_external: ExternalEnrichmentProvider | None = None


def register_external_provider(provider: ExternalEnrichmentProvider | None) -> None:
    global _external
    _external = provider


def find_email(
    *,
    map_email: str | None,
    website: str | None,
    business_name: str,
    country_code: str | None = None,
    client: httpx.Client | None = None,
) -> EmailFinding | None:
    """Run every source in trust order and return the first solid hit."""
    finding = from_map_tags(map_email)
    if finding:
        return finding

    if website:
        finding = from_website(website, business_name, client=client)
        if finding:
            return finding

    if _external is not None:
        try:
            result = _external.lookup(business_name, None, country_code)
        except Exception as exc:  # never let a third party break the pipeline
            log.warning("enrichment.external_failed", error=str(exc))
            result = None
        if result:
            validated = validate(result)
            if validated.valid:
                return EmailFinding.from_validation(validated, _external.name)
    return None
