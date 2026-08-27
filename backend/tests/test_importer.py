from __future__ import annotations

import httpx
import pytest

from app.models import Business, Lead, LeadStatus
from app.services.discovery.importer import (
    _normalize_header,
    import_reference_sheet,
    parse_tabular_data,
)


def test_normalize_headers():
    assert _normalize_header("Business Name") == "name"
    assert _normalize_header("Company") == "name"
    assert _normalize_header("Contact Email") == "email"
    assert _normalize_header("Website URL") == "website"
    assert _normalize_header("Phone Number") == "phone"
    assert _normalize_header("Industry / Type") == "category"
    assert _normalize_header("Decision Maker") == "contact_name"
    assert _normalize_header("Zip Code") == "postcode"
    assert _normalize_header("Town / City") == "city"
    assert _normalize_header("Country Code") == "country_code"


def test_parse_tabular_data_csv():
    csv_text = """Business Name,Email,Website,Phone,City,Country
Rossi Trattoria,info@rossis.ie,,+353 21 555 0100,Cork,IE
Bella Salon,hello@bellasalon.ie,https://instagram.com/bella,+353 21 555 0200,Cork,IE
"""
    records = parse_tabular_data(csv_text)
    assert len(records) == 2
    assert records[0]["name"] == "Rossi Trattoria"
    assert records[0]["email"] == "info@rossis.ie"
    assert records[0]["city"] == "Cork"
    assert records[1]["website"] == "https://instagram.com/bella"


def test_parse_tabular_data_tsv_and_semicolon():
    tsv_text = "Name\tEmail\tCity\nTech Firm\tinfo@techfirm.ie\tDublin\n"
    tsv_records = parse_tabular_data(tsv_text)
    assert len(tsv_records) == 1
    assert tsv_records[0]["name"] == "Tech Firm"
    assert tsv_records[0]["city"] == "Dublin"

    semi_text = "Name;Email;City\nBakery;info@bakery.ie;Galway\n"
    semi_records = parse_tabular_data(semi_text)
    assert len(semi_records) == 1
    assert semi_records[0]["name"] == "Bakery"
    assert semi_records[0]["email"] == "info@bakery.ie"


def test_parse_tabular_data_json():
    json_text = '[{"Company Name": "Alpha Co", "Contact Email": "alpha@example.org", "City": "Limerick"}]'
    records = parse_tabular_data(json_text)
    assert len(records) == 1
    assert records[0]["name"] == "Alpha Co"
    assert records[0]["email"] == "alpha@example.org"


def test_import_reference_sheet_e2e(db):
    csv_data = """Business Name,Contact Email,Website,Phone,City,Country,Category,Contact Person,Notes
O'Connor Plumbing,info@oconnorplumbing.ie,,+353 21 555 0999,Cork,IE,plumber,Sean O'Connor,High priority lead
Cork Bakery,hello@corkbakery.ie,https://facebook.com/corkbakery,,Cork,IE,bakery,Mary,Met at trade show
German Firm,contact@firm.de,,,Berlin,DE,dentist,,Blocked country
"""
    result = import_reference_sheet(
        db,
        csv_data,
        auto_qualify=True,
        auto_approve=True,
    )

    assert result["total_rows"] == 3
    assert result["candidates_parsed"] == 3
    assert result["businesses_created"] == 3
    # 2 qualify (Ireland allowed); 1 fails qualification (Germany is a blocked compliance country)
    assert result["leads_created"] == 2
    assert result["leads_approved"] == 2

    # Check lead details in DB
    lead1 = db.query(Lead).filter(Lead.email == "info@oconnorplumbing.ie").first()
    assert lead1 is not None
    assert lead1.approved is True
    assert lead1.status == LeadStatus.READY
    assert lead1.contact_name == "Sean O'Connor"
    assert lead1.notes == "High priority lead"
    assert lead1.score > 0

    # Re-importing same data should deduplicate and not duplicate leads
    result2 = import_reference_sheet(db, csv_data, auto_qualify=True, auto_approve=True)
    assert result2["businesses_created"] == 0
    assert result2["businesses_updated"] == 3
    assert result2["leads_created"] == 0


def test_import_reference_sheet_api(auth_client):
    csv_content = "Name,Email,City,Country\nJoe Auto,joe@joeauto.ie,Waterford,IE\n"
    response = auth_client.post(
        "/api/leads/import",
        json={
            "csv_data": csv_content,
            "auto_qualify": True,
            "auto_approve": True,
            "default_category": "car_repair",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_rows"] == 1
    assert data["candidates_parsed"] == 1
    assert data["leads_created"] == 1
    assert data["leads_approved"] == 1
