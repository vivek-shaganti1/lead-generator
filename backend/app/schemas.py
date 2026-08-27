"""API request/response contracts."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import (
    ChannelType,
    DealStage,
    DiscoveryStatus,
    LeadStatus,
    MessageDirection,
    MessageStatus,
    MultiChannelStatus,
    ReplyClass,
    UserRole,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------- auth
class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


class UserOut(ORMModel):
    id: int
    email: str
    is_admin: bool
    last_login_at: datetime | None = None


# ----------------------------------------------------------------- discovery
class BBox(BaseModel):
    south: float = Field(ge=-90, le=90)
    west: float = Field(ge=-180, le=180)
    north: float = Field(ge=-90, le=90)
    east: float = Field(ge=-180, le=180)

    @field_validator("north")
    @classmethod
    def _check_lat(cls, v, info):
        south = info.data.get("south")
        if south is not None and v <= south:
            raise ValueError("north must be greater than south")
        return v

    @field_validator("east")
    @classmethod
    def _check_lon(cls, v, info):
        west = info.data.get("west")
        if west is not None and v <= west:
            raise ValueError("east must be greater than west")
        return v


class DiscoveryRequest(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    bbox: BBox | None = None
    area_name: str | None = Field(default=None, max_length=200)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    categories: list[str] | None = None
    limit: int = Field(default=500, ge=1, le=5000)
    use_google_fallback: bool | None = None
    run_async: bool = True

    @field_validator("country_code")
    @classmethod
    def _upper(cls, v):
        return v.upper() if v else v

    def validate_scope(self) -> None:
        if self.bbox is None and not self.area_name:
            raise ValueError("provide either bbox or area_name")


class DiscoveryRunOut(ORMModel):
    id: int
    provider: str
    area_label: str
    status: DiscoveryStatus
    found_total: int
    without_website: int
    new_businesses: int
    leads_created: int
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime


# ---------------------------------------------------------------- businesses
class BusinessOut(ORMModel):
    id: int
    source: str
    name: str
    category: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    has_website: bool
    website_alive: bool | None = None
    facebook: str | None = None
    instagram: str | None = None
    address: str | None = None
    city: str | None = None
    region: str | None = None
    country_code: str | None = None
    lat: float | None = None
    lon: float | None = None
    timezone_name: str | None = None
    created_at: datetime


# --------------------------------------------------------------------- leads
class MessageOut(ORMModel):
    id: int
    step: int
    subject: str
    body_text: str
    status: MessageStatus
    to_email: str
    error: str | None = None
    sent_at: datetime | None = None
    opened_at: datetime | None = None
    open_count: int
    dry_run: bool


class InboundOut(ORMModel):
    id: int
    from_email: str
    subject: str | None = None
    body_text: str
    classification: ReplyClass
    confidence: float
    classifier: str
    summary: str | None = None
    received_at: datetime


class LeadOut(ORMModel):
    id: int
    email: str
    email_source: str
    email_confidence: float
    is_role_account: bool
    contact_name: str | None = None
    status: LeadStatus
    score: float
    approved: bool
    followups_sent: int
    last_contacted_at: datetime | None = None
    next_action_at: datetime | None = None
    replied_at: datetime | None = None
    reply_class: ReplyClass | None = None
    ai_summary: str | None = None
    block_reason: str | None = None
    notes: str | None = None
    created_at: datetime
    business: BusinessOut


class LeadDetail(LeadOut):
    messages: list[MessageOut] = []


class LeadUpdate(BaseModel):
    status: LeadStatus | None = None
    approved: bool | None = None
    contact_name: str | None = Field(default=None, max_length=160)
    notes: str | None = Field(default=None, max_length=5000)
    email: EmailStr | None = None


class BulkAction(BaseModel):
    lead_ids: list[int] = Field(min_length=1, max_length=500)
    action: str = Field(pattern="^(approve|unapprove|suppress|delete|send_now)$")


class LeadImportRequest(BaseModel):
    csv_data: str = Field(min_length=1)
    campaign_id: int | None = None
    auto_qualify: bool = True
    auto_approve: bool | None = None
    auto_dispatch: bool = False
    default_category: str | None = None
    default_country: str | None = Field(default=None, max_length=2)


class LeadImportOut(BaseModel):
    total_rows: int
    candidates_parsed: int
    businesses_created: int
    businesses_updated: int
    without_website: int
    leads_created: int
    leads_approved: int
    leads_dispatched: int = 0
    errors: list[str] = Field(default_factory=list)


class PaginatedLeads(BaseModel):
    items: list[LeadOut]
    total: int
    page: int
    page_size: int


# ----------------------------------------------------------------- campaigns
class CampaignIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    subject_template: str = Field(min_length=1)
    body_template: str = Field(min_length=1)
    followup_subject_template: str | None = None
    followup_body_template: str | None = None
    language: str = "en"
    is_active: bool = True
    daily_cap: int | None = Field(default=None, ge=1, le=10000)


class CampaignOut(ORMModel):
    id: int
    name: str
    subject_template: str
    body_template: str
    followup_subject_template: str | None = None
    followup_body_template: str | None = None
    language: str
    is_active: bool
    daily_cap: int | None = None
    created_at: datetime


class PreviewRequest(BaseModel):
    lead_id: int | None = None
    campaign_id: int | None = None
    step: int = Field(default=0, ge=0, le=5)


class PreviewResponse(BaseModel):
    subject: str
    text: str
    html: str


# ------------------------------------------------------------------ settings
class SuppressionIn(BaseModel):
    value: str = Field(min_length=3, max_length=320)
    kind: str = Field(default="email", pattern="^(email|domain)$")
    reason: str = Field(default="manual", max_length=255)


class SuppressionOut(ORMModel):
    id: int
    kind: str
    value: str
    reason: str
    created_at: datetime


class TestEmailRequest(BaseModel):
    to_email: EmailStr


class HealthOut(BaseModel):
    status: str
    version: str
    env: str
    dry_run: bool
    database: bool
    redis: bool
    smtp_configured: bool
    imap_configured: bool
    telegram_configured: bool
    groq_configured: bool


# ------------------------------------------------------------------ v2.0 Intelligence & CRM
class BusinessAuditOut(ORMModel):
    id: int
    business_id: int
    digital_presence_score: float
    website_quality_score: float
    seo_score: float
    mobile_score: float
    accessibility_score: float
    speed_score: float
    trust_score: float
    swot_analysis: dict
    audit_details: dict
    suggested_pitch: str | None = None
    buying_intent_score: float
    buying_intent_rationale: str | None = None
    created_at: datetime


class CompetitorOut(ORMModel):
    id: int
    business_id: int
    name: str
    website: str | None = None
    rating: float | None = None
    review_count: int | None = 0
    tech_stack: list = Field(default_factory=list)
    social_presence: dict = Field(default_factory=dict)
    speed_score: float | None = None
    advantages: list = Field(default_factory=list)
    gaps: list = Field(default_factory=list)
    created_at: datetime


class DealIn(BaseModel):
    lead_id: int | None = None
    business_id: int | None = None
    title: str = Field(min_length=1, max_length=255)
    company_name: str = Field(min_length=1, max_length=255)
    contact_name: str | None = Field(default=None, max_length=160)
    contact_email: EmailStr | None = None
    stage: DealStage = DealStage.PROSPECT
    value: float = Field(default=0.0, ge=0)
    probability: float = Field(default=10.0, ge=0, le=100)
    expected_close_at: datetime | None = None
    notes: str | None = None


class DealUpdate(BaseModel):
    title: str | None = None
    company_name: str | None = None
    contact_name: str | None = None
    contact_email: EmailStr | None = None
    stage: DealStage | None = None
    value: float | None = Field(default=None, ge=0)
    probability: float | None = Field(default=None, ge=0, le=100)
    expected_close_at: datetime | None = None
    win_loss_reason: str | None = None
    notes: str | None = None


class DealOut(ORMModel):
    id: int
    lead_id: int | None = None
    business_id: int | None = None
    title: str
    company_name: str
    contact_name: str | None = None
    contact_email: str | None = None
    stage: DealStage
    value: float
    probability: float
    expected_close_at: datetime | None = None
    win_loss_reason: str | None = None
    notes: str | None = None
    created_at: datetime


class KanbanStageOut(BaseModel):
    stage: DealStage
    total_value: float
    deals_count: int
    deals: list[DealOut]


class PipelineOut(BaseModel):
    total_pipeline_value: float
    forecasted_value: float
    total_deals: int
    stages: list[KanbanStageOut]


class MultiChannelMessageIn(BaseModel):
    lead_id: int
    channel: ChannelType = ChannelType.EMAIL
    to_handle: str
    from_handle: str | None = None
    subject: str | None = None
    content: str
    metadata_json: dict = Field(default_factory=dict)


class MultiChannelMessageOut(ORMModel):
    id: int
    lead_id: int
    channel: ChannelType
    direction: MessageDirection
    to_handle: str
    from_handle: str | None = None
    subject: str | None = None
    content: str
    status: MultiChannelStatus
    metadata_json: dict
    sent_at: datetime | None = None
    delivered_at: datetime | None = None
    read_at: datetime | None = None
    created_at: datetime


class DeliverabilityHealthOut(ORMModel):
    id: int
    domain: str
    spf_valid: bool
    dkim_valid: bool
    dmarc_valid: bool
    bimi_valid: bool
    blacklist_status: dict
    spam_score: float
    reputation_score: float
    is_paused: bool
    pause_reason: str | None = None
    last_checked_at: datetime


class LearningTelemetryOut(ORMModel):
    id: int
    campaign_id: int | None = None
    industry: str | None = None
    country_code: str | None = None
    subject_line: str
    hook_style: str | None = None
    sends_count: int
    opens_count: int
    clicks_count: int
    replies_count: int
    positive_count: int
    deals_won: int
    conversion_rate: float


class PitchGenerationRequest(BaseModel):
    business_id: int
    channel: ChannelType = ChannelType.EMAIL
    hook_style: str = "competitor_gap"  # competitor_gap | audit_deficit | speed_loss | direct_offer
    tone: str = "consultative"


class PitchGenerationResponse(BaseModel):
    business_id: int
    channel: ChannelType
    hook_style: str
    subject_line: str
    message_content: str
    rationale: str
    competitors_referenced: list[str] = Field(default_factory=list)

