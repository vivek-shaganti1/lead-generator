"""Multi-Channel Outreach Orchestration Service.

Manages message queues across:
- Email (via existing SMTP transport)
- LinkedIn (Queued drafts & webhook triggers)
- WhatsApp / SMS (Draft generator & API dispatch)
- Contact Forms (Automated or manual form submissions)
- Telegram (Real-time rep notifications)
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models import ChannelType, Lead, MessageDirection, MultiChannelMessage, MultiChannelStatus
from app.services.ai.copywriter import generate_multichannel_pitch
from app.utils import utcnow

log = get_logger(__name__)


def queue_multichannel_outreach(
    db: Session,
    lead: Lead,
    channel: ChannelType,
    *,
    hook_style: str = "competitor_gap",
    custom_content: str | None = None,
    custom_subject: str | None = None,
) -> MultiChannelMessage:
    """Create and queue a multi-channel outreach message."""
    biz = lead.business

    if custom_content is not None:
        subject = custom_subject
        content = custom_content
    else:
        pitch = generate_multichannel_pitch(biz, channel=channel, hook_style=hook_style)
        subject = pitch.subject
        content = pitch.content

    # Determine recipient handle
    if channel == ChannelType.EMAIL:
        to_handle = lead.email
    elif channel == ChannelType.LINKEDIN:
        to_handle = biz.linkedin or biz.name
    elif channel in (ChannelType.WHATSAPP, ChannelType.SMS):
        to_handle = biz.phone or lead.email
    else:
        to_handle = biz.website or biz.name

    msg = MultiChannelMessage(
        lead_id=lead.id,
        channel=channel,
        direction=MessageDirection.OUTBOUND,
        to_handle=to_handle,
        subject=subject,
        content=content,
        status=MultiChannelStatus.QUEUED,
        metadata_json={"hook_style": hook_style},
        sent_at=utcnow() if channel == ChannelType.EMAIL else None,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    log.info("multichannel.message_queued", lead_id=lead.id, channel=channel.value, msg_id=msg.id)
    return msg
