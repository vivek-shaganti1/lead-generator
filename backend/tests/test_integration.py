"""End-to-end: discovery all the way through to a Telegram alert and the dashboard."""
from __future__ import annotations

import httpx
import pytest

from app.config import settings
from app.models import Business, InboundMessage, Lead, LeadStatus
from app.services import stats
from app.services.discovery.base import PlaceCandidate, SearchArea
from app.services.inbox.parser import parse_message
from app.services.inbox.processor import process_inbound
from app.services.notify import telegram
from app.services.outreach.dispatcher import approve_lead, run_batch
from app.services.pipeline import get_or_create_default_campaign, qualify_business, run_discovery
from tests.test_inbox import build_raw

CORK = SearchArea(label="Cork", south=51.85, west=-8.55, north=51.95, east=-8.40,
                  country_code="IE")


class FakeOverpass:
    name = "overpass"

    def __init__(self, candidates):
        self.candidates = candidates

    def search(self, area, categories, limit):
        return self.candidates[:limit]


class CapturingTelegram(telegram.TelegramClient):
    def __init__(self):
        super().__init__(token="fake-token", chat_id="123")
        self.messages: list[str] = []

    def send(self, text: str, **kwargs) -> bool:
        self.messages.append(text)
        return True


@pytest.fixture
def telegram_capture():
    client = CapturingTelegram()
    telegram.set_client(client)
    yield client
    telegram.set_client(None)


def _candidates() -> list[PlaceCandidate]:
    return [
        # ideal lead: no website, publishes an email on the map
        PlaceCandidate(source="overpass", source_id="node/1", name="Rossi's Trattoria",
                       category="restaurant", email="info@rossis.ie", city="Cork",
                       country_code="IE", lat=51.90, lon=-8.47, phone="+353 21 555 0100"),
        # social-only: still a prospect
        PlaceCandidate(source="overpass", source_id="node/2", name="Bella Salon",
                       category="salon", email="hello@bellasalon.ie",
                       website="https://facebook.com/bellasalon", city="Cork",
                       country_code="IE", lat=51.91, lon=-8.46, phone="+353 21 555 0200"),
        # has a working website: must never be contacted
        PlaceCandidate(source="overpass", source_id="node/3", name="Modern Dental",
                       category="dentist", email="info@moderndental.ie",
                       website="https://moderndental.ie", city="Cork",
                       country_code="IE", lat=51.92, lon=-8.45, phone="+353 21 555 0300"),
        # German business: blocked jurisdiction
        PlaceCandidate(source="overpass", source_id="node/4", name="Berlin Backerei",
                       category="bakery", email="info@backerei.de", city="Berlin",
                       country_code="DE", lat=52.52, lon=13.40, phone="+49 30 555 0100"),
        # no email anywhere: cannot be contacted
        PlaceCandidate(source="overpass", source_id="node/5", name="Quiet Garage",
                       category="car_repair", city="Cork", country_code="IE",
                       lat=51.93, lon=-8.44, phone="+353 21 555 0400"),
    ]


