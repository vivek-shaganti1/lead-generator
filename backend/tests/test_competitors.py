from __future__ import annotations

import pytest

from app.models import Business, Competitor
from app.services.ai.competitor_intel import (
    discover_and_benchmark_competitors,
    sync_competitors_to_db,
)
from tests.conftest import make_business


def test_discover_and_benchmark_competitors(db):
    biz = make_business(db, name="Target Bakery", category="bakery", country_code="IE", has_website=False)
    comp1 = make_business(db, name="Rival Bakery 1", category="bakery", country_code="IE", has_website=True)
    comp1.review_count = 120
    comp1.rating = 4.9
    db.commit()

    benchmarks = discover_and_benchmark_competitors(db, biz)
    assert len(benchmarks) >= 1
    assert benchmarks[0].name == "Rival Bakery 1"
    assert len(benchmarks[0].advantages) > 0


def test_sync_competitors_to_db(db):
    biz = make_business(db, name="Target Plumber", category="plumber", country_code="IE", has_website=False)
    comp = make_business(db, name="Rival Plumber", category="plumber", country_code="IE", has_website=True)
    db.commit()

    synced = sync_competitors_to_db(db, biz)
    assert len(synced) >= 1
    assert synced[0].business_id == biz.id

    in_db = db.query(Competitor).filter(Competitor.business_id == biz.id).all()
    assert len(in_db) == len(synced)
