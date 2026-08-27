"""
Live Gmail Sender Script (Bypasses Simulation, connects directly to Google SMTP).
"""
import sys
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.crm import CRMDatabase
from src.copywriter import SalesCopywriter
from src.config import SENDER_NAME

def send_live(app_password: str, recipient_override: str = None, send_all: bool = False):
    email_user = "ksvdevlopers@gmail.com"
    app_password = app_password.strip().replace(" ", "")

    print(f"Connecting to Google SMTP (smtp.gmail.com:465) as {email_user}...")
    try:
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10)
        server.login(email_user, app_password)
        print("✅ Google SMTP Authentication SUCCESSFUL!")
    except Exception as e:
        print(f"❌ Authentication Failed: {e}")
        return False

    crm = CRMDatabase()
    leads = crm.get_all_leads()

    if recipient_override:
        # Send a live test email directly to the user
        lead = leads[0]
        seq = SalesCopywriter.generate_email_sequence(lead)
        pitch = seq["initial_pitch"]

        msg = MIMEMultipart()
        msg["From"] = f"{SENDER_NAME} <{email_user}>"
        msg["To"] = recipient_override
        msg["Subject"] = f"[LIVE TEST] {pitch['subject']}"
        msg.attach(MIMEText(pitch["body"], "plain", "utf-8"))

        server.sendmail(email_user, [recipient_override], msg.as_string())
        print(f"🎉 Live Test Email Sent to {recipient_override}! Check your Sent folder and Inbox now.")
        server.quit()
        return True

    if send_all:
        print(f"🚀 Dispatches live emails to all {len(leads)} leads...")
        sent_count = 0
        for lead in leads:
            email = lead.get("email")
            if not email:
                continue

            seq = SalesCopywriter.generate_email_sequence(lead)
            pitch = seq["initial_pitch"]

            msg = MIMEMultipart()
            msg["From"] = f"{SENDER_NAME} <{email_user}>"
            msg["To"] = email
            msg["Subject"] = pitch["subject"]
            msg.attach(MIMEText(pitch["body"], "plain", "utf-8"))

            try:
                server.sendmail(email_user, [email], msg.as_string())
                crm.log_outreach(
                    lead_id=lead["id"],
                    campaign=lead["campaign"],
                    recipient_email=email,
                    subject=pitch["subject"],
                    body=pitch["body"],
                    step_name="Initial Pitch",
                    status="SENT"
                )
                print(f"✔ [LIVE SENT] {lead['business']} -> {email}")
                sent_count += 1
            except Exception as e:
                print(f"❌ Failed to send to {email}: {e}")

        server.quit()
        print(f"🎉 Successfully sent {sent_count} live emails via Gmail!")
        return True

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 send_live_batch.py <16-char-app-password> [--test | --all]")
        sys.exit(1)

    pwd = sys.argv[1]
    is_all = "--all" in sys.argv
    test_mode = "--test" in sys.argv or not is_all

    if test_mode:
        send_live(pwd, recipient_override="ksvdevlopers@gmail.com")
    else:
        send_live(pwd, send_all=True)
