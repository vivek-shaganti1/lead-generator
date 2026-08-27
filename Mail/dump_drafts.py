from src.crm import CRMDatabase
from src.copywriter import SalesCopywriter

crm = CRMDatabase()
leads = crm.get_all_leads()

for l in leads:
    seq = SalesCopywriter.generate_email_sequence(l)
    print("=" * 80)
    print(f"[{l['campaign'].upper()}] - {l['business']} (Score: {l['lead_score']}/100)")
    print(f"Recipient: {l['email']} | Attention: {l['owner']} | Deal Size: ${l['deal_value']}")
    print("-" * 80)
    print(f"Subject: {seq['initial_pitch']['subject']}\n")
    print(seq['initial_pitch']['body'])
    print("\n" + "." * 40 + " [Follow-Up #1 at Day 3] " + "." * 40)
    print(f"Subject: {seq['followup_1']['subject']}\n")
    print(seq['followup_1']['body'])
    print("\n")
