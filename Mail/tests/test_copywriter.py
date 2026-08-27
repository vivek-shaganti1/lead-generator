"""
Unit tests for Sales Copywriter & Personalization Engine.
"""
import unittest
from src.copywriter import SalesCopywriter
from src.data_importer import get_normalized_leads

class TestSalesCopywriter(unittest.TestCase):
    def test_sequence_generation_for_all_campaigns(self):
        leads = get_normalized_leads()
        
        # Test Gym Lead
        gym_lead = next(l for l in leads if "Gym" in l["campaign"])
        gym_seq = SalesCopywriter.generate_email_sequence(gym_lead)
        self.assertIn("initial_pitch", gym_seq)
        self.assertIn("followup_1", gym_seq)
        self.assertIn("followup_2", gym_seq)
        self.assertIn("followup_final", gym_seq)
        self.assertIn(gym_lead["business"], gym_seq["initial_pitch"]["body"])
        self.assertIn(gym_lead["city"], gym_seq["initial_pitch"]["body"])

        # Test Salon Lead
        salon_lead = next(l for l in leads if "Salon" in l["campaign"])
        salon_seq = SalesCopywriter.generate_email_sequence(salon_lead)
        self.assertIn(salon_lead["business"], salon_seq["initial_pitch"]["body"])
        self.assertIn(str(salon_lead["reviews"]), salon_seq["initial_pitch"]["body"])

        # Test BigSocial Lead
        social_lead = next(l for l in leads if "BigSocial" in l["campaign"])
        social_seq = SalesCopywriter.generate_email_sequence(social_lead)
        self.assertIn(social_lead["business"], social_seq["initial_pitch"]["body"])
        self.assertIn(social_lead["pitch_hook"], social_seq["initial_pitch"]["body"])

if __name__ == "__main__":
    unittest.main()
