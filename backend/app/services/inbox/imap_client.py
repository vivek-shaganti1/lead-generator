"""IMAP fetching. Thin, so the interesting logic stays in parser.py / processor.py."""
from __future__ import annotations

import imaplib
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta

from app.config import settings
from app.logging_config import get_logger
from app.services.inbox.parser import ParsedInbound, parse_message
from app.utils import utcnow

log = get_logger(__name__)

MAX_FETCH = 200


class IMAPError(RuntimeError):
    pass


@contextmanager
def imap_connection(**overrides) -> Iterator[imaplib.IMAP4]:
    host = overrides.get("host") or settings.imap_host
    port = overrides.get("port") or settings.imap_port
    user = overrides.get("user") or settings.imap_user
    password = overrides.get("password") or settings.imap_password
    use_ssl = overrides.get("ssl", settings.imap_ssl)

    if not host or not user:
        raise IMAPError("IMAP is not configured (IMAP_HOST / IMAP_USER)")

    client = imaplib.IMAP4_SSL(host, port) if use_ssl else imaplib.IMAP4(host, port)
    try:
        client.login(user, password)
        yield client
    finally:
        try:
            client.logout()
        except Exception:  # pragma: no cover - best effort teardown
            pass


def fetch_recent(
    *, folder: str | None = None, days: int = 7, unseen_only: bool = True, limit: int = MAX_FETCH
) -> list[ParsedInbound]:
    """Pull recent messages and hand back parsed structures.

    Messages are left unread on the server: we track what we've processed by
    Message-ID in our own database, which survives another client marking mail
    as read.
    """
    folder = folder or settings.imap_folder
    since = (utcnow() - timedelta(days=days)).strftime("%d-%b-%Y")
    criteria = f'(SINCE {since})' if not unseen_only else f'(UNSEEN SINCE {since})'

    out: list[ParsedInbound] = []
    with imap_connection() as client:
        status, _ = client.select(folder, readonly=True)
        if status != "OK":
            raise IMAPError(f"cannot select folder {folder!r}")

        status, data = client.search(None, criteria)
        if status != "OK":
            raise IMAPError(f"IMAP search failed: {status}")

        ids = (data[0] or b"").split()
        for msg_id in ids[-limit:]:
            status, payload = client.fetch(msg_id, "(RFC822)")
            if status != "OK" or not payload:
                continue
            raw = next(
                (part[1] for part in payload if isinstance(part, tuple) and part[1]), None
            )
            if not raw:
                continue
            parsed = parse_message(raw)
            if parsed:
                out.append(parsed)
    log.info("imap.fetched", count=len(out), folder=folder)
    return out
