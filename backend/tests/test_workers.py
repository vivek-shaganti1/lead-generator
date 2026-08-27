"""Worker tasks are called as plain functions; Celery's transport is not under test."""
from __future__ import annotations

import pytest

from app.config import settings
from app.models import Business, DiscoveryStatus, Lead, LeadStatus
from app.workers import tasks
from app.workers.celery_app import celery_app
from tests.conftest import make_business, make_lead


@pytest.fixture(autouse=True)
def _no_dispatch(monkeypatch):
    """Stop tasks handing work to a broker that isn't running in tests."""
    monkeypatch.setattr(tasks.qualify_pending, "delay", lambda **kw: None)


def test_celery_configuration_is_safe():
    conf = celery_app.conf
    assert conf.task_acks_late is True            # a dead worker retries its task
    assert conf.worker_prefetch_multiplier == 1   # long tasks don't hog the queue
    assert conf.timezone == "UTC"
    assert "leadgen.outreach_batch" in [
        entry["task"] for entry in conf.beat_schedule.values()
    ]


def test_beat_schedule_covers_every_loop():
    tasks_scheduled = {entry["task"] for entry in celery_app.conf.beat_schedule.values()}
    assert tasks_scheduled == {
        "leadgen.outreach_batch", "leadgen.poll_inbox", "leadgen.qualify_pending",
        "leadgen.rollup_stats", "leadgen.daily_digest", "leadgen.retention_sweep",
    }


def test_discovery_run_task(db, monkeypatch):
    from app.services.discovery.base import PlaceCandidate

    candidate = PlaceCandidate(source="overpass", source_id="node/1", name="Cafe Roma",
                               category="cafe", lat=51.9, lon=-8.4, country_code="IE",
                               email="hello@caferoma.ie")

    class FakeProvider:
        name = "overpass"

        def search(self, area, categories, limit):
            return [candidate]

    monkeypatch.setattr("app.services.pipeline.OverpassProvider", lambda: FakeProvider())
    result = tasks.discovery_run(
        area={"label": "Cork", "south": 51.8, "west": -8.6, "north": 52.0, "east": -8.3,
              "country_code": "IE"},
        categories=["cafe"], limit=10, use_google_fallback=False,
    )
    assert result["status"] == DiscoveryStatus.SUCCESS.value
    assert result["new"] == 1
    assert db.query(Business).count() == 1


def test_qualify_pending_task_creates_leads(db):
    make_business(db, email="info@rossis.ie")
    make_business(db, source_id="node/2", name="No Email Shop", email=None,
                  phone="+353 21 555 0999")
    summary = tasks.qualify_pending(limit=10)
    assert summary["examined"] == 2
    assert summary["created"] == 1
    assert db.query(Lead).count() == 1


def test_qualify_pending_skips_businesses_with_websites(db):
    make_business(db, email="info@rossis.ie", has_website=True,
                  website="https://rossis.ie")
    assert tasks.qualify_pending(limit=10)["examined"] == 0


def test_outreach_batch_task(db, campaign, transport):
    make_lead(db, campaign=campaign)
    result = tasks.outreach_batch(limit=5)
    assert result["sent"] == 1
    assert len(transport.sent) == 1


def test_send_lead_now_task(db, campaign, transport):
    lead = make_lead(db, campaign=campaign)
    result = tasks.send_lead_now(lead.id)
    assert result["sent"] is True
    assert tasks.send_lead_now(999999)["reason"] == "lead not found"


def test_poll_inbox_skips_without_config(monkeypatch):
    monkeypatch.setattr(settings, "imap_host", "")
    assert tasks.poll_inbox() == {"skipped": "imap not configured"}


def test_poll_inbox_processes_messages(db, campaign, monkeypatch):
    from app.services.inbox.parser import parse_message
    from tests.test_inbox import build_raw

    make_lead(db, campaign=campaign, email="owner@rossis.ie",
              status=LeadStatus.CONTACTED)
    monkeypatch.setattr(settings, "imap_host", "imap.example.com")
    monkeypatch.setattr(
        tasks.imap_client, "fetch_recent",
        lambda **kw: [parse_message(build_raw(sender="owner@rossis.ie",
                                              body="Yes please, send a quote"))],
    )
    summary = tasks.poll_inbox()
    assert summary["stored"] == 1
    assert summary["positive"] == 1


def test_rollup_stats_task(db):
    assert tasks.rollup_stats(days=2) == {"days_rolled": 2}


def test_daily_digest_task(db):
    result = tasks.daily_digest()
    assert result["sent"] is False       # telegram disabled in tests
    assert "emails_sent" in result


def test_retention_sweep_task(db):
    result = tasks.retention_sweep()
    assert set(result) == {"google_purged", "uncontacted_purged", "events_purged",
                           "inbound_redacted"}


def test_heartbeat_task():
    assert tasks.heartbeat().endswith("+00:00")
