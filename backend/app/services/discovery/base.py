"""Provider-agnostic discovery contract.

Every map provider normalises into PlaceCandidate, so the pipeline downstream
(dedupe -> enrich -> lead) never learns which provider produced a row.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.utils import dedupe_key, domain_of, is_social_only


@dataclass(slots=True)
class PlaceCandidate:
    source: str
    source_id: str
    name: str
    category: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    facebook: str | None = None
    instagram: str | None = None
    address: str | None = None
    city: str | None = None
    region: str | None = None
    postcode: str | None = None
    country_code: str | None = None
    lat: float | None = None
    lon: float | None = None
    raw: dict = field(default_factory=dict)

    @property
    def has_real_website(self) -> bool:
        """A social profile or an aggregator listing does not count as a website."""
        if not self.website:
            return False
        if is_social_only(self.website):
            return False
        return bool(domain_of(self.website))

    @property
    def key(self) -> str:
        return dedupe_key(self.name, self.lat, self.lon, self.phone)

    def is_valid(self) -> bool:
        return bool(self.name and self.name.strip()) and bool(self.source_id)


@dataclass(slots=True)
class SearchArea:
    """Either a bounding box or a named administrative area."""

    label: str
    south: float | None = None
    west: float | None = None
    north: float | None = None
    east: float | None = None
    area_name: str | None = None
    country_code: str | None = None

    @property
    def is_bbox(self) -> bool:
        return None not in (self.south, self.west, self.north, self.east)

    def validate(self) -> None:
        if not self.is_bbox and not self.area_name:
            raise ValueError("SearchArea needs either a bbox or an area_name")
        if self.is_bbox:
            if not (-90 <= self.south <= 90 and -90 <= self.north <= 90):
                raise ValueError("latitude out of range")
            if not (-180 <= self.west <= 180 and -180 <= self.east <= 180):
                raise ValueError("longitude out of range")
            if self.south >= self.north or self.west >= self.east:
                raise ValueError("bbox corners are inverted")


class DiscoveryProvider(Protocol):
    name: str

    def search(self, area: SearchArea, categories: list[str], limit: int) -> list[PlaceCandidate]:
        ...
