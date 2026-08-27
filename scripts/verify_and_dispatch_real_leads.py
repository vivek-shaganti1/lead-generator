"""
High-Precision DNS MX Verified Direct International Outreach Engine.

Features:
1. Live DNS MX Verification: Resolves mail exchangers before sending; skips invalid domains.
2. Anti-Self-Loop Security Guard: Enforces that From != To. All emails go directly to verified prospects.
3. Deep Consultative Business Proposal: 3-pillar strategic value analysis tailored per industry.
4. Real-time CRM Tracking: Updates Deals, Leads, and synchronizes the 9-tab Master Excel Workbook.
"""
from __future__ import annotations

import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import os
from pathlib import Path
import smtplib
import sys
import time

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "backend"))
sys.path.insert(0, str(_REPO_ROOT / "Mail"))

from app.config import settings
from app.db import SessionLocal, init_db
from app.models import (
    Business,
    Campaign,
    Deal,
    DealStage,
    EmailMessage,
    Lead,
    LeadStatus,
    MessageStatus,
)
from app.services.crm.excel_sync import trigger_master_excel_sync
from app.services.enrichment.validator import validate
from app.utils import new_token, utcnow

GMAIL_USER = os.getenv("SMTP_USER", getattr(settings, "smtp_user", "ksvdevlopers@gmail.com"))
GMAIL_PASSWORD = os.getenv("SMTP_PASSWORD", getattr(settings, "smtp_password", "kztzxmkbrwhhtdzd"))
SENDER_NAME = "KSV Web & AI Solutions Team"


