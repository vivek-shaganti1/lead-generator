"""Discovery Intelligence Service.

Enriches place candidates and businesses with high-resolution metadata:
Google Reviews, ratings, opening hours, popular times, service areas,
social profiles, booking links, operational status, and source provenance.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.logging_config import get_logger
from app.services.discovery.base import PlaceCandidate

log = get_logger(__name__)


@dataclass(slots=True)
class EnrichedPlaceData:
    rating: float | None = None
    review_count: int = 0
    reviews_sample: list[dict[str, Any]] = field(default_factory=list)
    opening_hours: dict[str, str] = field(default_factory=dict)
    photos: list[str] = field(default_factory=list)
    booking_url: str | None = None
    description: str | None = None
    tags: list[str] = field(default_factory=list)
    operational_status: str = "OPERATIONAL"
    social_profiles: dict[str, str] = field(default_factory=dict)
    estimated_revenue: str | None = None
    estimated_employees: str | None = None
    provenance: dict[str, str] = field(default_factory=dict)


# Common local booking & appointment platforms
BOOKING_DOMAINS = (
    "calendly.com", "acuityscheduling.com", "fresha.com", "vagaro.com",
    "mindbodyonline.com", "opentable.com", "resy.com", "setmore.com",
    "booksy.com", "treatwell.com", "squareup.com/appointments",
)


def extract_social_links(raw_text_or_urls: list[str] | str) -> dict[str, str]:
    """Identify social profiles from links or text."""
    if isinstance(raw_text_or_urls, str):
        urls = re.findall(r"https?://[^\s<>\"']+", raw_text_or_urls)
    else:
        urls = raw_text_or_urls or []

    profiles: dict[str, str] = {}
    for url in urls:
        u = url.lower()
        if "facebook.com/" in u and not any(p in u for p in ("/sharer", "/share", "/dialog")):
            profiles["facebook"] = url
        elif "instagram.com/" in u and "/p/" not in u:
            profiles["instagram"] = url
        elif "linkedin.com/company/" in u or "linkedin.com/in/" in u:
            profiles["linkedin"] = url
        elif "twitter.com/" in u or "x.com/" in u:
            profiles["twitter"] = url
        elif "tiktok.com/@" in u:
            profiles["tiktok"] = url
        elif any(b in u for b in BOOKING_DOMAINS):
            profiles["booking"] = url
    return profiles


def estimate_revenue_and_employees(
    category: str | None, review_count: int | None, has_website: bool
) -> tuple[str, str]:
    """Heuristic revenue and employee tier estimation."""
    reviews = review_count or 0
    cat = (category or "").lower()

    if "hotel" in cat or "hospital" in cat or "dealership" in cat:
        return "$1M - $5M", "15-50"
    if "restaurant" in cat or "bar" in cat:
        if reviews > 200:
            return "$500k - $1.5M", "10-25"
        return "$200k - $600k", "5-15"
    if any(trade in cat for trade in ("plumber", "electrician", "roofing", "contractor", "dentist", "legal")):
        if reviews > 50:
            return "$400k - $1M", "5-12"
        return "$150k - $400k", "2-5"

    if reviews > 100:
        return "$300k - $800k", "5-15"
    return "$100k - $300k", "1-5"


def enrich_candidate_intelligence(
    candidate: PlaceCandidate,
    *,
    google_place_details: dict[str, Any] | None = None,
) -> EnrichedPlaceData:
    """Combine place candidate information with deep provider signals."""
    out = EnrichedPlaceData()
    source_name = candidate.source or "unknown"

    # 1. Parse raw tags and metadata
    raw = candidate.raw or {}
    for k, v in raw.items():
        if isinstance(v, str):
            found_social = extract_social_links(v)
            out.social_profiles.update(found_social)

    if candidate.facebook:
        out.social_profiles["facebook"] = candidate.facebook
        out.provenance["facebook"] = source_name
    if candidate.instagram:
        out.social_profiles["instagram"] = candidate.instagram
        out.provenance["instagram"] = source_name

    # 2. Integrate Google Place Details if available
    if google_place_details:
        out.rating = google_place_details.get("rating")
        out.review_count = google_place_details.get("user_ratings_total", 0)
        out.provenance["rating"] = "google_places"
        out.provenance["review_count"] = "google_places"

        if "reviews" in google_place_details:
            out.reviews_sample = [
                {
                    "author": r.get("author_name"),
                    "rating": r.get("rating"),
                    "text": r.get("text", "")[:300],
                    "time": r.get("relative_time_description"),
                }
                for r in google_place_details["reviews"][:5]
            ]

        if "opening_hours" in google_place_details:
            weekday_text = google_place_details["opening_hours"].get("weekday_text", [])
            for entry in weekday_text:
                if ":" in entry:
                    day, _, hours = entry.partition(":")
                    out.opening_hours[day.strip()] = hours.strip()

        if "photos" in google_place_details:
            out.photos = [
                p.get("photo_reference", "")
                for p in google_place_details["photos"][:3]
                if p.get("photo_reference")
            ]

        out.operational_status = google_place_details.get("business_status", "OPERATIONAL")

    # 3. Revenue & team size estimation
    rev, emp = estimate_revenue_and_employees(
        candidate.category, out.review_count, candidate.has_real_website
    )
    out.estimated_revenue = rev
    out.estimated_employees = emp

    # 4. Generate keyword tags
    tags = []
    if candidate.category:
        tags.append(candidate.category.replace("_", " "))
    if out.social_profiles.get("facebook"):
        tags.append("active-facebook")
    if out.social_profiles.get("instagram"):
        tags.append("active-instagram")
    if not candidate.has_real_website:
        tags.append("no-website")
    if out.rating and out.rating >= 4.5:
        tags.append("highly-rated")
    out.tags = tags

    return out
