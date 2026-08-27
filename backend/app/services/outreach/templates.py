"""Message rendering.

Templates are Jinja, rendered in a SandboxedEnvironment so campaign copy edited
from the dashboard can never reach into the runtime. Undefined variables raise
rather than silently rendering "Hi ," at a stranger.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass

from jinja2 import StrictUndefined, TemplateError
from jinja2.sandbox import SandboxedEnvironment

from app.config import settings
from app.services.compliance.unsubscribe import unsubscribe_url

_env = SandboxedEnvironment(undefined=StrictUndefined, autoescape=False, trim_blocks=True)

# The pitch differs by *why* they need us; keep it concrete and non-insulting.
PRESENCE_LINES = {
    "MISSING": "I couldn't find a website for {name} when I looked you up online",
    "SOCIAL": "I found {name} on social media, but no website of your own",
    "BROKEN": "I tried to open the website listed for {name} and it didn't load",
    "LIVE": "I had a look at your website for {name}",
    "UNKNOWN": "I came across {name} while looking up {category} in {city}",
}

DEFAULT_SUBJECT = "Quick question about {{ business_name }}'s website"

DEFAULT_BODY = """Hi{% if contact_name %} {{ contact_name }}{% endif %},

{{ presence_line }} — so customers searching for {{ category_label|lower }} in {{ city }} are probably finding your competitors first.

I build small, fast websites for local businesses: a home page, your services, opening hours, photos and a contact form, on your own domain. Typically live within a week, and priced so it pays for itself with one or two extra customers a month.

If that's useful, reply to this email and I'll send you a mockup of what {{ business_name }}'s site could look like — no charge, no obligation. If it's not, just say "no thanks" and I won't write again.

Best,
{{ sender_name }}
{{ company_name }}{% if company_website %}
{{ company_website }}{% endif %}
"""

DEFAULT_FOLLOWUP_SUBJECT = "Re: {{ business_name }}'s website"

DEFAULT_FOLLOWUP_BODY = """Hi{% if contact_name %} {{ contact_name }}{% endif %},

Just floating this back to the top of your inbox in case it got buried.

Happy to put together a free mockup for {{ business_name }} — you'd see exactly what you'd be getting before deciding anything.

If now isn't the right time, no problem at all: reply "not now" and I'll leave you be.

