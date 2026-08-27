"""Opt-out plumbing.

Every message carries a List-Unsubscribe header (RFC 2369) *and* RFC 8058
one-click support, plus a visible link in the body. Gmail and Yahoo require the
former for bulk senders; the latter is what an actual human clicks.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Event, Lead, LeadStatus
from app.services.compliance.policy import suppress


# Hosts that exist only on the sending machine. A recipient's mail client cannot
# reach any of these, so an unsubscribe link pointing at one is a dead link.
_PRIVATE_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "::1", ".local", ".internal", ".test")


def is_publicly_reachable(base_url: str | None = None) -> bool:
    """Can a recipient's mail client actually reach our unsubscribe endpoint?"""
    url = (base_url if base_url is not None else settings.public_base_url or "").lower()
    if not url:
        return False
    return not any(host in url for host in _PRIVATE_HOSTS)


def unsubscribe_mailto(token: str) -> str:
    """Opt-out by replying, for when there is no reachable web endpoint.

    RFC 8058 accepts a mailto: form, and the major providers honour it. Running
    the stack locally means the HTTP route is unreachable from outside this
    machine, and a broken opt-out link is both a legal problem and a spam
    signal in its own right — so we hand the recipient a route that works
    without publishing anything.

    The token travels in the subject so an inbound opt-out can still be matched
    back to the exact lead.
    """
    return f"mailto:{settings.effective_reply_to}?subject=Unsubscribe%20{token}"


def unsubscribe_url(token: str) -> str:
    """The opt-out route to advertise — HTTP when reachable, mailto otherwise."""
    if is_publicly_reachable():
        return f"{settings.public_base_url.rstrip('/')}/u/{token}"
    return unsubscribe_mailto(token)


def unsubscribe_instruction(token: str) -> str:
    """Human-readable opt-out line for the plain-text footer."""
    if is_publicly_reachable():
        return f"Unsubscribe and never hear from us again: {unsubscribe_url(token)}"
    return (
        'Reply with "unsubscribe" and you will never hear from us again '
        f"(reference {token[:12]})."
    )


def list_unsubscribe_headers(token: str) -> dict[str, str]:
    mailto = unsubscribe_mailto(token)
    if not is_publicly_reachable():
        # No One-Click: RFC 8058 one-click requires an HTTPS endpoint, and
        # claiming support we cannot honour is worse than not offering it.
        return {"List-Unsubscribe": f"<{mailto}>"}
    url = f"{settings.public_base_url.rstrip('/')}/u/{token}"
    return {
        "List-Unsubscribe": f"<{url}>, <{mailto}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }


def apply_unsubscribe(db: Session, lead: Lead, reason: str = "user opt-out") -> None:
    """Terminal and irreversible: mark the lead and suppress the address forever."""
    lead.status = LeadStatus.UNSUBSCRIBED
    lead.next_action_at = None
    lead.block_reason = reason
    suppress(db, lead.email, reason=reason, kind="email")
    db.add(Event(type="lead.unsubscribed", lead_id=lead.id, payload={"reason": reason}))
