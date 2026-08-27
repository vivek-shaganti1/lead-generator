export type LeadStatus =
  | "NEW" | "NEEDS_APPROVAL" | "READY" | "QUEUED" | "CONTACTED" | "FOLLOWED_UP"
  | "REPLIED" | "POSITIVE" | "NEUTRAL" | "NEGATIVE" | "UNSUBSCRIBED" | "BOUNCED"
  | "DO_NOT_CONTACT" | "FAILED" | "WON";

export type ReplyClass =
  | "POSITIVE" | "NEGATIVE" | "NEUTRAL" | "QUESTION" | "UNSUBSCRIBE"
  | "AUTO_REPLY" | "BOUNCE" | "UNKNOWN";

export interface Business {
  id: number;
  source: string;
  name: string;
  category: string | null;
  phone: string | null;
  email: string | null;
  website: string | null;
  has_website: boolean;
  website_alive: boolean | null;
  facebook: string | null;
  instagram: string | null;
  address: string | null;
  city: string | null;
  region: string | null;
  country_code: string | null;
  lat: number | null;
  lon: number | null;
  timezone_name: string | null;
  created_at: string;
}

export interface EmailMessage {
  id: number;
  step: number;
  subject: string;
  body_text: string;
  status: "PENDING" | "SENT" | "FAILED" | "BOUNCED" | "SKIPPED";
  to_email: string;
  error: string | null;
  sent_at: string | null;
  opened_at: string | null;
  open_count: number;
  dry_run: boolean;
}

export interface InboundMessage {
  id: number;
  from_email: string;
  subject: string | null;
  body_text: string;
  classification: ReplyClass;
  confidence: number;
  classifier: string;
  summary: string | null;
  received_at: string;
}

export interface Lead {
  id: number;
  email: string;
  email_source: string;
  email_confidence: number;
  is_role_account: boolean;
  contact_name: string | null;
  status: LeadStatus;
  score: number;
  approved: boolean;
  followups_sent: number;
  last_contacted_at: string | null;
  next_action_at: string | null;
  replied_at: string | null;
  reply_class: ReplyClass | null;
  ai_summary: string | null;
  block_reason: string | null;
  notes: string | null;
  created_at: string;
  business: Business;
  messages?: EmailMessage[];
}

export interface PaginatedLeads {
  items: Lead[];
  total: number;
  page: number;
  page_size: number;
}

export interface Campaign {
  id: number;
  name: string;
  subject_template: string;
  body_template: string;
  followup_subject_template: string | null;
  followup_body_template: string | null;
  language: string;
  is_active: boolean;
  daily_cap: number | null;
  created_at: string;
}

