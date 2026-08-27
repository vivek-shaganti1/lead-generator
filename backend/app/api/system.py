"""Operational endpoints: health, config visibility, suppression list, self-tests."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Suppression, User
from app.schemas import HealthOut, SuppressionIn, SuppressionOut, TestEmailRequest
from app.security import get_current_user
from app.services.compliance.policy import suppress
from app.services.notify import telegram
from app.services.outreach.sender import OutgoingEmail, get_transport
from app.services.outreach.throttle import usage_snapshot

router = APIRouter(prefix="/api/system", tags=["system"])
VERSION = "1.0.0"


def _redis_ok() -> bool:
    try:
        import redis

        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2)
        return bool(client.ping())
    except Exception:
        return False


@router.get("/health", response_model=HealthOut)
def health(db: Session = Depends(get_db)) -> HealthOut:
    try:
        db.execute(text("SELECT 1"))
        database_ok = True
    except Exception:
        database_ok = False
    return HealthOut(
        status="ok" if database_ok else "degraded",
        version=VERSION,
        env=settings.env,
        dry_run=settings.dry_run,
        database=database_ok,
        redis=_redis_ok(),
        smtp_configured=bool(settings.smtp_host),
        imap_configured=bool(settings.imap_host),
        telegram_configured=bool(settings.telegram_bot_token and settings.telegram_chat_id),
        groq_configured=bool(settings.groq_api_key),
    )


@router.get("/config")
def config(_: User = Depends(get_current_user)) -> dict:
    """Non-secret view of the running configuration."""
    return {
        "env": settings.env,
        "dry_run": settings.dry_run,
        "require_manual_approval": settings.require_manual_approval,
        "daily_send_cap": settings.daily_send_cap,
        "warmup_enabled": settings.warmup_enabled,
        "min_seconds_between_sends": settings.min_seconds_between_sends,
        "max_per_domain_per_day": settings.max_per_domain_per_day,
        "send_window": [settings.send_window_start_hour, settings.send_window_end_hour],
        "send_on_weekends": settings.send_on_weekends,
        "followup_enabled": settings.followup_enabled,
        "followup_delays_days": settings.followup_delay_list,
        "max_followups": settings.max_followups,
        "blocked_countries": sorted(settings.blocked_country_set),
        "google_places_enabled": settings.google_places_enabled,
        "ai_classify_replies": settings.ai_classify_replies,
        "sender": {"name": settings.sender_name, "email": settings.sender_email},
        "company": {"name": settings.company_name, "website": settings.company_website},
        "integrations": {
            "smtp": bool(settings.smtp_host),
            "imap": bool(settings.imap_host),
            "telegram": bool(settings.telegram_bot_token and settings.telegram_chat_id),
            "groq": bool(settings.groq_api_key),
            "google_places": bool(settings.google_places_api_key),
        },
    }


@router.get("/sending")
def sending(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    return usage_snapshot(db)


@router.get("/suppressions", response_model=list[SuppressionOut])
def list_suppressions(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return list(
        db.execute(
            select(Suppression).order_by(Suppression.id.desc()).limit(500)
        ).scalars().all()
    )


@router.post("/suppressions", response_model=SuppressionOut, status_code=201)
def add_suppression(
    payload: SuppressionIn, db: Session = Depends(get_db), _: User = Depends(get_current_user)
):
    entry = suppress(db, payload.value, reason=payload.reason, kind=payload.kind)
    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/suppressions/{suppression_id}", status_code=204)
def remove_suppression(
    suppression_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
):
    entry = db.get(Suppression, suppression_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(entry)
    db.commit()


@router.post("/test/email")
def test_email(payload: TestEmailRequest, _: User = Depends(get_current_user)) -> dict:
    """Send a self-test message. Honours DRY_RUN like every other send."""
    result = get_transport().send(
        OutgoingEmail(
            to_email=payload.to_email,
            subject=f"[{settings.company_name}] SMTP test",
            text="This is a configuration test from your lead generation system.\n"
                 "If you received it, SMTP is working.",
        )
    )
    if not result.ok:
        raise HTTPException(status_code=502, detail=result.error or "send failed")
    return {"sent": True, "dry_run": result.dry_run, "message_id": result.message_id}


@router.post("/test/telegram")
def test_telegram(_: User = Depends(get_current_user)) -> dict:
    client = telegram.get_client()
    if not client.enabled:
        raise HTTPException(status_code=400, detail="Telegram is not configured")
    ok = client.send("✅ Lead generator connected. Notifications are working.")
    if not ok:
        raise HTTPException(status_code=502, detail="Telegram rejected the message")
    return {"sent": True}


@router.post("/test/groq")
def test_groq(_: User = Depends(get_current_user)) -> dict:
    from app.services.ai.groq import GroqClient, classify_reply

    client = GroqClient()
    if not client.enabled:
        raise HTTPException(status_code=400, detail="GROQ_API_KEY is not configured")
    result = classify_reply("Re: website", "Yes please, how much would it cost?", client=client)
    return {
        "classification": result.classification.value,
        "confidence": result.confidence,
        "classifier": result.classifier,
        "summary": result.summary,
    }
