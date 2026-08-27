"""
Unit tests for Reply NLP Classifier & Intent Detection.
"""
import unittest
from src.classifier import ReplyClassifier

class TestReplyClassifier(unittest.TestCase):
    def test_hot_pricing_reply(self):
        res = ReplyClassifier.classify("Re: Proposal", "Please send over the pricing and mockup.")
        self.assertEqual(res["intent"], "PRICING_REQUEST")
        self.assertEqual(res["sentiment"], "POSITIVE")
        self.assertEqual(res["stage"], "HOT_REPLY")
        self.assertTrue(res["probability"] >= 0.7)

    def test_hot_meeting_reply(self):
        res = ReplyClassifier.classify("Re: Quick question", "Are you available for a quick call this Thursday?")
        self.assertEqual(res["intent"], "MEETING_REQUEST")
        self.assertEqual(res["sentiment"], "POSITIVE")
        self.assertEqual(res["stage"], "HOT_REPLY")

    def test_closed_won_reply(self):
        res = ReplyClassifier.classify("Re: Web Proposal", "We are ready to move forward. Send us the invoice.")
        self.assertEqual(res["intent"], "CLOSED_WON")
        self.assertEqual(res["sentiment"], "POSITIVE")
        self.assertEqual(res["stage"], "CLOSED_WON")
        self.assertEqual(res["probability"], 1.0)

    def test_negative_unsubscribe(self):
        res = ReplyClassifier.classify("Re: Inquiry", "Please unsubscribe and remove us from your list.")
        self.assertEqual(res["intent"], "UNSUBSCRIBE")
        self.assertEqual(res["sentiment"], "NEGATIVE")
        self.assertEqual(res["stage"], "CLOSED_LOST")
        self.assertEqual(res["probability"], 0.0)

if __name__ == "__main__":
    unittest.main()
