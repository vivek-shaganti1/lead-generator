from __future__ import annotations

import httpx

from app.config import settings
from app.models import Business, DiscoveryStatus, Lead, LeadStatus
from app.services.compliance.policy import suppress
from app.services.discovery.base import PlaceCandidate, SearchArea
from app.services.pipeline import (
    get_or_create_default_campaign,
    ingest_candidates,
    qualify_business,
    run_discovery,
)
from tests.conftest import make_business

CORK = SearchArea(label="Cork", south=51.85, west=-8.55, north=51.95, east=-8.40,
                  country_code="IE")


def _candidate(**kw) -> PlaceCandidate:
    base = dict(source="overpass", source_id="node/1", name="Rossi's Trattoria",
                category="restaurant", lat=51.9, lon=-8.47, country_code="IE",
                city="Cork", phone="+353 21 555 0100")
    base.update(kw)
    return PlaceCandidate(**base)


class FakeProvider:
    name = "overpass"

    def __init__(self, results=None, error=None):
        self.results = results or []
        self.error = error

    def search(self, area, categories, limit):
        if self.error:
            raise self.error
        return self.results[:limit]


# --------------------------------------------------------------------- ingest
def test_ingest_creates_businesses(db):
    stats = ingest_candidates(db, [
        _candidate(),
        _candidate(source_id="node/2", name="Bella Cafe", lat=51.91,
                   phone="+353 21 555 0200"),
    ])
    db.commit()
    assert stats.new == 2
    assert stats.without_website == 2
    assert db.query(Business).count() == 2


def test_ingest_is_idempotent(db):
    ingest_candidates(db, [_candidate()])
    db.commit()
    stats = ingest_candidates(db, [_candidate()])
    db.commit()
    assert stats.new == 0
    assert stats.updated == 1
    assert db.query(Business).count() == 1


def test_ingest_merges_the_same_place_from_google(db):
    ingest_candidates(db, [_candidate()])
    db.commit()
    ingest_candidates(db, [_candidate(source="google", source_id="ChIJ1",
                                      address="1 Main St")])
    db.commit()
    assert db.query(Business).count() == 1
    assert db.query(Business).one().address == "1 Main St"


def test_ingest_marks_real_websites(db):
    ingest_candidates(db, [_candidate(website="https://rossis.ie")])
    db.commit()
    assert db.query(Business).one().has_website is True


def test_ingest_treats_social_link_as_no_website(db):
    ingest_candidates(db, [_candidate(website="https://facebook.com/rossis")])
    db.commit()
    business = db.query(Business).one()
    assert business.has_website is False
    assert business.website == "https://facebook.com/rossis"


def test_ingest_assigns_timezone(db):
    ingest_candidates(db, [_candidate()])
    db.commit()
    assert db.query(Business).one().timezone_name


def test_ingest_never_erases_known_fields(db):
    ingest_candidates(db, [_candidate(phone="+353 21 555 0100", address="1 Main St")])
    db.commit()
    ingest_candidates(db, [_candidate(address=None)])
    db.commit()
    assert db.query(Business).one().address == "1 Main St"


# ------------------------------------------------------------------ discovery
def test_run_discovery_records_success(db):
    run = run_discovery(db, area=CORK, categories=["restaurant"],
                        overpass_provider=FakeProvider([_candidate()]),
                        use_google_fallback=False)
    db.commit()
    assert run.status == DiscoveryStatus.SUCCESS
    assert run.found_total == 1
    assert run.new_businesses == 1
    assert run.without_website == 1


def test_run_discovery_records_failure(db):
    run = run_discovery(db, area=CORK, categories=["restaurant"],
                        overpass_provider=FakeProvider(error=RuntimeError("overpass down")),
                        use_google_fallback=False)
    db.commit()
    assert run.status == DiscoveryStatus.FAILED
    assert "overpass down" in run.error


def test_google_fallback_used_when_osm_is_thin(db):
    google = FakeProvider([_candidate(source="google", source_id="ChIJ9",
                                      name="Google Only Cafe", lat=51.92)])
    run = run_discovery(db, area=CORK, categories=["restaurant"],
                        overpass_provider=FakeProvider([]),
                        google_provider=google, use_google_fallback=True)
    db.commit()
    assert run.provider == "overpass+google"
    assert run.found_total == 1


