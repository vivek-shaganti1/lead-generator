from __future__ import annotations

import pytest

from app.models import DeliverabilityHealth, EmailMessage, MessageStatus
from app.services.outreach.deliverability import (
    audit_and_save_deliverability,
    check_domain_dns_records,
    evaluate_circuit_breaker,
)
from tests.conftest import make_lead


def test_check_domain_dns_records():
    report = check_domain_dns_records("google.com")
    assert report.domain == "google.com"
    assert report.reputation_score > 0.0


def test_circuit_breaker_safe_below_threshold(db):
    tripped, reason = evaluate_circuit_breaker(db)
    assert tripped is False
    assert reason is None


def test_circuit_breaker_tripped_on_high_bounces(db):
    lead = make_lead(db, email="test@example.com")
    # Simulate 20 messages with 10 bounces (50% bounce rate)
    for i in range(20):
        status = MessageStatus.BOUNCED if i < 10 else MessageStatus.SENT
        msg = EmailMessage(
            lead_id=lead.id,
            to_email=f"user{i}@test.com",
            from_email="hello@yourstudio.com",
            subject="Test",
            body_text="Test",
            status=status,
        )
        db.add(msg)
    db.commit()

    tripped, reason = evaluate_circuit_breaker(db, lookback_messages=20)
    assert tripped is True
    assert "High bounce rate" in (reason or "")


def test_audit_and_save_deliverability(db):
    record = audit_and_save_deliverability(db, "yourstudio.com")
    assert record.id is not None
    assert record.domain == "yourstudio.com"
    assert record.reputation_score > 0.0
