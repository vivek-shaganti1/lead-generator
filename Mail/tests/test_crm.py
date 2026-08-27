"""
Unit tests for CRM Database Layer.
"""
import unittest
import tempfile
import os
from pathlib import Path
from src.crm import CRMDatabase
from src.data_importer import get_normalized_leads

class TestCRMDatabase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_crm.db"
        self.crm = CRMDatabase(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_import_and_retrieve_leads(self):
        leads = get_normalized_leads()
        count = self.crm.import_leads(leads)
        self.assertEqual(count, len(leads))

        retrieved = self.crm.get_all_leads()
        self.assertEqual(len(retrieved), len(leads))
        
        # Test get by ID
        lead_0 = retrieved[0]
        found = self.crm.get_lead(lead_0["id"])
        self.assertIsNotNone(found)
        self.assertEqual(found["business"], lead_0["business"])

    def test_update_lead_stage(self):
        leads = get_normalized_leads()
        self.crm.import_leads(leads)
        first_id = leads[0]["id"]

        self.crm.update_lead_stage(first_id, stage="HOT_REPLY", status="REPLIED", probability=0.75)
        updated = self.crm.get_lead(first_id)
        self.assertEqual(updated["stage"], "HOT_REPLY")
        self.assertEqual(updated["status"], "REPLIED")
        self.assertEqual(updated["probability"], 0.75)

    def test_outreach_and_inbox_logging(self):
        leads = get_normalized_leads()
        self.crm.import_leads(leads)
        first_id = leads[0]["id"]
        email = leads[0]["email"]

        self.crm.log_outreach(
            lead_id=first_id,
            campaign=leads[0]["campaign"],
            recipient_email=email,
            subject="Test Subject",
            body="Test Body",
            step_name="Initial Pitch",
            status="SIMULATED"
        )
        logs = self.crm.get_outreach_history(first_id)
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["step_name"], "Initial Pitch")

        self.crm.log_inbox_message(
            lead_id=first_id,
            sender_email=email,
            subject="Re: Test Subject",
            body="Interested in pricing",
            intent="PRICING_REQUEST",
            sentiment="POSITIVE"
        )
        inbox = self.crm.get_inbox_messages()
        self.assertEqual(len(inbox), 1)
        self.assertEqual(inbox[0]["intent"], "PRICING_REQUEST")

if __name__ == "__main__":
    unittest.main()
