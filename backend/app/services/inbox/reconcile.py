"""Reconcile the local database against the *actual* mailbox.

The database is a claim; the mailbox is the fact. Everything in here reads the
real account over IMAP and makes our records match it — never the other way
round.

Three sweeps, all read-only on the server:

  * :func:`sweep_sent`     — every message the account has actually sent.
  * :func:`sweep_bounces`  — DSNs, parsed properly out of ``message/delivery-status``
                             rather than regexed out of the body, so we get the
                             failed recipient and the real status code.
  * :func:`sweep_replies`  — genuine inbound mail from third parties, with mail
                             we sent to ourselves and mailer-daemon filtered out.

:func:`reconcile` folds all three into the database: hard bounces become
permanent suppressions, contacted addresses become send history, and any lead
whose address bounced is moved to ``BOUNCED`` so no follow-up can ever chase it.

Bounces are the thing that kills a sending account, so a bounced address is
suppressed here *before* anything else is allowed to run.
"""
from __future__ import annotations

import email
import imaplib
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from email.header import decode_header, make_header
from email.message import Message
from email.utils import getaddresses, parsedate_to_datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.logging_config import get_logger
from app.models import Lead, LeadStatus, Suppression
from app.services.inbox.imap_client import IMAPError, imap_connection

log = get_logger(__name__)

# Gmail's special folders. The account may present them under a localised name,
# so we resolve by \Sent / \All flags and fall back to these.
SENT_FOLDER = '"[Gmail]/Sent Mail"'
ALL_FOLDER = '"[Gmail]/All Mail"'

# Addresses that are never a real recipient or a real correspondent.
_INFRA_MARKERS = (
    "mailer-daemon",
    "postmaster",
    "googlemail.com>",
    "no-reply@",
    "noreply@",
)

# A 5.x.x status in a DSN is permanent: the address does not exist, or the
# domain does not. 4.x.x is transient (full mailbox, greylisting) and must NOT
# be suppressed — the address may be perfectly good tomorrow.
_PERMANENT = re.compile(r"^5\.\d+\.\d+$")

_FETCH_BATCH = 200


# --------------------------------------------------------------------------
# header helpers
# --------------------------------------------------------------------------
def _header(msg: Message, key: str) -> str:
    raw = msg.get(key, "") or ""
    try:
        return str(make_header(decode_header(raw)))
    except Exception:  # malformed encoded-word; the raw value is better than nothing
        return raw


def _addresses(msg: Message, key: str) -> list[str]:
    return [
        addr.lower().strip()
        for _, addr in getaddresses([msg.get(key, "") or ""])
        if addr and "@" in addr
    ]


def _sent_at(msg: Message) -> datetime | None:
    try:
        return parsedate_to_datetime(msg.get("Date", ""))
    except (TypeError, ValueError):
        return None


def _is_infra(addr: str) -> bool:
    low = addr.lower()
    return any(marker.rstrip(">") in low for marker in _INFRA_MARKERS)


# --------------------------------------------------------------------------
# folder plumbing
# --------------------------------------------------------------------------
def _resolve_folder(client: imaplib.IMAP4, flag: str, fallback: str) -> str:
    """Find a special-use folder by its IMAP flag, e.g. ``\\Sent``.

    Gmail localises display names ("Mensajes enviados"), so matching on the flag
    is the only reliable route. Falls back to the English name.
    """
    try:
        status, boxes = client.list()
        if status == "OK":
            for raw in boxes or []:
                line = raw.decode(errors="replace")
                if flag in line:
                    # ... (\Sent \HasNoChildren) "/" "[Gmail]/Sent Mail"
                    name = line.rsplit(' "', 1)[-1].rstrip('"')
                    return f'"{name}"'
    except Exception as exc:  # pragma: no cover - server-dependent
        log.warning("reconcile.folder_list_failed", flag=flag, error=str(exc))
    return fallback


