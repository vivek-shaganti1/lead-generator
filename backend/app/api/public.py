"""Unauthenticated endpoints that recipients hit: opt-out and open tracking."""
from __future__ import annotations

from html import escape

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import EmailMessage, Lead, LeadStatus
from app.services.compliance.unsubscribe import apply_unsubscribe
from app.services.outreach.tracking import PIXEL_GIF, parse_token
from app.utils import utcnow

router = APIRouter(tags=["public"])

_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>
body{{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:#f6f7f9;
margin:0;display:flex;min-height:100vh;align-items:center;justify-content:center;color:#111827}}
.card{{background:#fff;padding:40px;border-radius:14px;box-shadow:0 1px 3px rgba(0,0,0,.08);
max-width:460px;text-align:center}} h1{{font-size:20px;margin:0 0 12px}}
p{{color:#4b5563;line-height:1.6;margin:0 0 20px}}
button{{background:#111827;color:#fff;border:0;border-radius:8px;padding:12px 22px;
font-size:15px;cursor:pointer}} .muted{{font-size:12px;color:#9ca3af}}
</style></head><body><div class="card">{body}</div></body></html>"""


def _page(title: str, body: str, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(_PAGE.format(title=title, body=body), status_code=status_code)


def _find_lead(db: Session, token: str) -> Lead | None:
    return db.execute(
        select(Lead).where(Lead.unsubscribe_token == token)
    ).scalars().first()


@router.get("/u/{token}", response_class=HTMLResponse)
def unsubscribe_page(token: str, db: Session = Depends(get_db)) -> HTMLResponse:
    lead = _find_lead(db, token)
    if lead is None:
        return _page("Link not found", "<h1>Link not found</h1>"
                     "<p>This unsubscribe link is not valid or has already been used.</p>", 404)
    if lead.status == LeadStatus.UNSUBSCRIBED:
        return _page("Already unsubscribed",
                     "<h1>You're unsubscribed</h1>"
                     f"<p>{escape(lead.email)} will not be contacted again.</p>")
    return _page(
        "Unsubscribe",
        f"<h1>Unsubscribe</h1><p>Confirm that <strong>{escape(lead.email)}</strong> should "
        f"never receive email from {escape(settings.company_name)} again.</p>"
        f'<form method="post" action="/u/{token}"><button type="submit">'
        "Unsubscribe me</button></form>"
        '<p class="muted" style="margin-top:18px">This takes effect immediately.</p>',
    )


@router.post("/u/{token}")
async def unsubscribe_submit(
    token: str, request: Request, db: Session = Depends(get_db)
):
    """Handles both the confirmation form and RFC 8058 one-click POSTs."""
    lead = _find_lead(db, token)
    if lead is None:
        return _page("Link not found", "<h1>Link not found</h1>"
                     "<p>This unsubscribe link is not valid.</p>", 404)

    if lead.status != LeadStatus.UNSUBSCRIBED:
        apply_unsubscribe(db, lead, reason="clicked unsubscribe")
        db.commit()

    body = (await request.body()).decode(errors="ignore")
    if "List-Unsubscribe=One-Click" in body:
        return Response(status_code=200)

    return _page(
        "Unsubscribed",
        "<h1>Done</h1>"
        f"<p><strong>{escape(lead.email)}</strong> has been removed. "
        "You will not hear from us again.</p>",
    )


@router.get("/t/o/{token}.gif")
def track_open(token: str, db: Session = Depends(get_db)) -> Response:
    """1x1 pixel. Always returns the image, whatever the token says."""
    message_id = parse_token(token, kind="o")
    if message_id is not None:
        message = db.get(EmailMessage, message_id)
        if message is not None and message.status.value == "SENT":
            message.open_count = (message.open_count or 0) + 1
            if message.opened_at is None:
                message.opened_at = utcnow()
            db.commit()
    return Response(
        content=PIXEL_GIF,
        media_type="image/gif",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"},
    )
