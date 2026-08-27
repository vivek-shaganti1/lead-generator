"""Database schema.

Two-layer design on purpose:
  Business  -> the deduplicated real-world place we discovered (source of truth about the place)
  Lead      -> our outreach relationship with that place (email, status, campaign)
A Business with no usable email never becomes a Lead, so outreach tables stay clean.
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


# --------------------------------------------------------------------------- enums
class LeadStatus(str, enum.Enum):
    NEW = "NEW"                      # created, not yet enriched
    NEEDS_APPROVAL = "NEEDS_APPROVAL"  # enriched, waiting for a human to green-light
    READY = "READY"                  # approved + eligible, waiting for a send slot
    QUEUED = "QUEUED"                # handed to the sender task
    CONTACTED = "CONTACTED"          # first email delivered
    FOLLOWED_UP = "FOLLOWED_UP"      # at least one follow-up delivered
    REPLIED = "REPLIED"              # reply received, not yet classified
    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    NEGATIVE = "NEGATIVE"
    UNSUBSCRIBED = "UNSUBSCRIBED"
    BOUNCED = "BOUNCED"
    DO_NOT_CONTACT = "DO_NOT_CONTACT"  # compliance block (country, suppression, opt-out)
    FAILED = "FAILED"
    WON = "WON"

    @classmethod
    def terminal(cls) -> set["LeadStatus"]:
        return {cls.UNSUBSCRIBED, cls.BOUNCED, cls.DO_NOT_CONTACT, cls.NEGATIVE, cls.WON}


class MessageStatus(str, enum.Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    BOUNCED = "BOUNCED"
    SKIPPED = "SKIPPED"


class ReplyClass(str, enum.Enum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"
    QUESTION = "QUESTION"
    UNSUBSCRIBE = "UNSUBSCRIBE"
    AUTO_REPLY = "AUTO_REPLY"
    BOUNCE = "BOUNCE"
    UNKNOWN = "UNKNOWN"


class DiscoveryStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class DealStage(str, enum.Enum):
    PROSPECT = "PROSPECT"
    CONTACTED = "CONTACTED"
    QUALIFIED = "QUALIFIED"
    PROPOSAL_SENT = "PROPOSAL_SENT"
    NEGOTIATION = "NEGOTIATION"
    WON = "WON"
    LOST = "LOST"


class ChannelType(str, enum.Enum):
    EMAIL = "EMAIL"
    LINKEDIN = "LINKEDIN"
    WHATSAPP = "WHATSAPP"
    SMS = "SMS"
    CONTACT_FORM = "CONTACT_FORM"
    TELEGRAM = "TELEGRAM"


class MessageDirection(str, enum.Enum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class MultiChannelStatus(str, enum.Enum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    READ = "READ"
    REPLIED = "REPLIED"
    FAILED = "FAILED"


class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    MEMBER = "MEMBER"
    VIEWER = "VIEWER"


# --------------------------------------------------------------------------- auth
class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, native_enum=False), default=UserRole.ADMIN)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# --------------------------------------------------------------------------- places
class Business(Base, TimestampMixin):
    """A physical business discovered from a map provider or reference sheet."""

    __tablename__ = "businesses"
    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_business_source"),
        Index("ix_business_dedupe", "dedupe_key"),
        Index("ix_business_country_category", "country_code", "category"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32))          # overpass | google | manual | import
    source_id: Mapped[str] = mapped_column(String(128))
    dedupe_key: Mapped[str] = mapped_column(String(160))

    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(96))
    phone: Mapped[str | None] = mapped_column(String(64))
    email: Mapped[str | None] = mapped_column(String(320))
    website: Mapped[str | None] = mapped_column(String(512))
    has_website: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    website_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    website_alive: Mapped[bool | None] = mapped_column(Boolean)

    # v2.0 Enriched Intelligence
    rating: Mapped[float | None] = mapped_column(Float)
    review_count: Mapped[int | None] = mapped_column(Integer, default=0)
    reviews_sample: Mapped[list] = mapped_column(JSON, default=list)
    opening_hours: Mapped[dict] = mapped_column(JSON, default=dict)
    photos: Mapped[list] = mapped_column(JSON, default=list)
    booking_url: Mapped[str | None] = mapped_column(String(512))
    description: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    operational_status: Mapped[str | None] = mapped_column(String(32), default="OPERATIONAL")
    tech_stack: Mapped[list] = mapped_column(JSON, default=list)
    estimated_revenue: Mapped[str | None] = mapped_column(String(64))
    estimated_employees: Mapped[str | None] = mapped_column(String(32))
    data_provenance: Mapped[dict] = mapped_column(JSON, default=dict)

    # social presence is a strong signal: a facebook-only business is our ideal lead
    facebook: Mapped[str | None] = mapped_column(String(512))
    instagram: Mapped[str | None] = mapped_column(String(512))
    linkedin: Mapped[str | None] = mapped_column(String(512))

    address: Mapped[str | None] = mapped_column(String(512))
    city: Mapped[str | None] = mapped_column(String(128))
    region: Mapped[str | None] = mapped_column(String(128))
    postcode: Mapped[str | None] = mapped_column(String(32))
    country_code: Mapped[str | None] = mapped_column(String(2), index=True)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    timezone_name: Mapped[str | None] = mapped_column(String(64))

    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    discovery_run_id: Mapped[int | None] = mapped_column(ForeignKey("discovery_runs.id"))

    leads: Mapped[list["Lead"]] = relationship(back_populates="business")
    audits: Mapped[list["BusinessAudit"]] = relationship(back_populates="business", cascade="all, delete-orphan")
    competitors: Mapped[list["Competitor"]] = relationship(back_populates="business", cascade="all, delete-orphan")
    deals: Mapped[list["Deal"]] = relationship(back_populates="business")


class DiscoveryRun(Base, TimestampMixin):
    __tablename__ = "discovery_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    area_label: Mapped[str] = mapped_column(String(255))
    query: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[DiscoveryStatus] = mapped_column(
        Enum(DiscoveryStatus, native_enum=False), default=DiscoveryStatus.PENDING
    )
    found_total: Mapped[int] = mapped_column(Integer, default=0)
    without_website: Mapped[int] = mapped_column(Integer, default=0)
    new_businesses: Mapped[int] = mapped_column(Integer, default=0)
    leads_created: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# --------------------------------------------------------------------------- outreach
class Campaign(Base, TimestampMixin):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    subject_template: Mapped[str] = mapped_column(Text)
    body_template: Mapped[str] = mapped_column(Text)
    followup_subject_template: Mapped[str | None] = mapped_column(Text)
    followup_body_template: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(8), default="en")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    daily_cap: Mapped[int | None] = mapped_column(Integer)

    leads: Mapped[list["Lead"]] = relationship(back_populates="campaign")


class Lead(Base, TimestampMixin):
    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("business_id", "campaign_id", name="uq_lead_business_campaign"),
        Index("ix_lead_status_next", "status", "next_action_at"),
        Index("ix_lead_email", "email"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"))
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id"))

    email: Mapped[str] = mapped_column(String(320))
    email_source: Mapped[str] = mapped_column(String(48), default="unknown")
    email_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    is_role_account: Mapped[bool] = mapped_column(Boolean, default=False)
    contact_name: Mapped[str | None] = mapped_column(String(160))

    status: Mapped[LeadStatus] = mapped_column(
        Enum(LeadStatus, native_enum=False), default=LeadStatus.NEW, index=True
    )
    score: Mapped[float] = mapped_column(Float, default=0.0)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    unsubscribe_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    followups_sent: Mapped[int] = mapped_column(Integer, default=0)
    last_contacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reply_class: Mapped[ReplyClass | None] = mapped_column(Enum(ReplyClass, native_enum=False))
    reply_confidence: Mapped[float | None] = mapped_column(Float)
    ai_summary: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    block_reason: Mapped[str | None] = mapped_column(String(255))

    business: Mapped[Business] = relationship(back_populates="leads")
    campaign: Mapped[Campaign | None] = relationship(back_populates="leads")
    messages: Mapped[list["EmailMessage"]] = relationship(
        back_populates="lead", cascade="all, delete-orphan"
    )
    deals: Mapped[list["Deal"]] = relationship(back_populates="lead")
    multichannel_messages: Mapped[list["MultiChannelMessage"]] = relationship(
        back_populates="lead", cascade="all, delete-orphan"
    )


class BusinessAudit(Base, TimestampMixin):
    """360° AI and technical audit of a business and its web presence."""

    __tablename__ = "business_audits"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)

    digital_presence_score: Mapped[float] = mapped_column(Float, default=0.0)
    website_quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    seo_score: Mapped[float] = mapped_column(Float, default=0.0)
    mobile_score: Mapped[float] = mapped_column(Float, default=0.0)
    accessibility_score: Mapped[float] = mapped_column(Float, default=0.0)
    speed_score: Mapped[float] = mapped_column(Float, default=0.0)
    trust_score: Mapped[float] = mapped_column(Float, default=0.0)

    swot_analysis: Mapped[dict] = mapped_column(JSON, default=dict)
    audit_details: Mapped[dict] = mapped_column(JSON, default=dict)
    suggested_pitch: Mapped[str | None] = mapped_column(Text)
    buying_intent_score: Mapped[float] = mapped_column(Float, default=0.0)
    buying_intent_rationale: Mapped[str | None] = mapped_column(Text)

    business: Mapped[Business] = relationship(back_populates="audits")


class Competitor(Base, TimestampMixin):
    """Discovered local competitor benchmarked against a target business."""

    __tablename__ = "competitors"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)

    name: Mapped[str] = mapped_column(String(255))
    website: Mapped[str | None] = mapped_column(String(512))
    rating: Mapped[float | None] = mapped_column(Float)
    review_count: Mapped[int | None] = mapped_column(Integer, default=0)
    tech_stack: Mapped[list] = mapped_column(JSON, default=list)
    social_presence: Mapped[dict] = mapped_column(JSON, default=dict)
    speed_score: Mapped[float | None] = mapped_column(Float)

    advantages: Mapped[list] = mapped_column(JSON, default=list)
    gaps: Mapped[list] = mapped_column(JSON, default=list)

    business: Mapped[Business] = relationship(back_populates="competitors")


class Deal(Base, TimestampMixin):
    """CRM Opportunity / Deal in the sales pipeline."""

    __tablename__ = "deals"
    __table_args__ = (
        Index("ix_deal_stage", "stage"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id", ondelete="SET NULL"), index=True)
    business_id: Mapped[int | None] = mapped_column(ForeignKey("businesses.id", ondelete="SET NULL"), index=True)

    title: Mapped[str] = mapped_column(String(255))
    company_name: Mapped[str] = mapped_column(String(255))
    contact_name: Mapped[str | None] = mapped_column(String(160))
    contact_email: Mapped[str | None] = mapped_column(String(320))
    stage: Mapped[DealStage] = mapped_column(
        Enum(DealStage, native_enum=False), default=DealStage.PROSPECT, index=True
    )
    value: Mapped[float] = mapped_column(Float, default=0.0)
    probability: Mapped[float] = mapped_column(Float, default=10.0)
    expected_close_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    win_loss_reason: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    business: Mapped[Business | None] = relationship(back_populates="deals")
    lead: Mapped[Lead | None] = relationship(back_populates="deals")


class MultiChannelMessage(Base, TimestampMixin):
    """Outreach message across Email, LinkedIn, WhatsApp, SMS, or Contact Form."""

    __tablename__ = "multichannel_messages"
    __table_args__ = (
        Index("ix_mc_lead_channel", "lead_id", "channel"),
        Index("ix_mc_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"))
    channel: Mapped[ChannelType] = mapped_column(
        Enum(ChannelType, native_enum=False), default=ChannelType.EMAIL, index=True
    )
    direction: Mapped[MessageDirection] = mapped_column(
        Enum(MessageDirection, native_enum=False), default=MessageDirection.OUTBOUND
    )

    to_handle: Mapped[str] = mapped_column(String(320))
    from_handle: Mapped[str | None] = mapped_column(String(320))
    subject: Mapped[str | None] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[MultiChannelStatus] = mapped_column(
        Enum(MultiChannelStatus, native_enum=False), default=MultiChannelStatus.PENDING, index=True
    )
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    lead: Mapped[Lead] = relationship(back_populates="multichannel_messages")


class DeliverabilityHealth(Base, TimestampMixin):
    """Monitors sender domain DNS, SPF, DKIM, DMARC, BIMI and blacklist safety."""

    __tablename__ = "deliverability_health"

    id: Mapped[int] = mapped_column(primary_key=True)
    domain: Mapped[str] = mapped_column(String(255), unique=True, index=True)

    spf_valid: Mapped[bool] = mapped_column(Boolean, default=False)
    dkim_valid: Mapped[bool] = mapped_column(Boolean, default=False)
    dmarc_valid: Mapped[bool] = mapped_column(Boolean, default=False)
    bimi_valid: Mapped[bool] = mapped_column(Boolean, default=False)

    blacklist_status: Mapped[dict] = mapped_column(JSON, default=dict)
    spam_score: Mapped[float] = mapped_column(Float, default=0.0)
    reputation_score: Mapped[float] = mapped_column(Float, default=100.0)

    is_paused: Mapped[bool] = mapped_column(Boolean, default=False)
    pause_reason: Mapped[str | None] = mapped_column(String(255))
    last_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LearningTelemetry(Base, TimestampMixin):
    """Tracks performance signals to autonomously optimize copy, hooks, and timing."""

    __tablename__ = "learning_telemetry"
    __table_args__ = (
        Index("ix_learn_industry", "industry"),
        Index("ix_learn_campaign", "campaign_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id"))
    industry: Mapped[str | None] = mapped_column(String(96))
    country_code: Mapped[str | None] = mapped_column(String(2))
    subject_line: Mapped[str] = mapped_column(String(255))
    hook_style: Mapped[str | None] = mapped_column(String(64))

    sends_count: Mapped[int] = mapped_column(Integer, default=0)
    opens_count: Mapped[int] = mapped_column(Integer, default=0)
    clicks_count: Mapped[int] = mapped_column(Integer, default=0)
    replies_count: Mapped[int] = mapped_column(Integer, default=0)
    positive_count: Mapped[int] = mapped_column(Integer, default=0)
    deals_won: Mapped[int] = mapped_column(Integer, default=0)
    conversion_rate: Mapped[float] = mapped_column(Float, default=0.0)


class EmailMessage(Base, TimestampMixin):
    __tablename__ = "email_messages"
    __table_args__ = (
        Index("ix_msg_lead_step", "lead_id", "step"),
        Index("ix_msg_sent_at", "sent_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"))
    step: Mapped[int] = mapped_column(Integer, default=0)  # 0 = initial, 1..n = follow-ups
    direction: Mapped[str] = mapped_column(String(8), default="out")

    to_email: Mapped[str] = mapped_column(String(320))
    from_email: Mapped[str] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(Text)
    body_text: Mapped[str] = mapped_column(Text)
    body_html: Mapped[str | None] = mapped_column(Text)

    message_id: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    status: Mapped[MessageStatus] = mapped_column(
        Enum(MessageStatus, native_enum=False), default=MessageStatus.PENDING, index=True
    )
    error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    open_count: Mapped[int] = mapped_column(Integer, default=0)
    clicked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)

    lead: Mapped[Lead] = relationship(back_populates="messages")


class InboundMessage(Base, TimestampMixin):
    __tablename__ = "inbound_messages"
    __table_args__ = (Index("ix_inbound_received", "received_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id", ondelete="SET NULL"))
    message_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    in_reply_to: Mapped[str | None] = mapped_column(String(255), index=True)
    from_email: Mapped[str] = mapped_column(String(320), index=True)
    subject: Mapped[str | None] = mapped_column(Text)
    body_text: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    classification: Mapped[ReplyClass] = mapped_column(
        Enum(ReplyClass, native_enum=False), default=ReplyClass.UNKNOWN, index=True
    )
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    classifier: Mapped[str] = mapped_column(String(32), default="rules")
    summary: Mapped[str | None] = mapped_column(Text)
    notified: Mapped[bool] = mapped_column(Boolean, default=False)


class Suppression(Base, TimestampMixin):
    """Never contact these again. Matched on exact email or on domain."""

    __tablename__ = "suppressions"
    __table_args__ = (UniqueConstraint("value", "kind", name="uq_suppression"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), default="email")  # email | domain
    value: Mapped[str] = mapped_column(String(320), index=True)
    reason: Mapped[str] = mapped_column(String(255), default="manual")


class DailyStat(Base, TimestampMixin):
    """Materialised daily counters. Cheap dashboard reads, immune to table growth."""

    __tablename__ = "daily_stats"
    __table_args__ = (UniqueConstraint("day", name="uq_daily_stat_day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD (UTC)
    discovered: Mapped[int] = mapped_column(Integer, default=0)
    leads_created: Mapped[int] = mapped_column(Integer, default=0)
    emails_sent: Mapped[int] = mapped_column(Integer, default=0)
    followups_sent: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    opened: Mapped[int] = mapped_column(Integer, default=0)
    replies: Mapped[int] = mapped_column(Integer, default=0)
    positive: Mapped[int] = mapped_column(Integer, default=0)
    negative: Mapped[int] = mapped_column(Integer, default=0)
    neutral: Mapped[int] = mapped_column(Integer, default=0)
    unsubscribes: Mapped[int] = mapped_column(Integer, default=0)
    bounces: Mapped[int] = mapped_column(Integer, default=0)


class Event(Base):
    """Append-only audit trail. Every state change lands here."""

    __tablename__ = "events"
    __table_args__ = (Index("ix_event_type_time", "type", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(64))
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id", ondelete="SET NULL"))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AppSetting(Base, TimestampMixin):
    """Runtime-editable overrides so the dashboard can change policy without a redeploy."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
