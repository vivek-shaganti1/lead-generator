from __future__ import annotations

import pytest

from app.models import ChannelType, MultiChannelMessage, MultiChannelStatus
from app.services.ai.copywriter import generate_multichannel_pitch
from app.services.outreach.multichannel import queue_multichannel_outreach
from tests.conftest import make_business, make_lead


def test_generate_multichannel_pitch(db):
    biz = make_business(db, name="Elite Fitness", category="gym", city="Galway", has_website=False)

    email_pitch = generate_multichannel_pitch(biz, channel=ChannelType.EMAIL, hook_style="competitor_gap")
    assert "Elite Fitness" in email_pitch.subject or "Elite Fitness" in email_pitch.content
    assert email_pitch.channel == ChannelType.EMAIL

    linkedin_pitch = generate_multichannel_pitch(biz, channel=ChannelType.LINKEDIN)
    assert len(linkedin_pitch.content) < 400
    assert "Elite Fitness" in linkedin_pitch.content

    sms_pitch = generate_multichannel_pitch(biz, channel=ChannelType.SMS)
    assert "Elite Fitness" in sms_pitch.content


def test_queue_multichannel_outreach(db):
    biz = make_business(db, name="Galway Cafe", category="cafe", phone="+353 91 555 123", has_website=False)
    lead = make_lead(db, business=biz, email="hello@galwaycafe.ie")

    msg = queue_multichannel_outreach(db, lead, channel=ChannelType.WHATSAPP)
    assert msg.id is not None
    assert msg.channel == ChannelType.WHATSAPP
    assert msg.status == MultiChannelStatus.QUEUED
    assert msg.to_handle == "+353 91 555 123"
