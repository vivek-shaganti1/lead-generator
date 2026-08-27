"""
End-to-End Pipeline & Revenue Intelligence Tests.
"""
import unittest
import tempfile
from pathlib import Path
from src.crm import CRMDatabase
from src.data_importer import get_normalized_leads
from src.analytics import SalesAnalytics
from src.followups import FollowUpEngine
from src.gmail_client import GmailClient

class TestFullPipeline(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_crm.db"
        self.crm = CRMDatabase(self.db_path)
        self.leads = get_normalized_leads()
        self.crm.import_leads(self.leads)
        self.gmail = GmailClient(force_simulation=True)
        self.analytics = SalesAnalytics(self.crm)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_revenue_and_deal_transitions(self):
        # Initial state
        initial_metrics = self.analytics.generate_pipeline_metrics()
        self.assertEqual(initial_metrics["target_kpi"], 1000.0)
        self.assertEqual(initial_metrics["closed_revenue"], 0.0)

        # Close 2 deals ($500 + $600 = $1,100 -> Target reached!)
        lead_1 = self.leads[0]["id"]
        lead_2 = self.leads[1]["id"]
        val_1 = self.leads[0]["deal_value"]
        val_2 = self.leads[1]["deal_value"]

        self.crm.update_lead_stage(lead_1, stage="CLOSED_WON", status="REPLIED", probability=1.0)
        self.crm.update_lead_stage(lead_2, stage="CLOSED_WON", status="REPLIED", probability=1.0)

        after_metrics = self.analytics.generate_pipeline_metrics()
        expected_closed = val_1 + val_2
        self.assertEqual(after_metrics["closed_revenue"], expected_closed)
        self.assertTrue(after_metrics["closed_revenue"] >= 1000.0)
        self.assertTrue(after_metrics["target_progress_pct"] >= 100.0)

if __name__ == "__main__":
    unittest.main()
