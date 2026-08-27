"""
Cadence & Follow-Up Automation Engine.
Monitors lead age, last contact timestamps, and schedules multi-touch sequences (Day 3, 7, 14).
"""
import datetime
from typing import List, Dict, Any
from src.crm import CRMDatabase
from src.copywriter import SalesCopywriter
from src.gmail_client import GmailClient
from src.config import (
    FOLLOWUP_1_DAYS,
    FOLLOWUP_2_DAYS,
    FOLLOWUP_FINAL_DAYS
)

class FollowUpEngine:
    def __init__(self, crm: CRMDatabase, gmail_client: GmailClient):
        self.crm = crm
        self.gmail = gmail_client

    def evaluate_cadence(self) -> List[Dict[str, Any]]:
        """Evaluates all leads and identifies due follow-ups."""
        leads = self.crm.get_all_leads()
        now = datetime.datetime.now(datetime.timezone.utc)
        actions_due = []

        for lead in leads:
            stage = lead.get("stage", "UNCONTACTED")
            status = lead.get("status", "")
            last_contact = lead.get("last_contact_date")
            followup_count = lead.get("followup_count", 0)

            # Skip leads who have already replied or are closed
            if stage in ["HOT_REPLY", "WARM_REPLY", "MEETING_BOOKED", "NEGOTIATION", "CLOSED_WON", "CLOSED_LOST"]:
                continue

            if not last_contact:
                continue

            try:
                last_dt = datetime.datetime.fromisoformat(last_contact)
                days_since = (now - last_dt).total_seconds() / 86400.0
            except Exception:
                days_since = 0

            # Determine due sequence step
            due_step = None
            if followup_count == 1 and days_since >= FOLLOWUP_1_DAYS:
                due_step = "followup_1"
                next_stage = "FOLLOWUP_1_DUE"
            elif followup_count == 2 and days_since >= (FOLLOWUP_2_DAYS - FOLLOWUP_1_DAYS):
                due_step = "followup_2"
                next_stage = "FOLLOWUP_2_DUE"
            elif followup_count == 3 and days_since >= (FOLLOWUP_FINAL_DAYS - FOLLOWUP_2_DAYS):
                due_step = "followup_final"
                next_stage = "FINAL_FOLLOWUP_DUE"

            if due_step:
                actions_due.append({
                    "lead_id": lead["id"],
                    "business": lead["business"],
                    "email": lead.get("email", ""),
                    "campaign": lead.get("campaign", ""),
                    "step_key": due_step,
                    "followup_count": followup_count,
                    "days_since_contact": round(days_since, 1)
                })

        return actions_due

    def process_due_followups(self) -> int:
        """Dispatches due follow-up emails and updates lead stages."""
        due = self.evaluate_cadence()
        sent_count = 0

        for item in due:
            lead = self.crm.get_lead(item["lead_id"])
            if not lead or not lead.get("email"):
                continue

            seq = SalesCopywriter.generate_email_sequence(lead)
            step_data = seq.get(item["step_key"])
            if not step_data:
                continue

            res = self.gmail.send_email(
                to_email=lead["email"],
                subject=step_data["subject"],
                body=step_data["body"]
            )

            if res.get("success"):
                self.crm.log_outreach(
                    lead_id=lead["id"],
                    campaign=lead["campaign"],
                    recipient_email=lead["email"],
                    subject=step_data["subject"],
                    body=step_data["body"],
                    step_name=step_data["step_name"],
                    status="SENT" if res.get("mode") == "LIVE" else "SIMULATED",
                    message_id=res.get("message_id", "")
                )
                sent_count += 1

        return sent_count

if __name__ == "__main__":
    crm = CRMDatabase()
    gmail = GmailClient(force_simulation=True)
    engine = FollowUpEngine(crm, gmail)
    due = engine.evaluate_cadence()
    print(f"Evaluated follow-up cadence. Due follow-ups currently: {len(due)}")