def test_full_pipeline_discovery_to_positive_reply(db, transport, telegram_capture):
    # ---- 1. discovery -------------------------------------------------------
    run = run_discovery(db, area=CORK, categories=["restaurant", "salon", "dentist"],
                        overpass_provider=FakeOverpass(_candidates()),
                        use_google_fallback=False)
    db.commit()
    assert run.found_total == 5
    assert db.query(Business).count() == 5
    # Modern Dental is the only one with a genuine website.
    assert run.without_website == 4

    # ---- 2. qualification ---------------------------------------------------
    campaign = get_or_create_default_campaign(db)
    live_site = "<html>" + ("Real dental practice content. " * 60) + "</html>"
    client = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, text=live_site)
    ))
    outcomes = {}
    for business in db.query(Business).all():
        result = qualify_business(db, business, campaign, client=client)
        outcomes[business.name] = result
        db.commit()

    assert outcomes["Rossi's Trattoria"].created is True
    assert outcomes["Bella Salon"].created is True
    assert outcomes["Modern Dental"].created is False       # working website
    assert outcomes["Berlin Backerei"].created is False     # blocked country
    assert outcomes["Quiet Garage"].created is False        # no email
    assert db.query(Lead).count() == 2

    # Nothing may be sent before a human approves it.
    assert run_batch(db, limit=10)["sent"] == 0
    assert transport.sent == []

    # ---- 3. approval + sending ---------------------------------------------
    for lead in db.query(Lead).all():
        approve_lead(db, lead, True)
    db.commit()

    result = run_batch(db, limit=10)
    assert result["sent"] == 2
    assert len(transport.sent) == 2

    # The salon's pitch differs from the restaurant's, because the situations differ.
    bodies = [m.get_body(preferencelist=("plain",)).get_content() for m in transport.sent]
    assert any("social media" in body for body in bodies)
    assert any("couldn't find a website" in body for body in bodies)
    assert all("Unsubscribe" in body for body in bodies)

    # ---- 4. a positive reply comes back ------------------------------------
    rossi = db.query(Lead).filter(Lead.email == "info@rossis.ie").one()
    original_id = rossi.messages[0].message_id
    reply = parse_message(build_raw(
        sender="info@rossis.ie", in_reply_to=original_id, message_id="<reply-rossi@x>",
        body="Yes please! How much would a site like that cost?",
    ))
    processed = process_inbound(db, reply)
    db.commit()

    assert processed.classification.value == "POSITIVE"
    assert rossi.status == LeadStatus.POSITIVE
    assert rossi.next_action_at is None
    assert processed.notified is True
    assert "POSITIVE REPLY" in telegram_capture.messages[0]
    assert "Trattoria" in telegram_capture.messages[0]  # HTML-escaped apostrophe
    assert "info@rossis.ie" in telegram_capture.messages[0]

    # ---- 5. the numbers add up ---------------------------------------------
    stats.rollup_day(db)
    db.commit()
    dashboard = stats.dashboard(db, days=7)
    assert dashboard["totals"]["outbound"]["emails_sent"] == 2
    assert dashboard["totals"]["outbound"]["leads"] == 2
    assert dashboard["totals"]["inbound"]["replies"] == 1
    assert dashboard["totals"]["inbound"]["positive"] == 1
    assert dashboard["today"]["emails_sent"] == 2
    assert dashboard["today"]["positive"] == 1

    funnel = {row["stage"]: row["count"] for row in dashboard["funnel"]}
    assert funnel["Discovered"] == 5
    assert funnel["Contactable leads"] == 2
    assert funnel["Emailed"] == 2
    assert funnel["Positive"] == 1


def test_full_pipeline_negative_and_unsubscribe(db, transport, telegram_capture, monkeypatch):
    monkeypatch.setattr(settings, "require_manual_approval", False)
    run_discovery(db, area=CORK, categories=["restaurant", "salon"],
                  overpass_provider=FakeOverpass(_candidates()[:2]),
                  use_google_fallback=False)
    db.commit()

    campaign = get_or_create_default_campaign(db)
    for business in db.query(Business).all():
        qualify_business(db, business, campaign, check_site=False)
        db.commit()

    assert run_batch(db, limit=10)["sent"] == 2

    salon = db.query(Lead).filter(Lead.email == "hello@bellasalon.ie").one()
    rossi = db.query(Lead).filter(Lead.email == "info@rossis.ie").one()

    process_inbound(db, parse_message(build_raw(
        sender="hello@bellasalon.ie", message_id="<no@x>",
        body="No thanks, we already have a website.")))
    process_inbound(db, parse_message(build_raw(
        sender="info@rossis.ie", message_id="<stop@x>",
        body="Please remove me from your list.")))
    db.commit()

    assert salon.status == LeadStatus.NEGATIVE
    assert rossi.status == LeadStatus.UNSUBSCRIBED

    # Neither may ever be contacted again.
    assert run_batch(db, limit=10)["sent"] == 0
    assert len(transport.sent) == 2

    day = stats.compute_day(db, stats.utcnow().date().isoformat())
    assert day["negative"] == 1
    assert day["unsubscribes"] == 1
    assert telegram_capture.messages == []   # only positives ping the phone


def test_reply_from_a_different_mailbox_still_matches(db, transport):
    """Owners often reply from their personal address; threading headers save us."""
    run_discovery(db, area=CORK, categories=["restaurant"],
                  overpass_provider=FakeOverpass(_candidates()[:1]),
                  use_google_fallback=False)
    db.commit()
    campaign = get_or_create_default_campaign(db)
    business = db.query(Business).one()
    qualify_business(db, business, campaign, check_site=False)
    lead = db.query(Lead).one()
    approve_lead(db, lead, True)
    db.commit()
    run_batch(db, limit=5)

    original_id = lead.messages[0].message_id
    reply = parse_message(build_raw(
        sender="mario.personal@gmail.com", in_reply_to=original_id,
        message_id="<personal@x>", body="Interested, can you call me?"))
    result = process_inbound(db, reply)
    db.commit()

    assert result.lead_id == lead.id
    assert lead.status == LeadStatus.POSITIVE
    assert db.query(InboundMessage).one().from_email == "mario.personal@gmail.com"