def _iter_messages(
    client: imaplib.IMAP4, folder: str, fields: str | None, criteria: str = "ALL"
) -> Iterator[Message]:
    """Yield parsed messages from *folder*, batched so a big mailbox stays cheap.

    *fields* limits the fetch to those headers; pass ``None`` for the full body
    (needed to parse a DSN). BODY.PEEK never sets \\Seen — we must not change
    the read state of the user's own mailbox.
    """
    status, _ = client.select(folder, readonly=True)
    if status != "OK":
        log.warning("reconcile.select_failed", folder=folder)
        return

    status, data = client.search(None, criteria)
    if status != "OK":
        return
    ids = (data[0] or b"").split()
    if not ids:
        return

    part = f"(BODY.PEEK[HEADER.FIELDS ({fields})])" if fields else "(BODY.PEEK[])"
    for start in range(0, len(ids), _FETCH_BATCH):
        chunk = b",".join(ids[start : start + _FETCH_BATCH])
        status, payload = client.fetch(chunk, part)
        if status != "OK":
            continue
        for item in payload or []:
            if isinstance(item, tuple) and item[1]:
                yield email.message_from_bytes(item[1])


# --------------------------------------------------------------------------
# sweeps
# --------------------------------------------------------------------------
@dataclass(slots=True)
class SentRecord:
    to_email: str
    subject: str
    message_id: str | None
    sent_at: datetime | None


@dataclass(slots=True)
class BounceRecord:
    email: str
    status: str          # "5.1.1"
    diagnostic: str      # the server's own words, kept for the dashboard
    permanent: bool


@dataclass(slots=True)
class ReplyRecord:
    from_email: str
    subject: str
    message_id: str | None
    received_at: datetime | None


@dataclass(slots=True)
class MailboxTruth:
    """What the mailbox actually contains."""

    sent: list[SentRecord] = field(default_factory=list)
    bounces: list[BounceRecord] = field(default_factory=list)
    replies: list[ReplyRecord] = field(default_factory=list)
    self_sent: int = 0

    @property
    def real_recipients(self) -> set[str]:
        return {r.to_email for r in self.sent}

    @property
    def hard_bounced(self) -> set[str]:
        return {b.email for b in self.bounces if b.permanent}

    @property
    def bounce_rate(self) -> float:
        """Share of *unique* contacted addresses that permanently bounced."""
        contacted = self.real_recipients
        if not contacted:
            return 0.0
        return len(self.hard_bounced & contacted) / len(contacted)


def sweep_sent(client: imaplib.IMAP4, own_address: str) -> tuple[list[SentRecord], int]:
    """Every message actually sent, minus the ones addressed to ourselves.

    Mail we sent to our own address is a test artefact, not outreach, and
    counting it as a "send" is exactly how a pipeline ends up reporting numbers
    it never achieved.
    """
    folder = _resolve_folder(client, r"\Sent", SENT_FOLDER)
    own = own_address.lower()
    out: list[SentRecord] = []
    self_sent = 0

    for msg in _iter_messages(client, folder, "DATE TO SUBJECT MESSAGE-ID"):
        recipients = _addresses(msg, "To")
        if not recipients:
            continue
        if all(addr == own for addr in recipients):
            self_sent += 1
            continue
        subject = _header(msg, "Subject").replace("\n", " ").replace("\r", "").strip()
        when = _sent_at(msg)
        mid = (msg.get("Message-ID") or "").strip() or None
        for addr in recipients:
            if addr != own and not _is_infra(addr):
                out.append(SentRecord(addr, subject, mid, when))

    log.info("reconcile.sent_swept", real=len(out), to_self=self_sent)
    return out, self_sent


def _parse_dsn(msg: Message) -> list[BounceRecord]:
    """Pull failed recipients out of a delivery status notification.

    RFC 3464 puts one per-recipient block in a ``message/delivery-status`` part,
    each with ``Final-Recipient``, ``Action`` and ``Status``. Parsing that
    structure (rather than scraping the human-readable part) is what keeps us
    from mistaking the *sender's* address, a URL, or a quoted body for a
    bouncing recipient.
    """
    found: list[BounceRecord] = []

    for part in msg.walk():
        if part.get_content_type() != "message/delivery-status":
            continue
        # Each per-recipient group parses as its own header block.
        payload = part.get_payload()
        blocks = payload if isinstance(payload, list) else []
        for block in blocks:
            if not isinstance(block, Message):
                continue
            action = (block.get("Action") or "").strip().lower()
            recipient = (block.get("Final-Recipient") or block.get("Original-Recipient") or "")
            status = (block.get("Status") or "").strip()
            diagnostic = (block.get("Diagnostic-Code") or "").strip()

            # "rfc822; someone@example.com"
            addr = recipient.split(";", 1)[-1].strip().strip("<>").lower()
            if not addr or "@" not in addr:
                continue
            if action and action != "failed":
                continue  # delayed / relayed / expanded are not bounces
            found.append(
                BounceRecord(
                    email=addr,
                    status=status,
                    diagnostic=diagnostic.replace("\n", " ")[:500],
                    permanent=bool(_PERMANENT.match(status)),
                )
            )

    return found


