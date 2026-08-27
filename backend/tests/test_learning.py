from __future__ import annotations

import pytest

from app.models import LearningTelemetry
from app.services.ai.learning import (
    generate_learning_insights,
    record_reply_event,
    record_send_event,
)


def test_record_send_and_reply_telemetry(db):
    subj = "Quick question regarding business website"
    rec = record_send_event(db, subject_line=subj, industry="dentist", country_code="IE")
    assert rec.sends_count == 1
    assert rec.industry == "dentist"

    record_send_event(db, subject_line=subj, industry="dentist", country_code="IE")
    assert rec.sends_count == 2

    record_reply_event(db, subject_line=subj, industry="dentist", is_positive=True)
    assert rec.replies_count == 1
    assert rec.positive_count == 1
    assert rec.conversion_rate == 50.0  # 1 positive / 2 sends


def test_generate_learning_insights(db):
    insights = generate_learning_insights(db)
    assert len(insights) >= 1
    assert insights[0].headline != ""
    assert insights[0].recommended_action != ""
