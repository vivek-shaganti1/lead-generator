"""Pure MIME parsing, kept separate from IMAP so it can be tested offline."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import timedelta, timezone
from email import message_from_bytes, policy
from email.message import EmailMessage as MimeMessage
from email.utils import getaddresses, parsedate_to_datetime

from app.utils import utcnow

MSGID_RE = re.compile(r"<[^<>@\s]+@[^<>\s]+>")
# Widest believable gap between a message's Date header and the moment we
# fetched it; anything outside is treated as clock skew / spoofing.
RECEIVED_AT_MAX_AGE = timedelta(days=30)
# A DSN reports the *failed* recipient in these headers or in the body.
DSN_RECIPIENT_RE = re.compile(
    r"(?:Final-Recipient|Original-Recipient|X-Failed-Recipients|Recipient)\s*:\s*(?:rfc822;\s*)?<?([^\s<>]+@[^\s<>]+?)>?\s*$",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(slots=True)
class ParsedInbound:
    message_id: str
    from_email: str
    subject: str
    body_text: str
    in_reply_to: str | None = None
    references: list[str] = field(default_factory=list)
    received_at: object = None
    is_dsn: bool = False
    failed_recipient: str | None = None
    raw_headers: dict = field(default_factory=dict)


def _decode_part(part: MimeMessage) -> str:
    try:
        payload = part.get_payload(decode=True)
    except Exception:
        return ""
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except (LookupError, UnicodeDecodeError):
        return payload.decode("utf-8", errors="replace")


def _html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = (
        text.replace("&nbsp;", " ").replace("&amp;", "&")
        .replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    )
    text = re.sub(r"[ \t]{2,}", " ", text)
    # Stripping inline tags leaves "good , how much" - close those gaps up.
    text = re.sub(r"[ \t]+([,.;:!?])", r"\1", text)
    return text.strip()


def _dsn_text(part: MimeMessage) -> str:
    """Flatten a delivery-status part to text, whatever shape it arrives in."""
    decoded = _decode_part(part)
    if decoded:
        return decoded
    payload = part.get_payload()
    if isinstance(payload, list):
        return "\n".join(str(sub) for sub in payload)[:4000]
    return str(payload)[:4000]


def extract_body(msg: MimeMessage) -> str:
    """Prefer text/plain; fall back to a de-tagged text/html; include DSN parts."""
    plain_parts: list[str] = []
    html_parts: list[str] = []
    dsn_parts: list[str] = []

    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            # message/delivery-status is itself multipart, so it must be handled
            # before the multipart skip - otherwise every bounce reason is lost.
            if ctype in ("message/delivery-status", "text/rfc822-headers"):
                dsn_parts.append(_dsn_text(part))
                continue
            if part.is_multipart():
                continue
            disposition = (part.get("Content-Disposition") or "").lower()
            if "attachment" in disposition and not ctype.startswith("message/"):
                continue
            if ctype == "text/plain":
                plain_parts.append(_decode_part(part))
            elif ctype == "text/html":
                html_parts.append(_decode_part(part))
            elif ctype == "message/rfc822":
                dsn_parts.append(_dsn_text(part))
    else:
        if msg.get_content_type() == "text/html":
            html_parts.append(_decode_part(msg))
        else:
            plain_parts.append(_decode_part(msg))

    body = "\n".join(p for p in plain_parts if p).strip()
    if not body and html_parts:
        body = _html_to_text("\n".join(html_parts))
    if dsn_parts:
        body = (body + "\n\n" + "\n".join(dsn_parts)).strip()
    return body


def is_delivery_status(msg: MimeMessage, body: str) -> bool:
    if msg.get_content_type() == "multipart/report":
        return True
    if "report-type=delivery-status" in (msg.get("Content-Type") or "").lower():
        return True
    sender = str(msg.get("From") or "").lower()
    if any(m in sender for m in ("mailer-daemon", "postmaster", "mail delivery", "daemon@")):
        return True
    subject = str(msg.get("Subject") or "").lower()
    if any(m in subject for m in ("undeliverable:", "delivery status notification", "delivery failure", "failure notice")):
        return True
    return "Final-Recipient" in body or "Diagnostic-Code" in body or "Action: failed" in body


def parse_message(raw: bytes) -> ParsedInbound | None:
    try:
        msg = message_from_bytes(raw, policy=policy.default)
    except Exception:
        return None

    addresses = getaddresses([msg.get("From", "")])
    from_email = (addresses[0][1] if addresses else "").strip().lower()
    message_id = (msg.get("Message-ID") or "").strip()
    if not message_id:
        # Some DSNs omit it; synthesise something stable enough to dedupe on.
        message_id = f"<synthetic-{abs(hash(raw[:4096]))}@leadgen.local>"

    body = extract_body(msg)
    in_reply_to = (msg.get("In-Reply-To") or "").strip() or None
    references = MSGID_RE.findall(msg.get("References") or "")

    try:
        received_at = parsedate_to_datetime(msg.get("Date")) if msg.get("Date") else utcnow()
        if received_at and received_at.tzinfo is None:
            received_at = received_at.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        received_at = utcnow()
    # The Date header is sender-controlled and feeds stats, retention and
    # replied_at. A clock-skewed or spoofed value must not land outside the
    # window the poller could plausibly have fetched from.
    now = utcnow()
    if received_at > now or received_at < now - RECEIVED_AT_MAX_AGE:
        received_at = now

    dsn = is_delivery_status(msg, body)
    failed = None
    if dsn:
        match = DSN_RECIPIENT_RE.search(body)
        if match:
            failed = match.group(1).strip().lower()
        else:
            # last resort: any address in the body that isn't the daemon itself
            from app.utils import extract_emails

            for candidate in extract_emails(body):
                if "mailer-daemon" not in candidate and "postmaster" not in candidate:
                    failed = candidate
                    break

    return ParsedInbound(
        message_id=message_id,
        from_email=from_email,
        subject=(msg.get("Subject") or "").strip(),
        body_text=body,
        in_reply_to=in_reply_to,
        references=references,
        received_at=received_at,
        is_dsn=dsn,
        failed_recipient=failed,
        raw_headers={
            "to": msg.get("To", ""),
            "return_path": msg.get("Return-Path", ""),
            "auto_submitted": msg.get("Auto-Submitted", ""),
        },
    )
