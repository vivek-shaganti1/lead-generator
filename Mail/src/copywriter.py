"""
Production International B2B Copywriting & Personalization Engine.
Generates tailored, high-converting outreach sequences for global businesses (US, UK, Canada, Australia).
Focuses on Web Development, Mobile Apps, AI Product Engineering, and Automated Workflows.
"""
from typing import Dict, Any

class SalesCopywriter:
    @staticmethod
    def _first_name(owner: str) -> str:
        if not owner or owner in ["Business Owner", "Team", "None", "Not Found"]:
            return "there"
        parts = owner.split("&")[0].split("+")[0].strip().split()
        return parts[0] if parts else "there"

    @classmethod
    def generate_email_sequence(cls, lead: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
        first_name = cls._first_name(lead.get("owner", ""))
        business = lead.get("business", "your company")
        city = lead.get("city", "your city")
        country = lead.get("country", "your country")
        campaign = lead.get("campaign", "")
        industry = lead.get("industry", "Technology & Services")
        pitch_hook = lead.get("pitch_hook", "")
        followers = lead.get("followers", 0)
        platform = lead.get("platform", "online")

        # --- 0. GYMS & FITNESS CENTERS ---
        if "Gym" in campaign:
            subject_1 = f"Quick question for {business} (Mobile Booking & Local Web Presence in {city})"
            body_1 = (
                f"Hi {first_name},\n\n"
                f"Came across {business} in {city}—huge fan of the facility and community you've built!\n\n"
                f"We help high-performing gyms and fitness studios capture and convert more walk-ins and local searchers with modern mobile booking funnels:\n\n"
                f"⚡ Platform Upgrades Included for {business}:\n"
                f"• Sub-Second Mobile Redesign: Instant free trial class bookings directly from Instagram and Google\n"
                f"• AI 24/7 Member FAQ & Lead Qualifier: Books trials and answers class queries automatically\n"
                f"• Direct Membership Signup: Zero 3rd-party cut\n\n"
                f"Would you like to see a quick 2-minute mockup we designed for {business}?\n\n"
                f"👉 Please reply back to this email and our team will get in touch with you right away!\n\n"
                f"Best regards,\n\n"
                f"KSV Web & AI Solutions Team\n"
                f"Email: ksvdevlopers@gmail.com"
            )
            subject_2 = f"Re: Quick question for {business} (Mobile Booking & Local Web Presence in {city})"
            body_2 = (
                f"Hi {first_name},\n\n"
                f"Quick follow-up regarding {business} in {city}. A dedicated mobile site turns local searchers into booked trial sessions.\n\n"
                f"👉 Please reply back to this email to see the concept!\n\n"
                f"Best,\nKSV Web & AI Solutions Team"
            )

        # --- 0B. SALONS & BARBERSHOPS ---
        elif "Salon" in campaign:
            reviews_cnt = lead.get("reviews", 0)
            subject_1 = f"Commission-free direct booking for {business}"
            body_1 = (
                f"Hi {first_name},\n\n"
                f"Congratulations on {business}'s stellar reputation—seeing {reviews_cnt} reviews shows your clients love you!\n\n"
                f"We build custom mobile booking portals for premier barbershops and salons to eliminate third-party booking commissions (like Booksy) and capture appointments directly.\n\n"
                f"⚡ What's Included for {business}:\n"
                f"• Fast Direct Mobile Booking: 2-click client scheduling with automated SMS/email reminders\n"
                f"• AI Appointment Concierge: Books appointments 24/7 directly on WhatsApp & Web\n"
                f"• 100% Commission-Free: Keep 100% of your service revenue\n\n"
                f"Would you like to see a free visual mockup tailored for {business}?\n\n"
                f"👉 Simply reply back to this email and we'll send it over!\n\n"
                f"Best regards,\n\n"
                f"KSV Web & AI Solutions Team\n"
                f"Email: ksvdevlopers@gmail.com"
            )
            subject_2 = f"Re: Commission-free direct booking for {business}"
            body_2 = (
                f"Hi {first_name},\n\n"
                f"Quick follow-up on direct booking for {business}. Stop giving away commissions on every haircut and appointment.\n\n"
                f"👉 Reply back and we'll share the live demo!\n\n"
                f"Best,\nKSV Web & AI Solutions Team"
            )

        # --- 1. GLOBAL TECH AGENCIES & CONSULTANCIES ---
        if "Tech-Agencies" in campaign or "Technology" in industry or "Software" in industry or "Cloud" in industry:
            subject_1 = f"Strategic Engineering & AI Development Capacity for {business}"
            body_1 = (
                f"Hi {first_name},\n\n"
                f"I recently came across {business} while reviewing leading technology and digital firms in {city}. Your track record for delivering quality solutions across {country} stands out, and I wanted to reach out with a strategic proposition.\n\n"
                f"We collaborate with ambitious agency founders and technology leaders to expand their development bandwidth and product delivery capacity without the burden of heavy local payroll overhead.\n\n"
                f"Here is how we typically help teams like {business} scale:\n\n"
                f"1. On-Demand Full-Stack & Mobile Engineering\n"
                f"We provide dedicated, production-ready engineering support across modern web platforms (React, Next.js, TypeScript, Node.js) and native mobile apps (iOS, Android, Flutter) to help you deliver client projects on schedule.\n\n"
                f"2. Custom AI Workflows & Intelligent Client Intake\n"
                f"We build bespoke AI automation modules, intelligent inquiry qualification bots, and internal workflow tools that streamline client onboarding and reduce manual administrative overhead.\n\n"
                f"3. High-Performance Architecture & Optimization\n"
                f"Every system we engineer is built for extreme speed, flawless security, and effortless scalability—ensuring your clients experience sub-second responsiveness and zero technical debt.\n\n"
                f"We have put together an interactive architectural preview and portfolio concept specifically tailored for {business}.\n\n"
                f"Would you or your leadership team be open to a brief 10-minute visual walkthrough this Thursday at 11:00 AM, or sometime next week?\n\n"
                f"Simply reply to this email, and I will gladly share the preview.\n\n"
                f"Best regards,\n\n"
                f"KSV Web & AI Solutions Team\n"
                f"Enterprise Web & AI Architecture\n"
                f"Email: ksvdevlopers@gmail.com"
            )
            subject_2 = f"Re: Strategic Engineering & AI Development Capacity for {business}"
            body_2 = (
                f"Hi {first_name},\n\n"
                f"I wanted to follow up briefly regarding my previous note about expanding {business}'s development capacity.\n\n"
                f"We would love to share the brief interactive concept we prepared for your team—showing how we can support your upcoming sprint deliverables and AI product initiatives.\n\n"
                f"If you have 5 minutes this week, let me know what day works best, or feel free to reply with a quick 'send it over'.\n\n"
                f"Best regards,\nKSV Web & AI Solutions Team"
            )
                f"• Flexible White-Label Delivery: Seamless extension to your in-house team under your own brand\n\n"
                f"🎁 Special Introductory Rate: Because we are expanding our international agency network in {country}, we're offering our first joint sprint at a heavily discounted, minimal flat rate.\n\n"
                f"Would you be open to a quick 2-minute look at our portfolio and live code architecture?\n\n"
                f"👉 Please simply reply back to this email, and our team will get in touch with you right away with our demo portfolio!\n\n"
                f"Best regards,\n\n"
                f"KSV Web & AI Solutions Team\n"
                f"Email: ksvdevlopers@gmail.com"
            )

            subject_2 = f"Re: Quick question for {business} (AI & Full-Stack Development Capacity)"
            body_2 = (
                f"Hi {first_name},\n\n"
                f"Quick follow-up for {business}.\n\n"
                f"Whether you need an extra team to build client web/app projects or want to embed 24/7 AI agents into your product suite, we can deliver complete turn-key builds at very competitive international rates.\n\n"
                f"👉 Please reply back to this email, and our team will get in touch with you immediately!\n\n"
                f"Best,\n"
                f"KSV Web & AI Solutions Team"
            )

        # --- 2. GLOBAL HEALTHCARE & DENTAL CLINICS (London, New York, Sydney) ---
        elif "Healthcare-Dental" in campaign:
            subject_1 = f"Quick question for {business} (AI Patient Booking & Web Upgrade in {city})"
            body_1 = (
                f"Hi {first_name},\n\n"
                f"Came across {business} in {city}—congratulations on your stellar reputation in {industry}!\n\n"
                f"We build ultra-modern, high-converting medical & dental web applications supercharged with 24/7 AI models to help practices capture and convert more high-value patients:\n\n"
                f"⚡ What's Included for {business}:\n"
                f"• Custom Patient Web App & Booking Hub: Instant 2-click appointment scheduling with insurance verification intake\n"
                f"• 24/7 AI Patient Concierge: Greets web visitors, answers treatment FAQs, and books consultations 24 hours a day\n"
                f"• AI Re-Care & Follow-Up System: Automatically re-engages overdue patients via SMS/Email to fill cancellations and empty slots\n"
                f"• Direct Payments & Zero Platform Fees: Direct integration without costly monthly third-party software commissions\n\n"
                f"🎁 Special International Partner Discount: We are offering this complete custom web & AI package at an exclusive, minimal flat rate for premier {city} practices.\n\n"
                f"Would you like to see a free 2-minute visual layout we prepared for {business}?\n\n"
                f"👉 Please simply reply back to this email, and our team will get in touch with you immediately with your preview!\n\n"
                f"Best regards,\n\n"
                f"KSV Web & AI Solutions Team\n"
                f"Email: ksvdevlopers@gmail.com"
            )

            subject_2 = f"Re: Quick question for {business} (AI Patient Booking & Web Upgrade in {city})"
            body_2 = (
                f"Hi {first_name},\n\n"
                f"Quick follow-up regarding {business}.\n\n"
                f"Having an autonomous 24/7 AI Concierge on your site captures high-intent patients searching for care outside clinic hours and books them straight into your calendar.\n\n"
                f"👉 Please reply back to this email, and our team will get in touch with you right away with the live concept!\n\n"
                f"Best,\n"
                f"KSV Web & AI Solutions Team"
            )

        # --- 3. GLOBAL REAL ESTATE & LEGAL FIRMS (London, Toronto) ---
        elif "RealEstate-Legal" in campaign:
            subject_1 = f"Digital Platform & AI Intake System for {business} ({city})"
            body_1 = (
                f"Hi {first_name},\n\n"
                f"Came across {business} in {city}—exceptional work in {industry} across {country}!\n\n"
                f"We engineer bespoke digital platforms and high-converting client intake applications powered by AI models designed specifically for high-value client acquisition:\n\n"
                f"⚡ Platform Features for {business}:\n"
                f"• Luxury Web Application: Sub-second load times, responsive showcase layouts, and secure client portal\n"
                f"• 24/7 AI Case & Lead Qualification: Instantly screens prospective client inquiries, gathers initial requirements, and qualifies high-value opportunities\n"
                f"• Automated Consultation Scheduler: Direct calendar sync with conflict resolution and automated reminders\n"
                f"• High-Trust Security: Enterprise SSL, compliant data handling, and zero third-party platform cuts\n\n"
                f"🎁 Exclusive International Introductory Rate: We are offering full platform setup and AI deployment at a minimal, budget-friendly flat fee for top {city} firms.\n\n"
                f"Would you be open to reviewing a free 2-minute digital prototype tailored for {business}?\n\n"
                f"👉 Please simply reply back to this email, and our team will get in touch with you immediately with the prototype link!\n\n"
                f"Best regards,\n\n"
                f"KSV Web & AI Solutions Team\n"
                f"Email: ksvdevlopers@gmail.com"
            )

            subject_2 = f"Re: Digital Platform & AI Intake System for {business} ({city})"
            body_2 = (
                f"Hi {first_name},\n\n"
                f"Quick follow-up for {business}.\n\n"
                f"Our AI qualification intake ensures that your team only spends consultation hours with qualified, high-ticket clients.\n\n"
                f"👉 Please reply back to this email, and our team will get in touch with you right away!\n\n"
                f"Best,\n"
                f"KSV Web & AI Solutions Team"
            )

        # --- 4. GLOBAL FLAGSHIP BRANDS & E-COMMERCE ---
        else:
            defect_hook = pitch_hook if pitch_hook else f"Modernizing the web platform and conversion funnel for {business}."
            subject_1 = f"Technical Audit & AI Upgrade for {business}"
            body_1 = (
                f"Hi {first_name},\n\n"
                f"Huge fan of {business} and your audience across {platform}!\n\n"
                f"While reviewing your online presence, our technical team ran an audit of your current platform and identified key growth opportunities:\n"
                f"• {defect_hook}\n"
                f"• Mobile conversion bottlenecks causing lost orders among smartphone visitors\n\n"
                f"We engineer high-performance modern web platforms supercharged with custom AI models to maximize your revenue:\n\n"
                f"⚡ Platform Upgrades Included for {business}:\n"
                f"• Sub-Second Mobile Redesign: 100/100 Core Web Vitals speed score with zero friction\n"
                f"• AI 24/7 Lead & Quote Qualifier: Instantly collects project/order specifications and generates preliminary estimates\n"
                f"• AI Customer FAQ Engine: Resolves customer inquiries 24/7 automatically without tying up your staff\n"
                f"• High-Converting Checkout: Streamlined purchasing experience designed to maximize average order value\n\n"
                f"🎁 Exclusive Promotional Discount: Because of your brand visibility, we are offering this complete upgrade at a minimal promotional rate to feature as our premier industry case study.\n\n"
                f"Would you like to review the full technical audit and visual mockup we built for {business}?\n\n"
                f"👉 Please simply reply back to this email, and our team will get in touch with you immediately to walk you through it!\n\n"
                f"Best regards,\n\n"
                f"KSV Web & AI Solutions Team\n"
                f"Email: ksvdevlopers@gmail.com"
            )

            subject_2 = f"Re: Technical Audit & AI Upgrade for {business}"
            body_2 = (
                f"Hi {first_name},\n\n"
                f"Quick follow-up on the audit notes for {business}.\n\n"
                f"Fixing mobile friction and adding an automated AI quote intake will immediately capture thousands in lost orders each month.\n\n"
                f"👉 Please reply back to this email, and our team will get in touch with you right away with the complete teardown!\n\n"
                f"Best,\n"
                f"KSV Web & AI Solutions Team"
            )

        return {
            "initial_pitch": {
                "step_name": "Initial Pitch (Global Web & AI)",
                "subject": subject_1,
                "body": body_1,
                "html": cls.build_styled_html(subject_1, body_1, business, city, first_name),
            },
            "followup_1": {
                "step_name": "Follow-Up #1 (+3 Days)",
                "subject": subject_2,
                "body": body_2,
                "html": cls.build_styled_html(subject_2, body_2, business, city, first_name),
            },
            "followup_2": {
                "step_name": "Follow-Up #2 (+7 Days)",
                "subject": f"Design prototype for {business}",
                "body": f"Hi {first_name},\n\nWanted to check in and see if you had a chance to look over the AI web prototype for {business}.\n\n👉 Please reply back with 'Send' and our team will immediately email over your private demo link!\n\nBest,\nKSV Web & AI Solutions Team",
                "html": cls.build_styled_html(f"Design prototype for {business}", f"Hi {first_name},\n\nWanted to check in and see if you had a chance to look over the AI web prototype for {business}.\n\n👉 Please reply back with 'Send' and our team will immediately email over your private demo link!\n\nBest,\nKSV Web & AI Solutions Team", business, city, first_name),
            },
            "followup_final": {
                "step_name": "Final Follow-Up (+14 Days)",
                "subject": f"Closing the loop – {business}",
                "body": f"Hi {first_name},\n\nI will close your file for now so I don't crowd your inbox. If you ever want to launch a modern AI-powered platform for {business} at our minimal partner rate, feel free to reply back anytime!\n\nBest regards,\nKSV Web & AI Solutions Team",
                "html": cls.build_styled_html(f"Closing the loop – {business}", f"Hi {first_name},\n\nI will close your file for now so I don't crowd your inbox. If you ever want to launch a modern AI-powered platform for {business} at our minimal partner rate, feel free to reply back anytime!\n\nBest regards,\nKSV Web & AI Solutions Team", business, city, first_name),
            }
        }

    @staticmethod
    def build_styled_html(subject: str, body_text: str, business: str, city: str, first_name: str) -> str:
        import html, re

        escaped_biz = html.escape(business)
        escaped_text = html.escape(body_text)

        # Highlight business name with soft amber badge
        if business:
            escaped_text = escaped_text.replace(
                escaped_biz,
                f'<span style="background-color: #fef3c7; color: #92400e; padding: 2px 6px; border-radius: 4px; font-weight: 600; border: 1px solid #fde68a;">{escaped_biz}</span>'
            )

        paragraphs = [p.strip() for p in escaped_text.split("\n\n") if p.strip()]
        rendered_paragraphs = []

        for p in paragraphs:
            if "•" in p or "⚡" in p or "👉" in p:
                lines = p.split("\n")
                bullet_html = ""
                for line in lines:
                    line_str = line.strip()
                    if not line_str:
                        continue
                    if line_str.startswith("•") or line_str.startswith("⚡") or line_str.startswith("👉"):
                        bullet_html += f'<li style="margin-bottom: 8px; color: #334155; font-size: 14.5px; line-height: 1.55;">{line_str}</li>'
                    else:
                        bullet_html += f'<div style="font-weight: 700; color: #0f172a; margin-bottom: 8px; font-size: 14.5px;">{line_str}</div>'
                
                rendered_paragraphs.append(
                    f'<div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-left: 4px solid #2563eb; border-radius: 8px; padding: 16px 20px; margin: 18px 0;">'
                    f'<ul style="margin: 0; padding-left: 18px; list-style-type: none;">{bullet_html}</ul>'
                    f'</div>'
                )
            elif p.startswith("Best") or p.startswith("KSV"):
                continue
            else:
                rendered_paragraphs.append(
                    f'<p style="margin: 0 0 16px 0; line-height: 1.7; color: #334155; font-size: 15px;">{p.replace(chr(10), "<br>")}</p>'
                )

        content_body = "".join(rendered_paragraphs)

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(subject)}</title>
</head>
<body style="margin:0; padding:0; background-color:#f8f7f4; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
  <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color:#f8f7f4; padding: 32px 14px;">
    <tr>
      <td align="center">
        <!-- Main Email Card Container -->
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 600px; background-color: #ffffff; border-radius: 12px; border: 1px solid #e7e5e4; overflow: hidden; box-shadow: 0 4px 20px rgba(0,0,0,0.05);">
          
          <!-- Top Accent Stripe (Trustworthy Royal Indigo / Blue) -->
          <tr>
            <td height="4" style="background: linear-gradient(90deg, #2563eb 0%, #4f46e5 100%); line-height: 4px; font-size: 1px;">&nbsp;</td>
          </tr>

          <!-- Brand Header / Badge Bar -->
          <tr>
            <td style="padding: 22px 28px 18px 28px; border-bottom: 1px solid #f1f5f9; background-color: #ffffff;">
              <table role="presentation" width="100%" border="0" cellpadding="0" cellspacing="0">
                <tr>
                  <td>
                    <span style="font-size: 16px; font-weight: 700; color: #0f172a; letter-spacing: -0.2px;">
                      KSV Web &amp; AI Solutions
                    </span>
                  </td>
                  <td align="right">
                    <span style="display: inline-block; padding: 4px 10px; background-color: #eff6ff; border: 1px solid #dbeafe; border-radius: 20px; font-size: 11px; font-weight: 600; color: #1e40af; letter-spacing: 0.5px; text-transform: uppercase;">
                      ⚡ Technical Audit &amp; Proposal
                    </span>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Main Email Content Area -->
          <tr>
            <td style="padding: 28px 28px 24px 28px; background-color: #ffffff;">
              {content_body}

              <!-- Direct CTA Action Button -->
              <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="margin: 26px 0 18px 0;">
                <tr>
                  <td align="center">
                    <a href="mailto:ksvdevlopers@gmail.com?subject=Re:%20Mockup%20Preview%20for%20{html.escape(business)}" 
                       style="display: inline-block; padding: 13px 32px; background-color: #0f172a; color: #ffffff; text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 14px; letter-spacing: 0.1px; box-shadow: 0 4px 12px rgba(15, 23, 42, 0.18);">
                      👉 Reply to Preview Your Custom Mockup
                    </a>
                  </td>
                </tr>
              </table>

              <!-- Executive Signature Block -->
              <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-top: 24px; padding-top: 20px; border-top: 1px solid #f1f5f9;">
                <tr>
                  <td>
                    <div style="font-size: 14px; font-weight: 700; color: #0f172a;">KSV Web &amp; AI Solutions Team</div>
                    <div style="font-size: 13px; color: #64748b; margin-top: 2px;">Specialist Engineering &amp; Client Solutions</div>
                    <div style="font-size: 12px; color: #2563eb; margin-top: 4px;">ksvdevlopers@gmail.com</div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Compliant Warm Cream Footer -->
          <tr>
            <td style="background-color: #f8f7f4; padding: 22px 28px; border-top: 1px solid #e7e5e4; text-align: center;">
              <p style="margin: 0 0 6px 0; font-size: 12px; color: #64748b; line-height: 1.5;">
                KSV Web &amp; AI Solutions • 12 Example Street, Hyderabad, India
              </p>
              <p style="margin: 0 0 8px 0; font-size: 11px; color: #94a3b8; line-height: 1.4;">
                You received this proposal because {html.escape(business or 'your business')} is publicly listed in {html.escape(city)}.
              </p>
              <p style="margin: 0; font-size: 11px; color: #64748b;">
                <a href="mailto:ksvdevlopers@gmail.com?subject=Unsubscribe" style="color: #64748b; text-decoration: underline;">Unsubscribe &amp; Opt Out</a>
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

if __name__ == "__main__":
    from src.crm import CRMDatabase
    crm = CRMDatabase()
    leads = crm.get_all_leads()
    for l in leads[:3]:
        seq = SalesCopywriter.generate_email_sequence(l)
        print(f"=== {l['business']} ({l.get('country', 'US')}) ===")
        print(f"Subject: {seq['initial_pitch']['subject']}\n")
