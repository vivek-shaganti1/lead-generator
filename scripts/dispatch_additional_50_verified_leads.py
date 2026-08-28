"""
Additional 50+ High-Value International Web & AI Development Leads.
Performs live DNS MX verification, direct Google SMTP dispatch, and Master Excel update.
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


ADDITIONAL_INTERNATIONAL_LEADS = [
    # US Studios & Specialized Practices (New York, LA, San Francisco, Chicago, Miami, Boston)
    ("Instrument Digital Studio", "Creative Technology Lead", "New York", "United States", "US", "instrument.com", "hello@instrument.com", "Digital Brand Studio", "Full-stack web application engineering and scalable cloud infrastructure.", 1550.0),
    ("Fantasy Interactive NY", "Studio Director", "New York", "United States", "US", "fantasy.co", "contact@fantasy.co", "Digital Product Agency", "Sub-second React/Next.js frontend development and interactive user interfaces.", 1650.0),
    ("Area 17 Digital Studios", "Managing Director", "New York", "United States", "US", "area17.com", "hello@area17.com", "Brand & Systems Engineering", "Turnkey modern web platforms, headless CMS architecture, and performance optimization.", 1600.0),
    ("Stink Studios NY", "Executive Producer", "New York", "United States", "US", "stinkstudios.com", "hello@stinkstudios.com", "Creative Technology & Web", "High-performance digital experiences and interactive client portfolio portals.", 1500.0),
    ("BASIC Agency NY/SF", "Brand Director", "San Francisco", "United States", "US", "basicagency.com", "hello@basicagency.com", "Digital Experience Studio", "Enterprise web portal modernization, custom UI systems, and AI client intake.", 1700.0),
    ("Ueno Digital Studio SF", "Product Lead", "San Francisco", "United States", "US", "ueno.co", "hello@ueno.co", "Digital Product Design", "Dedicated mobile app engineering (iOS/Android/Flutter) and full-stack API systems.", 1600.0),
    ("B-Reel Creative Tech", "Managing Director", "Los Angeles", "United States", "US", "b-reel.com", "hello@b-reel.com", "Creative Production & Web", "Fast sub-second visual media delivery and interactive client project brief intake.", 1450.0),
    ("Hello Design Studio LA", "Creative Lead", "Los Angeles", "United States", "US", "hellodesign.com", "info@hellodesign.com", "Digital Product Studio", "Next.js 15 enterprise web portal modernization and custom automated AI support.", 1500.0),
    ("Teehan+Lax Labs", "Technical Partner", "San Francisco", "United States", "US", "teehanlax.com", "info@teehanlax.com", "Product Engineering", "High-speed React/Node web applications and custom conversational AI assistants.", 1550.0),
    ("Dogstudio Creative Chicago", "Operations Director", "Chicago", "United States", "US", "dogstudio.co", "hello@dogstudio.co", "Interactive Web Studio", "Immersive 3D web interfaces, smooth micro-interactions, and conversion-optimized funnels.", 1400.0),
    ("One Design Company Chicago", "Principal Director", "Chicago", "United States", "US", "onedesigncompany.com", "hello@onedesigncompany.com", "Digital Experience Design", "Scalable cloud architecture and 24/7 AI lead qualification workflows.", 1450.0),
    ("Viget Labs Boston", "Director of Engineering", "Boston", "United States", "US", "viget.com", "hello@viget.com", "Digital Product Studio", "Custom SaaS MVP development, cloud backends, and responsive client web portals.", 1550.0),
    ("Thoughtbot Boston", "Product Strategy Lead", "Boston", "United States", "US", "thoughtbot.com", "hello@thoughtbot.com", "Web & Mobile Development", "Full-stack web application development in React, Next.js, and automated AI tools.", 1750.0),
    ("Rokkan Digital Agency", "Client Services Lead", "New York", "United States", "US", "rokkan.com", "info@rokkan.com", "Digital Strategy & Web", "High-conversion digital brand experiences and sub-second React frontend systems.", 1450.0),
    ("Domani Studios New York", "Technical Director", "New York", "United States", "US", "domanistudios.com", "info@domanistudios.com", "Digital Craft Studio", "Modernization of legacy systems into high-performance Next.js web applications.", 1400.0),

    # UK Digital Agencies & Specialized Services (London, Oxford, Manchester)
    ("Potato Digital Studio London", "Technical Director", "London", "United Kingdom", "GB", "p.ota.to", "hello@p.ota.to", "Digital Product Studio", "Enterprise web application development and AI conversational workflow integration.", 1600.0),
    ("Made by Many London", "Partner in Engineering", "London", "United Kingdom", "GB", "madebymany.com", "hello@madebymany.com", "Product Innovation Studio", "Rapid MVP engineering, high-performance web architecture, and cloud backends.", 1550.0),
    ("Red Badger London", "Delivery Director", "London", "United Kingdom", "GB", "red-badger.com", "hello@red-badger.com", "Digital Transformation", "Next.js enterprise web modernization and zero-downtime scalable cloud deployments.", 1750.0),
    ("Clearleft Digital Agency", "Experience Director", "London", "United Kingdom", "GB", "clearleft.com", "hello@clearleft.com", "UX & Web Architecture", "High-speed responsive web platforms and conversion-focused customer journeys.", 1450.0),
    ("Deeson Digital London", "Technical Director", "London", "United Kingdom", "GB", "deeson.co.uk", "hello@deeson.co.uk", "Open-Source Web Systems", "Modern headless web architectures and automated client onboarding systems.", 1400.0),
    ("Ribot Studio UK", "Design Lead", "London", "United Kingdom", "GB", "ribot.co.uk", "hello@ribot.co.uk", "Mobile & Web Experience", "Dedicated mobile app engineering (iOS/Android/Flutter) and full-stack API systems.", 1350.0),
    ("Modern Human Studio", "Director of Research", "London", "United Kingdom", "GB", "modernhuman.co.uk", "hello@modernhuman.co.uk", "Digital Innovation Studio", "Interactive research portals and high-speed web application frontends.", 1300.0),
    ("Novoda Mobile Engineering", "Engineering Lead", "London", "United Kingdom", "GB", "novoda.com", "hello@novoda.com", "Mobile & Cloud Engineering", "Turnkey mobile apps and scalable backend cloud infrastructure.", 1500.0),
    ("Beyond Agency London", "Managing Director", "London", "United Kingdom", "GB", "bynd.com", "hello@bynd.com", "Design & Tech Agency", "Full-stack web application engineering and 24/7 AI client intake models.", 1650.0),
    ("Ustwo Studios London", "Studio Principal", "London", "United Kingdom", "GB", "ustwo.com", "hello@ustwo.com", "Digital Product Studio", "Bespoke digital product architecture and sub-second React client interfaces.", 1800.0),

    # Australia Digital & High-Ticket Specialists (Sydney, Melbourne, Brisbane)
    ("Never Sit Still Studio", "Creative Director", "Sydney", "Australia", "AU", "neversitstill.com.au", "hello@neversitstill.com.au", "Animation & Web Media", "Ultra-fast media streaming galleries and interactive client revision portals.", 1350.0),
    ("Mentally Friendly Sydney", "Strategy Director", "Sydney", "Australia", "AU", "mentallyfriendly.com", "hello@mentallyfriendly.com", "Digital Product Studio", "High-performance React application architecture and 24/7 AI client intake models.", 1550.0),
    ("Nightjar Studio Sydney", "Design & Tech Lead", "Sydney", "Australia", "AU", "nightjar.co", "hello@nightjar.co", "Experience Agency", "Custom web applications, client onboarding portals, and automated workflow systems.", 1600.0),
    ("Frank Digital Sydney", "Head of Digital", "Sydney", "Australia", "AU", "frankdigital.com.au", "hello@frankdigital.com.au", "Digital Transformation", "Next.js 15 enterprise web portal modernization and custom automated AI assistants.", 1500.0),
    ("Luminary Digital Melbourne", "Technical Director", "Melbourne", "Australia", "AU", "luminary.com", "hello@luminary.com", "Digital Agency & Web", "Enterprise CMS modernization, sub-second load times, and custom web applications.", 1650.0),
    ("Isobar Australia", "Solutions Lead", "Melbourne", "Australia", "AU", "isobar.com", "hello@isobar.com", "Digital Experience Agency", "Full-stack web application development and AI customer support assistants.", 1750.0),
    ("Evolution7 Melbourne", "Agency Principal", "Melbourne", "Australia", "AU", "evolution7.com.au", "hello@evolution7.com.au", "Digital Studio & UX", "High-speed portfolio galleries, custom web applications, and client brief intake systems.", 1350.0),
    ("Reactive Media Melbourne", "Managing Partner", "Melbourne", "Australia", "AU", "reactive.com", "hello@reactive.com", "Digital Product Studio", "Dedicated mobile app engineering (iOS/Android/Flutter) and cloud systems.", 1450.0),
    ("Liquice Digital Brisbane", "Studio Head", "Brisbane", "Australia", "AU", "liquidinteractive.com.au", "hello@liquidinteractive.com.au", "Interactive Web Agency", "Sub-second React web application engineering and 24/7 AI lead intake models.", 1400.0),
    ("Zeroseven Digital Brisbane", "Technical Lead", "Brisbane", "Australia", "AU", "zeroseven.com.au", "hello@zeroseven.com.au", "Web & Software Studio", "Custom SaaS MVP development, API integrations, and modern full-stack web applications.", 1450.0),

    # Canada Studios & Medical/Legal Practices (Toronto, Vancouver, Montreal)
    ("Critical Mass Calgary/Toronto", "Technical Lead", "Toronto", "Canada", "CA", "criticalmass.com", "hello@criticalmass.com", "Digital Experience Agency", "Enterprise web portal modernization and automated workflow integration.", 1750.0),
    ("Teehan+Lax Toronto", "Product Lead", "Toronto", "Canada", "CA", "teehanlax.com", "hello@teehanlax.com", "Digital Product Agency", "Sub-second React web applications and 24/7 AI lead intake models.", 1550.0),
    ("Havas CX Canada", "Digital Practice Lead", "Toronto", "Canada", "CA", "havas.com", "contact@havas.com", "Digital Customer Experience", "Modernization of legacy client portals into fast Next.js responsive web platforms.", 1650.0),
    ("Plastic Mobile Toronto", "VP of Engineering", "Toronto", "Canada", "CA", "plasticmobile.com", "hello@plasticmobile.com", "Mobile & Web Innovation", "Dedicated mobile app engineering (iOS/Android/Flutter) and full-stack API integration.", 1500.0),
    ("Cossette Digital Canada", "Technical Director", "Montreal", "Canada", "CA", "cossette.com", "hello@cossette.com", "Digital Communications & Web", "Bilingual French/English high-speed React web portal modernization.", 1600.0),
    ("Sid Lee Digital Montreal", "Digital Director", "Montreal", "Canada", "CA", "sidlee.com", "hello@sidlee.com", "Creative Technology Studio", "Turnkey modern web platforms, headless CMS architecture, and performance optimization.", 1700.0),
    ("Engine Digital Vancouver", "Partner & Tech Lead", "Vancouver", "Canada", "CA", "enginedigital.com", "hello@enginedigital.com", "Digital Product Studio", "High-performance React web application engineering and bespoke AI client intake.", 1600.0),
    ("Drive Digital Vancouver", "Head of Development", "Vancouver", "Canada", "CA", "drivedigital.ca", "hello@drivedigital.ca", "Web & E-Commerce Studio", "Custom e-commerce platforms and automated client onboarding systems.", 1450.0),
    ("SplitMango Vancouver", "Studio Manager", "Vancouver", "Canada", "CA", "splitmango.com", "hello@splitmango.com", "Web Development & Design", "High-speed portfolio showcases and automated client brief intake funnels.", 1300.0),
    ("Forge and Spark Media", "Managing Director", "Vancouver", "Canada", "CA", "forgeandspark.com", "hello@forgeandspark.com", "Content & Digital Agency", "Conversion-focused web portals and automated email nurture systems.", 1250.0),

    # New Zealand & Ireland
    ("Springload Web Wellington", "Technical Director", "Wellington", "New Zealand", "NZ", "springload.co.nz", "hello@springload.co.nz", "Digital Agency & Web", "Accessible, high-performance web platforms and bespoke AI workflow automations.", 1450.0),
    ("Resn Digital Auckland", "Creative Technologist", "Auckland", "New Zealand", "NZ", "resn.co.nz", "hello@resn.co.nz", "Creative Technology Lab", "Immersive interactive web experiences and sub-second React frontend systems.", 1650.0),
    ("DNA Digital Design NZ", "Strategy Director", "Auckland", "New Zealand", "NZ", "dna.co.nz", "hello@dna.co.nz", "Digital Experience Design", "Scalable cloud architecture and 24/7 AI lead qualification workflows.", 1500.0),
    ("Glider Digital Dublin", "Technical Partner", "Dublin", "Ireland", "IE", "glider.ie", "hello@glider.ie", "Digital Product Studio", "White-label Next.js software engineering and custom AI workflow automation.", 1400.0),
    ("Arekibo Digital Dublin", "Managing Director", "Dublin", "Ireland", "IE", "arekibo.com", "hello@arekibo.com", "Digital Transformation", "High-performance enterprise web portal modernization and client onboarding funnels.", 1550.0),
]


def run_additional_dispatch():
    print("=" * 80, flush=True)
    print("🚀 DISPATCHING ADDITIONAL 50+ VERIFIED INTERNATIONAL WEB LEADS", flush=True)
    print("=" * 80, flush=True)

    init_db()
    db = SessionLocal()

    sent_emails_in_db = {m.to_email.lower().strip() for m in db.query(EmailMessage).all() if m.to_email}
    verified_queue = []
    seen_in_batch = set()

    for item in ADDITIONAL_INTERNATIONAL_LEADS:
        biz_name, contact, city, country, country_code, website, target_email, category, hook, val = item
        clean_email = target_email.strip().lower()

        if clean_email == GMAIL_USER.lower() or clean_email in seen_in_batch or clean_email in sent_emails_in_db:
            continue

        val_res = validate(clean_email, check_mx=True)
        if not val_res.valid:
            continue

        seen_in_batch.add(clean_email)
        verified_queue.append({
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
        print(f"  ✔ [MX VALIDATED] {biz_name:<34} | {clean_email:<36} | {city}, {country}", flush=True)

    print(f"\n✅ Total Additional Verified Prospects: {len(verified_queue)}", flush=True)

    campaign = db.query(Campaign).filter(Campaign.name == "Default outreach").first()
    dispatched_count = 0
    now = utcnow()

    try:
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=25)
        server.login(GMAIL_USER, GMAIL_PASSWORD)

        for idx, prospect in enumerate(verified_queue, 1):
            biz_name = prospect["business"]
            contact = prospect["contact_name"]
            city = prospect["city"]
            category = prospect["category"]
            country = prospect["country"]
            country_code = prospect["country_code"]
            prospect_email = prospect["email"]
            hook = prospect["hook"]

            assert prospect_email != GMAIL_USER.lower(), "From and To cannot be the same!"

            subject = f"Strategic Digital & Client Growth Review for {biz_name}"

            plain_body = f"""Dear {contact},

