"""What can this business's website actually *do*?

The technical audit in ``website_audit.py`` answers "is this site well built".
This module answers a different and, for outreach, more useful question: "which
commercial capability is this business missing" — online booking, online
ordering, a quote form, live chat, payments.

That distinction is what makes an email land. "Your site scores 62 on SEO" is
noise to a dentist. "Patients can't book an appointment without phoning you"
is a business problem they already feel.

Evidence, not opinion
---------------------
Every detection records *why* it fired: the literal substring matched and where.
Nothing in this module infers, guesses, or asks a model. A capability is either
demonstrably present in bytes we fetched, or it is recorded as absent.

That matters because these findings are used to veto an LLM. When the copy
generator is about to claim "you have no booking system", the deterministic
evidence here overrides it — a model that has not read the page does not get to
overrule a page that plainly contains a Calendly widget. Pitching a business a
feature it already has is worse than not writing at all: it proves instantly
that nobody looked.

Absence of evidence
-------------------
A capability marked absent means "we did not find it on the pages we fetched",
which is not the same as "it does not exist". Booking widgets living behind a
JS bundle, or on a page we did not crawl, will read as absent. Anything acted on
gets a second opinion in :mod:`app.services.ai.gap_consensus` before it reaches
a human, and the confidence recorded here reflects that uncertainty.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class Capability(str, Enum):
    ONLINE_BOOKING = "ONLINE_BOOKING"
    ONLINE_ORDERING = "ONLINE_ORDERING"
    ECOMMERCE = "ECOMMERCE"
    ONLINE_PAYMENTS = "ONLINE_PAYMENTS"
    LIVE_CHAT = "LIVE_CHAT"
    CONTACT_FORM = "CONTACT_FORM"
    QUOTE_REQUEST = "QUOTE_REQUEST"
    MOBILE_RESPONSIVE = "MOBILE_RESPONSIVE"
    HTTPS = "HTTPS"
    ANALYTICS = "ANALYTICS"
    REVIEWS = "REVIEWS"
    MENU_OR_PRICING = "MENU_OR_PRICING"
    NEWSLETTER = "NEWSLETTER"
    SOCIAL_LINKS = "SOCIAL_LINKS"


# Third-party vendors are the strongest signal available: a page that loads
# calendly.com is running online booking, full stop. Vendor hits are weighted
# far above prose, because "book now" in a paragraph may just be a phone number
# next to the word "book".
VENDOR_SIGNALS: dict[Capability, tuple[str, ...]] = {
    Capability.ONLINE_BOOKING: (
        "calendly.com", "acuityscheduling.com", "squareup.com/appointments",
        "opentable.com", "resy.com", "sevenrooms.com", "mindbodyonline.com",
        "fresha.com", "booksy.com", "setmore.com", "simplybook.me",
        "appointlet.com", "youcanbook.me", "cal.com", "bookwhen.com",
        "timely.com", "vagaro.com", "schedulicity.com", "planyo.com",
        "tidycal.com", "zcal.co", "savvycal.com", "quandoo.", "thefork.",
    ),
    Capability.ONLINE_ORDERING: (
        "ubereats.com", "doordash.com", "deliveroo.", "grubhub.com",
        "just-eat.", "justeat.", "menulog.com", "skipthedishes.com",
        "toasttab.com", "chownow.com", "slicelife.com", "olo.com",
        "order.online", "seamless.com", "postmates.com", "foodpanda.",
    ),
    Capability.ECOMMERCE: (
        "shopify.com", "cdn.shopify", "woocommerce", "bigcommerce.com",
        "magento", "squarespace.com/commerce", "snipcart.com", "ecwid.com",
        "opencart", "prestashop",
    ),
    Capability.ONLINE_PAYMENTS: (
        "js.stripe.com", "paypal.com/sdk", "paypalobjects.com",
        "squareup.com/payments", "checkout.stripe.com", "razorpay.com",
        "braintreegateway.com", "adyen.com", "gocardless.com",
    ),
    Capability.LIVE_CHAT: (
        "intercom.io", "widget.intercom", "drift.com", "tawk.to", "crisp.chat",
        "zendesk.com/embeddable", "tidio.co", "livechatinc.com", "olark.com",
        "hubspot.com/conversations", "wa.me/", "api.whatsapp.com",
        "messenger.com/t/", "chatway", "smartsupp.com",
    ),
    Capability.ANALYTICS: (
        "googletagmanager.com", "google-analytics.com", "gtag/js",
        "connect.facebook.net", "hotjar.com", "clarity.ms", "plausible.io",
        "matomo", "segment.com", "mixpanel.com",
    ),
    Capability.NEWSLETTER: (
        "mailchimp.com", "list-manage.com", "klaviyo.com", "constantcontact.com",
        "convertkit.com", "substack.com", "sendinblue.com", "brevo.com",
    ),
    Capability.REVIEWS: (
        "trustpilot.com", "yotpo.com", "reviews.io", "feefo.com",
        "judge.me", "stamped.io", "birdeye.com", "google.com/maps/place",
    ),
    Capability.SOCIAL_LINKS: (
        "facebook.com/", "instagram.com/", "twitter.com/", "x.com/",
        "linkedin.com/", "tiktok.com/", "youtube.com/",
    ),
}

# Phrase signals are weaker: they show intent but can be satisfied by a phone
# number. They are enough to *rule a capability in* (preventing a false "you're
# missing this"), never enough to prove a polished implementation.
PHRASE_SIGNALS: dict[Capability, tuple[str, ...]] = {
    Capability.ONLINE_BOOKING: (
        "book now", "book online", "book an appointment", "book a table",
        "make a booking", "make a reservation", "schedule an appointment",
        "schedule online", "request an appointment", "reserve a table",
        "book your", "appointment request", "online booking",
    ),
    Capability.ONLINE_ORDERING: (
        "order online", "order now", "add to basket", "add to cart",
        "start your order", "click and collect", "collection or delivery",
    ),
    Capability.ECOMMERCE: ("add to cart", "add to basket", "shopping cart", "proceed to checkout"),
    Capability.QUOTE_REQUEST: (
        "get a quote", "request a quote", "free quote", "free estimate",
        "request an estimate", "get a free consultation", "request a callback",
        "book a consultation", "enquire now", "request pricing",
    ),
    Capability.MENU_OR_PRICING: (
        "our menu", "view menu", "price list", "our prices", "pricing",
        "treatment prices", "services and prices", "tariff",
    ),
    Capability.NEWSLETTER: ("subscribe to our newsletter", "sign up for updates", "join our mailing list"),
    Capability.REVIEWS: ("what our clients say", "testimonials", "customer reviews", "read our reviews"),
}

_FORM_RE = re.compile(r"<form\b[^>]*>(.*?)</form>", re.I | re.S)
_EMAIL_INPUT_RE = re.compile(r'type\s*=\s*["\']?email|name\s*=\s*["\']?(email|e-mail)', re.I)
_MESSAGE_INPUT_RE = re.compile(r"<textarea\b|name\s*=\s*[\"']?(message|enquiry|comments?)", re.I)
_VIEWPORT_RE = re.compile(r'<meta[^>]+name\s*=\s*["\']?viewport', re.I)


@dataclass(slots=True)
class CapabilityFinding:
    capability: Capability
    present: bool
    confidence: float           # 0..1 — how sure we are about `present`
    evidence: list[str] = field(default_factory=list)
    source: str = ""            # "vendor" | "phrase" | "markup" | "none"

    def as_dict(self) -> dict:
        return {
            "capability": self.capability.value,
            "present": self.present,
            "confidence": round(self.confidence, 2),
            "evidence": self.evidence[:5],
            "source": self.source,
        }


@dataclass(slots=True)
class CapabilityReport:
    url: str
    findings: dict[Capability, CapabilityFinding] = field(default_factory=dict)
    pages_fetched: list[str] = field(default_factory=list)
    bytes_analysed: int = 0

    def has(self, cap: Capability) -> bool:
        found = self.findings.get(cap)
        return bool(found and found.present)

    def missing(self) -> list[Capability]:
        return [c for c, f in self.findings.items() if not f.present]

    def present(self) -> list[Capability]:
        return [c for c, f in self.findings.items() if f.present]

    def evidence_for(self, cap: Capability) -> list[str]:
        found = self.findings.get(cap)
        return list(found.evidence) if found else []

    def as_dict(self) -> dict:
        return {
            "url": self.url,
            "pages_fetched": self.pages_fetched,
            "bytes_analysed": self.bytes_analysed,
            "present": [c.value for c in self.present()],
            "missing": [c.value for c in self.missing()],
            "findings": [f.as_dict() for f in self.findings.values()],
        }


def _scan(haystack: str, needles: tuple[str, ...]) -> list[str]:
    return [n for n in needles if n in haystack]


def detect_capabilities(html: str, *, url: str = "", pages: list[str] | None = None) -> CapabilityReport:
    """Detect commercial capabilities in fetched page source.

    *html* should be the concatenated source of every page fetched for this
    business — a booking link often lives on ``/contact`` rather than the home
    page, and judging a site by its home page alone produces false "missing"
    findings.
    """
    report = CapabilityReport(url=url, pages_fetched=pages or [], bytes_analysed=len(html))
    low = html.lower()

    for cap in Capability:
        vendors = _scan(low, VENDOR_SIGNALS.get(cap, ()))
        if vendors:
            report.findings[cap] = CapabilityFinding(
                cap, True, 0.95, [f"loads {v}" for v in vendors[:4]], "vendor"
            )
            continue

        phrases = _scan(low, PHRASE_SIGNALS.get(cap, ()))
        if phrases:
            # Present, but we cannot tell a real booking engine from a "call us
            # to book" line. Enough to stop us claiming it is missing.
            report.findings[cap] = CapabilityFinding(
                cap, True, 0.55, [f'page text: "{p}"' for p in phrases[:4]], "phrase"
            )
            continue

        report.findings[cap] = CapabilityFinding(cap, False, 0.6, [], "none")

    # --- markup-level checks that don't fit the vendor/phrase pattern --------
    forms = _FORM_RE.findall(html)
    contact_forms = [
        f for f in forms if _EMAIL_INPUT_RE.search(f) or _MESSAGE_INPUT_RE.search(f)
    ]
    if contact_forms:
        report.findings[Capability.CONTACT_FORM] = CapabilityFinding(
            Capability.CONTACT_FORM, True, 0.9,
            [f"{len(contact_forms)} form(s) with an email or message field"], "markup",
        )
    else:
        report.findings[Capability.CONTACT_FORM] = CapabilityFinding(
            Capability.CONTACT_FORM, False, 0.8, [], "markup"
        )

    if _VIEWPORT_RE.search(html):
        report.findings[Capability.MOBILE_RESPONSIVE] = CapabilityFinding(
            Capability.MOBILE_RESPONSIVE, True, 0.75, ["<meta name=viewport> present"], "markup",
        )
    else:
        # No viewport tag in 2026 means the site predates responsive design or
        # was never built for phones — a genuine, demonstrable problem.
        report.findings[Capability.MOBILE_RESPONSIVE] = CapabilityFinding(
            Capability.MOBILE_RESPONSIVE, False, 0.9, ["no <meta name=viewport> tag"], "markup",
        )

    secure = url.lower().startswith("https://")
    report.findings[Capability.HTTPS] = CapabilityFinding(
        Capability.HTTPS, secure, 1.0,
        ["served over https"] if secure else ["served over plain http"], "markup",
    )

    return report


# Which missing capability actually matters depends on the trade. A restaurant
# without online ordering is losing covers; a solicitor without one is fine.
# Ordered by commercial weight, strongest first.
CATEGORY_PRIORITIES: dict[str, tuple[Capability, ...]] = {
    "restaurant": (Capability.ONLINE_BOOKING, Capability.ONLINE_ORDERING, Capability.MENU_OR_PRICING),
    "cafe": (Capability.ONLINE_ORDERING, Capability.MENU_OR_PRICING, Capability.ONLINE_BOOKING),
    "bakery": (Capability.ONLINE_ORDERING, Capability.ECOMMERCE, Capability.MENU_OR_PRICING),
    "bar": (Capability.ONLINE_BOOKING, Capability.MENU_OR_PRICING),
    "hotel": (Capability.ONLINE_BOOKING, Capability.ONLINE_PAYMENTS, Capability.REVIEWS),
    "dentist": (Capability.ONLINE_BOOKING, Capability.CONTACT_FORM, Capability.REVIEWS),
    "doctor": (Capability.ONLINE_BOOKING, Capability.CONTACT_FORM),
    "veterinary": (Capability.ONLINE_BOOKING, Capability.CONTACT_FORM),
    "physiotherapist": (Capability.ONLINE_BOOKING, Capability.CONTACT_FORM),
    "salon": (Capability.ONLINE_BOOKING, Capability.MENU_OR_PRICING, Capability.REVIEWS),
    "hairdresser": (Capability.ONLINE_BOOKING, Capability.MENU_OR_PRICING),
    "spa": (Capability.ONLINE_BOOKING, Capability.ONLINE_PAYMENTS),
    "gym": (Capability.ONLINE_BOOKING, Capability.ONLINE_PAYMENTS, Capability.MENU_OR_PRICING),
    "plumber": (Capability.QUOTE_REQUEST, Capability.CONTACT_FORM, Capability.REVIEWS),
    "electrician": (Capability.QUOTE_REQUEST, Capability.CONTACT_FORM, Capability.REVIEWS),
    "roofing": (Capability.QUOTE_REQUEST, Capability.CONTACT_FORM, Capability.REVIEWS),
    "contractor": (Capability.QUOTE_REQUEST, Capability.CONTACT_FORM, Capability.REVIEWS),
    "builder": (Capability.QUOTE_REQUEST, Capability.CONTACT_FORM),
    "landscaper": (Capability.QUOTE_REQUEST, Capability.CONTACT_FORM),
    "car_repair": (Capability.ONLINE_BOOKING, Capability.QUOTE_REQUEST),
    "lawyer": (Capability.CONTACT_FORM, Capability.ONLINE_BOOKING, Capability.REVIEWS),
    "accountant": (Capability.CONTACT_FORM, Capability.ONLINE_BOOKING),
    "estate_agent": (Capability.CONTACT_FORM, Capability.ONLINE_BOOKING),
    "photographer": (Capability.QUOTE_REQUEST, Capability.ONLINE_BOOKING),
    "retail": (Capability.ECOMMERCE, Capability.ONLINE_PAYMENTS, Capability.MENU_OR_PRICING),
    "florist": (Capability.ECOMMERCE, Capability.ONLINE_ORDERING),
}

# Applied when the category is unknown or not listed above.
DEFAULT_PRIORITIES: tuple[Capability, ...] = (
    Capability.CONTACT_FORM,
    Capability.MOBILE_RESPONSIVE,
    Capability.QUOTE_REQUEST,
    Capability.REVIEWS,
)


def priority_gap(
    report: CapabilityReport,
    category: str | None,
    *,
    can_judge_absence: bool = True,
) -> CapabilityFinding | None:
    """The single most commercially relevant capability this business lacks.

    One gap, not a list. A cold email that opens with six problems reads as a
    generated audit; one specific, checkable observation reads as a person who
    looked at the site.

    *can_judge_absence* comes from :attr:`~app.services.enrichment.site_fetch.SiteFetch.can_judge_absence`.
    When it is False the fetch was a bot wall, a parked page, or a JavaScript
    shell, and nothing is missing merely because we could not see it — so no gap
    is returned at all. This is the guard that stops us telling a retailer with
    a JS basket that they have no e-commerce.
    """
    if not can_judge_absence:
        return None

    order = CATEGORY_PRIORITIES.get((category or "").strip().lower(), DEFAULT_PRIORITIES)
    for cap in order:
        finding = report.findings.get(cap)
        if finding and not finding.present:
            return finding
    # Nothing from the priority list is missing — fall back to any real gap,
    # ignoring the ones that are merely nice to have.
    ignorable = {Capability.NEWSLETTER, Capability.ANALYTICS, Capability.SOCIAL_LINKS}
    for cap in report.missing():
        if cap not in ignorable:
            return report.findings[cap]
    return None
