"""Fetch a business's site well enough to judge it — or admit that we cannot.

The trap this module exists to avoid
------------------------------------
Testing the capability detector against real sites surfaced two ways to be
confidently wrong:

  * **dominos.co.uk returned 403.** We received a 6KB bot-block page and the
    detector duly reported twelve missing capabilities. A blocked fetch looks
    exactly like a featureless site.
  * **johnlewis.com was reported as having no e-commerce.** It is one of the
    largest retailers in the UK. Its basket lives inside a JavaScript bundle,
    and nothing in the server-rendered HTML says "add to cart".

Both would have produced an email telling a business it lacks something it
plainly has, which is the single most expensive mistake this pipeline can make:
it is unrecoverable with that recipient, and it is exactly what makes cold
outreach read as automated spam.

So the rule here is: **a fetch that cannot support a judgement must say so.**
:class:`SiteFetch` carries a :class:`FetchQuality`, and only ``GOOD`` licenses a
claim that something is missing. Everything else means we either skip the lead
or pitch only on evidence we positively have.

Multi-page by design
--------------------
Booking links live on ``/contact`` or ``/book`` far more often than on the home
page. Judging a site by its landing page alone invents gaps. We fetch a small,
polite set of likely pages and analyse them together.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import urljoin, urlparse

import httpx

from app.config import settings
from app.logging_config import get_logger

log = get_logger(__name__)

# Pages worth checking, in order. Kept short — this runs per business and we are
# a guest on someone else's server.
CANDIDATE_PATHS = (
    "",
    "/contact", "/contact-us",
    "/book", "/booking", "/appointments", "/reservations",
    "/order", "/shop", "/menu", "/services", "/pricing",
    "/about",
)
MAX_PAGES = 5
MAX_BYTES_PER_PAGE = 2_000_000

# Signals that we were served a bot wall or a holding page rather than the site.
_BLOCK_MARKERS = (
    "captcha", "cf-browser-verification", "checking your browser",
    "access denied", "attention required", "cloudflare",
    "enable javascript and cookies", "request unsuccessful",
    "are you a robot", "ddos protection", "incapsula", "perimeterx",
)
_PARKED_MARKERS = (
    "this domain is for sale", "buy this domain", "domain parking",
    "under construction", "coming soon", "default web page",
    "godaddy.com/domainsearch", "sedoparking", "future home of",
    "index of /", "apache2 debian default page", "welcome to nginx",
)
# Frameworks that render the real page client-side. Their server HTML is a shell.
_SPA_MARKERS = (
    "__next_data__", "id=\"__next\"", "ng-version", "data-reactroot",
    "window.__nuxt__", "id=\"root\"></div>", "id=\"app\"></div>",
    "vue-ssr-outlet", "__remixcontext", "svelte-",
)

_SCRIPT_RE = re.compile(r"<script\b.*?</script>", re.I | re.S)
_STYLE_RE = re.compile(r"<style\b.*?</style>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")


class FetchQuality(str, Enum):
    GOOD = "GOOD"                # real HTML, server-rendered, safe to judge
    JS_RENDERED = "JS_RENDERED"  # SPA shell — absence proves nothing
    BLOCKED = "BLOCKED"          # bot wall / 403 / captcha
    PARKED = "PARKED"            # parked, holding, or default server page
    DEAD = "DEAD"                # DNS failure, connection refused, 5xx, 404
    THIN = "THIN"                # loaded, but too little content to judge


@dataclass(slots=True)
class SiteFetch:
    url: str
    quality: FetchQuality
    status_code: int | None = None
    html: str = ""
    pages: list[str] = field(default_factory=list)
    visible_text_chars: int = 0
    error: str = ""
    final_url: str = ""

    @property
    def can_judge_absence(self) -> bool:
        """May we claim a capability is *missing* based on this fetch?

        Only a clean server-rendered fetch earns that right. On a JS shell or a
        bot wall the absence of a booking widget in the HTML tells us nothing
        about whether the business has one.
        """
        return self.quality is FetchQuality.GOOD

    @property
    def is_working_site(self) -> bool:
        return self.quality in (FetchQuality.GOOD, FetchQuality.JS_RENDERED)

    def as_dict(self) -> dict:
        return {
            "url": self.url,
            "final_url": self.final_url,
            "quality": self.quality.value,
            "status_code": self.status_code,
            "pages": self.pages,
            "visible_text_chars": self.visible_text_chars,
            "can_judge_absence": self.can_judge_absence,
            "error": self.error[:300],
        }


def visible_text(html: str) -> str:
    """Strip scripts, styles and tags — what a human would actually read."""
    stripped = _SCRIPT_RE.sub(" ", html)
    stripped = _STYLE_RE.sub(" ", stripped)
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", stripped)).strip()


def _classify(html: str, status: int, final_url: str) -> FetchQuality:
    low = html.lower()

    if any(marker in low for marker in _BLOCK_MARKERS) and len(html) < 60_000:
        return FetchQuality.BLOCKED
    if any(marker in low for marker in _PARKED_MARKERS):
        return FetchQuality.PARKED

    text = visible_text(html)
    if len(text) < 350:
        # Almost no readable content. Either a shell or an empty site; the SPA
        # check below decides which, and both forbid claiming absence.
        return FetchQuality.JS_RENDERED if any(m in low for m in _SPA_MARKERS) else FetchQuality.THIN

    if any(marker in low for marker in _SPA_MARKERS):
        # A framework shell that still ships real text (Next.js with SSR) is
        # judgeable; one that ships almost none is not.
        script_bytes = sum(len(m) for m in _SCRIPT_RE.findall(html))
        if script_bytes > len(text) * 25:
            return FetchQuality.JS_RENDERED

    return FetchQuality.GOOD


def _user_agent() -> str:
    template = settings.http_user_agent or "LeadGenBot/2.0 (+contact: {email})"
    return template.replace("{email}", settings.sender_email or "")


def fetch_site(url: str, *, max_pages: int = MAX_PAGES, timeout: float | None = None) -> SiteFetch:
    """Fetch the home page plus a few likely sub-pages and grade the result."""
    timeout = timeout or float(settings.scrape_timeout or 15)
    if not url:
        return SiteFetch(url="", quality=FetchQuality.DEAD, error="no url")
    if not urlparse(url).scheme:
        url = f"https://{url}"

    headers = {
        "User-Agent": _user_agent(),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en",
    }
    combined: list[str] = []
    fetched: list[str] = []
    home_status: int | None = None
    home_quality: FetchQuality | None = None
    final_url = url

    try:
        with httpx.Client(
            headers=headers, follow_redirects=True, timeout=timeout, verify=False
        ) as client:
            try:
                home = client.get(url)
            except httpx.HTTPError as exc:
                return SiteFetch(url, FetchQuality.DEAD, error=f"{type(exc).__name__}: {exc}")

            home_status = home.status_code
            final_url = str(home.url)

            if home_status >= 500 or home_status == 404:
                return SiteFetch(url, FetchQuality.DEAD, home_status, final_url=final_url,
                                 error=f"HTTP {home_status}")
            if home_status in (401, 403, 429):
                return SiteFetch(url, FetchQuality.BLOCKED, home_status, final_url=final_url,
                                 error=f"HTTP {home_status}")
            if home_status >= 400:
                return SiteFetch(url, FetchQuality.DEAD, home_status, final_url=final_url,
                                 error=f"HTTP {home_status}")

            body = home.text[:MAX_BYTES_PER_PAGE]
            home_quality = _classify(body, home_status, final_url)
            combined.append(body)
            fetched.append(final_url)

            # A blocked or parked home page settles it; don't crawl further.
            if home_quality in (FetchQuality.BLOCKED, FetchQuality.PARKED):
                return SiteFetch(url, home_quality, home_status, body, fetched,
                                 len(visible_text(body)), final_url=final_url)

            # Follow a handful of likely sub-pages. Only same-host links, and we
            # stop at the first few that exist.
            host = urlparse(final_url).netloc
            for path in CANDIDATE_PATHS[1:]:
                if len(fetched) >= max_pages:
                    break
                target = urljoin(final_url, path)
                if urlparse(target).netloc != host:
                    continue
                try:
                    page = client.get(target)
                except httpx.HTTPError:
                    continue
                if page.status_code == 200 and page.text:
                    combined.append(page.text[:MAX_BYTES_PER_PAGE])
                    fetched.append(str(page.url))

    except Exception as exc:  # pragma: no cover - network is unpredictable
        return SiteFetch(url, FetchQuality.DEAD, home_status, error=f"{type(exc).__name__}: {exc}")

    html = "\n".join(combined)
    text_len = len(visible_text(html))

    # Re-grade on everything we gathered: a thin home page plus a rich contact
    # page is judgeable even though the home page alone was not.
    quality = home_quality or FetchQuality.THIN
    if quality is FetchQuality.THIN and text_len >= 350:
        quality = FetchQuality.GOOD

    log.debug("site_fetch.done", url=url, quality=quality.value, pages=len(fetched), text=text_len)
    return SiteFetch(url, quality, home_status, html, fetched, text_len, final_url=final_url)