Best,
{{ sender_name }}
{{ company_name }}
"""

FOOTER_TEXT = """
--
{company_name}
{company_address}
You received this one-off message because {business_name} is listed publicly as a {category} business.
Unsubscribe and never hear from us again: {unsub}
"""


@dataclass(slots=True)
class RenderedEmail:
    subject: str
    text: str
    html: str


def presence_line(presence: str, name: str, category: str, city: str) -> str:
    template = PRESENCE_LINES.get(presence, PRESENCE_LINES["UNKNOWN"])
    return template.format(name=name, category=category or "business", city=city or "your area")


def build_context(lead, business, *, presence: str = "MISSING", category_label: str = "") -> dict:
    from app.services.discovery.categories import CATEGORY_PRESETS

    category_key = business.category or ""
    label = category_label or CATEGORY_PRESETS.get(category_key, {}).get("label") or (
        category_key.replace("_", " ") or "local"
    )
    city = business.city or business.region or "your area"
    return {
        "business_name": business.name,
        "contact_name": lead.contact_name or "",
        "category": category_key,
        "category_label": label,
        "city": city,
        "country": business.country_code or "",
        "presence": presence,
        "presence_line": presence_line(presence, business.name, label, city),
        "sender_name": settings.sender_name,
        "company_name": settings.company_name,
        "company_website": settings.company_website,
        "calendar_link": settings.calendar_link,
        "unsubscribe_url": unsubscribe_url(lead.unsubscribe_token),
    }


def render_string(template: str, context: dict) -> str:
    try:
        return _env.from_string(template).render(**context).strip()
    except TemplateError as exc:
        raise ValueError(f"template error: {exc}") from exc


def _linkify_text_to_html(text: str, context: dict | None = None) -> str:
    ctx = context or {}
    biz_name = ctx.get("business_name", "")
    sender_name = ctx.get("sender_name", settings.sender_name)
    company_name = ctx.get("company_name", settings.company_name)
    category_label = ctx.get("category_label", "business")
    if not category_label or category_label.lower() in ["none", "null"]:
        category_label = "local business"
    city = ctx.get("city", "your area")
    unsub_url = ctx.get("unsubscribe_url", "#")
    company_address = settings.company_address

    # Extract paragraphs and split out footer if present
    escaped = html.escape(text)
    
    # Highlight business name with sleek soft amber pill badge
    if biz_name:
        escaped_biz = html.escape(biz_name)
        escaped = escaped.replace(
            escaped_biz,
            f'<span style="background-color: #fef3c7; color: #92400e; padding: 2px 6px; border-radius: 4px; font-weight: 600; border: 1px solid #fde68a;">{escaped_biz}</span>'
        )

    # Linkify URLs
    escaped = re.sub(
        r"(https?://[^\s<]+)",
        r'<a href="\1" style="color:#2563eb; text-decoration: underline;">\1</a>',
        escaped,
    )

    paragraphs = [p.strip() for p in escaped.split("\n\n") if p.strip()]
    rendered_paragraphs = []

    for p in paragraphs:
        # Check if paragraph is bullet points / list
        if "•" in p or "⚡" in p or "👉" in p or "-" in p:
            lines = p.split("\n")
            bullet_html = ""
            for line in lines:
                line_str = line.strip()
                if not line_str:
                    continue
                if line_str.startswith("•") or line_str.startswith("-") or line_str.startswith("⚡") or line_str.startswith("👉"):
                    bullet_html += f'<li style="margin-bottom: 8px; color: #334155; font-size: 14.5px; line-height: 1.55;">{line_str.lstrip("•- ")}</li>'
                else:
                    bullet_html += f'<div style="font-weight: 700; color: #0f172a; margin-bottom: 8px; font-size: 14.5px;">{line_str}</div>'
            
            rendered_paragraphs.append(
                f'<div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-left: 4px solid #2563eb; border-radius: 8px; padding: 16px 20px; margin: 18px 0;">'
                f'<ul style="margin: 0; padding-left: 18px; list-style-type: none;">{bullet_html}</ul>'
                f'</div>'
            )
        elif p.startswith("--") or "Unsubscribe" in p:
            # Footer text handled separately in container footer
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
  <title>{html.escape(ctx.get('subject', 'Proposal'))}</title>
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
                      {html.escape(company_name)}
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
                    <a href="mailto:{html.escape(settings.sender_email)}?subject=Re:%20Mockup%20Preview%20for%20{html.escape(biz_name)}" 
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
                    <div style="font-size: 14px; font-weight: 700; color: #0f172a;">{html.escape(sender_name)}</div>
                    <div style="font-size: 13px; color: #64748b; margin-top: 2px;">{html.escape(company_name)} • Client Solutions</div>
                    <div style="font-size: 12px; color: #2563eb; margin-top: 4px;">{html.escape(settings.sender_email)}</div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Compliant Warm Cream Footer -->
          <tr>
            <td style="background-color: #f8f7f4; padding: 22px 28px; border-top: 1px solid #e7e5e4; text-align: center;">
              <p style="margin: 0 0 6px 0; font-size: 12px; color: #64748b; line-height: 1.5;">
                {html.escape(company_name)} • {html.escape(company_address)}
              </p>
              <p style="margin: 0 0 8px 0; font-size: 11px; color: #94a3b8; line-height: 1.4;">
                You received this proposal because {html.escape(biz_name or 'your business')} is publicly listed in {html.escape(city)}.
              </p>
              <p style="margin: 0; font-size: 11px; color: #64748b;">
                <a href="{html.escape(unsub_url)}" style="color: #64748b; text-decoration: underline;">Unsubscribe &amp; Opt Out</a>
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def render_email(
    subject_template: str,
    body_template: str,
    context: dict,
    *,
    include_footer: bool = True,
) -> RenderedEmail:
    subject = render_string(subject_template, context)
    body = render_string(body_template, context)

    html_version = _linkify_text_to_html(body.strip(), {**context, "subject": subject})

    if include_footer:
        body = body + "\n" + FOOTER_TEXT.format(
            company_name=settings.company_name,
            company_address=settings.company_address,
            business_name=context.get("business_name", "this business"),
            category=context.get("category_label", "local"),
            unsub=context["unsubscribe_url"],
        )
    return RenderedEmail(subject=subject, text=body.strip(), html=html_version)


def default_campaign_payload(name: str = "Default outreach") -> dict:
    return {
        "name": name,
        "subject_template": DEFAULT_SUBJECT,
        "body_template": DEFAULT_BODY,
        "followup_subject_template": DEFAULT_FOLLOWUP_SUBJECT,
        "followup_body_template": DEFAULT_FOLLOWUP_BODY,
    }
