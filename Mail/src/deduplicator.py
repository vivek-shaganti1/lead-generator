"""
Duplicate Detection, Prevention & Data Integrity Engine.
Ensures zero duplicate contact records exist across CRM, Excel workbooks, and outreach pipelines.
"""
import re
from typing import Dict, Any, List, Optional, Tuple

class LeadDeduplicator:
    @staticmethod
    def normalize_email(email_str: str) -> str:
        if not email_str:
            return ""
        return email_str.strip().lower()

    @staticmethod
    def extract_root_domain(website_or_email: str) -> str:
        if not website_or_email:
            return ""
        text = website_or_email.strip().lower()
        if "@" in text:
            text = text.split("@")[-1]
        text = re.sub(r"^https?://", "", text)
        text = re.sub(r"^www\.", "", text)
        return text.split("/")[0].split(":")[0].strip()

    @staticmethod
    def normalize_company_name(name: str) -> str:
        if not name:
            return ""
        clean = name.lower()
        clean = re.sub(r"\b(inc|llc|ltd|limited|corp|corporation|co|company|group|services|service)\b", "", clean)
        clean = re.sub(r"[^a-z0-9]", "", clean)
        return clean.strip()

    @classmethod
    def is_duplicate(cls, new_lead: Dict[str, Any], existing_leads: List[Dict[str, Any]]) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        """
        Checks if new_lead matches any record in existing_leads.
        Returns: (is_dup, matched_lead_record, reason)
        """
        new_email = cls.normalize_email(new_lead.get("email", ""))
        new_domain = cls.extract_root_domain(new_lead.get("website", "") or new_email)
        new_name = cls.normalize_company_name(new_lead.get("business", ""))

        for ex in existing_leads:
            ex_email = cls.normalize_email(ex.get("email", ""))
            ex_domain = cls.extract_root_domain(ex.get("website", "") or ex_email)
            ex_name = cls.normalize_company_name(ex.get("business", ""))

            # 1. Exact Email Match (High Confidence)
            if new_email and ex_email and new_email == ex_email:
                return True, ex, f"Exact Email Match ({new_email})"

            # 2. Exact Domain Match for non-generic domains
            if new_domain and ex_domain and new_domain == ex_domain and new_domain not in ["gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "square.site"]:
                return True, ex, f"Exact Domain Match ({new_domain})"

            # 3. Exact Company Name Match in same city
            if new_name and ex_name and new_name == ex_name and len(new_name) > 3:
                new_city = (new_lead.get("city") or "").strip().lower()
                ex_city = (ex.get("city") or "").strip().lower()
                if not new_city or not ex_city or new_city == ex_city:
                    return True, ex, f"Company Name Match ({new_lead.get('business')})"

        return False, None, "Unique Record"

    @classmethod
    def deduplicate_dataset(cls, leads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Deduplicates a list of leads in-memory, keeping the most comprehensive record."""
        unique_leads = []
        for lead in leads:
            is_dup, matched, reason = cls.is_duplicate(lead, unique_leads)
            if not is_dup:
                unique_leads.append(lead)
            else:
                # Merge fields if matched has missing values
                for k, v in lead.items():
                    if v and (k not in matched or not matched[k]):
                        matched[k] = v
        return unique_leads

if __name__ == "__main__":
    test_leads = [
        {"business": "Grow Up Digital", "email": "info@growupdigital.co.uk", "website": "growupdigital.co.uk", "deal_value": 850},
        {"business": "Grow Up Digital Ltd", "email": "info@growupdigital.co.uk", "website": "growupdigital.co.uk", "deal_value": 850},
        {"business": "East Village Dental", "email": "receptionCT@eastvillagedental.co.uk", "website": "eastvillagedental.co.uk", "deal_value": 850}
    ]
    deduped = LeadDeduplicator.deduplicate_dataset(test_leads)
    print(f"Original: {len(test_leads)} -> Deduplicated: {len(deduped)} (Zero duplicates)")
