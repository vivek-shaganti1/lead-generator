"""Discovery -> businesses -> qualified leads.

Split into two halves on purpose:
  ingest_candidates()  - pure database work, no network, fast, transactional
  qualify_business()   - the slow part (HTTP checks, scraping), run per-business
                         by a worker so one dead website can't stall a whole run.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.logging_config import get_logger
from app.models import (
    Business,
    Campaign,
    DiscoveryRun,
    DiscoveryStatus,
    Event,
    Lead,
    LeadStatus,
)
from app.services.compliance.policy import country_allowed, is_suppressed
from app.services.discovery.base import PlaceCandidate, SearchArea
from app.services.discovery.categories import resolve
from app.services.discovery.google_places import GooglePlacesProvider
from app.services.discovery.merge import dedupe
from app.services.discovery.overpass import OverpassProvider
from app.services.enrichment.email_finder import find_email
from app.services.enrichment.scoring import score_lead
from app.services.enrichment.validator import validate
from app.services.enrichment.website_check import WebPresence, check_website, classify_static
from app.services.outreach.templates import default_campaign_payload
from app.services.outreach.throttle import timezone_for
from app.utils import dedupe_key, new_token, utcnow

log = get_logger(__name__)

# If OSM gives us fewer than this for an area, it is probably under-mapped and
# Google is worth the money.
GOOGLE_FALLBACK_THRESHOLD = 15


@dataclass(slots=True)
class IngestStats:
    found: int = 0
    new: int = 0
    updated: int = 0
    without_website: int = 0

    def as_dict(self) -> dict:
        return {
            "found": self.found, "new": self.new,
            "updated": self.updated, "without_website": self.without_website,
        }


def _area_dict(area: SearchArea) -> dict:
    """SearchArea uses __slots__, so it has no __dict__ to copy."""
    return {
        "label": area.label, "south": area.south, "west": area.west,
        "north": area.north, "east": area.east, "area_name": area.area_name,
        "country_code": area.country_code,
    }


def get_or_create_default_campaign(db: Session) -> Campaign:
    campaign = db.execute(
        select(Campaign).where(Campaign.is_active.is_(True)).order_by(Campaign.id)
    ).scalars().first()
    if campaign:
        return campaign
    campaign = Campaign(**default_campaign_payload())
    db.add(campaign)
    db.flush()
    return campaign


# --------------------------------------------------------------------- ingest
def _apply_candidate(business: Business, candidate: PlaceCandidate) -> None:
    """Copy candidate data onto a Business row without erasing what we already know."""
    business.name = candidate.name or business.name
    for field in (
        "category", "phone", "email", "website", "facebook", "instagram",
        "address", "city", "region", "postcode", "country_code", "lat", "lon",
    ):
        value = getattr(candidate, field, None)
        if value not in (None, ""):
            setattr(business, field, value)
    business.has_website = candidate.has_real_website
    merged = dict(business.raw or {})
    merged.update(candidate.raw or {})
    business.raw = merged
    if business.lat is not None and business.timezone_name is None:
        business.timezone_name = timezone_for(business.lat, business.lon)


def ingest_candidates(
    db: Session, candidates: list[PlaceCandidate], run: DiscoveryRun | None = None
) -> IngestStats:
    stats = IngestStats(found=len(candidates))
    for candidate in dedupe(candidates):
        existing = db.execute(
            select(Business).where(
                Business.source == candidate.source, Business.source_id == candidate.source_id
            )
        ).scalars().first()

        if existing is None:
            key = candidate.key
            existing = db.execute(
                select(Business).where(Business.dedupe_key == key)
            ).scalars().first()
            if existing is not None:
                # Same place, different provider: enrich the row we already have.
                _apply_candidate(existing, candidate)
                stats.updated += 1
            else:
                business = Business(
                    source=candidate.source,
                    source_id=candidate.source_id,
                    dedupe_key=key,
                    name=candidate.name,
                    discovery_run_id=run.id if run else None,
                )
                _apply_candidate(business, candidate)
                db.add(business)
                db.flush()
                stats.new += 1
                existing = business
        else:
            _apply_candidate(existing, candidate)
            stats.updated += 1

        if not existing.has_website:
            stats.without_website += 1

    db.flush()
    return stats


def run_discovery(
    db: Session,
    *,
    area: SearchArea,
    categories: list[str] | None = None,
    limit: int | None = None,
    use_google_fallback: bool | None = None,
    overpass_provider=None,
    google_provider=None,
) -> DiscoveryRun:
    """Execute one discovery run end to end and record it."""
    categories = resolve(categories)
    limit = limit or settings.discovery_max_results_per_run
    area.validate()

    run = DiscoveryRun(
        provider="overpass",
        area_label=area.label,
        query={"categories": categories, "area": _area_dict(area), "limit": limit},
        status=DiscoveryStatus.RUNNING,
        started_at=utcnow(),
    )
    db.add(run)
    db.flush()

    candidates: list[PlaceCandidate] = []
    errors: list[str] = []

    provider = overpass_provider or OverpassProvider()
    try:
        candidates.extend(provider.search(area, categories, limit))
    except Exception as exc:
        errors.append(f"overpass: {exc}")
        log.error("discovery.overpass_failed", error=str(exc), area=area.label)

    should_fallback = (
        settings.google_places_enabled if use_google_fallback is None else use_google_fallback
    )
    if should_fallback and len(candidates) < GOOGLE_FALLBACK_THRESHOLD:
        g_provider = google_provider or GooglePlacesProvider()
        try:
            found = g_provider.search(area, categories, limit - len(candidates))
            candidates.extend(found)
            run.provider = "overpass+google"
        except Exception as exc:
            errors.append(f"google: {exc}")
            log.error("discovery.google_failed", error=str(exc), area=area.label)

    stats = ingest_candidates(db, candidates, run)
    run.found_total = stats.found
    run.new_businesses = stats.new
    run.without_website = stats.without_website
    run.finished_at = utcnow()
    run.error = "; ".join(errors) or None

    if errors and not candidates:
        run.status = DiscoveryStatus.FAILED
    elif errors:
        run.status = DiscoveryStatus.PARTIAL
    else:
        run.status = DiscoveryStatus.SUCCESS

    db.add(Event(type="discovery.completed", payload={
        "run_id": run.id, "area": area.label, **stats.as_dict(),
        "status": run.status.value,
    }))
    db.flush()
    return run


# -------------------------------------------------------------------- qualify
@dataclass(slots=True)
class QualifyResult:
    created: bool
    reason: str
    lead_id: int | None = None
    presence: str | None = None


def qualify_business(
    db: Session,
    business: Business,
    campaign: Campaign | None = None,
    *,
    client: httpx.Client | None = None,
    check_site: bool = True,
) -> QualifyResult:
    """Decide whether this business becomes a Lead, and build it if so."""
    existing = db.execute(
        select(Lead).where(Lead.business_id == business.id)
    ).scalars().first()
    if existing:
        return QualifyResult(False, "lead already exists", existing.id)

    check = classify_static(business.website)
    if check is None:
        # Only a URL we cannot judge offline costs us a network round trip.
        if not check_site:
            return QualifyResult(False, "website not checked")
        check = check_website(business.website, client=client)

    business.website_checked_at = utcnow()
    business.website_alive = check.presence == WebPresence.LIVE
    business.has_website = check.presence == WebPresence.LIVE

    if not check.is_prospect:
        return QualifyResult(False, f"has a working website ({check.detail})",
                             presence=check.presence.value)

    decision = country_allowed(business.country_code)
    if not decision.allowed:
        return QualifyResult(False, f"country blocked: {decision.reason}",
                             presence=check.presence.value)

    finding = find_email(
        map_email=business.email,
        website=business.website,
        business_name=business.name,
        country_code=business.country_code,
        client=client,
    )
    if finding is None:
        return QualifyResult(False, "no contact email found", presence=check.presence.value)

    validated = validate(finding.email)
    if not validated.valid:
        return QualifyResult(False, f"email rejected: {validated.reason}",
                             presence=check.presence.value)

    if is_suppressed(db, validated.email):
        return QualifyResult(False, "address is suppressed", presence=check.presence.value)

    business.email = validated.email
    campaign = campaign or get_or_create_default_campaign(db)

    score, breakdown = score_lead(
        presence=check.presence,
        category=business.category,
        email_confidence=finding.confidence,
        is_role_account=finding.is_role,
        has_phone=bool(business.phone),
        has_address=bool(business.address),
        has_social=bool(business.facebook or business.instagram),
    )

    lead = Lead(
        business_id=business.id,
        campaign_id=campaign.id,
        email=validated.email,
        email_source=finding.source,
        email_confidence=finding.confidence,
        is_role_account=finding.is_role,
        score=score,
        unsubscribe_token=new_token(),
        status=(
            LeadStatus.NEEDS_APPROVAL if settings.require_manual_approval else LeadStatus.READY
        ),
        approved=not settings.require_manual_approval,
        next_action_at=utcnow(),
        notes=None,
    )
    db.add(lead)
    db.flush()
    db.add(Event(type="lead.created", lead_id=lead.id, payload={
        "business": business.name, "presence": check.presence.value,
        "email_source": finding.source, "score": score, "score_breakdown": breakdown,
    }))
    return QualifyResult(True, "lead created", lead.id, check.presence.value)


def ensure_dedupe_key(business: Business) -> str:
    if not business.dedupe_key:
        business.dedupe_key = dedupe_key(
            business.name, business.lat, business.lon, business.phone
        )
    return business.dedupe_key
