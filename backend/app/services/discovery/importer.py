"""Universal reference sheet / CSV / JSON lead importer.

Allows users to upload custom spreadsheets, CRM exports, lead lists, or
reference sheets with fuzzy header detection, automated deduplication,
qualification, scoring, and automated pipeline integration.
"""
from __future__ import annotations

import csv
import io
import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.logging_config import get_logger
from app.models import Business, Campaign, Lead, LeadStatus
from app.services import pipeline
from app.services.discovery.base import PlaceCandidate
from app.utils import dedupe_key, domain_of, new_token, utcnow

log = get_logger(__name__)

# Fuzzy column name mappings
HEADER_MAP: dict[str, list[str]] = {
    "name": [
        "name", "business_name", "business", "company_name", "company",
        "organization", "org_name", "store_name", "title", "firm", "account_name"
    ],
    "email": [
        "email", "email_address", "contact_email", "e-mail", "mail",
        "primary_email", "business_email", "owner_email"
    ],
    "website": [
        "website", "url", "website_url", "site", "web", "domain", "homepage",
        "link", "web_url"
    ],
    "phone": [
        "phone", "phone_number", "tel", "telephone", "mobile", "cell",
        "contact_phone", "contact_number"
    ],
    "category": [
        "category", "industry", "type", "business_type", "niche",
        "vertical", "tag", "sector"
    ],
    "contact_name": [
        "contact_name", "contact_person", "owner", "owner_name", "first_name",
        "full_name", "person", "contact", "decision_maker"
    ],
    "address": [
        "address", "street", "street_address", "address_line_1", "addr", "location"
    ],
    "city": [
        "city", "town", "locality", "municipality"
    ],
    "region": [
        "region", "state", "province", "county", "district"
    ],
    "postcode": [
        "postcode", "postal_code", "zip", "zip_code", "postal", "pin", "pincode"
    ],
    "country_code": [
        "country_code", "country", "c_code", "nation", "geo_country"
    ],
    "lat": [
        "lat", "latitude", "y"
    ],
    "lon": [
        "lon", "lng", "longitude", "x"
    ],
    "facebook": [
        "facebook", "fb", "fb_url", "facebook_url"
    ],
    "instagram": [
        "instagram", "ig", "ig_url", "instagram_url"
    ],
    "notes": [
        "notes", "comments", "remarks", "description", "custom", "details"
    ],
}


def _normalize_header(header: str) -> str:
    """Turn 'Business Name / Company (Required)' into 'business_name'."""
    cleaned = re.sub(r"[^\w\s]", "", str(header or "").lower())
    cleaned = re.sub(r"\s+", "_", cleaned.strip())
    for canonical, variants in HEADER_MAP.items():
        if cleaned == canonical or cleaned in variants:
            return canonical
        for variant in variants:
            if variant in cleaned:
                return canonical
    return cleaned


def parse_tabular_data(raw_content: str | bytes) -> list[dict[str, Any]]:
    """Parse CSV, TSV, or JSON data into normalized list of dictionaries."""
    if isinstance(raw_content, bytes):
        try:
            text = raw_content.decode("utf-8")
        except UnicodeDecodeError:
            text = raw_content.decode("latin-1", errors="replace")
    else:
        text = str(raw_content)

    text = text.strip()
    if not text:
        return []

    # Check if raw text is JSON array or JSON lines
    if text.startswith("[") and text.endswith("]"):
        try:
            data = json.loads(text)
            if isinstance(data, list):
                out = []
                for item in data:
                    if isinstance(item, dict):
                        normalized = {_normalize_header(k): v for k, v in item.items()}
                        out.append(normalized)
                return out
        except Exception:
            pass

    # Detect delimiter
    first_line = text.splitlines()[0] if text.splitlines() else ""
    delimiter = ","
    if "\t" in first_line:
        delimiter = "\t"
    elif ";" in first_line and first_line.count(";") > first_line.count(","):
        delimiter = ";"
    elif "|" in first_line and first_line.count("|") > first_line.count(","):
        delimiter = "|"

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = list(reader)
    if not rows:
        return []

    raw_headers = rows[0]
    normalized_headers = [_normalize_header(h) for h in raw_headers]

    out_records = []
    for row_idx, row in enumerate(rows[1:], start=2):
        if not any(cell.strip() for cell in row):
            continue
        record: dict[str, Any] = {}
        for col_idx, cell in enumerate(row):
            if col_idx < len(normalized_headers):
                field_name = normalized_headers[col_idx]
                val = cell.strip()
                if val:
                    record[field_name] = val
        if record:
            record["_row_number"] = row_idx
            out_records.append(record)

    return out_records


def _parse_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _clean_country_code(val: Any) -> str | None:
    if not val:
        return None
    cleaned = str(val).strip().upper()
    if len(cleaned) == 2:
        return cleaned
    # Map common full country names to ISO alpha-2 codes
    country_name_map = {
        "UNITED STATES": "US", "USA": "US", "UNITED KINGDOM": "GB", "UK": "GB",
        "GREAT BRITAIN": "GB", "IRELAND": "IE", "AUSTRALIA": "AU", "CANADA": "CA",
        "NEW ZEALAND": "NZ", "INDIA": "IN", "SINGAPORE": "SG", "SOUTH AFRICA": "ZA",
        "GERMANY": "DE", "FRANCE": "FR", "ITALY": "IT", "SPAIN": "ES",
    }
    return country_name_map.get(cleaned, cleaned[:2])


