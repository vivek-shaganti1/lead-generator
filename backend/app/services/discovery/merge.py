"""Cross-provider dedupe and record merging."""
from __future__ import annotations

from app.services.discovery.base import PlaceCandidate

# Higher wins when two providers describe the same place.
SOURCE_PRIORITY = {"manual": 3, "google": 2, "overpass": 1, "import": 0}


def _richness(c: PlaceCandidate) -> int:
    """How many useful fields this record actually carries."""
    fields = (c.phone, c.email, c.website, c.address, c.postcode, c.lat, c.city)
    return sum(1 for f in fields if f)


def merge_pair(primary: PlaceCandidate, other: PlaceCandidate) -> PlaceCandidate:
    """Fill primary's blanks from other. Never overwrites a value we already have."""
    for field in (
        "category", "phone", "email", "website", "facebook", "instagram",
        "address", "city", "region", "postcode", "country_code", "lat", "lon",
    ):
        if getattr(primary, field, None) in (None, "") and getattr(other, field, None):
            setattr(primary, field, getattr(other, field))
    merged_raw = dict(other.raw or {})
    merged_raw.update(primary.raw or {})
    primary.raw = merged_raw
    primary.raw.setdefault("merged_sources", [])
    if other.source not in primary.raw["merged_sources"]:
        primary.raw["merged_sources"].append(other.source)
    return primary


def dedupe(candidates: list[PlaceCandidate]) -> list[PlaceCandidate]:
    """Collapse candidates that describe the same physical business.

    Keeps the record from the highest-priority source, breaking ties by how
    much data it carries, then folds in the losers' extra fields.
    """
    buckets: dict[str, PlaceCandidate] = {}
    for candidate in candidates:
        if not candidate.is_valid():
            continue
        key = candidate.key
        existing = buckets.get(key)
        if existing is None:
            buckets[key] = candidate
            continue
        existing_rank = (SOURCE_PRIORITY.get(existing.source, 0), _richness(existing))
        new_rank = (SOURCE_PRIORITY.get(candidate.source, 0), _richness(candidate))
        if new_rank > existing_rank:
            buckets[key] = merge_pair(candidate, existing)
        else:
            buckets[key] = merge_pair(existing, candidate)
    return list(buckets.values())