def test_google_fallback_skipped_when_osm_is_rich(db):
    many = [_candidate(source_id=f"node/{i}", name=f"Cafe {i}", lat=51.9 + i / 1000)
            for i in range(20)]

    class Boom:
        name = "google"

        def search(self, *a, **k):
            raise AssertionError("google must not be called")

    run = run_discovery(db, area=CORK, categories=["cafe"],
                        overpass_provider=FakeProvider(many),
                        google_provider=Boom(), use_google_fallback=True)
    db.commit()
    assert run.provider == "overpass"


def test_partial_status_when_one_provider_fails(db):
    run = run_discovery(
        db, area=CORK, categories=["cafe"],
        overpass_provider=FakeProvider([_candidate()]),
        google_provider=FakeProvider(error=RuntimeError("quota")),
        use_google_fallback=True,
    )
    db.commit()
    # OSM returned only one row, so google was tried and failed.
    assert run.status == DiscoveryStatus.PARTIAL
    assert "quota" in run.error


# -------------------------------------------------------------------- qualify
def test_qualify_creates_lead_from_map_email(db):
    business = make_business(db, email="info@rossis.ie")
    result = qualify_business(db, business)
    db.commit()
    assert result.created is True
    lead = db.query(Lead).one()
    assert lead.email == "info@rossis.ie"
    assert lead.email_source == "map_tag"
    assert lead.status == LeadStatus.NEEDS_APPROVAL
    assert lead.approved is False
    assert lead.unsubscribe_token
    assert lead.score > 0


def test_qualify_auto_approves_when_manual_review_is_off(db, monkeypatch):
    monkeypatch.setattr(settings, "require_manual_approval", False)
    business = make_business(db, email="info@rossis.ie")
    qualify_business(db, business)
    db.commit()
    lead = db.query(Lead).one()
    assert lead.status == LeadStatus.READY and lead.approved is True


def test_qualify_skips_business_with_no_email(db):
    business = make_business(db, email=None)
    result = qualify_business(db, business)
    assert result.created is False
    assert "no contact email" in result.reason


def test_qualify_skips_live_website(db):
    body = "<html>" + ("Genuine content. " * 60) + "</html>"
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=body)))
    business = make_business(db, website="https://rossis.ie", email="info@rossis.ie")
    result = qualify_business(db, business, client=client)
    db.commit()
    assert result.created is False
    assert "working website" in result.reason
    assert business.has_website is True


def test_qualify_accepts_broken_website(db):
    client = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, text="<html>This domain is parked</html>")
    ))
    business = make_business(db, website="https://rossis.ie", email="info@rossis.ie")
    result = qualify_business(db, business, client=client)
    db.commit()
    assert result.created is True
    assert result.presence == "BROKEN"
    assert business.website_alive is False


def test_qualify_accepts_social_only_without_network(db):
    business = make_business(db, website="https://facebook.com/rossis",
                             email="info@rossis.ie")
    result = qualify_business(db, business, check_site=False)
    db.commit()
    assert result.created is True
    assert result.presence == "SOCIAL"


def test_qualify_blocks_restricted_country(db):
    business = make_business(db, country_code="DE", email="info@rossis.ie")
    result = qualify_business(db, business)
    assert result.created is False
    assert "country blocked" in result.reason


def test_qualify_skips_suppressed_address(db):
    suppress(db, "info@rossis.ie", reason="opted out")
    db.commit()
    business = make_business(db, email="info@rossis.ie")
    result = qualify_business(db, business)
    assert result.created is False
    assert "suppressed" in result.reason


def test_qualify_rejects_unsafe_mailbox(db):
    business = make_business(db, email="noreply@rossis.ie")
    result = qualify_business(db, business)
    assert result.created is False


def test_qualify_is_idempotent(db):
    business = make_business(db, email="info@rossis.ie")
    qualify_business(db, business)
    db.commit()
    second = qualify_business(db, business)
    assert second.created is False
    assert "already exists" in second.reason
    assert db.query(Lead).count() == 1


def test_default_campaign_created_once(db):
    first = get_or_create_default_campaign(db)
    db.commit()
    second = get_or_create_default_campaign(db)
    assert first.id == second.id
