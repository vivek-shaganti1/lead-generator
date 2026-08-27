"""Turn a fetched mailbox message into a lead state change and a notification.

Order matters: store first, classify second, notify third. If Groq or Telegram
are down we still have the reply on disk and can re-run classification later.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.logging_config import get_logger
from app.models import Event, InboundMessage, Lead, LeadStatus, MessageStatus, ReplyClass
from app.models import EmailMessage
from app.services.ai.groq import classify_reply
from app.services.compliance.policy import suppress
from app.services.compliance.unsubscribe import apply_unsubscribe
from app.services.inbox.matcher import match_lead
from app.services.inbox.parser import ParsedInbound
from app.services.notify import telegram
from app.utils import utcnow

log = get_logger(__name__)

# How a classification maps onto the lead's lifecycle.
STATUS_BY_CLASS = {
    ReplyClass.POSITIVE: LeadStatus.POSITIVE,
    ReplyClass.NEGATIVE: LeadStatus.NEGATIVE,
    ReplyClass.QUESTION: LeadStatus.REPLIED,
    ReplyClass.NEUTRAL: LeadStatus.NEUTRAL,
    ReplyClass.UNKNOWN: LeadStatus.REPLIED,
}


@dataclass(slots=True)
class ProcessResult:
    stored: bool
    reason: str
    inbound_id: int | None = None
    lead_id: int | None = None
    classification: ReplyClass | None = None
    notified: bool = False


def already_seen(db: Session, message_id: str) -> bool:
    return db.execute(
        select(InboundMessage.id).where(InboundMessage.message_id == message_id)
    ).first() is not None


def _is_our_own_message(db: Session, message_id: str) -> bool:
    """Guard against polling a folder that also contains our sent mail."""
    return db.execute(
        select(EmailMessage.id).where(EmailMessage.message_id == message_id)
    ).first() is not None


def _handle_bounce(db: Session, lead: Lead | None, inbound: InboundMessage) -> None:
    address = inbound.from_email
    if lead:
        lead.status = LeadStatus.BOUNCED
        lead.next_action_at = None
        lead.block_reason = "hard bounce"
        address = lead.email
        for message in lead.messages:
            if message.status == MessageStatus.SENT and message.step == (
                max((m.step for m in lead.messages), default=0)
            ):
                message.status = MessageStatus.BOUNCED
    if address:
        suppress(db, address, reason="hard bounce", kind="email")
    db.add(Event(type="inbound.bounce", lead_id=lead.id if lead else None,
                 payload={"address": address}))


def process_inbound(db: Session, parsed: ParsedInbound) -> ProcessResult:
    if not parsed.message_id:
        return ProcessResult(False, "message has no id")
    if already_seen(db, parsed.message_id):
        return ProcessResult(False, "already processed")
    if _is_our_own_message(db, parsed.message_id):
        return ProcessResult(False, "our own outbound message")

    lead, match_method = match_lead(db, parsed)

    classification = classify_reply(parsed.subject, parsed.body_text)

    inbound = InboundMessage(
        lead_id=lead.id if lead else None,
        message_id=parsed.message_id,
        in_reply_to=parsed.in_reply_to,
        from_email=parsed.from_email,
        subject=parsed.subject,
        body_text=parsed.body_text[:20000],
        received_at=parsed.received_at or utcnow(),
        classification=classification.classification,
        confidence=classification.confidence,
        classifier=classification.classifier,
        # The rules classifier's "summary" is really a debug reason ("positive
        # marker: yes please"); that belongs in the event log, not in an alert
        # presented to the user as an AI reading of the reply.
        summary=(classification.summary or None)
        if classification.classifier != "rules" else None,
    )
    db.add(inbound)
    db.flush()

    db.add(Event(type="inbound.received", lead_id=lead.id if lead else None, payload={
        "message_id": parsed.message_id, "match": match_method,
        "classification": classification.classification.value,
        "classifier": classification.classifier,
        "confidence": classification.confidence,
        "reason": classification.summary,
    }))

    if parsed.is_dsn or classification.classification == ReplyClass.BOUNCE:
        _handle_bounce(db, lead, inbound)
        return ProcessResult(True, "bounce handled", inbound.id,
                             lead.id if lead else None, ReplyClass.BOUNCE)

    if lead is None:
        return ProcessResult(True, f"stored, unmatched ({match_method})", inbound.id,
                             None, classification.classification)

    lead.replied_at = lead.replied_at or inbound.received_at
    lead.reply_class = classification.classification
    lead.reply_confidence = classification.confidence
    if classification.summary:
        lead.ai_summary = classification.summary

    if classification.classification == ReplyClass.UNSUBSCRIBE:
        apply_unsubscribe(db, lead, reason="requested by reply")
    elif classification.classification == ReplyClass.AUTO_REPLY:
        # An out-of-office is not a reply; leave the sequence running.
        pass
    else:
        lead.status = STATUS_BY_CLASS.get(classification.classification, LeadStatus.REPLIED)
        # A human answered: stop the automated follow-ups either way.
        lead.next_action_at = None

        if lead.status == LeadStatus.POSITIVE:
            try:
                from app.services.crm.deals import create_deal_from_positive_lead
                create_deal_from_positive_lead(db, lead)
            except Exception as exc:
                log.warning("crm.auto_deal_failed", lead_id=lead.id, error=str(exc))

        try:
            from app.services.ai.learning import record_reply_event
            record_reply_event(
                db,
                subject_line=parsed.subject or "Outreach email",
                industry=lead.business.category if lead.business else None,
                is_positive=(lead.status == LeadStatus.POSITIVE),
            )
        except Exception:
            pass

        try:
            from app.services.crm.excel_sync import trigger_master_excel_sync
            trigger_master_excel_sync(db)
        except Exception:
            pass

    notified = _notify(db, lead, inbound, classification.classification)
    inbound.notified = notified
    return ProcessResult(True, "processed", inbound.id, lead.id,
                         classification.classification, notified)


def _notify(db: Session, lead: Lead, inbound: InboundMessage, kind: ReplyClass) -> bool:
    business = lead.business
    client = telegram.get_client()
    if not client.enabled:
        return False
    try:
        if kind == ReplyClass.POSITIVE and settings.telegram_notify_positive:
            return client.send(telegram.format_positive_reply(lead, business, inbound))
        if settings.telegram_notify_any_reply:
            return client.send(telegram.format_reply(lead, business, inbound))
    except Exception as exc:  # notifications must never break ingestion
        log.warning("notify.failed", error=str(exc), lead_id=lead.id)
    return False


def process_batch(db: Session, messages: list[ParsedInbound]) -> dict:
    summary = {"seen": len(messages), "stored": 0, "skipped": 0, "positive": 0,
               "bounces": 0, "unsubscribes": 0, "unmatched": 0}
    for parsed in messages:
        try:
            result = process_inbound(db, parsed)
        except Exception as exc:
            log.error("inbound.process_failed", error=str(exc),
                      message_id=parsed.message_id)
            db.rollback()
            continue
        if not result.stored:
            summary["skipped"] += 1
            continue
        summary["stored"] += 1
        if result.lead_id is None:
            summary["unmatched"] += 1
        if result.classification == ReplyClass.POSITIVE:
            summary["positive"] += 1
        elif result.classification == ReplyClass.BOUNCE:
            summary["bounces"] += 1
        elif result.classification == ReplyClass.UNSUBSCRIBE:
            summary["unsubscribes"] += 1
        db.commit()
    return summary
