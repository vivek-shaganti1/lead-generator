from __future__ import annotations

import httpx
import pytest
from tenacity import wait_none

from app.services.discovery.base import PlaceCandidate, SearchArea
from app.services.discovery.categories import osm_filters, resolve
from app.services.discovery.google_places import parse_place
from app.services.discovery.merge import dedupe, merge_pair
from app.services.discovery.overpass import (
    OverpassProvider,
    OverpassRateLimitError,
    build_query,
    parse_element,
    parse_response,
)

CORK = SearchArea(label="Cork", south=51.85, west=-8.55, north=51.95, east=-8.40,
                  country_code="IE")


# ------------------------------------------------------------------ categories
def test_resolve_rejects_unknown_category():
    with pytest.raises(ValueError, match="Unknown categories"):
        resolve(["restaurant", "spaceport"])


def test_resolve_defaults_and_dedupes():
    assert resolve(None)
    assert resolve(["cafe", "cafe", "restaurant"]) == ["cafe", "restaurant"]


def test_osm_filters_expand_categories():
    filters = osm_filters(["cafe", "bar"])
    assert ("amenity", "cafe") in filters
    assert ("amenity", "pub") in filters


# --------------------------------------------------------------------- query
def test_build_query_covers_all_element_types_and_bbox():
    query = build_query(CORK, ["cafe"])
    assert '[out:json]' in query
    assert query.count("(51.85,-8.55,51.95,-8.4)") == 3  # node, way, relation
    assert '["amenity"="cafe"]["name"]' in query


def test_build_query_for_named_area():
    area = SearchArea(label="Galway", area_name="Galway", country_code="IE")
    query = build_query(area, ["cafe"])
    assert 'area["name"="Galway"]->.searchArea' in query
    assert "(area.searchArea)" in query


def test_search_area_validation():
    with pytest.raises(ValueError, match="either a bbox or an area_name"):
        SearchArea(label="nowhere").validate()
    with pytest.raises(ValueError, match="inverted"):
        SearchArea(label="bad", south=52.0, west=-8.0, north=51.0, east=-7.0).validate()


# --------------------------------------------------------------------- parse
def test_parse_element_without_website():
    element = {
        "type": "node", "id": 42, "lat": 51.9, "lon": -8.47,
        "tags": {
            "name": "Rossi's Trattoria", "amenity": "restaurant",
            "contact:phone": "+353 21 555 0100", "addr:city": "Cork",
            "addr:housenumber": "12", "addr:street": "Main Street",
        },
    }
    candidate = parse_element(element, default_country="IE")
    assert candidate.name == "Rossi's Trattoria"
    assert candidate.category == "restaurant"
    assert candidate.phone == "+353 21 555 0100"
    assert candidate.address == "12 Main Street, Cork"
    assert candidate.country_code == "IE"
    assert candidate.has_real_website is False


def test_parse_element_uses_center_for_ways():
    element = {"type": "way", "id": 7, "center": {"lat": 51.1, "lon": -8.1},
               "tags": {"name": "Shop", "shop": "bakery"}}
    candidate = parse_element(element)
    assert (candidate.lat, candidate.lon) == (51.1, -8.1)
    assert candidate.source_id == "way/7"


def test_parse_element_skips_unnamed():
    assert parse_element({"type": "node", "id": 1, "tags": {"amenity": "cafe"}}) is None


def test_social_website_is_not_a_real_website():
    candidate = PlaceCandidate(
        source="overpass", source_id="node/1", name="Shop",
        website="https://facebook.com/shop",
    )
    assert candidate.has_real_website is False


def test_real_website_detected():
    candidate = PlaceCandidate(
        source="overpass", source_id="node/1", name="Shop", website="https://shop.ie"
    )
    assert candidate.has_real_website is True


def test_parse_response_survives_bad_rows():
    payload = {"elements": [
        {"type": "node", "id": 1, "tags": {"name": "Good", "amenity": "cafe"},
         "lat": 51.0, "lon": -8.0},
        {"garbage": True},
        {"type": "node", "id": 2, "tags": {}},
    ]}
    results = parse_response(payload)
    assert len(results) == 1
    assert results[0].name == "Good"


