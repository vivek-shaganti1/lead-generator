"""Groq client.

Used for two jobs: classifying replies with more nuance than keywords allow, and
(optionally) personalising the opening line. Both degrade gracefully - if the
key is missing, the request fails, or the model returns junk, we fall back to
the deterministic classifier and carry on.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import settings
from app.logging_config import get_logger
from app.models import ReplyClass
from app.services.ai import rules

log = get_logger(__name__)

VALID_CLASSES = {c.value for c in ReplyClass}

CLASSIFY_SYSTEM = """You classify replies to a cold B2B email offering website design to small businesses.

Return STRICT JSON only, no prose, with exactly these keys:
  "classification": one of POSITIVE, NEGATIVE, NEUTRAL, QUESTION, UNSUBSCRIBE, AUTO_REPLY, BOUNCE, UNKNOWN
  "confidence": number between 0 and 1
  "summary": one sentence, max 20 words, describing what they want
  "wants_call": true or false
  "budget_mentioned": string or null

Definitions:
  POSITIVE    - any interest: wants a mockup, asks price, wants to talk, says yes
  QUESTION    - asks something before deciding, or the reply is genuinely ambiguous
  NEGATIVE    - declines, already has a website, tells us not now
  UNSUBSCRIBE - demands removal, threatens spam report, cites data protection law
  AUTO_REPLY  - out of office / automated acknowledgement
  BOUNCE      - mail system delivery failure notice
  NEUTRAL     - acknowledgement with no signal either way"""


@dataclass(slots=True)
class Classification:
    classification: ReplyClass
    confidence: float
    summary: str
    classifier: str = "rules"
    wants_call: bool = False
    budget_mentioned: str | None = None


class GroqError(RuntimeError):
    pass


class GroqRateLimit(GroqError):
    pass


class GroqClient:
    def __init__(self, api_key: str | None = None, client: httpx.Client | None = None) -> None:
        self._api_key = api_key if api_key is not None else settings.groq_api_key
        self._client = client

    @property
    def enabled(self) -> bool:
        return bool(self._api_key)

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=45)
        return self._client

    @retry(
        retry=retry_if_exception_type((GroqRateLimit, httpx.TransportError)),
        wait=wait_exponential(multiplier=2, min=2, max=20),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def chat(self, messages: list[dict], *, json_mode: bool = True, max_tokens: int = 400) -> str:
        if not self._api_key:
            raise GroqError("GROQ_API_KEY is not configured")
        payload: dict = {
            "model": settings.groq_model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        response = self._http().post(
            f"{settings.groq_base_url.rstrip('/')}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        if response.status_code == 429:
            raise GroqRateLimit("groq rate limit")
        if response.status_code >= 400:
            raise GroqError(f"{response.status_code}: {response.text[:300]}")
        data = response.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise GroqError(f"unexpected response shape: {exc}") from exc

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


def parse_classification(content: str) -> Classification | None:
    """Parse and *validate* the model's JSON. Anything off-contract is rejected."""
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None

    raw_class = str(data.get("classification", "")).strip().upper()
    if raw_class not in VALID_CLASSES:
        return None
    try:
        confidence = float(data.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = min(max(confidence, 0.0), 1.0)

    return Classification(
        classification=ReplyClass(raw_class),
        confidence=confidence,
        summary=str(data.get("summary") or "")[:400],
        classifier="groq",
        wants_call=bool(data.get("wants_call")),
        budget_mentioned=(str(data["budget_mentioned"])[:80]
                          if data.get("budget_mentioned") else None),
    )


def classify_reply(
    subject: str | None, body: str, client: GroqClient | None = None
) -> Classification:
    """AI classification with a deterministic floor underneath it."""
    fallback_class, fallback_conf, reason = rules.classify(subject, body)
    fallback = Classification(fallback_class, fallback_conf, reason, classifier="rules")

    if not settings.ai_classify_replies:
        return fallback
    client = client or GroqClient()
    if not client.enabled:
        return fallback

    # Bounces and opt-outs are unambiguous; don't spend a call on them.
    if fallback_class in (ReplyClass.BOUNCE, ReplyClass.UNSUBSCRIBE) and fallback_conf >= 0.9:
        return fallback

    trimmed = rules.strip_quoted(body)[:4000]
    try:
        content = client.chat(
            [
                {"role": "system", "content": CLASSIFY_SYSTEM},
                {"role": "user", "content": f"Subject: {subject or '(none)'}\n\nReply:\n{trimmed}"},
            ]
        )
    except (GroqError, httpx.HTTPError) as exc:
        log.warning("groq.classify_failed", error=str(exc))
        return fallback

    parsed = parse_classification(content)
    if parsed is None:
        log.warning("groq.classify_unparseable", content=content[:200])
        return fallback

    # If the model and the rules disagree on an opt-out, trust the rules: the
    # cost of ignoring a removal request is far higher than a missed lead.
    if fallback_class == ReplyClass.UNSUBSCRIBE and parsed.classification != ReplyClass.UNSUBSCRIBE:
        return fallback
    return parsed


PERSONALISE_SYSTEM = """You write ONE opening sentence for a cold email to a small business.
Rules: max 25 words, plain language, no flattery, no exclamation marks, no emoji,
never claim to have visited or bought from them, never invent facts.
Return JSON: {"line": "..."}"""


def personalise_opening(business: dict, client: GroqClient | None = None) -> str | None:
    if not settings.ai_personalize_copy:
        return None
    client = client or GroqClient()
    if not client.enabled:
        return None
    try:
        content = client.chat(
            [
                {"role": "system", "content": PERSONALISE_SYSTEM},
                {"role": "user", "content": json.dumps(business)[:1500]},
            ],
            max_tokens=120,
        )
        data = json.loads(content)
        line = str(data.get("line") or "").strip()
        return line[:220] or None
    except (GroqError, httpx.HTTPError, json.JSONDecodeError, TypeError) as exc:
        log.warning("groq.personalise_failed", error=str(exc))
        return None
