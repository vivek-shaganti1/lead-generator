"""Telegram notifications.

Instant ping the moment a lead says yes, plus a daily digest. Failures here are
always swallowed: a notification outage must never stop the pipeline or lose a
reply that we have already stored.
"""
from __future__ import annotations

import html as html_lib

import httpx

from app.config import settings
from app.logging_config import get_logger
from app.utils import truncate

log = get_logger(__name__)

API_BASE = "https://api.telegram.org"


class TelegramClient:
    def __init__(
        self,
        token: str | None = None,
        chat_id: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._token = token if token is not None else settings.telegram_bot_token
        self._chat_id = chat_id if chat_id is not None else settings.telegram_chat_id
        self._client = client

    @property
    def enabled(self) -> bool:
        return bool(self._token and self._chat_id)

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=15)
        return self._client

    def send(self, text: str, *, disable_preview: bool = True) -> bool:
        if not self.enabled:
            log.debug("telegram.disabled")
            return False
        try:
            response = self._http().post(
                f"{API_BASE}/bot{self._token}/sendMessage",
                json={
                    "chat_id": self._chat_id,
                    "text": text[:4096],
                    "parse_mode": "HTML",
                    "disable_web_page_preview": disable_preview,
                },
            )
            if response.status_code >= 400:
                log.warning("telegram.send_failed", status=response.status_code,
                            body=response.text[:200])
                return False
            return True
        except httpx.HTTPError as exc:
            log.warning("telegram.send_error", error=str(exc))
            return False

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


def _esc(value) -> str:
    return html_lib.escape(str(value or ""))


def format_positive_reply(lead, business, inbound) -> str:
    lines = [
        "🟢 <b>POSITIVE REPLY</b>",
        "",
        f"<b>{_esc(business.name)}</b>",
        f"📍 {_esc(', '.join(p for p in [business.city, business.country_code] if p))}",
        f"✉️ {_esc(lead.email)}",
    ]
    if business.phone:
        lines.append(f"📞 {_esc(business.phone)}")
    if business.category:
        lines.append(f"🏷 {_esc(business.category)}")
    lines += [
        f"⭐ score {lead.score:.0f}",
        "",
        f"<b>Subject:</b> {_esc(truncate(inbound.subject, 120))}",
        "",
        f"<i>{_esc(truncate(inbound.body_text, 600))}</i>",
    ]
    if inbound.summary:
        lines += ["", f"🤖 {_esc(inbound.summary)}"]
    lines += ["", f"🔗 {settings.public_base_url.rstrip('/')}/leads/{lead.id}"]
    return "\n".join(lines)


def format_reply(lead, business, inbound) -> str:
    icon = {"POSITIVE": "🟢", "NEGATIVE": "🔴", "QUESTION": "🟡",
            "UNSUBSCRIBE": "⛔", "AUTO_REPLY": "🤖", "BOUNCE": "↩️"}.get(
        inbound.classification.value, "⚪"
    )
    return (
        f"{icon} <b>{_esc(inbound.classification.value)}</b> — {_esc(business.name)}\n"
        f"✉️ {_esc(lead.email)}\n\n<i>{_esc(truncate(inbound.body_text, 400))}</i>"
    )


def format_daily_digest(stats: dict) -> str:
    return "\n".join(
        [
            f"📊 <b>Daily report — {_esc(stats.get('day'))}</b>",
            "",
            f"📤 Sent: <b>{stats.get('emails_sent', 0)}</b> "
            f"(+{stats.get('followups_sent', 0)} follow-ups)",
            f"👀 Opened: {stats.get('opened', 0)}",
            f"📥 Replies: <b>{stats.get('replies', 0)}</b>",
            f"   🟢 Positive: <b>{stats.get('positive', 0)}</b>",
            f"   🔴 Negative: {stats.get('negative', 0)}",
            f"   ⚪ Neutral: {stats.get('neutral', 0)}",
            f"⛔ Unsubscribes: {stats.get('unsubscribes', 0)}",
            f"↩️ Bounces: {stats.get('bounces', 0)}",
            "",
            f"🔎 Discovered: {stats.get('discovered', 0)} • "
            f"New leads: {stats.get('leads_created', 0)}",
            f"❌ Failed sends: {stats.get('failed', 0)}",
        ]
    )


def format_alert(title: str, detail: str) -> str:
    return f"⚠️ <b>{_esc(title)}</b>\n\n{_esc(truncate(detail, 800))}"


_client: TelegramClient | None = None


def get_client() -> TelegramClient:
    global _client
    if _client is None:
        _client = TelegramClient()
    return _client


def set_client(client: TelegramClient | None) -> None:
    global _client
    _client = client


def notify(text: str) -> bool:
    return get_client().send(text)
