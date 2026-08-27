"""
AI Reply Classifier & Intent Detection Engine.
Classifies incoming email responses into sales categories, sentiment, and actionable stages.
"""
import re
from typing import Dict, Any, Tuple

class ReplyClassifier:
    """Classifies sales outreach replies into actionable CRM states."""

    POSITIVE_HOT_KEYWORDS = [
        "interested", "send pricing", "price", "pricing", "quote", "cost", "how much",
        "demo", "mockup", "send over", "send it", "let's talk", "lets talk", "call me", "call",
        "schedule", "meeting", "zoom", "available", "thursday", "friday", "monday",
        "tuesday", "wednesday", "this week", "next week", "sounds good", "let's do it",
        "lets do it", "show me", "send preview", "preview"
    ]

    POSITIVE_WARM_KEYWORDS = [
        "more info", "tell me more", "details", "questions", "later", "busy right now",
        "next month", "maybe", "check back", "who are you", "what is this", "portfolio",
        "examples", "case studies"
    ]

    CLOSED_WON_KEYWORDS = [
        "ready to buy", "sign contract", "send invoice", "payment", "paid", "contract",
        "let's proceed", "lets proceed", "move forward", "get started", "deal", "hired"
    ]

    NEGATIVE_COLD_KEYWORDS = [
        "not interested", "no thanks", "no thank you", "pass", "remove", "unsubscribe",
        "stop emailing", "don't contact", "dont contact", "already have", "not looking",
        "not needed", "spam", "leave us alone", "take me off"
    ]

    @classmethod
    def classify(cls, subject: str, body: str) -> Dict[str, Any]:
        """Analyzes email subject and body, returning classification dictionary."""
        text = f"{subject} {body}".lower()

        # Check Closed Won
        for kw in cls.CLOSED_WON_KEYWORDS:
            if re.search(r"\b" + re.escape(kw) + r"\b", text):
                return {
                    "intent": "CLOSED_WON",
                    "sentiment": "POSITIVE",
                    "stage": "CLOSED_WON",
                    "probability": 1.0,
                    "is_actionable": True,
                    "summary": f"Customer ready to proceed/contract: matched '{kw}'",
                    "priority": "CRITICAL",
                    "suggested_action": "Send invoice / contract agreement immediately and onboard."
                }

        # Check Unsubscribe / Negative / Cold
        for kw in cls.NEGATIVE_COLD_KEYWORDS:
            if re.search(r"\b" + re.escape(kw) + r"\b", text):
                is_unsub = any(w in text for w in ["unsubscribe", "remove", "stop emailing", "don't contact", "dont contact", "take me off"])
                return {
                    "intent": "UNSUBSCRIBE" if is_unsub else "CLOSED_LOST",
                    "sentiment": "NEGATIVE",
                    "stage": "CLOSED_LOST",
                    "probability": 0.0,
                    "is_actionable": False,
                    "summary": f"Lead expressed no interest or opt-out: matched '{kw}'",
                    "priority": "LOW",
                    "suggested_action": "Mark as inactive / DNC in CRM and do not follow up."
                }

        # Check Meeting Request
        meeting_triggers = ["meeting", "call", "zoom", "schedule", "talk", "thursday", "friday", "monday", "tuesday", "wednesday", "available for a"]
        for mt in meeting_triggers:
            if re.search(r"\b" + re.escape(mt) + r"\b", text):
                return {
                    "intent": "MEETING_REQUEST",
                    "sentiment": "POSITIVE",
                    "stage": "HOT_REPLY",
                    "probability": 0.80,
                    "is_actionable": True,
                    "summary": f"Meeting / call requested: matched '{mt}'",
                    "priority": "HIGH",
                    "suggested_action": "Respond within 15 minutes with calendar booking link and demo confirmation."
                }

        # Check Pricing / Mockup Request
        pricing_triggers = ["price", "pricing", "cost", "how much", "quote", "mockup", "preview", "send over", "send it"]
        for pt in pricing_triggers:
            if re.search(r"\b" + re.escape(pt) + r"\b", text):
                return {
                    "intent": "PRICING_REQUEST",
                    "sentiment": "POSITIVE",
                    "stage": "HOT_REPLY",
                    "probability": 0.75,
                    "is_actionable": True,
                    "summary": f"Pricing / mockup preview requested: matched '{pt}'",
                    "priority": "HIGH",
                    "suggested_action": "Send 3-tiered package breakdown ($350 Starter, $500 Growth, $750 Pro) + live interactive prototype link."
                }

        # Check General Hot Lead
        for kw in cls.POSITIVE_HOT_KEYWORDS:
            if re.search(r"\b" + re.escape(kw) + r"\b", text):
                return {
                    "intent": "HOT_LEAD",
                    "sentiment": "POSITIVE",
                    "stage": "HOT_REPLY",
                    "probability": 0.70,
                    "is_actionable": True,
                    "summary": f"High purchase interest: matched '{kw}'",
                    "priority": "HIGH",
                    "suggested_action": "Follow up with tailored proposal and next steps."
                }

        # Check Warm Lead
        for kw in cls.POSITIVE_WARM_KEYWORDS:
            if re.search(r"\b" + re.escape(kw) + r"\b", text):
                return {
                    "intent": "WARM_LEAD",
                    "sentiment": "POSITIVE",
                    "stage": "WARM_REPLY",
                    "probability": 0.45,
                    "is_actionable": True,
                    "summary": f"Lead requested additional information: matched '{kw}'",
                    "priority": "MEDIUM",
                    "suggested_action": "Send informative portfolio breakdown and value proposition."
                }

        # Default Neutral / Inquiry
        return {
            "intent": "QUESTION",
            "sentiment": "NEUTRAL",
            "stage": "WARM_REPLY",
            "probability": 0.35,
            "is_actionable": True,
            "summary": "General inquiry or response received requiring review.",
            "priority": "MEDIUM",
            "suggested_action": "Review inquiry context and reply with personalized answer."
        }
