"""
Live Gmail Bounce & Mail Delivery Subsystem Parser.
Identifies failed delivery notices, extracts invalid addresses, and marks them in CRM.
"""
import re
import imaplib
import email
from email.header import decode_header
from typing import List, Set
from src.crm import CRMDatabase
from src.config import GMAIL_USER, GMAIL_APP_PASSWORD, GMAIL_IMAP_SERVER, GMAIL_IMAP_PORT

class BounceCleaner:
    def __init__(self, crm: CRMDatabase, user: str = GMAIL_USER, password: str = GMAIL_APP_PASSWORD):
        self.crm = crm
        self.user = user
        self.password = password

    def scan_and_clean_bounces(self) -> Set[str]:
        """Connects to IMAP, identifies bounce messages, and marks leads as BOUNCED."""
        bounced_emails = set()
        try:
            imap = imaplib.IMAP4_SSL(GMAIL_IMAP_SERVER, GMAIL_IMAP_PORT, timeout=10)
            imap.login(self.user, self.password)
            imap.select("INBOX")

            # Search for messages from mailer-daemon or with 'Address not found'
            status, data = imap.search(None, '(OR FROM "mailer-daemon" SUBJECT "Address not found")')
            if status == "OK" and data[0]:
                msg_ids = data[0].split()
                for mid in msg_ids:
                    res, msg_data = imap.fetch(mid, "(RFC822)")
                    for part in msg_data:
                        if isinstance(part, tuple):
                            msg = email.message_from_bytes(part[1])
                            body = ""
                            if msg.is_multipart():
                                for p in msg.walk():
                                    if p.get_content_type() == "text/plain":
                                        body += p.get_payload(decode=True).decode("utf-8", errors="ignore")
                            else:
                                body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")

                            # Extract failed email addresses
                            found = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", body)
                            for e in found:
                                e_clean = e.strip().lower()
                                if e_clean != self.user.lower() and not e_clean.endswith("googlemail.com") and not e_clean.endswith("google.com"):
                                    bounced_emails.add(e_clean)

            imap.logout()
        except Exception as e:
            print(f"Error scanning bounces: {e}")

        # Update CRM
        cleaned_count = 0
        for b_email in bounced_emails:
            lead = self.crm.get_lead_by_email(b_email)
            if lead:
                self.crm.update_lead_stage(
                    lead_id=lead["id"],
                    stage="BOUNCED",
                    status="INVALID_EMAIL",
                    probability=0.0
                )
                cleaned_count += 1
                print(f"🚫 Marked invalid/bounced lead in CRM: {lead['business']} ({b_email})")

        return bounced_emails

if __name__ == "__main__":
    crm = CRMDatabase()
    cleaner = BounceCleaner(crm)
    bounces = cleaner.scan_and_clean_bounces()
    print(f"Completed bounce scan. Total bounced addresses identified: {len(bounces)}")
