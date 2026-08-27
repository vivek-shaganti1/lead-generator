from __future__ import annotations

import httpx
import pytest

from app.config import settings
from app.models import ReplyClass
from app.services.ai.groq import (
    Classification,
    GroqClient,
    GroqError,
    classify_reply,
    parse_classification,
)
from app.services.ai.rules import classify, strip_quoted


# ---------------------------------------------------------------------- rules
@pytest.mark.parametrize(
    "body,expected",
    [
        ("Yes please, how much would it cost?", ReplyClass.POSITIVE),
        ("Sounds good, let's talk next week", ReplyClass.POSITIVE),
        ("Can you send me a mockup?", ReplyClass.POSITIVE),
        ("No thanks, we already have a website", ReplyClass.NEGATIVE),
        ("Not interested.", ReplyClass.NEGATIVE),
        ("Please remove me from your list", ReplyClass.UNSUBSCRIBE),
        ("Unsubscribe", ReplyClass.UNSUBSCRIBE),
        ("I am out of office until Monday", ReplyClass.AUTO_REPLY),
        ("Your message could not be delivered: 550 5.1.1 user unknown",
         ReplyClass.BOUNCE),
        ("Who are you and where did you get my address?", ReplyClass.QUESTION),
        ("Thanks.", ReplyClass.NEUTRAL),
    ],
)
def test_rule_classifier(body, expected):
    result, confidence, _ = classify(None, body)
    assert result == expected
    assert 0 <= confidence <= 1


def test_bounce_beats_every_other_marker():
    body = "Not interested. Delivery status notification: undeliverable"
    assert classify(None, body)[0] == ReplyClass.BOUNCE


def test_unsubscribe_beats_positive():
    assert classify(None, "Interested but please remove me from your list")[0] \
        == ReplyClass.UNSUBSCRIBE


def test_no_website_yet_plus_price_question_is_positive():
    # This is our best possible lead, not an ambiguous one.
    assert classify(None, "We don't have a website yet. How much is it?")[0] \
        == ReplyClass.POSITIVE


def test_mixed_signals_become_a_question():
    result, _, reason = classify(None, "Not interested right now, but how much would it cost?")
    assert result == ReplyClass.QUESTION
    assert "mixed" in reason


def test_strip_quoted_removes_original_message():
    body = (
        "Yes, interested!\n\n"
        "On Tue, 25 Aug 2026 at 10:00, Tester <hello@studio.test> wrote:\n"
        "> I couldn't find a website for your business\n"
    )
    cleaned = strip_quoted(body)
    assert "Yes, interested!" in cleaned
    assert "couldn't find" not in cleaned


def test_classification_ignores_our_own_quoted_pitch():
    body = (
        "No thanks.\n\n"
        "> Reply to this email and I'll send you a mockup, tell me more, "
        "how much would it cost\n"
    )
    assert classify(None, body)[0] == ReplyClass.NEGATIVE


# ----------------------------------------------------------------- groq parse
def test_parse_classification_valid():
    parsed = parse_classification(
        '{"classification":"POSITIVE","confidence":0.9,"summary":"wants a quote",'
        '"wants_call":true,"budget_mentioned":"500 EUR"}'
    )
    assert parsed.classification == ReplyClass.POSITIVE
    assert parsed.confidence == 0.9
    assert parsed.wants_call is True
    assert parsed.budget_mentioned == "500 EUR"
    assert parsed.classifier == "groq"


@pytest.mark.parametrize(
    "content",
    ["not json", "[]", '{"classification":"MAYBE"}', '{"confidence":0.5}', "null"],
)
def test_parse_classification_rejects_bad_output(content):
    assert parse_classification(content) is None


def test_parse_classification_clamps_confidence():
    assert parse_classification('{"classification":"NEUTRAL","confidence":9}').confidence == 1.0
    assert parse_classification('{"classification":"NEUTRAL","confidence":-2}').confidence == 0.0


def test_parse_classification_survives_bad_confidence_type():
    parsed = parse_classification('{"classification":"NEUTRAL","confidence":"high"}')
    assert parsed.confidence == 0.5


# --------------------------------------------------------------- groq client
def _groq_client(handler) -> GroqClient:
    return GroqClient(api_key="test-key",
                      client=httpx.Client(transport=httpx.MockTransport(handler)))


def _response(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def test_classify_reply_uses_groq_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "ai_classify_replies", True)
    client = _groq_client(lambda r: _response(
        '{"classification":"POSITIVE","confidence":0.93,"summary":"wants pricing"}'
    ))
    result = classify_reply("Re: website", "Hmm, tell me more about the numbers.",
                            client=client)
    assert result.classifier == "groq"
    assert result.classification == ReplyClass.POSITIVE
    assert result.summary == "wants pricing"


def test_classify_reply_falls_back_when_groq_errors(monkeypatch):
    monkeypatch.setattr(settings, "ai_classify_replies", True)
    client = _groq_client(lambda r: httpx.Response(500, text="boom"))
    result = classify_reply("Re: website", "Yes please, how much?", client=client)
    assert result.classifier == "rules"
    assert result.classification == ReplyClass.POSITIVE


def test_classify_reply_falls_back_on_unparseable_output(monkeypatch):
    monkeypatch.setattr(settings, "ai_classify_replies", True)
    client = _groq_client(lambda r: _response("I think it's positive!"))
    result = classify_reply("Re: website", "Yes please, how much?", client=client)
    assert result.classifier == "rules"


def test_groq_never_overrides_an_opt_out(monkeypatch):
    monkeypatch.setattr(settings, "ai_classify_replies", True)
    client = _groq_client(lambda r: _response(
        '{"classification":"POSITIVE","confidence":0.99,"summary":"keen"}'
    ))
    result = classify_reply("Re: website", "Please remove me from your list.",
                            client=client)
    assert result.classification == ReplyClass.UNSUBSCRIBE
    assert result.classifier == "rules"


def test_classify_reply_uses_rules_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "ai_classify_replies", False)
    client = _groq_client(lambda r: pytest.fail("groq must not be called"))
    assert classify_reply("s", "Yes please", client=client).classifier == "rules"


def test_classify_reply_uses_rules_without_api_key(monkeypatch):
    monkeypatch.setattr(settings, "ai_classify_replies", True)
    client = GroqClient(api_key="")
    assert client.enabled is False
    assert classify_reply("s", "Yes please", client=client).classifier == "rules"


def test_groq_chat_requires_api_key():
    with pytest.raises(GroqError, match="not configured"):
        GroqClient(api_key="").chat([{"role": "user", "content": "hi"}])


def test_groq_request_shape():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured.update(json.loads(request.content))
        captured["auth"] = request.headers.get("authorization")
        return _response('{"classification":"NEUTRAL","confidence":0.5,"summary":"x"}')

    client = _groq_client(handler)
    client.chat([{"role": "user", "content": "hi"}])
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["model"] == settings.groq_model
    assert captured["auth"] == "Bearer test-key"


def test_classification_dataclass_defaults():
    c = Classification(ReplyClass.NEUTRAL, 0.5, "s")
    assert c.classifier == "rules" and c.wants_call is False