def sweep_bounces(client: imaplib.IMAP4) -> list[BounceRecord]:
    """Parse every DSN in the account into structured bounce records."""
    folder = _resolve_folder(client, r"\All", ALL_FOLDER)
    out: list[BounceRecord] = []
    seen: set[tuple[str, str]] = set()

    for msg in _iter_messages(client, folder, None, criteria='(FROM "mailer-daemon")'):
        for record in _parse_dsn(msg):
            key = (record.email, record.status)
            if key not in seen:
                seen.add(key)
                out.append(record)

    permanent = sum(1 for b in out if b.permanent)
    log.info("reconcile.bounces_swept", total=len(out), permanent=permanent)
    return out


def sweep_replies(client: imaplib.IMAP4, own_address: str) -> list[ReplyRecord]:
    """Genuine inbound mail: not from ourselves, not from mail infrastructure."""
    own = own_address.lower()
    out: list[ReplyRecord] = []

    for msg in _iter_messages(client, settings.imap_folder, "DATE FROM SUBJECT MESSAGE-ID"):
        senders = _addresses(msg, "From")
        if not senders:
            continue
        sender = senders[0]
        if sender == own or _is_infra(sender):
            continue
        out.append(
            ReplyRecord(
                from_email=sender,
                subject=_header(msg, "Subject").replace("\n", " ").strip(),
                message_id=(msg.get("Message-ID") or "").strip() or None,
                received_at=_sent_at(msg),
            )
        )

    log.info("reconcile.replies_swept", genuine=len(out))
    return out


def read_mailbox(own_address: str | None = None) -> MailboxTruth:
    """Run all three sweeps against the configured account."""
    own = (own_address or settings.imap_user or "").lower()
    if not own:
        raise IMAPError("IMAP_USER is not configured; cannot reconcile")

    truth = MailboxTruth()
    with imap_connection() as client:
        truth.sent, truth.self_sent = sweep_sent(client, own)
        truth.bounces = sweep_bounces(client)
        truth.replies = sweep_replies(client, own)
    return truth


# --------------------------------------------------------------------------
# database side
# --------------------------------------------------------------------------
def suppress(session: Session, address: str, reason: str, kind: str = "email") -> bool:
    """Add a permanent suppression. Returns True if it was newly added."""
    value = address.lower().strip()
    exists = session.scalar(
        select(Suppression).where(Suppression.value == value, Suppression.kind == kind)
    )
    if exists:
        return False
    session.add(Suppression(kind=kind, value=value, reason=reason[:255]))
    return True


def reconcile(session: Session, truth: MailboxTruth | None = None) -> dict[str, int]:
    """Make the database agree with the mailbox.

    Hard bounces are suppressed permanently and their leads marked ``BOUNCED``,
    so neither the sender nor the follow-up scheduler can ever pick them up
    again.
    """
    truth = truth or read_mailbox()
    stats = {
        "sent_real": len(truth.sent),
        "sent_to_self": truth.self_sent,
        "unique_contacted": len(truth.real_recipients),
        "bounces_permanent": len(truth.hard_bounced),
        "replies_genuine": len(truth.replies),
        "suppressed_new": 0,
        "leads_marked_bounced": 0,
    }

    for bounce in truth.bounces:
        if not bounce.permanent:
            continue
        reason = f"hard_bounce {bounce.status} {bounce.diagnostic}".strip()
        if suppress(session, bounce.email, reason):
            stats["suppressed_new"] += 1

    # Any lead we hold for a bounced address is dead: stop all future contact.
    hard = truth.hard_bounced
    if hard:
        leads = session.scalars(select(Lead).where(Lead.email.in_(hard))).all()
        for lead in leads:
            if lead.status != LeadStatus.BOUNCED:
                lead.status = LeadStatus.BOUNCED
                lead.block_reason = "hard bounce confirmed from mailbox"
                lead.next_action_at = None
                stats["leads_marked_bounced"] += 1

    session.commit()
    log.info("reconcile.complete", **stats)
    return stats
