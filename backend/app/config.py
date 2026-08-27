"""Central configuration. Everything is env-driven so the same image runs anywhere."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Anchored to the repo, not to the working directory. A bare env_file=".env" is
# resolved against the CWD, and every local entrypoint (uvicorn, celery, alembic)
# runs from backend/ — so the repo-root .env was silently ignored and the code
# defaults won instead. Docker never hit this because compose injects .env as
# real environment variables. Both paths are listed; the later one wins, so a
# backend/.env can still override for a single checkout.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_DIR.parent

def env_files_for(env: str | None) -> tuple[Path, ...] | None:
    """Which .env files to load, or None to load none.

    The suite must not inherit whatever a developer happens to have in .env, or a
    local edit turns into a red build on one machine only. conftest sets ENV=test
    before this module is imported.
    """
    if env == "test":
        return None
    return (_REPO_ROOT / ".env", _BACKEND_DIR / ".env")


_ENV_FILES = env_files_for(os.environ.get("ENV"))


def anchor_sqlite_path(url: str) -> str:
    """Resolve a relative SQLite path against the repo, not the CWD.

    Same trap as env_file: `sqlite:///./leadgen.db` means a different file
    depending on whether you ran uvicorn from the repo root or from backend/,
    so migrations land in one database and the app reads another. In-memory and
    already-absolute URLs are left alone.
    """
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return url
    path = url[len(prefix):]
    if not path or path.startswith("/") or path.startswith(":memory:"):
        return url
    return prefix + str((_REPO_ROOT / path).resolve())


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- core ----
    env: Literal["dev", "test", "prod"] = "dev"
    debug: bool = True
    secret_key: str = "change-me-in-production-please-32chars-min"
    database_url: str = "postgresql+psycopg://leadgen:leadgen@postgres:5432/leadgen"
    redis_url: str = "redis://redis:6379/0"
    public_base_url: str = "http://localhost:8000"
    cors_origins: str = "http://localhost:3000"

    # ---- dashboard auth ----
    admin_email: str = "admin@example.com"
    admin_password: str = "changeme123"
    jwt_ttl_minutes: int = 60 * 12
    # slowapi limit string applied to the unauthenticated login endpoint.
    auth_rate_limit: str = "10/minute"

    # ---- sender identity (used in every email + CAN-SPAM footer) ----
    company_name: str = "Your Web Studio"
    company_address: str = "Street, City, Country"
    company_website: str = "https://example.com"
    sender_name: str = "Vivek"
    sender_email: str = "hello@example.com"
    reply_to_email: str = ""
    calendar_link: str = ""

    # ---- SMTP ----
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    smtp_ssl: bool = False
    smtp_timeout: int = 30

    # ---- IMAP (reply + bounce detection) ----
    imap_host: str = ""
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""
    imap_ssl: bool = True
    imap_folder: str = "INBOX"
    imap_poll_seconds: int = 120

    # ---- sending policy ----
    daily_send_cap: int = 200
    warmup_enabled: bool = True
    warmup_start: int = 20
    warmup_increment: int = 15
    min_seconds_between_sends: int = 45
    max_per_domain_per_day: int = 2
    send_window_start_hour: int = 9   # local time of the lead
    send_window_end_hour: int = 17
    send_on_weekends: bool = False
    dry_run: bool = True  # never actually delivers mail until explicitly disabled
    track_opens: bool = True  # embed the 1x1 open-tracking pixel in outbound HTML

    # ---- follow-ups ----
    followup_enabled: bool = True
    followup_delays_days: str = "3,7"   # comma separated, one per follow-up step
    max_followups: int = 2

    # ---- discovery ----
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    overpass_timeout: int = 180
    overpass_min_interval_seconds: float = 5.0
    google_places_api_key: str = ""
    google_places_enabled: bool = False
    discovery_max_results_per_run: int = 500

    # ---- enrichment ----
    enable_website_email_scrape: bool = True
    http_user_agent: str = "LeadGenBot/1.0 (+contact: {email})"
    scrape_timeout: int = 15
    verify_mx: bool = True

    # ---- AI ----
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    ai_classify_replies: bool = True
    ai_personalize_copy: bool = False

    # ---- Telegram ----
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_notify_positive: bool = True
    telegram_notify_any_reply: bool = False
    telegram_daily_digest_hour: int = 20

    # ---- compliance ----
    # Countries where unsolicited B2B email needs prior consent -> never auto-send.
    blocked_countries: str = "DE,AT,CH,IT,GR,FI,HU,PL,SI,SK,HR,LT,LV,EE,PT,ES,CZ,BG,RO,DK,NO,IS"
    require_manual_approval: bool = True
    honour_role_accounts: bool = True  # info@/contact@ are fine for B2B, but tracked separately

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, v: str) -> str:
        if v.startswith("postgres://"):
            v = v.replace("postgres://", "postgresql+psycopg://", 1)
        elif v.startswith("postgresql://") and not v.startswith("postgresql+"):
            v = v.replace("postgresql://", "postgresql+psycopg://", 1)
        elif v.startswith("sqlite"):
            v = anchor_sqlite_path(v)
        return v

    @field_validator("secret_key")
    @classmethod
    def _secret_len(cls, v: str) -> str:
        if len(v) < 16:
            raise ValueError("SECRET_KEY must be at least 16 characters")
        return v

    # ---- derived helpers ----
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def blocked_country_set(self) -> set[str]:
        return {c.strip().upper() for c in self.blocked_countries.split(",") if c.strip()}

    @property
    def followup_delay_list(self) -> list[int]:
        out = []
        for part in self.followup_delays_days.split(","):
            part = part.strip()
            if part:
                out.append(int(part))
        return out

    @property
    def effective_reply_to(self) -> str:
        return self.reply_to_email or self.sender_email

    @property
    def user_agent(self) -> str:
        try:
            return self.http_user_agent.format(email=self.sender_email)
        except (KeyError, IndexError):
            return self.http_user_agent


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
