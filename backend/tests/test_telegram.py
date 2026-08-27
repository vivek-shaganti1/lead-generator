from __future__ import annotations

import httpx

from app.models import InboundMessage, ReplyClass
from app.services.notify import telegram
from app.utils import utcnow
from tests.conftest import make_lead


def _inbound(**kw) -> InboundMessage:
    base = dict(message_id="<r@x>", from_email="owner@rossis.ie", subject="Re: website",
                body_text="Yes please, how much?", received_at=utcnow(),
                classification=ReplyClass.POSITIVE, confidence=0.9)
    base.update(kw)
    return InboundMessage(**base)


def test_disabled_client_never_sends():
    client = telegram.TelegramClient(token="", chat_id="")
    assert client.enabled is False
    assert client.send("hello") is False


def test_send_posts_to_telegram_api():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["url"] = str(request.url)
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    client = telegram.TelegramClient(
        token="tok", chat_id="42",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert client.send("hello") is True
    assert captured["url"].endswith("/bottok/sendMessage")
    assert captured["chat_id"] == "42"
    assert captured["parse_mode"] == "HTML"


def test_send_reports_api_failure():
    client = telegram.TelegramClient(
        token="tok", chat_id="42",
        client=httpx.Client(transport=httpx.MockTransport(
            lambda r: httpx.Response(400, text="bad chat id"))),
    )
    assert client.send("hello") is False


def test_send_swallows_network_errors():
    def handler(request):
        raise httpx.ConnectError("no route")

    client = telegram.TelegramClient(
        token="tok", chat_id="42",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert client.send("hello") is False


def test_positive_reply_message_contains_everything_needed(db, campaign):
    lead = make_lead(db, campaign=campaign, email="owner@rossis.ie", score=88)
    text = telegram.format_positive_reply(lead, lead.business, _inbound())
    assert "POSITIVE REPLY" in text
    assert "owner@rossis.ie" in text
    assert "+353 21 555 0100" in text
    assert "Cork" in text
    assert "score 88" in text
    assert f"/leads/{lead.id}" in text


def test_message_escapes_html(db, campaign):
    lead = make_lead(db, campaign=campaign)
    lead.business.name = "<b>Injected</b>"
    text = telegram.format_positive_reply(lead, lead.business,
                                          _inbound(body_text="<script>x</script>"))
    assert "<b>Injected</b>" not in text.replace("<b>", "", 1)
    assert "&lt;script&gt;" in text


def test_reply_message_icons_by_class(db, campaign):
    lead = make_lead(db, campaign=campaign)
    negative = telegram.format_reply(lead, lead.business,
                                     _inbound(classification=ReplyClass.NEGATIVE))
    assert "🔴" in negative and "NEGATIVE" in negative


def test_daily_digest_formats_all_counters():
    text = telegram.format_daily_digest({
        "day": "2026-08-25", "emails_sent": 40, "followups_sent": 12, "opened": 18,
        "replies": 6, "positive": 3, "negative": 2, "neutral": 1, "unsubscribes": 1,
        "bounces": 2, "discovered": 300, "leads_created": 45, "failed": 0,
    })
    for fragment in ("2026-08-25", "40", "12", "Positive: <b>3</b>", "Bounces: 2",
                     "Discovered: 300"):
        assert fragment in text


def test_alert_formatting():
    assert "⚠️" in telegram.format_alert("SMTP down", "connection refused")


def test_long_message_is_truncated_to_api_limit():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    client = telegram.TelegramClient(
        token="t", chat_id="1",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    client.send("x" * 9000)
    assert len(captured["text"]) == 4096