export interface DiscoveryRun {
  id: number;
  provider: string;
  area_label: string;
  status: "PENDING" | "RUNNING" | "SUCCESS" | "PARTIAL" | "FAILED";
  found_total: number;
  without_website: number;
  new_businesses: number;
  leads_created: number;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

export interface DaySeries {
  day: string;
  emails_sent: number;
  followups_sent: number;
  opened: number;
  replies: number;
  positive: number;
  negative: number;
  neutral: number;
  bounces: number;
  unsubscribes: number;
  leads_created: number;
  discovered: number;
}

export interface Dashboard {
  generated_at: string;
  totals: {
    outbound: {
      businesses_discovered: number;
      without_website: number;
      leads: number;
      emails_sent: number;
      unique_contacted: number;
      opened: number;
      open_rate: number;
    };
    inbound: {
      replies: number;
      positive: number;
      negative: number;
      neutral: number;
      bounces: number;
      unsubscribes: number;
      reply_rate: number;
      positive_rate: number;
      bounce_rate: number;
      unsubscribe_rate: number;
      won: number;
    };
  };
  today: Record<string, number | string>;
  sending: {
    day: string; cap: number; sent: number; remaining: number;
    warmup_day: number; warmup_enabled: boolean; dry_run: boolean;
  };
  funnel: { stage: string; count: number; pct_of_top: number }[];
  timeseries: DaySeries[];
  by_status: { status: string; count: number }[];
  by_country: { key: string; count: number }[];
  by_category: { key: string; count: number }[];
}

export interface AppConfig {
  env: string;
  dry_run: boolean;
  require_manual_approval: boolean;
  daily_send_cap: number;
  warmup_enabled: boolean;
  min_seconds_between_sends: number;
  max_per_domain_per_day: number;
  send_window: [number, number];
  send_on_weekends: boolean;
  followup_enabled: boolean;
  followup_delays_days: number[];
  max_followups: number;
  blocked_countries: string[];
  google_places_enabled: boolean;
  ai_classify_replies: boolean;
  sender: { name: string; email: string };
  company: { name: string; website: string };
  integrations: Record<string, boolean>;
}

export interface Suppression {
  id: number;
  kind: string;
  value: string;
  reason: string;
  created_at: string;
}

export interface CategoryOption {
  key: string;
  label: string;
  google_supported: boolean;
}

export interface SystemHealth {
  status: string;
  version: string;
  env: string;
  dry_run: boolean;
  database: boolean;
  redis: boolean;
  smtp_configured: boolean;
  imap_configured: boolean;
  telegram_configured: boolean;
  groq_configured: boolean;
}

export interface SendingStatus {
  day: string;
  cap: number;
  sent: number;
  remaining: number;
  warmup_day: number;
  warmup_enabled: boolean;
  dry_run: boolean;
}

export interface SuppressionInput {
  value: string;
  kind: "email" | "domain";
  reason: string;
}

export interface EmailTestResult {
  sent: boolean;
  dry_run: boolean;
  message_id: string | null;
}

export interface TelegramTestResult {
  sent: boolean;
}

export interface GroqTestResult {
  classification: string;
  confidence: number;
  classifier: string;
  summary: string | null;
}

export interface LeadImportResult {
  total_rows: number;
  candidates_parsed: number;
  businesses_created: number;
  businesses_updated: number;
  without_website: number;
  leads_created: number;
  leads_approved: number;
  errors: string[];
}

export type DealStage =
  | "PROSPECT"
  | "CONTACTED"
  | "QUALIFIED"
  | "PROPOSAL_SENT"
  | "NEGOTIATION"
  | "WON"
  | "LOST";

export interface Deal {
  id: number;
  lead_id: number | null;
  business_id: number | null;
  title: string;
  company_name: string;
  contact_name: string | null;
  contact_email: string | null;
  stage: DealStage;
  value: number;
  probability: number;
  expected_close_at: string | null;
  win_loss_reason: string | null;
  notes: string | null;
  created_at: string;
}

export interface KanbanStage {
  stage: DealStage;
  total_value: number;
  deals_count: number;
  deals: Deal[];
}

export interface PipelineSummary {
  total_pipeline_value: number;
  forecasted_value: number;
  total_deals: number;
  stages: KanbanStage[];
}

export interface BusinessAudit {
  id: number;
  business_id: number;
  digital_presence_score: number;
  website_quality_score: number;
  seo_score: number;
  mobile_score: number;
  accessibility_score: number;
  speed_score: number;
  trust_score: number;
  swot_analysis: {
    strengths?: string[];
    weaknesses?: string[];
    opportunities?: string[];
    threats?: string[];
  };
  audit_details: Record<string, any>;
  suggested_pitch: string | null;
  buying_intent_score: number;
  buying_intent_rationale: string | null;
  created_at: string;
}

export interface Competitor {
  id: number;
  business_id: number;
  name: string;
  website: string | null;
  rating: number | null;
  review_count: number;
  tech_stack: string[];
  social_presence: Record<string, string>;
  speed_score: number | null;
  advantages: string[];
  gaps: string[];
  created_at: string;
}

export interface DeliverabilityHealth {
  id: number;
  domain: string;
  spf_valid: boolean;
  dkim_valid: boolean;
  dmarc_valid: boolean;
  bimi_valid: boolean;
  blacklist_status: {
    blacklisted: boolean;
    zones?: string[];
  };
  spam_score: number;
  reputation_score: number;
  is_paused: boolean;
  pause_reason: string | null;
  last_checked_at: string;
}

export interface LearningInsight {
  category: string;
  headline: string;
  description: string;
  impact_level: "HIGH" | "MEDIUM" | "LOW";
  recommended_action: string;
}

export interface PitchResponse {
  business_id: number;
  channel: string;
  hook_style: string;
  subject_line: string;
  message_content: string;
  rationale: string;
  competitors_referenced: string[];
}


