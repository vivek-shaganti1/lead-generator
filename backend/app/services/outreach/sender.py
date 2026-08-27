"""SMTP transport.

Two transports behind one interface: a real SMTP client, and a recording
transport used by DRY_RUN and by the tests. DRY_RUN is the default so a
misconfigured deploy cannot mail strangers by accident.
"""
from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage as MimeMessage
from email.utils import formataddr, formatdate, make_msgid

from app.config import settings
from app.logging_config import get_logger

log = get_logger(__name__)


@dataclass(slots=True)
class OutgoingEmail:
    to_email: str
    subject: str
    text: str
    html: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    from_name: str | None = None
    from_email: str | None = None
    reply_to: str | None = None
    in_reply_to: str | None = None
    references: str | None = None


@dataclass(slots=True)
class SendResult:
    ok: bool
    message_id: str | None = None
    error: str | None = None
    dry_run: bool = False


def build_mime(email: OutgoingEmail, domain: str | None = None) -> MimeMessage:
    msg = MimeMessage()
    from_email = email.from_email or settings.sender_email
    from_name = email.from_name or settings.sender_name

    msg["From"] = formataddr((from_name, from_email))
    msg["To"] = email.to_email
    msg["Subject"] = email.subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=domain or (from_email.split("@")[-1] or None))
    msg["Reply-To"] = email.reply_to or settings.effective_reply_to
    # Tells mailbox providers this is bulk-but-legitimate rather than transactional.
    msg["Precedence"] = "bulk"
    msg["Auto-Submitted"] = "auto-generated"

    if email.in_reply_to:
        msg["In-Reply-To"] = email.in_reply_to
        msg["References"] = email.references or email.in_reply_to

    for key, value in (email.headers or {}).items():
        if key in msg:
            del msg[key]
        msg[key] = value

    msg.set_content(email.text)
    if email.html:
        msg.add_alternative(email.html, subtype="html")
    return msg


class BaseTransport:
    def send(self, email: OutgoingEmail) -> SendResult:  # pragma: no cover - interface
        raise NotImplementedError


class RecordingTransport(BaseTransport):
    """Captures messages instead of delivering them. Used by DRY_RUN and tests."""

    def __init__(self) -> None:
        self.sent: list[MimeMessage] = []

    def send(self, email: OutgoingEmail) -> SendResult:
        msg = build_mime(email)
        self.sent.append(msg)
        log.info("smtp.dry_run", to=email.to_email, subject=email.subject)
        return SendResult(ok=True, message_id=msg["Message-ID"], dry_run=True)

    def clear(self) -> None:
        self.sent.clear()


class SMTPTransport(BaseTransport):
    def __init__(self, **overrides) -> None:
        self.host = overrides.get("host") or settings.smtp_host
        self.port = overrides.get("port") or settings.smtp_port
        self.user = overrides.get("user") or settings.smtp_user
        self.password = overrides.get("password") or settings.smtp_password
        self.use_ssl = overrides.get("ssl", settings.smtp_ssl)
        self.starttls = overrides.get("starttls", settings.smtp_starttls)
        self.timeout = overrides.get("timeout", settings.smtp_timeout)

    def _connect(self):
        if self.use_ssl:
            return smtplib.SMTP_SSL(
                self.host, self.port, timeout=self.timeout, context=ssl.create_default_context()
            )
        client = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
        if self.starttls:
            client.starttls(context=ssl.create_default_context())
        return client

    def send(self, email: OutgoingEmail) -> SendResult:
        if not self.host:
            return SendResult(ok=False, error="SMTP_HOST is not configured")
        msg = build_mime(email)
        try:
            client = self._connect()
        except (OSError, smtplib.SMTPException) as exc:
            log.error("smtp.connect_failed", error=str(exc))
            return SendResult(ok=False, error=f"connect: {exc}")
        try:
            if self.user:
                client.login(self.user, self.password)
            client.send_message(msg)
            log.info("smtp.sent", to=email.to_email, message_id=msg["Message-ID"])
            return SendResult(ok=True, message_id=msg["Message-ID"])
        except smtplib.SMTPRecipientsRefused as exc:
            return SendResult(ok=False, error=f"recipient refused: {exc}")
        except smtplib.SMTPException as exc:
            return SendResult(ok=False, error=str(exc))
        finally:
            try:
                client.quit()
            except Exception:  # pragma: no cover - best effort teardown
                pass


_transport: BaseTransport | None = None


def get_transport() -> BaseTransport:
    """DRY_RUN short-circuits to the recording transport; nothing leaves the box."""
    global _transport
    if _transport is None:
        _transport = RecordingTransport() if settings.dry_run else SMTPTransport()
    return _transport


def set_transport(transport: BaseTransport | None) -> None:
    """Test/DI seam."""
    global _transport
    _transport = transport
