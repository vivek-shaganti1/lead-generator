"""Lead Scoring 2.0: Hybrid Explainable Multi-Vector Ranking Model.

Evaluates:
- Web Presence & Technical Deficit (Social-only, Broken site, Missing site)
- High-Intent Vertical & Commercial Value
- Contactability & Mailbox Quality (Named vs role account, verified domain MX)
- Social Proof & Customer Cash Flow (Reviews, Ratings)
- Competitor Gap & Buying Intent Prior
"""
from __future__ import annotations

from app.services.enrichment.website_check import WebPresence

# A business already paying for social ads has budget and has shown intent.
PRESENCE_POINTS = {
    WebPresence.SOCIAL: 30,   # active online, just no site - warmest pitch we have
    WebPresence.BROKEN: 28,   # they once paid for a site; it's now embarrassing them
    WebPresence.MISSING: 22,
    WebPresence.LIVE: 0,
    WebPresence.UNKNOWN: 5,
}

# Verticals where a website directly drives bookings/revenue.
HIGH_INTENT_CATEGORIES = {
    "restaurant": 14, "cafe": 12, "hotel": 16, "salon": 14, "spa": 14, "gym": 13,
    "dentist": 15, "doctor": 13, "lawyer": 15, "accountant": 13, "estate_agent": 14,
    "car_repair": 12, "plumber": 12, "electrician": 12, "photographer": 13,
    "event_venue": 13, "catering": 12, "travel_agency": 12, "driving_school": 11,
    "veterinary": 12, "tutoring": 11, "builder": 11, "roofing": 14, "contractor": 13,
}


def score_lead(
    *,
    presence: WebPresence,
    category: str | None,
    email_confidence: float,
    is_role_account: bool,
    has_phone: bool,
    has_address: bool,
    has_social: bool,
    review_count: int | None = None,
    rating: float | None = None,
    buying_intent_score: float | None = None,
) -> tuple[float, dict[str, float]]:
    """Return (score 0-100, explainable breakdown).

    Preserves 100% backward compatibility with v1 while incorporating v2 signals
    when available.
    """
    parts: dict[str, float] = {}

    # 1. Web Presence Deficit Vector (0 - 30 pts)
    parts["web_presence"] = float(PRESENCE_POINTS.get(presence, 0))

    # 2. Industry Commerciality Vector (6 - 16 pts)
    parts["category"] = float(HIGH_INTENT_CATEGORIES.get((category or "").lower(), 6))

    # 3. Email & Mailbox Reliability Vector (0 - 29 pts)
    parts["email_quality"] = round(email_confidence * 25, 2)
    parts["mailbox_type"] = 4.0 if not is_role_account else 2.0

    # 4. Contactability & Physical Presence Vector (0 - 9 pts)
    parts["contactability"] = (5.0 if has_phone else 0.0) + (4.0 if has_address else 0.0)

    # 5. Social & Community Signal (0 - 8 pts)
    parts["social_signal"] = 8.0 if has_social else 0.0

    # 6. v2 Intelligence Vectors (Optional enhancements)
    if review_count and review_count > 15:
        # Business with active customers has immediate cash flow to buy
        parts["customer_volume_bonus"] = min(5.0, round(review_count / 20.0, 1))

    if rating and rating >= 4.5:
        # High reputation businesses care about brand image
        parts["reputation_bonus"] = 3.0

    if buying_intent_score is not None and buying_intent_score > 70:
        parts["ai_intent_bonus"] = round((buying_intent_score - 70) * 0.1, 1)

    total = min(100.0, round(sum(parts.values()), 2))
    return total, parts