TARGET_CANDIDATES = [
    # London, United Kingdom
    ("Kyan Digital Studio", "Managing Director", "London", "United Kingdom", "GB", "kyan.com", "hello@kyan.com", "Digital Product Studio", "Dedicated engineering bandwidth for Next.js web applications, mobile platforms, and AI workflow automations.", 1450.0),
    ("Cyber-Duck Digital Transformation", "Leadership Team", "London", "United Kingdom", "GB", "cyber-duck.co.uk", "info@cyber-duck.co.uk", "Digital Agency & UX", "White-label full-stack engineering support and high-performance client portal development.", 1600.0),
    ("Bravura Dental London", "Clinical Director", "London", "United Kingdom", "GB", "bravuradental.co.uk", "reception@bravuradental.co.uk", "Cosmetic Dentistry", "24/7 AI Patient Booking Assistant, direct smile consultation intake, and automated appointment reminders.", 1200.0),
    ("Ten Health & Fitness London", "Operations Manager", "London", "United Kingdom", "GB", "ten.co.uk", "info@ten.co.uk", "Physiotherapy & Wellness", "Frictionless mobile booking, package checkout, and automated client retention workflows.", 950.0),
    ("Clerkenwell Design Studio", "Principal Architect", "London", "United Kingdom", "GB", "clerkenwelldesign.co.uk", "info@clerkenwelldesign.co.uk", "Architectural Design", "High-speed 3D architectural portfolio showcases and automated consultation intake funnels.", 1350.0),
    ("London IP Law Chambers", "Senior Partner", "London", "United Kingdom", "GB", "londonip.com", "info@londonip.com", "IP & Patent Law", "Sub-second client onboarding portal, conflict-check intake, and automated consultation scheduling.", 1500.0),
    ("Mayfair Aesthetics London", "Clinic Director", "London", "United Kingdom", "GB", "mayfairaesthetics.co.uk", "info@mayfairaesthetics.co.uk", "Laser & Aesthetic Medicine", "24/7 AI VIP Consultation Intake, treatment preview funnels, and automated deposit processing.", 1400.0),
    ("Richmond Dental Suite", "Practice Lead", "London", "United Kingdom", "GB", "richmonddentalsuite.co.uk", "info@richmonddentalsuite.co.uk", "Cosmetic Dentistry", "Direct smile consultation intake, automated SMS reminders, and zero-friction patient scheduling.", 1150.0),
    ("Mint Digital Agency", "Client Services Lead", "London", "United Kingdom", "GB", "mintdigital.com", "hello@mintdigital.com", "Web & Mobile Studio", "Turnkey mobile app engineering (iOS/Android/Flutter) and scalable cloud backend integration.", 1300.0),
    ("The Goring Hospitality", "General Manager", "London", "United Kingdom", "GB", "thegoring.com", "reception@thegoring.com", "Prestige Hospitality", "0% commission direct VIP table reservation system and private dining event request CRM.", 1250.0),

    # New York & Miami, USA
    ("Postlight Software Studios", "Engineering Partners", "New York", "United States", "US", "postlight.com", "hello@postlight.com", "Digital Systems Architecture", "Full-stack web application engineering and scalable cloud infrastructure modernization.", 1750.0),
    ("Huge Inc Digital", "Studio Directors", "New York", "United States", "US", "hugeinc.com", "hello@hugeinc.com", "Creative Technology", "High-conversion digital brand experiences and sub-second React/Next.js frontend development.", 1650.0),
    ("Code and Theory New York", "Tech Lead", "New York", "United States", "US", "codeandtheory.com", "info@codeandtheory.com", "Creative Tech Agency", "Custom AI workflow integration, intelligent intake bots, and enterprise dashboard architecture.", 1600.0),
    ("Tribeca Dental Studio", "Dr. Practice Manager", "New York", "United States", "US", "tribecadentalstudio.com", "info@tribecadentalstudio.com", "Cosmetic Dentistry", "24/7 AI Patient Booking Assistant, direct smile consultation funnels, and insurance pre-check bot.", 1200.0),
    ("Manhattan MedSpa", "Clinical Director", "New York", "United States", "US", "manhattanmedspa.com", "info@manhattanmedspa.com", "Medical Aesthetics", "Seamless online consultation intake, treatment previews, and automated deposit checkout.", 1350.0),
    ("Miami Beach Dental Spa", "Office Manager", "Miami", "United States", "US", "miamibeachdentalspa.com", "info@miamibeachdentalspa.com", "Cosmetic Dentistry", "Bilingual Spanish/English 24/7 appointment concierge and automated SMS confirmation funnels.", 1150.0),
    ("SF App Works", "Product Director", "San Francisco", "United States", "US", "sfappworks.com", "contact@sfappworks.com", "Mobile & Web Engineering", "Dedicated mobile app engineering (iOS/Android/Flutter) and full-stack API integration.", 1500.0),
    ("Beverly Hills Dental Lab", "Director", "Los Angeles", "United States", "US", "beverlyhillsdentallab.com", "info@beverlyhillsdentallab.com", "Aesthetic Dentistry", "Exclusive VIP smile assessment funnels and direct digital consultation booking.", 1300.0),

    # Sydney & Melbourne, Australia
    ("Humaan Experience Agency", "Founders & Team", "Perth", "Australia", "AU", "humaan.com", "hello@humaan.com", "Digital Experience Agency", "White-label Next.js frontend development and custom conversational customer support models.", 1400.0),
    ("Blick Creative Melbourne", "Creative Directors", "Melbourne", "Australia", "AU", "blickcreative.com.au", "info@blickcreative.com.au", "Creative Studio", "High-speed portfolio galleries, custom web applications, and client brief intake systems.", 950.0),
    ("Sydney Design Agency", "Studio Head", "Sydney", "Australia", "AU", "sydneydesignagency.com.au", "info@sydneydesignagency.com.au", "Web Design & Branding", "Sub-second React web application engineering and 24/7 AI lead intake models.", 1100.0),
    ("Bondi Dental Clinic", "Practice Manager", "Sydney", "Australia", "AU", "bondidental.com.au", "info@bondidental.com.au", "Cosmetic Dentistry", "24/7 AI Patient Booking Assistant and automatic SMS appointment confirmation.", 1150.0),
    ("Melbourne Dental Studio", "Clinical Lead", "Melbourne", "Australia", "AU", "melbournedentalstudio.com.au", "info@melbournedentalstudio.com.au", "Implant Dentistry", "Online smile makeover assessments and automated appointment booking.", 1200.0),
    ("Collins Dental Image", "Practice Lead", "Melbourne", "Australia", "AU", "collinsdentalimage.com.au", "info@collinsdentalimage.com.au", "Aesthetic Dentistry", "Direct consultation intake, test result delivery, and patient communication CRM.", 1100.0),
    ("Prime Law Group Sydney", "Principal Solicitors", "Sydney", "Australia", "AU", "primelaw.com.au", "info@primelaw.com.au", "Commercial Law Practice", "Encrypted client onboarding portal, confidential intake questionnaires, and retainer booking.", 1450.0),
    ("Solar Choice Australia", "Commercial Sales Lead", "Sydney", "Australia", "AU", "solarchoice.net.au", "sales@solarchoice.net.au", "Commercial Solar", "Instant commercial solar ROI calculator and automated proposal generation bot.", 1350.0),
    ("Energy Matters Australia", "Operations Team", "Melbourne", "Australia", "AU", "energymatters.com.au", "info@energymatters.com.au", "Renewable Energy Systems", "Automated customer qualification and field sales rep lead dispatch engine.", 1250.0),
    ("Crown Sydney Hospitality", "Concierge & VIP Services", "Sydney", "Australia", "AU", "crownsydney.com.au", "reservations@crownsydney.com.au", "Luxury Hospitality & Dining", "0% commission direct table booking funnels, VIP loyalty CRM, and event dining requests.", 1500.0),

    # Toronto & Vancouver, Canada
    ("Massive Media Vancouver", "Agency Principals", "Vancouver", "Canada", "CA", "massivemedia.ca", "hello@massivemedia.ca", "Branding & Web Studio", "High-performance React web application engineering and bespoke AI client intake.", 1400.0),
    ("Say Yeah Product Agency", "Product Strategy Team", "Toronto", "Canada", "CA", "sayyeah.com", "hello@sayyeah.com", "Digital Product Studio", "Dedicated mobile app engineering (iOS/Android/Flutter) and full-stack API integration.", 1350.0),
    ("Yorkville Dental Arts", "Practice Manager", "Toronto", "Canada", "CA", "yorkvilledentalarts.com", "info@yorkvilledentalarts.com", "Cosmetic Dentistry", "24/7 AI Patient Booking Assistant, direct smile consultation funnels, and SMS reminders.", 1150.0),
    ("Bayview Dental Clinic", "Office Coordinator", "Toronto", "Canada", "CA", "bayviewdental.ca", "info@bayviewdental.ca", "General & Cosmetic Dental", "Direct appointment booking intake, test result delivery, and patient communication CRM.", 1100.0),
    ("Vancouver Dental Group", "Clinical Coordinator", "Vancouver", "Canada", "CA", "vancouverdentalgroup.com", "info@vancouverdentalgroup.com", "Cosmetic Dentistry", "Online smile makeover assessments and automated appointment booking.", 1200.0),
    ("Coal Harbour Dental Clinic", "Practice Lead", "Vancouver", "Canada", "CA", "coalharbourdental.com", "info@coalharbourdental.com", "Aesthetic Dentistry", "VIP virtual consultation intake funnels and automated appointment deposit processing.", 1250.0),
    ("Pacific Dental Centre", "Practice Manager", "Vancouver", "Canada", "CA", "pacificdental.ca", "info@pacificdental.ca", "Cosmetic & Restorative", "Direct appointment booking intake, patient communication CRM, and automated reminders.", 1150.0),
    ("Vancouver Solar Power", "Commercial Estimator", "Vancouver", "Canada", "CA", "vancouversolar.ca", "info@vancouversolar.ca", "Solar Energy Solutions", "Instant solar cost estimate engine and automated lead distribution to sales reps.", 1200.0),
    ("Toronto Tech Law Associates", "Managing Partner", "Toronto", "Canada", "CA", "torontotechlaw.com", "info@torontotechlaw.com", "Tech IP & Corporate Law", "Sub-second client onboarding portal, conflict-check intake, and retainer scheduling.", 1400.0),
]


