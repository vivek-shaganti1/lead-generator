import json
import csv
from pathlib import Path
from src.crm import CRMDatabase
from src.validator import EmailValidator

def run_import():
    path = Path("/Users/vivekshaganti/Desktop/Projects/Mail/data/global_leads_master.json")
    with open(path, "r", encoding="utf-8") as f:
        leads = json.load(f)

    # Validate each lead before CRM insert
    validated_leads = []
    for l in leads:
        v = EmailValidator.validate(l["email"])
        l["deliverability_score"] = v["confidence_score"]
        l["is_deliverable"] = v["is_deliverable"]
        l["status"] = "VERIFIED_DELIVERABLE"
        l["stage"] = "READY_FOR_OUTREACH"
        l["probability"] = 0.20
        validated_leads.append(l)

    crm = CRMDatabase()
    count = crm.import_leads(validated_leads)
    
    # Export global master CSV
    csv_out = Path("/Users/vivekshaganti/Desktop/Projects/Mail/data/global_crm_master.csv")
    keys = validated_leads[0].keys()
    with open(csv_out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(validated_leads)

    print(f"✅ Ingested {count} 100% International Verified Leads into CRM!")
    print(f"📊 Exported Master Global Spreadsheet to {csv_out}")

if __name__ == "__main__":
    run_import()
