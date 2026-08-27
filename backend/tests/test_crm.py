from __future__ import annotations

import pytest

from app.models import Deal, DealStage
from app.schemas import DealIn, DealUpdate
from app.services.crm.deals import (
    create_deal,
    create_deal_from_positive_lead,
    get_pipeline_summary,
    update_deal,
)
from tests.conftest import make_business, make_lead


def test_create_and_update_deal(db):
    deal_in = DealIn(
        title="Dental Website Redesign",
        company_name="Apex Dental",
        contact_email="dr@apexdental.ie",
        value=3500.0,
        stage=DealStage.PROSPECT,
    )
    deal = create_deal(db, deal_in)
    assert deal.id is not None
    assert deal.value == 3500.0
    assert deal.stage == DealStage.PROSPECT
    assert deal.probability == 10.0

    updated = update_deal(db, deal.id, DealUpdate(stage=DealStage.WON, value=4000.0))
    assert updated is not None
    assert updated.stage == DealStage.WON
    assert updated.probability == 100.0
    assert updated.value == 4000.0


def test_create_deal_from_positive_lead(db):
    biz = make_business(db, name="Bistro Paris", city="Dublin")
    lead = make_lead(db, business=biz, email="chef@bistroparis.ie")
    lead.ai_summary = "Wants pricing for menu redesign"

    deal = create_deal_from_positive_lead(db, lead)
    assert deal.lead_id == lead.id
    assert deal.business_id == biz.id
    assert deal.company_name == "Bistro Paris"
    assert deal.stage == DealStage.QUALIFIED
    assert deal.value > 0


def test_pipeline_summary(db):
    deal_in1 = DealIn(title="Deal 1", company_name="Co 1", value=2000.0, stage=DealStage.PROSPECT)
    deal_in2 = DealIn(title="Deal 2", company_name="Co 2", value=3000.0, stage=DealStage.WON)
    create_deal(db, deal_in1)
    create_deal(db, deal_in2)

    summary = get_pipeline_summary(db)
    assert summary.total_deals >= 2
    assert summary.total_pipeline_value >= 5000.0
    assert summary.forecasted_value > 0.0
    assert len(summary.stages) == 7


def test_master_excel_sync(db, tmp_path):
    from app.services.crm.excel_sync import MasterExcelSync

    biz = make_business(db, name="Elite Gym", city="Dallas", category="Fitness")
    lead = make_lead(db, business=biz, email="owner@elitegym.com")

    syncer = MasterExcelSync(db)
    workbook_data = syncer.generate_workbook_data()
    assert len(workbook_data) == 9  # 9 worksheets

    sheet_names = [name for name, _ in workbook_data]
    assert "Master Leads" in sheet_names
    assert "New Leads" in sheet_names
    assert "Sent Emails Log" in sheet_names
    assert "Reply History" in sheet_names
    assert "Follow-ups & Reminders" in sheet_names
    assert "Meetings & Hot Deals" in sheet_names
    assert "Converted Clients" in sheet_names
    assert "Invalid & Bounces" in sheet_names
    assert "KPI & Analytics" in sheet_names

    # Check XLSX byte export
    xlsx_bytes = syncer.export_excel_bytes()
    assert isinstance(xlsx_bytes, bytes)
    assert len(xlsx_bytes) > 500
    assert xlsx_bytes[:2] == b"PK"  # Valid ZIP/OpenXML signature

    # Check CSV export
    csv_str = syncer.export_master_csv_string()
    assert "Elite Gym" in csv_str
    assert "owner@elitegym.com" in csv_str

    # Check sync to disk
    excel_file = tmp_path / "MASTER_TEST.xlsx"
    csv_file = tmp_path / "MASTER_TEST.csv"
    p1, p2 = syncer.sync_to_disk(excel_file, csv_file)
    assert excel_file.exists()
    assert csv_file.exists()


def test_crm_api_endpoints(auth_client, db):
    biz = make_business(db, name="Royal Cuts", city="Austin")
    make_lead(db, business=biz, email="barber@royalcuts.com")

    # Test pipeline
    resp = auth_client.get("/api/crm/pipeline")
    assert resp.status_code == 200
    data = resp.json()
    assert "stages" in data
    assert "total_pipeline_value" in data

    # Test Excel Export
    resp_xlsx = auth_client.get("/api/crm/export-excel")
    assert resp_xlsx.status_code == 200
    assert resp_xlsx.content[:2] == b"PK"
    assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in resp_xlsx.headers["content-type"]

    # Test CSV Export
    resp_csv = auth_client.get("/api/crm/export-csv")
    assert resp_csv.status_code == 200
    assert "Royal Cuts" in resp_csv.text

    # Test Sync Excel API
    resp_sync = auth_client.post("/api/crm/sync-excel")
    assert resp_sync.status_code == 200
    assert resp_sync.json()["status"] == "synced"

