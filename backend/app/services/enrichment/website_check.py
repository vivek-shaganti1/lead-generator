"""Decide whether a business genuinely lacks a working website.

Three cases are all sellable, and we tell them apart because the pitch differs:
  MISSING  - no website at all
  SOCIAL   - only a Facebook/Instagram/linktree presence
  BROKEN   - a URL exists but the site is dead, parked, or errors
"""
from __future__ import annotations

import enum
from dataclasses import dataclass

import httpx

from app.config import settings
from app.logging_config import get_logger
from app.utils import is_social_only

log = get_logger(__name__)

PARKED_MARKERS = (
    "domain is for sale", "buy this domain", "parked domain", "this domain is parked",
    "future home of something quite cool", "coming soon", "under construction",
    "default web page", "welcome to nginx", "apache2 ubuntu default page",
    "site not published", "godaddy.com", "sedoparking", "account suspended",
    "this site can't be reached", "index of /",
)
MIN_CONTENT_LENGTH = 600  # bytes of HTML below which nothing real is being served


class WebPresence(str, enum.Enum):
    MISSING = "MISSING"
    SOCIAL = "SOCIAL"
    BROKEN = "BROKEN"
    LIVE = "LIVE"
    UNKNOWN = "UNKNOWN"


@dataclass(slots=True)
class WebsiteCheck:
    presence: WebPresence
    url: str | None = None
    status_code: int | None = None
    detail: str = ""

    @property
    def is_prospect(self) -> bool:
        """True when a missing/weak web presence makes this business worth pitching."""
        return self.presence in (WebPresence.MISSING, WebPresence.SOCIAL, WebPresence.BROKEN)


def classify_static(website: str | None) -> WebsiteCheck | None:
    """The part we can decide without any network call."""
    if not website or not website.strip():
        return WebsiteCheck(WebPresence.MISSING, detail="no url on record")
    if is_social_only(website):
        return WebsiteCheck(WebPresence.SOCIAL, url=website, detail="social profile only")
    return None


def check_website(website: str | None, client: httpx.Client | None = None) -> WebsiteCheck:
    static = classify_static(website)
    if static is not None:
        return static

    url = website if "://" in website else f"http://{website}"
    owns_client = client is None
    client = client or httpx.Client(
        timeout=settings.scrape_timeout,
        headers={"User-Agent": settings.user_agent},
        follow_redirects=True,
    )
    try:
        response = client.get(url)
    except httpx.HTTPError as exc:
        return WebsiteCheck(WebPresence.BROKEN, url=website, detail=f"unreachable: {exc}")
    finally:
        if owns_client:
            client.close()

    if response.status_code >= 400:
        return WebsiteCheck(
            WebPresence.BROKEN, url=website, status_code=response.status_code,
            detail=f"http {response.status_code}",
        )

    body = (response.text or "")
    lowered = body.lower()
    if any(marker in lowered for marker in PARKED_MARKERS):
        return WebsiteCheck(
            WebPresence.BROKEN, url=website, status_code=response.status_code,
            detail="parked or placeholder page",
        )
    if len(body.strip()) < MIN_CONTENT_LENGTH:
        return WebsiteCheck(
            WebPresence.BROKEN, url=website, status_code=response.status_code,
            detail="page has almost no content",
        )
    return WebsiteCheck(WebPresence.LIVE, url=website, status_code=response.status_code)
