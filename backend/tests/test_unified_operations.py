"""
End-to-End Unified Operations Integration Test.
Tests full pipeline: Lead Generation -> Qualification -> AI Personalization ->
Outreach Dispatch -> Reply Ingestion & NLP Classification -> CRM Deal Creation ->
Master Multi-Tab Excel (.xlsx) & CSV Real-Time Synchronization -> API Exports.
"""
from __future__ import annotations

import pytest

from app.models import Deal, DealStage, Lead, LeadStatus, MessageStatus, ReplyClass
from app.services.crm.excel_sync import MasterExcelSync
from app.services.discovery.importer import import_reference_sheet
from app.services.inbox.parser import ParsedInbound
from app.services.inbox.processor import process_inbound
from app.services.outreach.dispatcher import send_lead
from tests.conftest import make_business, make_lead


def test_unified_lead_to_excel_and_deal_lifecycle(db, auth_client, tmp_path):
    # 1. Ingest sample leads via Reference Sheet / CSV
    sample_csv = """Business Name,Category,City,Country,Public Email,Phone,Website,Owner
Iron Peak Gym,Gym & Fitness,Dallas,US,coach@ironpeak.com,+12145550199,,Brandon Cole
Luxe Glow Salon,Hair Salon & Spa,Austin,US,contact@luxeglow.com,+15125550188,,Elena Rostova
HyperPulse Media,Digital Agency,Miami,US,hello@hyperpulse.io,+13055550177,https://broken-hyperpulse-agency-site.com,Marcus Vance
"""
    result = import_reference_sheet(
        db,
        sample_csv,
        auto_qualify=True,
        auto_approve=True,
        auto_dispatch=False,
    )

    assert result["candidates_parsed"] == 3
    assert result["businesses_created"] == 3
    assert result["leads_created"] >= 2
    assert result["leads_approved"] >= 2

    # Verify leads in database
    lead1 = db.query(Lead).filter(Lead.email == "coach@ironpeak.com").first()
    assert lead1 is not None
    assert lead1.status == LeadStatus.READY
    assert lead1.approved is True

    # 2. Dispatch Outreach
    send_res = send_lead(db, lead1, force=True)
    assert send_res.sent is True
    db.commit()
    db.refresh(lead1)
    assert lead1.status == LeadStatus.CONTACTED
    assert lead1.followups_sent == 0
    assert len(lead1.messages) == 1
    assert lead1.messages[0].status == MessageStatus.SENT

    # 3. Simulate Inbound Positive Reply from Prospect
    reply_parsed = ParsedInbound(
        message_id="msg-reply-ironpeak-001",
        in_reply_to=lead1.messages[0].message_id,
        from_email="coach@ironpeak.com",
        subject="Re: Quick question for Iron Peak Gym",
        body_text="Hi Vivek, thanks for reaching out! We would love to see the mobile booking mockup. Are you free for a 10-minute call tomorrow at 2 PM?",
    )
    inbound_res = process_inbound(db, reply_parsed)
    assert inbound_res.stored is True
    assert inbound_res.classification == ReplyClass.POSITIVE

    # Verify Lead updated to Positive and Deal automatically created
    db.refresh(lead1)
    assert lead1.status == LeadStatus.POSITIVE
    assert lead1.reply_class == ReplyClass.POSITIVE

    deal = db.query(Deal).filter(Deal.lead_id == lead1.id).first()
    assert deal is not None
    assert deal.company_name == "Iron Peak Gym"
    assert deal.stage in (DealStage.QUALIFIED, DealStage.PROSPECT)
    assert deal.value > 0

    # 4. Generate & Verify Multi-Tab Master Excel (.xlsx) & CSV
    syncer = MasterExcelSync(db)
    sheets_data = syncer.generate_workbook_data()
    assert len(sheets_data) == 9

    sheet_dict = {name: rows for name, rows in sheets_data}
    assert "Master Leads" in sheet_dict
    assert "Sent Emails Log" in sheet_dict
    assert "Reply History" in sheet_dict
    assert "Meetings & Hot Deals" in sheet_dict
    assert "KPI & Analytics" in sheet_dict

    # Check that the positive lead is in Meetings & Hot Deals
    hot_rows = sheet_dict["Meetings & Hot Deals"]
    assert any("coach@ironpeak.com" in str(row) for row in hot_rows)

    # Check Sent Emails Log
    sent_rows = sheet_dict["Sent Emails Log"]
    assert any("coach@ironpeak.com" in str(row) for row in sent_rows)

    # Check KPI & Analytics sheet
    kpi_rows = sheet_dict["KPI & Analytics"]
    assert any("Target Revenue KPI" in str(row) for row in kpi_rows)
    assert any("Active Weighted Pipeline" in str(row) for row in kpi_rows)

    # Check Excel file writing to disk
    excel_path = tmp_path / "MASTER_CRM_OPERATIONS.xlsx"
    csv_path = tmp_path / "MASTER_CRM_OPERATIONS.csv"
    syncer.sync_to_disk(excel_path, csv_path)
    assert excel_path.exists()
    assert csv_path.exists()
    assert excel_path.stat().st_size > 1000

    # 5. Verify API endpoints for Excel & CSV downloading
    resp_xlsx = auth_client.get("/api/crm/export-excel")
    assert resp_xlsx.status_code == 200
    assert resp_xlsx.content[:2] == b"PK"

    resp_csv = auth_client.get("/api/crm/export-csv")
    assert resp_csv.status_code == 200
    assert "Iron Peak Gym" in resp_csv.text
    assert "coach@ironpeak.com" in resp_csv.text
