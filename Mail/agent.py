#!/usr/bin/env python3
"""
Autonomous AI Sales & Gmail Operations Agent.
Master CLI Command Center for outreach, CRM management, inbox monitoring, and revenue optimization.
"""
import argparse
import sys
import os
import json
from pathlib import Path

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.config import (
    GMAIL_USER,
    REVENUE_TARGET,
    DB_PATH,
    MASTER_CSV_PATH,
    REPORT_MD_PATH,
    DASHBOARD_HTML_PATH
)
from src.crm import CRMDatabase
from src.data_importer import get_normalized_leads
from src.copywriter import SalesCopywriter
from src.gmail_client import GmailClient
from src.classifier import ReplyClassifier
from src.followups import FollowUpEngine
from src.analytics import SalesAnalytics
from src.dashboard_generator import DashboardGenerator

class AutonomousSalesAgent:
    def __init__(self, force_simulation: bool = False):
        self.crm = CRMDatabase()
        self.gmail = GmailClient(force_simulation=force_simulation)
        self.followups = FollowUpEngine(self.crm, self.gmail)
        self.analytics = SalesAnalytics(self.crm)
        self.dashboard = DashboardGenerator(self.crm)

    def import_leads(self):
        """Imports and normalizes all campaign leads into the CRM."""
        leads = get_normalized_leads()
        count = self.crm.import_leads(leads)
        print(f"✅ Imported {count} verified leads into CRM Database ({DB_PATH}).")
        print(f"📊 Exported Master CSV to {MASTER_CSV_PATH}.")
        return count

    def test_gmail(self):
        """Tests Gmail IMAP & SMTP connectivity."""
        print(f"🔍 Testing Gmail connectivity for user: {GMAIL_USER}...")
        status = self.gmail.test_connection()
        print(f"Mode: {status.get('mode')}")
        print(f"SMTP Connected: {status.get('smtp_connected')}")
        print(f"IMAP Connected: {status.get('imap_connected')}")
        print(f"Status Message: {status.get('message')}")
        if status.get("smtp_error"):
            print(f"⚠️ SMTP Note: {status.get('smtp_error')}")
        if status.get("imap_error"):
            print(f"⚠️ IMAP Note: {status.get('imap_error')}")
        return status

    def send_batch_outreach(self, limit: int = 30) -> int:
        """Dispatches personalized initial outreach emails to uncontacted leads."""
        leads = self.crm.get_all_leads()
        uncontacted = [l for l in leads if l.get("stage") == "UNCONTACTED"]
        print(f"📨 Found {len(uncontacted)} uncontacted leads. Preparing outreach (limit={limit})...")

        sent_count = 0
        for lead in uncontacted[:limit]:
            if not lead.get("email"):
                continue

            seq = SalesCopywriter.generate_email_sequence(lead)
            pitch = seq["initial_pitch"]

            res = self.gmail.send_email(
                to_email=lead["email"],
                subject=pitch["subject"],
                body=pitch["body"]
            )

            if res.get("success"):
                mode = res.get("mode", "SIMULATION")
                self.crm.log_outreach(
                    lead_id=lead["id"],
                    campaign=lead["campaign"],
                    recipient_email=lead["email"],
                    subject=pitch["subject"],
                    body=pitch["body"],
                    step_name=pitch["step_name"],
                    status="SENT" if mode == "LIVE" else "SIMULATED",
                    message_id=res.get("message_id", "")
                )
                self.crm.update_lead_stage(
                    lead_id=lead["id"],
                    stage="EMAIL_1_SENT",
                    status="CONTACTED",
                    probability=0.20
                )
                sent_count += 1
                print(f"  ✓ [{mode}] Sent pitch to {lead['business']} ({lead['email']})")

        print(f"🚀 Outreach complete! Dispatched {sent_count} initial pitch emails.")
        return sent_count

    def sync_inbox_and_classify(self) -> int:
        """Fetches inbox replies, classifies intent, and updates CRM deal stages."""
        print(f"📥 Fetching inbox messages and monitoring replies for {GMAIL_USER}...")
        messages = self.gmail.fetch_inbox_messages()
        print(f"📬 Retrieved {len(messages)} incoming messages.")

        processed = 0
        for msg in messages:
            sender = msg.get("sender", "")
            subject = msg.get("subject", "")
            body = msg.get("body", "")

            # Attempt to associate with CRM lead by sender email
            lead = self.crm.get_lead_by_email(sender)
            lead_id = lead["id"] if lead else None

            # Run NLP reply classifier
            analysis = ReplyClassifier.classify(subject, body)
            intent = analysis["intent"]
            sentiment = analysis["sentiment"]
            stage = analysis["stage"]
            prob = analysis["probability"]

            # Log message in CRM
            self.crm.log_inbox_message(
                lead_id=lead_id,
                sender_email=sender,
                subject=subject,
                body=body,
                intent=intent,
                sentiment=sentiment,
                is_actionable=analysis["is_actionable"]
            )

            # Update lead stage if matched
            if lead:
                self.crm.update_lead_stage(
                    lead_id=lead["id"],
                    stage=stage,
                    status="REPLIED",
                    probability=prob
                )
                print(f"  ⭐ [{intent}] Classified reply from {lead['business']} ({sender}) -> Moved to '{stage}' (Prob: {int(prob*100)}%)")
            else:
                print(f"  📩 [{intent}] Classified incoming message from {sender} -> {analysis['summary']}")

            processed += 1

        return processed

    def run_followups(self) -> int:
        """Executes multi-touch follow-up cadence."""
        print("⏰ Evaluating follow-up cadences (Day 3, Day 7, Day 14)...")
        count = self.followups.process_due_followups()
        print(f"🔄 Processed {count} due follow-ups.")
        return count

    def generate_report(self):
        """Generates executive sales report and prints revenue KPIs."""
        report = self.analytics.generate_markdown_report()
        metrics = self.analytics.generate_pipeline_metrics()

        print("\n" + "="*70)
        print("🎯 REVENUE & BUSINESS INTELLIGENCE KPI REPORT")
        print("="*70)
        print(f"Target Revenue KPI:        ${metrics['target_kpi']:,.2f}")
        print(f"Current Closed Revenue:    ${metrics['closed_revenue']:,.2f} ({metrics['target_progress_pct']}%)")
        print(f"Active Weighted Pipeline:  ${metrics['weighted_pipeline']:,.2f}")
        print(f"Total Pipeline Potential:  ${metrics['total_potential_pipeline']:,.2f}")
        print(f"Total Leads in CRM:        {metrics['counts']['total_leads']}")
        print(f"Contacted Leads:           {metrics['counts']['contacted']}")
        print(f"Hot Replies / Demos:       {metrics['counts']['hot_replies']}")
        print(f"Warm Inquiries:            {metrics['counts']['warm_replies']}")
        print(f"Reply Rate:                {metrics['reply_rate']}%")
        print("="*70)
        print(f"📄 Full Markdown Report saved to: {REPORT_MD_PATH}")
        return metrics

    def generate_dashboard(self):
        """Generates interactive visual dashboard HTML."""
        self.dashboard.generate_html()
        print(f"🌐 Generated interactive dashboard at {DASHBOARD_HTML_PATH}")

    def run_all(self):
        """Full autonomous workflow run."""
        print("🚀 Starting Autonomous AI Sales & Gmail Agent Pipeline...\n")
        self.import_leads()
        self.test_gmail()
        self.send_batch_outreach()
        self.sync_inbox_and_classify()
        self.run_followups()
        self.generate_report()
        self.generate_dashboard()
        print("\n🎉 Autonomous Agent Pipeline executed successfully!")

def main():
    parser = argparse.ArgumentParser(description="Autonomous Sales & Gmail Operations Agent CLI")
    parser.add_argument(
        "--action",
        choices=["import-leads", "test-gmail", "send-batch", "sync-inbox", "run-followups", "report", "dashboard", "run-all"],
        default="run-all",
        help="Action to execute"
    )
    parser.add_argument("--simulate", action="store_true", help="Force high-fidelity simulation mode")
    args = parser.parse_args()

    agent = AutonomousSalesAgent(force_simulation=args.simulate)

    if args.action == "import-leads":
        agent.import_leads()
    elif args.action == "test-gmail":
        agent.test_gmail()
    elif args.action == "send-batch":
        agent.send_batch_outreach()
    elif args.action == "sync-inbox":
        agent.sync_inbox_and_classify()
    elif args.action == "run-followups":
        agent.run_followups()
    elif args.action == "report":
        agent.generate_report()
    elif args.action == "dashboard":
        agent.generate_dashboard()
    elif args.action == "run-all":
        agent.run_all()

if __name__ == "__main__":
    main()