# --------------------------------------------------------------------- dedupe
def _candidate(**kw):
    base = dict(source="overpass", source_id="node/1", name="Cafe Roma",
                lat=51.9, lon=-8.47)
    base.update(kw)
    return PlaceCandidate(**base)


def test_dedupe_merges_same_place_from_two_providers():
    osm = _candidate(source="overpass", source_id="node/1", phone="+353 21 555 0100")
    google = _candidate(source="google", source_id="ChIJ1", name="Cafe Roma Ltd",
                        phone="00353 21 555 0100", address="1 Main St", city="Cork")
    merged = dedupe([osm, google])
    assert len(merged) == 1
    winner = merged[0]
    assert winner.source == "google"          # google outranks overpass
    assert winner.address == "1 Main St"
    assert "overpass" in winner.raw["merged_sources"]


def test_dedupe_keeps_distinct_businesses():
    a = _candidate(name="Cafe Roma", source_id="node/1")
    b = _candidate(name="Cafe Milano", source_id="node/2")
    assert len(dedupe([a, b])) == 2


def test_merge_pair_never_overwrites_existing_values():
    primary = _candidate(phone="111111111", website="https://a.ie")
    other = _candidate(phone="222222222", website="https://b.ie", email="x@a.ie")
    result = merge_pair(primary, other)
    assert result.phone == "111111111"
    assert result.website == "https://a.ie"
    assert result.email == "x@a.ie"


def test_dedupe_drops_invalid_candidates():
    assert dedupe([_candidate(name="")]) == []


# ------------------------------------------------------------------- provider
def test_overpass_provider_parses_transport_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert b"amenity" in request.content
        return httpx.Response(200, json={"elements": [
            {"type": "node", "id": 9, "lat": 51.9, "lon": -8.4,
             "tags": {"name": "Bella", "amenity": "cafe"}}
        ]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = OverpassProvider(client=client, url="http://mock/api")
    results = provider.search(CORK, ["cafe"], limit=10)
    assert [r.name for r in results] == ["Bella"]


def test_overpass_rate_limit_raises_after_retries(monkeypatch):
    monkeypatch.setattr("app.services.discovery.overpass._throttle.wait", lambda *a, **k: 0.0)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = OverpassProvider(client=client, url="http://mock/api")
    # Bypass the real exponential backoff so the test stays fast.
    monkeypatch.setattr(OverpassProvider._post.retry, "wait", wait_none())
    with pytest.raises(OverpassRateLimitError):
        provider.search(CORK, ["cafe"])
    assert calls["n"] == 4


def test_overpass_respects_limit():
    def handler(request: httpx.Request) -> httpx.Response:
        elements = [
            {"type": "node", "id": i, "lat": 51.9, "lon": -8.4,
             "tags": {"name": f"Cafe {i}", "amenity": "cafe"}}
            for i in range(10)
        ]
        return httpx.Response(200, json={"elements": elements})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = OverpassProvider(client=client, url="http://mock/api")
    assert len(provider.search(CORK, ["cafe"], limit=3)) == 3


# --------------------------------------------------------------------- google
def test_google_parse_place():
    place = {
        "id": "ChIJabc",
        "displayName": {"text": "Bella Cafe"},
        "formattedAddress": "1 Main St, Cork, Ireland",
        "location": {"latitude": 51.9, "longitude": -8.47},
        "primaryType": "cafe",
        "nationalPhoneNumber": "021 555 0100",
        "addressComponents": [
            {"types": ["locality"], "longText": "Cork", "shortText": "Cork"},
            {"types": ["country"], "longText": "Ireland", "shortText": "IE"},
        ],
    }
    candidate = parse_place(place)
    assert candidate.source == "google"
    assert candidate.country_code == "IE"
    assert candidate.city == "Cork"
    assert candidate.has_real_website is False


def test_google_skips_permanently_closed():
    assert parse_place({
        "id": "x", "displayName": {"text": "Gone"}, "businessStatus": "CLOSED_PERMANENTLY"
    }) is None


def test_google_skips_nameless():
    assert parse_place({"id": "x"}) is None
