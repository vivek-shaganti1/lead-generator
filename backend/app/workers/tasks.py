"""Background tasks.

Design rules followed here:
  * every task is idempotent - re-running it must not double-send or double-count
  * every task owns its own session and commits or rolls back explicitly
  * network failures retry with backoff; logic failures do not retry forever
"""
from __future__ import annotations

from celery import shared_task
from sqlalchemy import select

from app.db import session_scope
from app.logging_config import get_logger
from app.models import Business, DiscoveryStatus, Lead
from app.services import pipeline, stats
from app.services.compliance import retention
from app.services.discovery.base import SearchArea
from app.services.inbox import imap_client
from app.services.inbox.processor import process_batch
from app.services.notify import telegram
from app.services.outreach.dispatcher import run_batch
from app.utils import utcnow

log = get_logger(__name__)


@shared_task(name="leadgen.discovery_run", bind=True, max_retries=2, default_retry_delay=120)
def discovery_run(self, area: dict, categories: list[str] | None = None,
                  limit: int | None = None, use_google_fallback: bool | None = None) -> dict:
    search_area = SearchArea(**area)
    with session_scope() as db:
        run = pipeline.run_discovery(
            db, area=search_area, categories=categories, limit=limit,
            use_google_fallback=use_google_fallback,
        )
        result = {
            "run_id": run.id, "status": run.status.value, "found": run.found_total,
            "new": run.new_businesses, "without_website": run.without_website,
        }
    if result["status"] != DiscoveryStatus.FAILED.value:
        qualify_pending.delay(limit=200)
    return result


@shared_task(name="leadgen.qualify_pending", bind=True, max_retries=1)
def qualify_pending(self, limit: int = 50) -> dict:
    """Turn discovered businesses into leads: website check + email discovery."""
    summary = {"examined": 0, "created": 0, "skipped": 0, "reasons": {}}
    with session_scope() as db:
        campaign = pipeline.get_or_create_default_campaign(db)
        businesses = db.execute(
            select(Business)
            .outerjoin(Lead, Lead.business_id == Business.id)
            .where(Lead.id.is_(None), Business.has_website.is_(False))
            .order_by(Business.created_at.desc())
            .limit(limit)
        ).scalars().all()

        for business in businesses:
            summary["examined"] += 1
            try:
                result = pipeline.qualify_business(db, business, campaign)
            except Exception as exc:  # one bad site must not kill the batch
                log.warning("qualify.failed", business_id=business.id, error=str(exc))
                summary["reasons"]["error"] = summary["reasons"].get("error", 0) + 1
                db.rollback()
                continue
            if result.created:
                summary["created"] += 1
            else:
                summary["skipped"] += 1
                key = result.reason[:60]
                summary["reasons"][key] = summary["reasons"].get(key, 0) + 1
            db.commit()
    return summary


@shared_task(name="leadgen.outreach_batch", bind=True, max_retries=1)
def outreach_batch(self, limit: int = 25) -> dict:
    with session_scope() as db:
        return run_batch(db, limit=limit)


@shared_task(name="leadgen.send_lead_now", bind=True, max_retries=2, default_retry_delay=60)
def send_lead_now(self, lead_id: int, force: bool = False) -> dict:
    from app.services.outreach.dispatcher import send_lead

    with session_scope() as db:
        lead = db.get(Lead, lead_id)
        if lead is None:
            return {"sent": False, "reason": "lead not found"}
        outcome = send_lead(db, lead, force=force)
        return {"sent": outcome.sent, "reason": outcome.reason, "step": outcome.step}


@shared_task(name="leadgen.poll_inbox", bind=True, max_retries=3, default_retry_delay=120)
def poll_inbox(self, days: int = 7) -> dict:
    from app.config import settings

    if not settings.imap_host:
        return {"skipped": "imap not configured"}
    try:
        messages = imap_client.fetch_recent(days=days, unseen_only=False)
    except Exception as exc:
        log.error("inbox.fetch_failed", error=str(exc))
        raise self.retry(exc=exc)

    with session_scope() as db:
        summary = process_batch(db, messages)
    log.info("inbox.processed", **summary)
    return summary


@shared_task(name="leadgen.rollup_stats")
def rollup_stats(days: int = 3) -> dict:
    """Recompute the last few days; older days never change."""
    with session_scope() as db:
        rows = stats.rollup_range(db, days=days)
        return {"days_rolled": len(rows)}


@shared_task(name="leadgen.daily_digest")
def daily_digest() -> dict:
    with session_scope() as db:
        stats.rollup_day(db)
        digest = stats.digest_for(db)
    sent = telegram.get_client().send(telegram.format_daily_digest(digest))
    return {"sent": sent, **digest}


@shared_task(name="leadgen.retention_sweep")
def retention_sweep() -> dict:
    with session_scope() as db:
        return retention.run_all(db)


@shared_task(name="leadgen.alert")
def alert(title: str, detail: str) -> bool:
    return telegram.get_client().send(telegram.format_alert(title, detail))


@shared_task(name="leadgen.heartbeat")
def heartbeat() -> str:
    return utcnow().isoformat()


@shared_task(name="leadgen.sync_excel_master")
def sync_excel_master() -> dict:
    from app.services.crm.excel_sync import trigger_master_excel_sync

    with session_scope() as db:
        excel_path, csv_path = trigger_master_excel_sync(db)
        return {"status": "synced", "excel_path": excel_path, "csv_path": csv_path}
