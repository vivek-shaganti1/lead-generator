"""Google Places API (New) provider — the fallback when OSM coverage is thin.

Compliance note (read before enabling): the Google Maps Platform terms allow
caching Places content only for a limited period (place IDs may be stored
indefinitely, other fields must be refreshed - currently a 30 day window), and
forbid re-displaying the data outside a Google map. We therefore treat Google
purely as a *discovery signal*: we keep the place id, and we re-fetch details
rather than treating our copy as durable. `purge_stale_google_content()` in
app/services/compliance/retention.py enforces that.
"""
from __future__ import annotations

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import settings
from app.logging_config import get_logger
from app.services.discovery.base import PlaceCandidate, SearchArea
from app.services.discovery.categories import google_types

log = get_logger(__name__)

BASE_URL = "https://places.googleapis.com/v1"
FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.addressComponents",
        "places.location",
        "places.primaryType",
        "places.nationalPhoneNumber",
        "places.internationalPhoneNumber",
        "places.websiteUri",
        "places.businessStatus",
        "nextPageToken",
    ]
)
MAX_PAGE_SIZE = 20


class GooglePlacesError(RuntimeError):
    pass


class GoogleRateLimitError(GooglePlacesError):
    pass


def _component(components: list[dict], wanted: str, short: bool = False) -> str | None:
    for comp in components or []:
        if wanted in (comp.get("types") or []):
            return comp.get("shortText") if short else comp.get("longText")
    return None


def parse_place(place: dict) -> PlaceCandidate | None:
    name = ((place.get("displayName") or {}).get("text") or "").strip()
    place_id = place.get("id")
    if not name or not place_id:
        return None
    if place.get("businessStatus") in ("CLOSED_PERMANENTLY",):
        return None

    location = place.get("location") or {}
    components = place.get("addressComponents") or []
    return PlaceCandidate(
        source="google",
        source_id=place_id,
        name=name,
        category=place.get("primaryType"),
        phone=place.get("nationalPhoneNumber") or place.get("internationalPhoneNumber"),
        website=place.get("websiteUri"),
        address=place.get("formattedAddress"),
        city=_component(components, "locality") or _component(components, "postal_town"),
        region=_component(components, "administrative_area_level_1"),
        postcode=_component(components, "postal_code"),
        country_code=_component(components, "country", short=True),
        lat=location.get("latitude"),
        lon=location.get("longitude"),
        raw={"google_place_id": place_id, "business_status": place.get("businessStatus")},
    )


class GooglePlacesProvider:
    name = "google"

    def __init__(self, client: httpx.Client | None = None, api_key: str | None = None) -> None:
        self._client = client
        self._api_key = api_key if api_key is not None else settings.google_places_api_key

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=30)
        return self._client

    @retry(
        retry=retry_if_exception_type((GoogleRateLimitError, httpx.TransportError)),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def _post(self, path: str, payload: dict) -> dict:
        if not self._api_key:
            raise GooglePlacesError("GOOGLE_PLACES_API_KEY is not configured")
        response = self._http().post(
            f"{BASE_URL}/{path}",
            json=payload,
            headers={
                "X-Goog-Api-Key": self._api_key,
                "X-Goog-FieldMask": FIELD_MASK,
                "Content-Type": "application/json",
            },
        )
        if response.status_code == 429:
            raise GoogleRateLimitError("Google Places rate limit")
        if response.status_code >= 400:
            raise GooglePlacesError(f"{response.status_code}: {response.text[:300]}")
        return response.json()

    def search(
        self, area: SearchArea, categories: list[str], limit: int = 200
    ) -> list[PlaceCandidate]:
        area.validate()
        types = google_types(categories)
        if not types:
            raise ValueError("none of the requested categories map to a Google place type")

        results: list[PlaceCandidate] = []
        seen: set[str] = set()
        for place_type in types:
            if len(results) >= limit:
                break
            for place in self._search_type(area, place_type, limit - len(results)):
                candidate = parse_place(place)
                if candidate and candidate.is_valid() and candidate.source_id not in seen:
                    seen.add(candidate.source_id)
                    results.append(candidate)
        log.info("google.search_done", area=area.label, count=len(results))
        return results[:limit]

    def _search_type(self, area: SearchArea, place_type: str, remaining: int) -> list[dict]:
        payload: dict = {
            "includedTypes": [place_type],
            "maxResultCount": min(MAX_PAGE_SIZE, max(1, remaining)),
        }
        if area.is_bbox:
            payload["locationRestriction"] = {
                "rectangle": {
                    "low": {"latitude": area.south, "longitude": area.west},
                    "high": {"latitude": area.north, "longitude": area.east},
                }
            }
        else:
            # Nearby search requires geometry; fall back to text search by name.
            return self._text_search(f"{place_type} in {area.area_name}", remaining)
        data = self._post("places:searchNearby", payload)
        return data.get("places") or []

    def _text_search(self, query: str, remaining: int) -> list[dict]:
        out: list[dict] = []
        page_token = None
        while len(out) < remaining:
            payload = {"textQuery": query, "pageSize": MAX_PAGE_SIZE}
            if page_token:
                payload["pageToken"] = page_token
            data = self._post("places:searchText", payload)
            out.extend(data.get("places") or [])
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return out[:remaining]

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
