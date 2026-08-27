"""OpenStreetMap discovery via the Overpass API.

Overpass is free and global, and OSM tags tell us directly whether a place has
a website. We are a polite client: identifying User-Agent, a hard interval
between calls, and exponential backoff on 429/504 (Overpass' 'slow down' codes).
"""
from __future__ import annotations

import threading
import time

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings
from app.logging_config import get_logger
from app.services.discovery.base import PlaceCandidate, SearchArea
from app.services.discovery.categories import label_for_osm_tags, osm_filters

log = get_logger(__name__)

WEBSITE_TAGS = ("website", "contact:website", "url", "website:official")
PHONE_TAGS = ("phone", "contact:phone", "contact:mobile", "mobile")
EMAIL_TAGS = ("email", "contact:email")


class OverpassRateLimitError(RuntimeError):
    """Overpass asked us to back off (429 / 504)."""


class _Throttle:
    """Process-wide minimum interval between Overpass calls."""

    def __init__(self, min_interval: float) -> None:
        self._min_interval = min_interval
        self._lock = threading.Lock()
        # None (not 0.0) means "never called" - a clock that legitimately reads
        # zero must not be mistaken for the first call.
        self._last: float | None = None

    def wait(self, sleeper=time.sleep, clock=time.monotonic) -> float:
        with self._lock:
            slept = 0.0
            if self._last is not None:
                delta = clock() - self._last
                if delta < self._min_interval:
                    slept = self._min_interval - delta
                    sleeper(slept)
            self._last = clock()
            return slept


_throttle = _Throttle(settings.overpass_min_interval_seconds)


def build_query(area: SearchArea, categories: list[str], timeout: int | None = None) -> str:
    """Compose Overpass QL for every requested category across nodes/ways/relations."""
    area.validate()
    filters = osm_filters(categories)
    if not filters:
        raise ValueError("no OSM filters resolved for the requested categories")
    timeout = timeout or settings.overpass_timeout

    if area.is_bbox:
        scope = f"({area.south},{area.west},{area.north},{area.east})"
        prelude = ""
    else:
        # area name -> Overpass area id, resolved server-side
        escaped = area.area_name.replace('"', '\\"')
        prelude = f'area["name"="{escaped}"]->.searchArea;\n'
        scope = "(area.searchArea)"

    parts = []
    for tag_k, tag_v in filters:
        for element in ("node", "way", "relation"):
            parts.append(f'  {element}["{tag_k}"="{tag_v}"]["name"]{scope};')
    body = "\n".join(parts)
    return f'[out:json][timeout:{timeout}];\n{prelude}(\n{body}\n);\nout center tags;'


def _first_tag(tags: dict, keys: tuple[str, ...]) -> str | None:
    for k in keys:
        value = tags.get(k)
        if value and str(value).strip():
            return str(value).strip()
    return None


def parse_element(element: dict, default_country: str | None = None) -> PlaceCandidate | None:
    """Turn one Overpass element into a candidate, or None if unusable."""
    tags = element.get("tags") or {}
    name = (tags.get("name") or "").strip()
    if not name:
        return None

    lat = element.get("lat")
    lon = element.get("lon")
    if lat is None and isinstance(element.get("center"), dict):
        lat = element["center"].get("lat")
        lon = element["center"].get("lon")

    website = _first_tag(tags, WEBSITE_TAGS)
    facebook = _first_tag(tags, ("contact:facebook", "facebook"))
    instagram = _first_tag(tags, ("contact:instagram", "instagram"))

    street = " ".join(
        p for p in (tags.get("addr:housenumber"), tags.get("addr:street")) if p
    ).strip()
    address = ", ".join(p for p in (street, tags.get("addr:city")) if p) or None

    country = (tags.get("addr:country") or default_country or "").upper()[:2] or None

    return PlaceCandidate(
        source="overpass",
        source_id=f"{element.get('type', 'node')}/{element.get('id')}",
        name=name,
        category=label_for_osm_tags(tags),
        phone=_first_tag(tags, PHONE_TAGS),
        email=_first_tag(tags, EMAIL_TAGS),
        website=website,
        facebook=facebook,
        instagram=instagram,
        address=address,
        city=tags.get("addr:city"),
        region=tags.get("addr:state") or tags.get("addr:province"),
        postcode=tags.get("addr:postcode"),
        country_code=country,
        lat=float(lat) if lat is not None else None,
        lon=float(lon) if lon is not None else None,
        raw={"tags": tags, "osm_type": element.get("type"), "osm_id": element.get("id")},
    )


def parse_response(payload: dict, default_country: str | None = None) -> list[PlaceCandidate]:
    out: list[PlaceCandidate] = []
    for element in payload.get("elements") or []:
        try:
            candidate = parse_element(element, default_country)
        except (TypeError, ValueError) as exc:  # a single bad row must not kill the run
            log.warning("overpass.parse_element_failed", error=str(exc))
            continue
        if candidate and candidate.is_valid():
            out.append(candidate)
    return out


class OverpassProvider:
    name = "overpass"

    def __init__(self, client: httpx.Client | None = None, url: str | None = None) -> None:
        self._client = client
        self._url = url or settings.overpass_url

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=settings.overpass_timeout + 30,
                headers={"User-Agent": settings.user_agent},
            )
        return self._client

    @retry(
        retry=retry_if_exception_type((OverpassRateLimitError, httpx.TransportError)),
        wait=wait_exponential(multiplier=5, min=5, max=120),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def _post(self, query: str) -> dict:
        _throttle.wait()
        response = self._http().post(self._url, data={"data": query})
        if response.status_code in (429, 504):
            raise OverpassRateLimitError(f"Overpass returned {response.status_code}")
        response.raise_for_status()
        return response.json()

    def search(
        self, area: SearchArea, categories: list[str], limit: int = 500
    ) -> list[PlaceCandidate]:
        query = build_query(area, categories)
        log.info("overpass.search", area=area.label, categories=categories)
        payload = self._post(query)
        results = parse_response(payload, default_country=area.country_code)
        log.info("overpass.search_done", area=area.label, count=len(results))
        return results[:limit]

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