def row_to_candidate(record: dict[str, Any], index: int) -> PlaceCandidate | None:
    """Convert a normalized dict record into a PlaceCandidate."""
    name = (record.get("name") or record.get("business_name") or "").strip()
    if not name:
        return None

    email = (record.get("email") or "").strip() or None
    website = (record.get("website") or "").strip() or None
    phone = (record.get("phone") or "").strip() or None
    category = (record.get("category") or "").strip() or None
    address = (record.get("address") or "").strip() or None
    city = (record.get("city") or "").strip() or None
    region = (record.get("region") or "").strip() or None
    postcode = (record.get("postcode") or "").strip() or None
    country_code = _clean_country_code(record.get("country_code"))
    lat = _parse_float(record.get("lat"))
    lon = _parse_float(record.get("lon"))
    facebook = (record.get("facebook") or "").strip() or None
    instagram = (record.get("instagram") or "").strip() or None

    source_id = f"import_{index}_{abs(hash((name, phone or '', email or '', website or '')))}"

    raw_data = {k: v for k, v in record.items() if not k.startswith("_")}

    return PlaceCandidate(
        source="import",
        source_id=source_id,
        name=name,
        category=category,
        phone=phone,
        email=email,
        website=website,
        facebook=facebook,
        instagram=instagram,
        address=address,
        city=city,
        region=region,
        postcode=postcode,
        country_code=country_code,
        lat=lat,
        lon=lon,
        raw=raw_data,
    )


def import_reference_sheet(
    db: Session,
    raw_content: str | bytes,
    *,
    campaign_id: int | None = None,
    auto_qualify: bool = True,
    auto_approve: bool | None = None,
    auto_dispatch: bool = False,
    default_category: str | None = None,
    default_country: str | None = None,
) -> dict[str, Any]:
    """Ingest a reference spreadsheet, deduplicate, qualify, optionally auto-approve, auto-dispatch, and sync Master Excel."""
    from app.services.crm.excel_sync import trigger_master_excel_sync

    records = parse_tabular_data(raw_content)
    if not records:
        return {
            "total_rows": 0,
            "candidates_parsed": 0,
            "businesses_created": 0,
            "businesses_updated": 0,
            "without_website": 0,
            "leads_created": 0,
            "leads_approved": 0,
            "leads_dispatched": 0,
            "errors": ["No valid data rows found in input."],
        }

    campaign = (
        db.get(Campaign, campaign_id) if campaign_id else pipeline.get_or_create_default_campaign(db)
    )
    if campaign is None:
        campaign = pipeline.get_or_create_default_campaign(db)

    should_approve = (
        auto_approve if auto_approve is not None else (not settings.require_manual_approval)
    )

    candidates: list[PlaceCandidate] = []
    record_meta_by_key: dict[str, dict[str, Any]] = {}

    for idx, rec in enumerate(records, start=1):
        if default_category and not rec.get("category"):
            rec["category"] = default_category
        if default_country and not rec.get("country_code"):
            rec["country_code"] = default_country

        cand = row_to_candidate(rec, idx)
        if cand:
            candidates.append(cand)
            record_meta_by_key[cand.key] = rec

    ingest_stats = pipeline.ingest_candidates(db, candidates)
    db.commit()

    leads_created = 0
    leads_approved = 0
    leads_dispatched = 0
    errors: list[str] = []
    created_lead_objs: list[Lead] = []

    if auto_qualify:
        for cand in candidates:
            biz = db.execute(
                select(Business).where(Business.dedupe_key == cand.key)
            ).scalars().first()
            if not biz:
                continue

            # Check if lead already exists
            existing_lead = db.execute(
                select(Lead).where(Lead.business_id == biz.id)
            ).scalars().first()
            if existing_lead:
                continue

            try:
                res = pipeline.qualify_business(db, biz, campaign=campaign)
                if res.created and res.lead_id:
                    leads_created += 1
                    lead = db.get(Lead, res.lead_id)
                    if lead:
                        # Copy extra metadata from sheet
                        rec = record_meta_by_key.get(cand.key, {})
                        if rec.get("contact_name"):
                            lead.contact_name = str(rec["contact_name"]).strip()
                        if rec.get("notes"):
                            lead.notes = str(rec["notes"]).strip()
                        if should_approve:
                            lead.approved = True
                            lead.status = LeadStatus.READY
                            lead.next_action_at = utcnow()
                            leads_approved += 1
                        created_lead_objs.append(lead)
                    db.commit()
                else:
                    db.rollback()
            except Exception as exc:
                db.rollback()
                log.warning("import.qualify_failed", business_id=biz.id, error=str(exc))
                errors.append(f"Row '{biz.name}': {exc}")

    # Optional auto-dispatch
    if auto_dispatch and created_lead_objs:
        from app.services.outreach.dispatcher import send_lead
        for lead in created_lead_objs:
            if lead.status == LeadStatus.READY or lead.approved:
                try:
                    outcome = send_lead(db, lead, force=True)
                    if outcome.sent:
                        leads_dispatched += 1
                    db.commit()
                except Exception as exc:
                    db.rollback()
                    log.warning("import.dispatch_failed", lead_id=lead.id, error=str(exc))

    # Real-time Master Multi-Tab Excel synchronization
    try:
        trigger_master_excel_sync(db)
    except Exception as exc:
        log.warning("import.excel_sync_failed", error=str(exc))

    return {
        "total_rows": len(records),
        "candidates_parsed": len(candidates),
        "businesses_created": ingest_stats.new,
        "businesses_updated": ingest_stats.updated,
        "without_website": ingest_stats.without_website,
        "leads_created": leads_created,
        "leads_approved": leads_approved,
        "leads_dispatched": leads_dispatched,
        "errors": errors[:20],
    }
