from __future__ import annotations

import json

import httpx
import pytest
from tenacity import wait_none

from app.services.discovery.base import SearchArea
from app.services.discovery.google_places import (
    GooglePlacesError,
    GooglePlacesProvider,
    GoogleRateLimitError,
)

CORK = SearchArea(label="Cork", south=51.85, west=-8.55, north=51.95, east=-8.40,
                  country_code="IE")
NAMED = SearchArea(label="Galway", area_name="Galway", country_code="IE")


def _place(pid: str, name: str, website: str | None = None) -> dict:
    place = {
        "id": pid,
        "displayName": {"text": name},
        "formattedAddress": "1 Main St",
        "location": {"latitude": 51.9, "longitude": -8.47},
        "primaryType": "restaurant",
        "addressComponents": [{"types": ["country"], "shortText": "IE",
                               "longText": "Ireland"}],
    }
    if website:
        place["websiteUri"] = website
    return place


def _provider(handler, api_key="key") -> GooglePlacesProvider:
    return GooglePlacesProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler)), api_key=api_key
    )


def test_nearby_search_sends_rectangle_restriction():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        captured["field_mask"] = request.headers.get("x-goog-fieldmask")
        captured["api_key"] = request.headers.get("x-goog-api-key")
        return httpx.Response(200, json={"places": [_place("p1", "Rossi's")]})

    results = _provider(handler).search(CORK, ["restaurant"], limit=10)
    assert [r.name for r in results] == ["Rossi's"]
    assert captured["includedTypes"] == ["restaurant"]
    assert captured["locationRestriction"]["rectangle"]["low"]["latitude"] == 51.85
    assert "places.websiteUri" in captured["field_mask"]
    assert captured["api_key"] == "key"


def test_named_area_falls_back_to_text_search():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"places": [_place("p1", "Galway Grill")]})

    results = _provider(handler).search(NAMED, ["restaurant"], limit=5)
    assert results[0].name == "Galway Grill"
    assert any("searchText" in url for url in seen)


def test_text_search_follows_page_tokens():
    pages = [
        {"places": [_place(f"p{i}", f"Place {i}") for i in range(20)],
         "nextPageToken": "tok"},
        {"places": [_place("p20", "Place 20")]},
    ]
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        response = httpx.Response(200, json=pages[min(calls["n"], 1)])
        calls["n"] += 1
        return response

    results = _provider(handler).search(NAMED, ["restaurant"], limit=25)
    assert len(results) == 21
    assert calls["n"] == 2


def test_deduplicates_places_across_types():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"places": [_place("same", "Duplicate")]})

    # salon maps to two Google types, so the same place comes back twice.
    results = _provider(handler).search(CORK, ["salon"], limit=10)
    assert len(results) == 1


def test_missing_api_key_raises():
    with pytest.raises(GooglePlacesError, match="not configured"):
        _provider(lambda r: httpx.Response(200, json={}), api_key="").search(
            CORK, ["restaurant"]
        )


def test_http_error_is_wrapped():
    provider = _provider(lambda r: httpx.Response(403, text="denied"))
    with pytest.raises(GooglePlacesError, match="403"):
        provider.search(CORK, ["restaurant"])


def test_rate_limit_retries_then_raises(monkeypatch):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429)

    provider = _provider(handler)
    monkeypatch.setattr(GooglePlacesProvider._post.retry, "wait", wait_none())
    with pytest.raises(GoogleRateLimitError):
        provider.search(CORK, ["restaurant"])
    assert calls["n"] == 4


def test_category_without_google_type_raises():
    provider = _provider(lambda r: httpx.Response(200, json={}))
    with pytest.raises(ValueError, match="Google place type"):
        provider.search(CORK, ["carpenter"], limit=5)


def test_website_from_google_marks_business_as_having_one():
    def handler(request):
        return httpx.Response(200, json={"places": [
            _place("p1", "Has Site", website="https://hassite.ie"),
            _place("p2", "Social Only", website="https://facebook.com/x"),
        ]})

    results = _provider(handler).search(CORK, ["restaurant"], limit=5)
    by_name = {r.name: r for r in results}
    assert by_name["Has Site"].has_real_website is True
    assert by_name["Social Only"].has_real_website is False
