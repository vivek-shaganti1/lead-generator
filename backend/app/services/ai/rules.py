"""Deterministic reply classifier.

This is the default and the fallback: it runs with no API key, costs nothing,
and is what the system falls back to whenever Groq is unavailable. Groq only
has to beat it, not replace it.
"""
from __future__ import annotations

import re

from app.models import ReplyClass

BOUNCE_MARKERS = (
    "mail delivery failed", "delivery status notification", "undeliverable",
    "returned mail", "recipient address rejected", "user unknown", "mailbox full",
    "550 5.1.1", "554 5.7.1", "550 5.7.1", "550 user", "does not exist", "address not found",
    "delivery has failed to these recipients", "message could not be delivered",
    "mailbox unavailable", "host or domain name not found", "no such user",
    "user does not exist", "status: 5.", "action: failed",
)
AUTO_MARKERS = (
    "out of office", "auto-reply", "autoreply", "automatic reply", "away from my desk",
    "on holiday", "on vacation", "annual leave", "currently away", "thank you for contacting",
    "we have received your", "this is an automated", "ticket has been created",
    "abwesenheitsnotiz", "ich bin bis", "automatisches antwort", "réponse automatique",
    "absence du bureau", "fuera de la oficina", "risposta automatica",
    "i am currently out", "i will be out", "maternity leave", "paternity leave",
)
UNSUB_MARKERS = (
    "unsubscribe", "remove me", "remove us", "take me off", "take us off", "stop emailing",
    "stop sending", "do not contact", "don't contact", "dont contact", "don't email",
    "dont email", "opt out", "opt-out", "un-subscribe", "delete my data", "gdpr",
    "report as spam", "stop contacting", "lose my email",
)
NEGATIVE_MARKERS = (
    "not interested", "no thanks", "no thank you", "we already have a website",
    "already have a site", "we have a website", "already got a website", "not looking",
    "no need", "we're all set", "we are all set", "please stop", "not right now",
    "not at this time", "we handle this in house", "we have someone", "we have an agency",
    "we have a web designer", "spam", "no interest", "wrong person",
)
POSITIVE_MARKERS = (
    "interested", "sounds good", "sounds great", "sounds interesting", "yes please",
    "yes, please", "sure, send", "tell me more", "how much", "what would it cost",
    "what are your rates", "what are your prices", "pricing", "quote", "send me",
    "send over", "send a mockup", "send the mockup", "let's talk", "lets talk",
    "can you call", "give me a call", "give us a call", "call me", "reach me at",
    "set up a call", "book a call", "when can we", "i'd like", "i would like",
    "would love to see", "keen", "definitely interested", "go ahead", "please send",
    "mockup", "sample", "portfolio", "let's do it", "lets do it", "we need a website",
)
QUESTION_MARKERS = (
    "who are you", "where did you get", "how did you find", "what exactly",
    "do you also", "can you also", "how does it work", "what is included",
    "can i see examples", "could you send more information",
)


def _contains(text: str, markers: tuple[str, ...]) -> str | None:
    for marker in markers:
        if marker in text:
            return marker
    return None


def _spans(text: str, markers: tuple[str, ...]) -> list[tuple[int, int, str]]:
    """Every marker hit, as (start, end, marker)."""
    out = []
    for marker in markers:
        start = text.find(marker)
        if start != -1:
            out.append((start, start + len(marker), marker))
    return out


def _swallowed(span: tuple[int, int, str], others: list[tuple[int, int, str]]) -> bool:
    """True when this hit sits inside a longer hit from the other polarity.

    "not interested" contains "interested"; without this the two cancel out and
    a flat refusal gets read as ambiguous.
    """
    start, end, _ = span
    return any(o_start <= start and end <= o_end for o_start, o_end, _ in others)


def strip_quoted(body: str) -> str:
    """Drop the quoted original so we classify what *they* wrote, not our own pitch."""
    lines = []
    for line in (body or "").splitlines():
        stripped = line.strip()
        if stripped.startswith(">"):
            break
        if re.match(r"^on .{10,80}wrote:$", stripped, re.IGNORECASE):
            break
        if re.match(r"^le .{10,80}a écrit\s*:$", stripped, re.IGNORECASE):
            break
        if re.match(r"^am .{10,80}schrieb .{1,80}:$", stripped, re.IGNORECASE):
            break
        if stripped in ("--", "-- ") or stripped.startswith("-----Original Message") or stripped.startswith("---------- Forwarded"):
            break
        if re.match(r"^_{5,}$", stripped) or re.match(r"^(From|Von|De|Da):\s", stripped, re.IGNORECASE):
            break
        lines.append(line)
    return "\n".join(lines).strip() or (body or "").strip()


def classify(subject: str | None, body: str) -> tuple[ReplyClass, float, str]:
    """Return (class, confidence, reason)."""
    reply_text = strip_quoted(body)
    haystack = f"{subject or ''}\n{reply_text}".lower()

    marker = _contains(haystack, BOUNCE_MARKERS)
    if marker:
        return ReplyClass.BOUNCE, 0.95, f"bounce marker: {marker}"

    marker = _contains(haystack, UNSUB_MARKERS)
    if marker:
        return ReplyClass.UNSUBSCRIBE, 0.9, f"opt-out marker: {marker}"

    marker = _contains(haystack, AUTO_MARKERS)
    if marker:
        return ReplyClass.AUTO_REPLY, 0.8, f"auto-reply marker: {marker}"

    negative_hits = _spans(haystack, NEGATIVE_MARKERS)
    positive_hits = _spans(haystack, POSITIVE_MARKERS)
    # Drop hits that are merely substrings of an opposite-polarity phrase.
    negative_hits = [h for h in negative_hits if not _swallowed(h, positive_hits)]
    positive_hits = [h for h in positive_hits if not _swallowed(h, negative_hits)]

    negative = negative_hits[0][2] if negative_hits else None
    positive = positive_hits[0][2] if positive_hits else None

    if negative and not positive:
        return ReplyClass.NEGATIVE, 0.85, f"negative marker: {negative}"
    if positive and not negative:
        return ReplyClass.POSITIVE, 0.8, f"positive marker: {positive}"
    if positive and negative:
        # Genuinely mixed ("not now, but how much?") - a human should read it.
        return ReplyClass.QUESTION, 0.5, f"mixed markers: {positive} / {negative}"

    marker = _contains(haystack, QUESTION_MARKERS)
    if marker or "?" in reply_text:
        return ReplyClass.QUESTION, 0.55, "contains a question"

    if len(reply_text) < 400:
        return ReplyClass.NEUTRAL, 0.4, "short reply, no clear signal"
    return ReplyClass.UNKNOWN, 0.2, "no marker matched"
