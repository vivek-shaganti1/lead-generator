"""The outreach engine: pick the next lead, gate it, render it, send it, record it.

Every send passes compliance *and* throttle checks immediately before delivery,
not when it was queued - policy may have changed in between, and a lead may have
unsubscribed while sitting in the queue.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.logging_config import get_logger
from app.models import (
    Campaign,
    EmailMessage,
    Event,
    Lead,
    LeadStatus,
    MessageStatus,
)
from app.services.compliance.policy import enforce
from app.services.compliance.unsubscribe import list_unsubscribe_headers
from app.services.enrichment.website_check import WebPresence
from app.services.outreach import tracking
from app.services.outreach.sender import OutgoingEmail, get_transport
from app.services.outreach.templates import build_context, render_email
from app.services.outreach.throttle import check_send_slot
from app.utils import coerce_aware, utcnow

log = get_logger(__name__)

# Reasons that mean "not now" rather than "something went wrong".
_THROTTLE_MARKERS = (
    "cap reached", "campaign daily limit", "business hours", "weekend", "minimum gap",
)


@dataclass(slots=True)
class SendOutcome:
    sent: bool
    reason: str
    lead_id: int
    message_id: int | None = None
    step: int = 0


def presence_of(business) -> str:
    """Recover the pitch angle from what we stored during qualification."""
    if business.has_website and business.website_alive:
        return WebPresence.LIVE.value
    if business.website:
        from app.utils import is_social_only

        if is_social_only(business.website):
            return WebPresence.SOCIAL.value
        if business.website_alive is False:
            return WebPresence.BROKEN.value
        return WebPresence.BROKEN.value
    return WebPresence.MISSING.value


def due_leads(db: Session, limit: int = 50) -> list[Lead]:
    """Leads eligible for their first touch or their next follow-up, best first."""
    now = utcnow()
    followup_states = [LeadStatus.CONTACTED, LeadStatus.FOLLOWED_UP]

    conditions = [
        (Lead.status.in_([LeadStatus.READY, LeadStatus.QUEUED]))
    ]
    if settings.followup_enabled:
        conditions.append(
            (Lead.status.in_(followup_states))
            & (Lead.followups_sent < settings.max_followups)
            & (Lead.next_action_at.isnot(None))
            & (Lead.next_action_at <= now)
        )

    stmt = (
        select(Lead)
        .where(Lead.approved.is_(True) if settings.require_manual_approval else True)
        .where(or_(*conditions))
        .order_by(Lead.score.desc(), Lead.id.asc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def _next_step_for(lead: Lead) -> int:
    return 0 if lead.status in (LeadStatus.READY, LeadStatus.QUEUED) else lead.followups_sent + 1


def _thread_parent(db: Session, lead: Lead) -> EmailMessage | None:
    return db.execute(
        select(EmailMessage)
        .where(EmailMessage.lead_id == lead.id, EmailMessage.status == MessageStatus.SENT)
        .order_by(EmailMessage.step.asc())
    ).scalars().first()


def _templates_for(campaign: Campaign | None, step: int) -> tuple[str, str]:
    from app.services.outreach import templates as tpl

    if campaign is None:
        return (
            (tpl.DEFAULT_SUBJECT, tpl.DEFAULT_BODY) if step == 0
            else (tpl.DEFAULT_FOLLOWUP_SUBJECT, tpl.DEFAULT_FOLLOWUP_BODY)
        )
    if step == 0:
        return campaign.subject_template, campaign.body_template
    return (
        campaign.followup_subject_template or tpl.DEFAULT_FOLLOWUP_SUBJECT,
        campaign.followup_body_template or tpl.DEFAULT_FOLLOWUP_BODY,
    )


def _schedule_next(lead: Lead, step: int) -> None:
    delays = settings.followup_delay_list
    next_index = step  # step 0 sent -> next delay is delays[0]
    if not settings.followup_enabled or next_index >= len(delays) or step >= settings.max_followups:
        lead.next_action_at = None
        return
    lead.next_action_at = utcnow() + timedelta(days=delays[next_index])


def send_lead(db: Session, lead: Lead, *, force: bool = False) -> SendOutcome:
    decision = enforce(db, lead)
    if not decision.allowed:
        log.info("outreach.blocked", lead_id=lead.id, reason=decision.reason)
        return SendOutcome(False, decision.reason, lead.id)

    if not force:
        slot = check_send_slot(db, lead)
        if not slot.allowed:
            lead.next_action_at = slot.retry_after or lead.next_action_at
            return SendOutcome(False, slot.reason, lead.id)

    step = _next_step_for(lead)
    if step > settings.max_followups:
        lead.next_action_at = None
        return SendOutcome(False, "follow-up sequence exhausted", lead.id)

    if step > 0:
        if not settings.followup_enabled:
            return SendOutcome(False, "follow-ups are disabled", lead.id)
        # due_leads() already filters on this, but send_lead is also reachable
        # from the API and from a retried task, where nothing else checks the
        # schedule. Without this a retry would fire the follow-up immediately.
        due_at = coerce_aware(lead.next_action_at)
        if not force and (due_at is None or due_at > utcnow()):
            return SendOutcome(False, "follow-up is not due yet", lead.id, step=step)

    already = db.execute(
        select(EmailMessage).where(EmailMessage.lead_id == lead.id, EmailMessage.step == step)
    ).scalars().first()
    if already and already.status == MessageStatus.SENT and not force:
        # Idempotency guard: a retried task must never double-mail a lead.
        return SendOutcome(False, f"step {step} already sent", lead.id, already.id, step)

    business = lead.business
    context = build_context(lead, business, presence=presence_of(business))
    subject_tpl, body_tpl = _templates_for(lead.campaign, step)

    try:
        rendered = render_email(subject_tpl, body_tpl, context)
    except ValueError as exc:
        lead.status = LeadStatus.FAILED
        lead.block_reason = str(exc)
        db.add(Event(type="outreach.render_failed", lead_id=lead.id, payload={"error": str(exc)}))
        return SendOutcome(False, f"render failed: {exc}", lead.id)

    parent = _thread_parent(db, lead) if step > 0 else None

    record = already or EmailMessage(
        lead_id=lead.id,
        step=step,
        to_email=lead.email,
        from_email=settings.sender_email,
        subject=rendered.subject,
        body_text=rendered.text,
        body_html=rendered.html,
        status=MessageStatus.PENDING,
    )
    record.subject = rendered.subject
    record.body_text = rendered.text
    record.body_html = rendered.html
    if already is None:
        db.add(record)
    db.flush()  # we need record.id for the tracking pixel

    html_body = (
        tracking.inject_pixel(rendered.html, record.id)
        if settings.track_opens else rendered.html
    )

    outgoing = OutgoingEmail(
        to_email=lead.email,
        subject=rendered.subject,
        text=rendered.text,
        html=html_body,
        headers=list_unsubscribe_headers(lead.unsubscribe_token),
        in_reply_to=parent.message_id if parent else None,
        references=parent.message_id if parent else None,
    )

    result = get_transport().send(outgoing)
    now = utcnow()

    if not result.ok:
        record.status = MessageStatus.FAILED
        record.error = result.error
        lead.block_reason = result.error
        # A refused recipient is the mailbox telling us it does not exist.
        if result.error and "recipient refused" in result.error.lower():
            lead.status = LeadStatus.BOUNCED
        db.add(Event(type="outreach.send_failed", lead_id=lead.id,
                     payload={"step": step, "error": result.error}))
        return SendOutcome(False, result.error or "send failed", lead.id, record.id, step)

    record.status = MessageStatus.SENT
    record.sent_at = now
    record.message_id = result.message_id
    record.dry_run = result.dry_run
    record.error = None

    lead.last_contacted_at = now
    lead.block_reason = None
    if step == 0:
        lead.status = LeadStatus.CONTACTED
    else:
        lead.status = LeadStatus.FOLLOWED_UP
        lead.followups_sent = step
    _schedule_next(lead, step)

    db.add(Event(type="outreach.sent", lead_id=lead.id, payload={
        "step": step, "message_id": result.message_id, "dry_run": result.dry_run,
        "to": lead.email,
    }))

    try:
        from app.services.ai.learning import record_send_event
        record_send_event(
            db,
            subject_line=rendered.subject,
            industry=business.category if business else None,
            country_code=business.country_code if business else None,
            campaign_id=lead.campaign_id,
        )
    except Exception:
        pass

    try:
        from app.services.crm.excel_sync import trigger_master_excel_sync
        trigger_master_excel_sync(db)
    except Exception:
        pass

    log.info("outreach.sent", lead_id=lead.id, step=step, dry_run=result.dry_run)
    return SendOutcome(True, "sent", lead.id, record.id, step)


def run_batch(db: Session, limit: int = 25) -> dict:
    """Process one batch of due leads. Stops early when the daily cap is hit."""
    results = {"attempted": 0, "sent": 0, "blocked": 0, "failed": 0, "reasons": {}}
    for lead in due_leads(db, limit=limit):
        results["attempted"] += 1
        outcome = send_lead(db, lead)
        if outcome.sent:
            results["sent"] += 1
        else:
            key = outcome.reason[:80]
            results["reasons"][key] = results["reasons"].get(key, 0) + 1
            # A pacing decision is "blocked" (try again later); anything else is a
            # genuine failure. The global cap ends the batch outright, but a
            # per-campaign limit only stops that campaign, so it must not break.
            if any(marker in outcome.reason for marker in _THROTTLE_MARKERS):
                results["blocked"] += 1
                if "cap reached" in outcome.reason:
                    break  # nothing else will get through today
            else:
                results["failed"] += 1
        db.commit()
    return results


def approve_lead(db: Session, lead: Lead, approved: bool = True) -> Lead:
    lead.approved = approved
    if approved and lead.status == LeadStatus.NEEDS_APPROVAL:
        lead.status = LeadStatus.READY
        lead.next_action_at = utcnow()
    elif not approved and lead.status == LeadStatus.READY:
        lead.status = LeadStatus.NEEDS_APPROVAL
    db.add(Event(type="lead.approved" if approved else "lead.unapproved", lead_id=lead.id,
                 payload={}))
    return lead


def overdue_followups(db: Session) -> int:
    now = utcnow()
    rows = db.execute(
        select(Lead).where(
            Lead.status.in_([LeadStatus.CONTACTED, LeadStatus.FOLLOWED_UP]),
            Lead.next_action_at.isnot(None),
        )
    ).scalars().all()
    return sum(1 for r in rows if (coerce_aware(r.next_action_at) or now) <= now)