I recently came across {biz_name} while conducting a strategic review of leading {category.lower()} across {city}. Your track record of excellence in {country} is evident, and I wanted to reach out directly with a few strategic observations regarding your client-facing digital systems.

We partner with established businesses in {city} to elevate their customer acquisition funnels, automate administrative inquiry intake, and capture high-value inquiries with zero friction.

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
          <tr>
            <td height="4" style="background: linear-gradient(90deg, #2563eb, #4f46e5); font-size: 0; line-height: 0;">&nbsp;</td>
          </tr>
          <tr>
            <td style="padding: 36px 36px 32px 36px;">
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
              
              <table border="0" cellspacing="0" cellpadding="0" style="margin: 28px 0 20px 0;">
                <tr>
                  <td align="center" style="border-radius: 8px; background-color: #0f172a;">
                    <a href="mailto:{GMAIL_USER}?subject=Re:%20Strategic%20Walkthrough%20for%20{biz_name}" target="_blank" style="font-size: 14px; font-weight: 600; color: #ffffff; text-decoration: none; padding: 14px 28px; border-radius: 8px; display: inline-block;">
                      Schedule 10-Minute Walkthrough &rarr;
                    </a>
                  </td>
                </tr>
              </table>

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

            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"{SENDER_NAME} <{GMAIL_USER}>"
            msg["To"] = prospect_email  # DIRECT TO PROSPECT
            msg["Reply-To"] = GMAIL_USER
            msg["X-Target-Company"] = biz_name

            msg.attach(MIMEText(plain_body, "plain", "utf-8"))
            msg.attach(MIMEText(styled_html, "html", "utf-8"))

            server.sendmail(GMAIL_USER, [prospect_email], msg.as_string())
            dispatched_count += 1
            print(f"  🚀 [{idx}/{len(verified_queue)}] SENT DIRECT TO -> {prospect_email} ({biz_name})", flush=True)

            biz_obj = db.query(Business).filter(Business.name == biz_name).first()
            if not biz_obj:
                biz_obj = Business(
                    source="additional_50_batch",
                    source_id=f"add50_{idx}_{abs(hash(biz_name))}",
                    dedupe_key=f"add50:{idx}:{biz_name.lower()}",
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
                message_id=f"add50-msg-{lead_obj.id}-{new_token(8)}",
            )
            db.add(out_msg)

            deal_obj = db.query(Deal).filter(Deal.lead_id == lead_obj.id).first()
            if not deal_obj:
                deal_obj = Deal(
                    lead_id=lead_obj.id,
                    business_id=biz_obj.id,
                    title=f"Web & AI Architecture — {biz_name}",
                    company_name=biz_name,
                    contact_name=contact,
                    contact_email=prospect_email,
                    stage=DealStage.CONTACTED,
                    value=prospect["deal_value"],
                    probability=25.0,
                    expected_close_at=now + datetime.timedelta(days=21),
                    notes=f"DNS MX verified prospect in {city}, {country}.",
                )
                db.add(deal_obj)

            if idx % 10 == 0 or idx == len(verified_queue):
                db.commit()

            time.sleep(0.4)

        server.quit()
        db.commit()
        print(f"\n✅ All {dispatched_count} Additional Verified Emails Sent Directly to Prospects!", flush=True)

    except Exception as e:
        print(f"❌ Error: {e}", flush=True)
        db.rollback()

    # Step 3: Synchronize Master Excel & CSV
    xlsx_path, csv_path = trigger_master_excel_sync(db)
    print(f"  ✔ Synchronized Master Excel: {xlsx_path} ({Path(xlsx_path).stat().st_size:,} bytes)", flush=True)
    print(f"  ✔ Synchronized Master CSV:   {csv_path} ({Path(csv_path).stat().st_size:,} bytes)", flush=True)

    db.close()


if __name__ == "__main__":
    run_additional_dispatch()
