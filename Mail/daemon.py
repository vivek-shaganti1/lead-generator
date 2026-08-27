#!/usr/bin/env python3
"""
24/7 Autonomous AI Sales & Gmail Operations Daemon.
Runs continuously in the background to monitor incoming replies, clean bounces, automate follow-ups,
and synchronize the Master Excel Workbook (data/MASTER_CRM_OPERATIONS.xlsx).
"""
import time
import datetime
import json
import os
import sys
from pathlib import Path

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.crm import CRMDatabase
from src.gmail_client import GmailClient
from src.classifier import ReplyClassifier
from src.followups import FollowUpEngine
from src.analytics import SalesAnalytics
from src.dashboard_generator import DashboardGenerator
from src.bounce_cleaner import BounceCleaner
from src.excel_engine import MasterExcelSync
from src.config import DATA_DIR, REPORT_MD_PATH, DASHBOARD_HTML_PATH

LIVE_STATUS_FILE = DATA_DIR / "daemon_live_status.json"
ALERTS_LOG_FILE = DATA_DIR / "live_alerts.log"

def log_alert(message: str):
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{ts}] 🔔 ALERT: {message}\n"
    print(line, end="")
    with open(ALERTS_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line)

def run_daemon(poll_interval: int = 30):
    crm = CRMDatabase()
    gmail = GmailClient(force_simulation=False)
    cleaner = BounceCleaner(crm)
    followups = FollowUpEngine(crm, gmail)
    analytics = SalesAnalytics(crm)
    dash_gen = DashboardGenerator(crm)
    excel_sync = MasterExcelSync(crm)

    log_alert(f"24/7 Autonomous Sales & Master CRM Daemon started. Monitoring Gmail: {gmail.user}")

    iteration = 0
    while True:
        iteration += 1
        now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        
        try:
            # 1. Scan and clean any bounced / invalid addresses
            bounces = cleaner.scan_and_clean_bounces()
            if bounces:
                log_alert(f"Cleaned {len(bounces)} bounced address(es) from CRM.")

            # 2. Fetch and classify new inbox replies
            inbox_msgs = gmail.fetch_inbox_messages(limit=20)

            for msg in inbox_msgs:
                sender = msg.get("sender", "")
                subject = msg.get("subject", "")
                body = msg.get("body", "")

                # Skip automated delivery notices
                if "mailer-daemon" in sender.lower() or "address not found" in subject.lower():
                    continue

                lead = crm.get_lead_by_email(sender)
                analysis = ReplyClassifier.classify(subject, body)
                
                # Check if this message was already logged
                existing_msgs = crm.get_inbox_messages()
                already_logged = any(m["sender_email"] == sender and m["subject"] == subject for m in existing_msgs)

                if not already_logged and (lead or analysis["intent"] != "QUESTION"):
                    crm.log_inbox_message(
                        lead_id=lead["id"] if lead else None,
                        sender_email=sender,
                        subject=subject,
                        body=body,
                        intent=analysis["intent"],
                        sentiment=analysis["sentiment"],
                        is_actionable=analysis["is_actionable"]
                    )
                    
                    if lead:
                        crm.update_lead_stage(
                            lead_id=lead["id"],
                            stage=analysis["stage"],
                            status="REPLIED",
                            probability=analysis["probability"]
                        )
                        log_alert(f"REPLY RECEIVED from {lead['business']} ({sender})! Classified as [{analysis['intent']}] -> Stage: {analysis['stage']}")
                    else:
                        log_alert(f"New Inbound Email from {sender}: [{analysis['intent']}] {subject}")

            # 3. Evaluate and process due follow-ups
            followup_count = followups.process_due_followups()
            if followup_count > 0:
                log_alert(f"Dispatched {followup_count} automated follow-up sequence email(s).")

            # 4. Generate updated metrics, dashboard, and Master Excel Workbook
            metrics = analytics.generate_pipeline_metrics()
            analytics.generate_markdown_report()
            dash_gen.generate_html()
            excel_sync.generate_all()

            # 5. Write live status
            status_data = {
                "daemon_status": "RUNNING_24_7",
                "last_active": now_str,
                "iteration": iteration,
                "weighted_pipeline": metrics["weighted_pipeline"],
                "closed_revenue": metrics["closed_revenue"],
                "target_progress_pct": metrics["target_progress_pct"],
                "total_leads": metrics["counts"]["total_leads"],
                "hot_replies": metrics["counts"]["hot_replies"],
                "total_replies_logged": metrics["counts"]["total_replies_received"],
                "poll_interval_sec": poll_interval
            }
            with open(LIVE_STATUS_FILE, "w", encoding="utf-8") as f:
                json.dump(status_data, f, indent=2)

        except Exception as e:
            print(f"[{now_str}] Daemon error: {e}")

        # Sleep until next check
        time.sleep(poll_interval)

if __name__ == "__main__":
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    run_daemon(poll_interval=interval)
