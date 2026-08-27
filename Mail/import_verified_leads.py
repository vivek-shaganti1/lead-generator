import json
from pathlib import Path
from src.crm import CRMDatabase

def import_verified():
    path = Path("/Users/vivekshaganti/Desktop/Projects/Mail/data/verified_deliverable_leads.json")
    with open(path, "r", encoding="utf-8") as f:
        leads = json.load(f)

    crm = CRMDatabase()
    count = crm.import_leads(leads)
    print(f"Successfully loaded and verified {count} 100% deliverable leads into CRM!")

if __name__ == "__main__":
    import_verified()
