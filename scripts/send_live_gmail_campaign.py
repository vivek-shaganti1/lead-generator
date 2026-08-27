"""
Live Gmail Outreach Campaign Dispatcher.
Authenticates with Google SMTP (smtp.gmail.com:465) via SSL and sends real outbound emails
using ksvdevlopers@gmail.com.
"""
import smtplib
import ssl
import sys
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

# Add backend and Mail directories to sys.path
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "backend"))
sys.path.insert(0, str(_REPO_ROOT / "Mail"))

from app.config import settings
from app.db import SessionLocal
from app.models import EmailMessage, Lead, LeadStatus, MessageStatus
from app.services.crm.excel_sync import trigger_master_excel_sync
from app.utils import new_token, utcnow
from src.copywriter import SalesCopywriter
from src.crm import CRMDatabase

import os

GMAIL_USER = os.getenv("SMTP_USER", getattr(settings, "smtp_user", "ksvdevlopers@gmail.com"))
GMAIL_PASSWORD = os.getenv("SMTP_PASSWORD", getattr(settings, "smtp_password", ""))
SENDER_NAME = getattr(settings, "sender_name", "KSV Web & AI Solutions Team")


def run_live_dispatch(batch_size: int = 25):
    print("=" * 80)
    print("🚀 LAUNCHING LIVE GMAIL SMTP OUTREACH DISPATCH")
    print(f"📧 Sending Account: {GMAIL_USER}")
    print(f"🔒 Server: smtp.gmail.com:465 (SSL)")
    print("=" * 80)

    # 1. Verify Connection
    context = ssl.create_default_context()
    try:
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15, context=context)
        server.login(GMAIL_USER, GMAIL_PASSWORD)
        print("✅ Authenticated successfully with Google SMTP!")
    except Exception as e:
        print(f"❌ Failed to connect to Google SMTP: {e}")
        return False

    db = SessionLocal()
    mail_crm = CRMDatabase()

    try:
        # Send a direct test confirmation email to ksvdevlopers@gmail.com with the styled HTML template
        test_msg = MIMEMultipart("alternative")
        test_msg["From"] = f"{SENDER_NAME} <{GMAIL_USER}>"
        test_msg["To"] = GMAIL_USER
        test_msg["Subject"] = f"🟢 Live AI Sales OS Dispatched — {time.strftime('%I:%M %p')}"
        test_body = f"""Hi Vivek,

This confirms that the Lead Generator v2.0 & AI Sales Operating System is actively connected and sending live emails directly through your Gmail account ({GMAIL_USER}).

Live Outreach Summary:
⚡ Transport: Google SSL SMTP (smtp.gmail.com:465)
⚡ Sender: {SENDER_NAME}
⚡ Active Mode: LIVE_DELIVERY
⚡ Professional Styling: Red Accent Card + Badges + Custom Callouts

Check your Sent folder and Inbox to inspect the styling!
"""
        test_html = SalesCopywriter.build_styled_html(
            subject=test_msg["Subject"],
            body_text=test_body,
            business="KSV Web & AI Solutions",
            city="Hyderabad",
            first_name="Vivek",
        )
        test_msg.attach(MIMEText(test_body, "plain", "utf-8"))
        test_msg.attach(MIMEText(test_html, "html", "utf-8"))
        server.send_message(test_msg)
        print(f"🎉 Sent Styled Live Confirmation Email to {GMAIL_USER}!")

        # Fetch candidate leads from backend database
        candidates = db.query(Lead).filter(
            Lead.email.isnot(None),
            Lead.status.in_([LeadStatus.READY, LeadStatus.CONTACTED, LeadStatus.NEW]),
        ).limit(batch_size).all()

        print(f"\n📨 Dispatching live email batch ({len(candidates)} leads)...")
        live_sent = 0

        for i, lead in enumerate(candidates, start=1):
            recipient = lead.email
            if not recipient or "@" not in recipient:
                continue

            biz_name = lead.business.name if lead.business else "your business"
            city = lead.business.city if (lead.business and lead.business.city and str(lead.business.city).lower() not in ["none", "null", ""]) else "your area"
            raw_cat = lead.business.category if (lead.business and lead.business.category and str(lead.business.category).lower() not in ["none", "null", ""]) else "business"
            
            if raw_cat.lower() in ["gym", "fitness", "fitness_center"]:
                category_plural = "gyms and fitness studios"
            elif raw_cat.lower() in ["salon", "barbershop", "hair_salon"]:
                category_plural = "salons and barbershops"
            elif raw_cat.lower() in ["restaurant", "cafe", "bakery"]:
                category_plural = "restaurants and cafes"
            elif raw_cat.lower() in ["dentist", "dental", "clinic"]:
                category_plural = "dental and medical practices"
            elif raw_cat.lower() in ["lawyer", "legal", "attorney"]:
                category_plural = "law firms and legal practices"
            elif raw_cat.lower() in ["contractor", "plumber", "electrician", "roofing"]:
                category_plural = "local service contractors"
            elif raw_cat.lower() == "business":
                category_plural = "local businesses"
            else:
                category_plural = f"{raw_cat}s" if not raw_cat.endswith("s") else raw_cat

            # Generate hyper-personalized copy and styled HTML
            subject = f"Quick question about {biz_name}'s website"
            body = f"""Hi {lead.contact_name or 'there'},

I was reviewing {category_plural} in {city} and came across {biz_name}. Your customer reputation is strong, but I noticed potential customers on mobile devices might be encountering friction when trying to book or reach your team directly.

We built a sub-second mobile booking and client intake concept specifically tailored for {biz_name}:
⚡ Sub-Second Mobile Redesign: Instant client bookings directly from Google and social platforms
⚡ AI 24/7 Inquiry & Lead Qualifier: Captures customer questions and appointment requests automatically
⚡ Zero Third-Party Fees: 100% direct customer acquisition on your own domain

Would you be open to a 5-minute preview this week? No obligation at all—just wanted to share what we prepared for you.

Best regards,

{SENDER_NAME}
{GMAIL_USER}
"""

            styled_html = SalesCopywriter.build_styled_html(
                subject=subject,
                body_text=body,
                business=biz_name,
                city=city,
                first_name=lead.contact_name or "there",
            )

            msg = MIMEMultipart("alternative")
            msg["From"] = f"{SENDER_NAME} <{GMAIL_USER}>"
            msg["To"] = recipient
            msg["Subject"] = subject
            msg["Reply-To"] = GMAIL_USER
            msg.attach(MIMEText(body, "plain", "utf-8"))
            msg.attach(MIMEText(styled_html, "html", "utf-8"))

            try:
                server.send_message(msg)
                live_sent += 1
                now = utcnow()

                # Update backend DB record
                lead.status = LeadStatus.CONTACTED
                lead.last_contacted_at = now

                email_rec = EmailMessage(
                    lead_id=lead.id,
                    step=0,
                    direction="out",
                    to_email=recipient,
                    from_email=GMAIL_USER,
                    subject=subject,
                    body_text=body,
                    body_html=styled_html,
                    status=MessageStatus.SENT,
                    dry_run=False,
                    sent_at=now,
                    message_id=f"live-gmail-{lead.id}-{new_token(6)}",
                )
                db.add(email_rec)
                db.commit()

                # Update Mail CRM log
                mail_crm.log_outreach(
                    lead_id=str(lead.id),
                    campaign="Enterprise Outreach",
                    recipient_email=recipient,
                    subject=subject,
                    body=body,
                    step_name="Initial Live Pitch",
                    status="SENT",
                )

                print(f"  ✔ [{i}/{len(candidates)}] Sent to: {recipient} ({biz_name})")
                time.sleep(1.5)  # Politeness spacing for Gmail rate limits

            except Exception as send_err:
                print(f"  ❌ Error sending to {recipient}: {send_err}")

        # Update Master Multi-Tab Excel (.xlsx) & CSV
        trigger_master_excel_sync(db)
        print(f"\n📊 Master Multi-Tab Excel & CSV Synchronized with {live_sent} new live dispatch records!")
        print(f"🎉 Successfully sent {live_sent + 1} live emails through Gmail ({GMAIL_USER})!")
        print("👉 Check your Gmail 'Sent' folder now to see the sent messages!\n")

    finally:
        server.quit()
        db.close()


if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    run_live_dispatch(batch_size=count)
