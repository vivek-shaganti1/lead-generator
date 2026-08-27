"""Test harness.

Environment is configured *before* anything imports app.config, because the
settings object is a module-level singleton.
"""
from __future__ import annotations

import os
import pathlib
import tempfile

# Per-process file: a fixed name lets two concurrent pytest runs drop each
# other's tables mid-test, which shows up as unrelated Operational/StaleData errors.
TEST_DB = pathlib.Path(tempfile.gettempdir()) / f"leadgen_test_{os.getpid()}.db"
os.environ.update(
    ENV="test",
    DEBUG="false",
    DATABASE_URL=f"sqlite:///{TEST_DB}",
    REDIS_URL="redis://localhost:6379/15",
    SECRET_KEY="test-secret-key-that-is-long-enough",
    PUBLIC_BASE_URL="http://testserver",
    ADMIN_EMAIL="admin@leadgen-example.com",
    ADMIN_PASSWORD="test-password-123",
    SENDER_EMAIL="hello@studio-example.com",
    SENDER_NAME="Tester",
    COMPANY_NAME="Test Studio",
    COMPANY_ADDRESS="1 Test Street, Testville",
    COMPANY_WEBSITE="https://studio.test",
    DRY_RUN="true",
    REQUIRE_MANUAL_APPROVAL="true",
    VERIFY_MX="false",
    ENABLE_WEBSITE_EMAIL_SCRAPE="false",
    AI_CLASSIFY_REPLIES="false",
    GROQ_API_KEY="",
    TELEGRAM_BOT_TOKEN="",
    TELEGRAM_CHAT_ID="",
    SEND_WINDOW_START_HOUR="0",
    SEND_WINDOW_END_HOUR="24",
    SEND_ON_WEEKENDS="true",
    MIN_SECONDS_BETWEEN_SENDS="0",
    WARMUP_ENABLED="false",
    DAILY_SEND_CAP="1000",
    MAX_PER_DOMAIN_PER_DAY="2",
)

import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import (  # noqa: E402
    Business,
    Campaign,
    Lead,
    LeadStatus,
)
from app.security import ensure_admin_user  # noqa: E402
from app.services.notify import telegram  # noqa: E402
from app.services.outreach import sender as sender_module  # noqa: E402
from app.services.outreach.templates import default_campaign_payload  # noqa: E402
from app.utils import new_token  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _remove_test_database_file():
    """The per-process file is disposable; do not leave it behind in the temp dir."""
    yield
    engine.dispose()
    TEST_DB.unlink(missing_ok=True)


@pytest.fixture(autouse=True)
def _clean_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def transport():
    """Recording transport, installed globally and reset between tests."""
    recorder = sender_module.RecordingTransport()
    sender_module.set_transport(recorder)
    yield recorder
    sender_module.set_transport(None)


@pytest.fixture(autouse=True)
def _no_overpass_throttle():
    """The politeness delay is real in production; tests must not pay for it."""
    from app.services.discovery import overpass

    original = overpass._throttle._min_interval
    overpass._throttle._min_interval = 0.0
    overpass._throttle._last = None
    yield
    overpass._throttle._min_interval = original


@pytest.fixture(autouse=True)
def _no_telegram():
    telegram.set_client(telegram.TelegramClient(token="", chat_id=""))
    yield
    telegram.set_client(None)


@pytest.fixture
def campaign(db) -> Campaign:
    """Reuses the campaign the app bootstrap creates, when a client fixture ran first."""
    payload = default_campaign_payload()
    row = db.execute(
        select(Campaign).where(Campaign.name == payload["name"])
    ).scalars().first()
    if row is None:
        row = Campaign(**payload)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def make_business(db, **overrides) -> Business:
    from app.utils import dedupe_key

    data = {
        "source": "overpass",
        "source_id": f"node/{new_token(6)}",
        "name": "Rossi's Trattoria",
        "category": "restaurant",
        "phone": "+353 21 555 0100",
        "website": None,
        "has_website": False,
        "address": "12 Main Street",
        "city": "Cork",
        "country_code": "IE",
        "lat": 51.8985,
        "lon": -8.4756,
        "timezone_name": "UTC",
    }
    data.update(overrides)
    data["dedupe_key"] = dedupe_key(
        data["name"], data.get("lat"), data.get("lon"), data.get("phone")
    )
    business = Business(**data)
    db.add(business)
    db.commit()
    db.refresh(business)
    return business


def make_lead(db, business=None, campaign=None, **overrides) -> Lead:
    business = business or make_business(db)
    data = {
        "business_id": business.id,
        "campaign_id": campaign.id if campaign else None,
        "email": "info@rossis.ie",
        "email_source": "map_tag",
        "email_confidence": 0.9,
        "is_role_account": True,
        "score": 72.0,
        "status": LeadStatus.READY,
        "approved": True,
        "unsubscribe_token": new_token(),
    }
    data.update(overrides)
    lead = Lead(**data)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


@pytest.fixture
def business(db) -> Business:
    return make_business(db)


@pytest.fixture
def lead(db, campaign) -> Lead:
    return make_lead(db, campaign=campaign)


@pytest.fixture
def client():
    from app.main import create_app

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_client(client, db):
    ensure_admin_user(db)
    db.commit()
    response = client.post(
        "/api/auth/login",
        json={"email": settings.admin_email, "password": settings.admin_password},
    )
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client
