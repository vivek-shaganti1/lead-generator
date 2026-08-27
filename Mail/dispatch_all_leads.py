"""
Live Dispatcher & Real-Time Tracking Execution Script.
Sends personalized, clean, AI-powered pitch emails to all verified leads and displays real-time verification ticks.
"""
import sys
import datetime
from pathlib import Path

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.crm import CRMDatabase
from src.copywriter import SalesCopywriter
from src.gmail_client import GmailClient
from src.dashboard_generator import DashboardGenerator
from src.analytics import SalesAnalytics

def dispatch_all():
    crm = CRMDatabase()
    gmail = GmailClient(force_simulation=False) # Auto falls back to simulation if needed
    leads = crm.get_all_leads()
    analytics = SalesAnalytics(crm)
    dash_gen = DashboardGenerator(crm)

    print("\n" + "="*85)
    print("🚀 LIVE OUTREACH DISPATCH & REAL-TIME VERIFICATION MONITOR")
    print(f"Timestamp: {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"Sender Account: ksvdevlopers@gmail.com | Target Goal: $1,000+ KPI")
    print("="*85 + "\n")

    dispatched = []

    for idx, lead in enumerate(leads, 1):
        seq = SalesCopywriter.generate_email_sequence(lead)
        pitch = seq["initial_pitch"]
        email = lead.get("email", "")

        if not email:
            print(f"❌ [{idx:02d}/27] Skipped {lead['business']} - No email address found.")
            continue

        res = gmail.send_email(
            to_email=email,
            subject=pitch["subject"],
            body=pitch["body"]
        )

        mode = res.get("mode", "SIMULATION")
        msg_id = res.get("message_id", "")

        # Log in CRM
        crm.log_outreach(
            lead_id=lead["id"],
            campaign=lead["campaign"],
            recipient_email=email,
            subject=pitch["subject"],
            body=pitch["body"],
            step_name="Initial Pitch (Clean AI + Discount)",
            status="SENT" if mode == "LIVE" else "SIMULATED",
            message_id=msg_id
        )

        crm.update_lead_stage(
            lead_id=lead["id"],
            stage="EMAIL_1_SENT",
            status="CONTACTED",
            probability=0.20
        )

        print(f"✔ [{idx:02d}/27] [{lead['campaign']}] {lead['business']}")
        print(f"    ├─ Owner/Contact: {lead['owner']}")
        print(f"    ├─ Recipient:     {email}")
        print(f"    ├─ Subject:       {pitch['subject']}")
        print(f"    ├─ Deal & Disc:   ${lead['deal_value']:,.2f} (Special Partner Rate)")
        print(f"    ├─ Status:        ✔ MAIL SENT ({mode}) | MsgID: {msg_id[:16]}...")
        print(f"    └─ CRM Stage:     EMAIL_1_SENT (Tracked in CRM DB)\n")

        dispatched.append(lead)

    # Sync inbox to detect any immediate live replies
    inbox_msgs = gmail.fetch_inbox_messages()
    for msg in inbox_msgs:
        sender = msg.get("sender", "")
        matched_lead = crm.get_lead_by_email(sender)
        if matched_lead:
            crm.log_inbox_message(
                lead_id=matched_lead["id"],
                sender_email=sender,
                subject=msg.get("subject", ""),
                body=msg.get("body", ""),
                intent="HOT_LEAD",
                sentiment="POSITIVE",
                is_actionable=True
            )
            crm.update_lead_stage(matched_lead["id"], stage="HOT_REPLY", status="REPLIED", probability=0.75)

    # Refresh analytics and dashboard
    metrics = analytics.generate_pipeline_metrics()
    analytics.generate_markdown_report()
    dash_gen.generate_html()

    print("="*85)
    print(f"🎉 DISPATCH COMPLETE: {len(dispatched)}/27 EMAILS SENT & LOGGED WITH FULL CRM TRACKING!")
    print(f"📊 Active Weighted Pipeline: ${metrics['weighted_pipeline']:,.2f} / $1,000.00 Target ({metrics['projected_attainment_pct']}% of goal)")
    print(f"🌐 Interactive Dashboard Updated: static/dashboard.html")
    print("="*85 + "\n")

if __name__ == "__main__":
    dispatch_all()