def run_verified_outreach():
    print("=" * 80, flush=True)
    print("🛡️ REAL-TIME DNS MX VERIFICATION & DIRECT-TO-PROSPECT OUTREACH ENGINE", flush=True)
    print(f"📧 Sender Account: {GMAIL_USER} (From != To strictly enforced)", flush=True)
    print("=" * 80, flush=True)

    init_db()
    db = SessionLocal()

    # Step 1: Pre-Flight DNS MX Verification
    print("\n🔍 [STEP 1/3] VERIFYING DOMAINS & MAIL EXCHANGERS (MX)...", flush=True)
    print("-" * 80, flush=True)

    verified_list = []
    for item in TARGET_CANDIDATES:
        biz_name, contact, city, country, country_code, website, target_email, category, hook, val = item
        clean_email = target_email.strip().lower()

        # Strict anti-self check
        if clean_email == GMAIL_USER.lower():
            print(f"  ❌ SKIPPED {biz_name}: Email matches sender ({clean_email})", flush=True)
            continue

        # Live DNS MX check
        val_res = validate(clean_email, check_mx=True)
        if not val_res.valid:
            print(f"  ❌ SKIPPED {biz_name} ({clean_email}): No valid MX record (Reason: {val_res.reason})", flush=True)
            continue

        print(f"  ✔ [MX VALIDATED] {biz_name:<32} | {clean_email:<35} | Score: {val_res.confidence}", flush=True)
        verified_list.append({
            "business": biz_name,
            "contact_name": contact,
            "city": city,
            "country": country,
            "country_code": country_code,
            "website": website,
            "email": clean_email,
            "category": category,
            "hook": hook,
            "deal_value": val,
        })

    print(f"\n✅ Total Verified Live Prospects Ready for Dispatch: {len(verified_list)} / {len(TARGET_CANDIDATES)}", flush=True)

    if not verified_list:
        print("❌ No verified prospects passed MX check.", flush=True)
        return

    # Step 2: Send Deep Consultative Emails Directly to Prospects
    print("\n" + "=" * 80, flush=True)
    print(f"✉️ [STEP 2/3] SENDING {len(verified_list)} CONSULTATIVE PROPOSALS DIRECTLY TO PROSPECTS...", flush=True)
    print("=" * 80, flush=True)

    campaign = db.query(Campaign).filter(Campaign.name == "Default outreach").first()
    dispatched_count = 0
    now = utcnow()

    try:
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=25)
        server.login(GMAIL_USER, GMAIL_PASSWORD)
        print(f"  ✔ Connected & Authenticated to Google SMTP", flush=True)

        for idx, prospect in enumerate(verified_list, 1):
            biz_name = prospect["business"]
            contact = prospect["contact_name"]
            city = prospect["city"]
            category = prospect["category"]
            country = prospect["country"]
            country_code = prospect["country_code"]
            prospect_email = prospect["email"]
            hook = prospect["hook"]

            # Double safety check
            assert prospect_email != GMAIL_USER.lower(), "From and To cannot be the same!"

            subject = f"Strategic Digital & Client Growth Review for {biz_name}"

            plain_body = f"""Dear {contact},

I recently came across {biz_name} while conducting a strategic review of leading {category.lower()} across {city}. Your track record of excellence in {country} is evident, and I wanted to reach out directly with a few observations regarding your client-facing digital systems.

We collaborate with established businesses in {city} to elevate their customer acquisition funnels, automate administrative inquiry intake, and capture high-value inquiries with zero friction.

Based on an initial review of {biz_name}, we identified 3 key growth levers:

1. Frictionless Client Acquisition & Mobile Conversion
Modern prospective clients in {city} evaluate services predominantly on mobile. We engineer intuitive, high-speed interfaces that present your offerings with prestige and convert visitors into booked consultations.

2. 24/7 Intelligent Client Intake & Workflow Automation
{hook} By replacing static contact forms with an intelligent intake workflow, your team captures and pre-qualifies high-intent prospects around the clock.

3. Flawless Brand Positioning & Authority
Reinforce your market standing with a tailored digital presence that reflects {biz_name}'s premium service standards while eliminating third-party platform commissions.

We have already assembled an interactive digital concept and architectural walkthrough prepared specifically for {biz_name}.

Would you or your leadership team be open to a brief 10-minute visual walkthrough this Thursday at 11:00 AM, or sometime next week?

Simply reply directly to this email, and I will be delighted to share the walkthrough with you.

Best regards,

{SENDER_NAME}
Enterprise Web & AI Systems Architecture
Email: {GMAIL_USER}
"""

            styled_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 28px 0; background-color: #f8f7f4; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #1e293b;">
  <table width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color: #f8f7f4;">
    <tr>
      <td align="center" style="padding: 12px 16px;">
        <table width="100%" border="0" cellspacing="0" cellpadding="0" style="max-width: 620px; background-color: #ffffff; border: 1px solid #e7e5e4; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 20px rgba(0,0,0,0.04);">
          <!-- Top Royal Indigo Header Stripe -->
          <tr>
            <td height="4" style="background: linear-gradient(90deg, #2563eb, #4f46e5); font-size: 0; line-height: 0;">&nbsp;</td>
          </tr>
          <!-- Body Content -->
          <tr>
            <td style="padding: 36px 36px 32px 36px;">
              <!-- Header Badges -->
              <div style="margin-bottom: 24px;">
                <span style="display: inline-block; padding: 5px 14px; background-color: #fef3c7; color: #92400e; font-size: 12px; font-weight: 700; border-radius: 9999px; letter-spacing: 0.03em; text-transform: uppercase;">
                  {biz_name}
                </span>
                <span style="display: inline-block; margin-left: 8px; padding: 5px 12px; background-color: #f1f5f9; color: #475569; font-size: 12px; font-weight: 600; border-radius: 9999px;">
                  {city}, {country_code}
                </span>
                <span style="display: inline-block; margin-left: 8px; padding: 5px 12px; background-color: #eff6ff; color: #1e40af; font-size: 12px; font-weight: 600; border-radius: 9999px;">
                  Strategic Review
                </span>
              </div>
              
              <p style="margin: 0 0 18px 0; font-size: 16px; font-weight: 600; color: #0f172a; line-height: 1.5;">
                Dear {contact},
              </p>
              
              <p style="margin: 0 0 18px 0; font-size: 15px; line-height: 1.65; color: #334155;">
                I recently came across <strong>{biz_name}</strong> while conducting a review of leading {category.lower()} across <strong>{city}</strong>. Your track record of excellence in {country} is evident, and I wanted to reach out directly with a few strategic observations regarding your client-facing digital touchpoints.
              </p>

              <p style="margin: 0 0 20px 0; font-size: 15px; line-height: 1.65; color: #334155;">
                We partner with established businesses in {city} to elevate their customer acquisition funnels, automate administrative intake, and capture high-value inquiries with zero friction.
              </p>
              
              <!-- 3 Strategic Value Pillars -->
              <div style="margin: 24px 0; padding: 22px 24px; background-color: #f8f7f4; border-left: 4px solid #2563eb; border-radius: 8px;">
                <div style="font-size: 15px; font-weight: 700; color: #0f172a; margin-bottom: 14px;">
                  📌 Key Strategic Growth Levers for {biz_name}:
                </div>
                
                <div style="margin-bottom: 14px;">
                  <strong style="color: #0f172a; font-size: 14px;">1. Frictionless Client Acquisition &amp; Mobile Conversion</strong>
                  <div style="font-size: 14px; line-height: 1.55; color: #475569; margin-top: 4px;">
                    Modern prospective clients in {city} evaluate services predominantly on mobile. We engineer intuitive, high-speed interfaces that present your offerings with prestige and convert visitors into booked consultations.
                  </div>
                </div>

                <div style="margin-bottom: 14px;">
                  <strong style="color: #0f172a; font-size: 14px;">2. 24/7 Intelligent Client Intake &amp; Workflow Automation</strong>
                  <div style="font-size: 14px; line-height: 1.55; color: #475569; margin-top: 4px;">
                    {hook} By replacing static forms with an intelligent intake workflow, your team captures and pre-qualifies high-intent prospects around the clock.
                  </div>
                </div>

                <div>
                  <strong style="color: #0f172a; font-size: 14px;">3. Flawless Brand Positioning &amp; Authority</strong>
                  <div style="font-size: 14px; line-height: 1.55; color: #475569; margin-top: 4px;">
                    Reinforce your market standing with a tailored digital presence that reflects {biz_name}'s premium service standards while eliminating third-party platform commissions.
                  </div>
                </div>
              </div>

              <p style="margin: 0 0 24px 0; font-size: 15px; line-height: 1.65; color: #334155;">
                We have already assembled an interactive digital concept and architectural walkthrough prepared specifically for <strong>{biz_name}</strong>.
              </p>

              <p style="margin: 0 0 28px 0; font-size: 15px; line-height: 1.65; color: #334155;">
                Would you or your leadership team be open to a brief 10-minute visual walkthrough this Thursday at 11:00 AM, or sometime next week?
              </p>
              
              <!-- Direct Action CTA Button -->
              <table border="0" cellspacing="0" cellpadding="0" style="margin: 28px 0 20px 0;">
                <tr>
                  <td align="center" style="border-radius: 8px; background-color: #0f172a;">
                    <a href="mailto:{GMAIL_USER}?subject=Re:%20Strategic%20Walkthrough%20for%20{biz_name}" target="_blank" style="font-size: 14px; font-weight: 600; color: #ffffff; text-decoration: none; padding: 14px 28px; border-radius: 8px; display: inline-block;">
                      Schedule 10-Minute Walkthrough &rarr;
                    </a>
                  </td>
                </tr>
              </table>

              <!-- Executive Signature Block -->
              <div style="margin-top: 32px; padding-top: 24px; border-top: 1px solid #f1f5f9; font-size: 14px; line-height: 1.55; color: #64748b;">
                Best regards,<br>
                <strong style="color: #0f172a; font-size: 15px;">{SENDER_NAME}</strong><br>
                <span style="font-size: 13px; color: #64748b;">Enterprise Web &amp; AI Systems Architecture</span><br>
                <span style="font-size: 12px; color: #2563eb;">{GMAIL_USER}</span>
              </div>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

            # Build and send email directly to prospect
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"{SENDER_NAME} <{GMAIL_USER}>"
            msg["To"] = prospect_email  # DIRECT TO PROSPECT!
            msg["Reply-To"] = GMAIL_USER
            msg["X-Target-Company"] = biz_name

            msg.attach(MIMEText(plain_body, "plain", "utf-8"))
            msg.attach(MIMEText(styled_html, "html", "utf-8"))

            server.sendmail(GMAIL_USER, [prospect_email], msg.as_string())
            dispatched_count += 1
            print(f"  🚀 [{idx}/{len(verified_list)}] SENT DIRECT TO -> {prospect_email} ({biz_name}, {city})", flush=True)

            # Record in Database
            biz_obj = db.query(Business).filter(Business.name == biz_name).first()
            if not biz_obj:
                biz_obj = Business(
                    source="verified_outreach",
                    source_id=f"verif_out_{idx}_{abs(hash(biz_name))}",
                    dedupe_key=f"verif_out:{idx}:{biz_name.lower()}",
                    name=biz_name,
                    category=category,
                    email=prospect_email,
                    city=city,
                    country_code=country_code,
                )
                db.add(biz_obj)
                db.flush()

            lead_obj = db.query(Lead).filter(Lead.business_id == biz_obj.id).first()
            if not lead_obj:
                lead_obj = Lead(
                    business_id=biz_obj.id,
                    campaign_id=campaign.id if campaign else None,
                    email=prospect_email,
                    contact_name=contact,
                    status=LeadStatus.CONTACTED,
                    score=96.0,
                    approved=True,
                    unsubscribe_token=new_token(32),
                    last_contacted_at=now,
                )
                db.add(lead_obj)
                db.flush()
            else:
                lead_obj.status = LeadStatus.CONTACTED
                lead_obj.last_contacted_at = now

            out_msg = EmailMessage(
                lead_id=lead_obj.id,
                step=0,
                direction="out",
                to_email=prospect_email,
                from_email=GMAIL_USER,
                subject=subject,
                body_text=plain_body,
                body_html=styled_html,
                status=MessageStatus.SENT,
                sent_at=now,
                message_id=f"verif-msg-{lead_obj.id}-{new_token(8)}",
            )
            db.add(out_msg)

            # Record in Deals
            deal_obj = db.query(Deal).filter(Deal.lead_id == lead_obj.id).first()
            if not deal_obj:
                deal_obj = Deal(
                    lead_id=lead_obj.id,
                    business_id=biz_obj.id,
                    title=f"Enterprise Modernization — {biz_name}",
                    company_name=biz_name,
                    contact_name=contact,
                    contact_email=prospect_email,
                    stage=DealStage.CONTACTED,
                    value=prospect["deal_value"],
                    probability=25.0,
                    expected_close_at=now + datetime.timedelta(days=21),
                    notes=f"DNS MX verified prospect in {city}, {country}. Sent consultative pitch.",
                )
                db.add(deal_obj)

            if idx % 5 == 0 or idx == len(verified_list):
                db.commit()

            time.sleep(0.5)

        server.quit()
        db.commit()
        print(f"\n✅ All {dispatched_count} Verified International Emails Successfully Sent Directly to Prospects!", flush=True)

    except Exception as e:
        print(f"❌ Error during outreach dispatch: {e}", flush=True)
        db.rollback()

    # Step 3: Synchronize Master Excel & CSV
    print("\n" + "=" * 80, flush=True)
    print("📊 [STEP 3/3] SYNCHRONIZING MASTER EXCEL & CRM AUDIT TRAIL...", flush=True)
    print("=" * 80, flush=True)

    xlsx_path, csv_path = trigger_master_excel_sync(db)
    print(f"  ✔ Synchronized Master Excel: {xlsx_path} ({Path(xlsx_path).stat().st_size:,} bytes)", flush=True)
    print(f"  ✔ Synchronized Master CSV:   {csv_path} ({Path(csv_path).stat().st_size:,} bytes)", flush=True)

    db.close()


if __name__ == "__main__":
    run_verified_outreach()
