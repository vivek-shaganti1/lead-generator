"""Open/click tracking tokens.

HMAC-signed so nobody can inflate someone else's stats by guessing ids, and so
we never have to store a second random token per message.

Privacy note: open tracking works by loading a 1x1 image from our server, which
records that the recipient's client fetched it. Set TRACK_OPENS=false to disable
it entirely; the rest of the system does not depend on it.
"""
from __future__ import annotations

import base64
import hashlib
import hmac

from app.config import settings

# A 1x1 transparent GIF.
PIXEL_GIF = base64.b64decode(
    b"R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
)


def _sign(payload: str) -> str:
    digest = hmac.new(
        settings.secret_key.encode(), payload.encode(), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")[:22]


def make_token(message_id: int, kind: str = "o") -> str:
    return f"{message_id}.{_sign(f'{kind}:{message_id}')}"


def parse_token(token: str, kind: str = "o") -> int | None:
    """Return the message id if the signature checks out, else None."""
    if not token or "." not in token:
        return None
    raw_id, _, signature = token.partition(".")
    if not raw_id.isdigit():
        return None
    expected = _sign(f"{kind}:{int(raw_id)}")
    return int(raw_id) if hmac.compare_digest(signature, expected) else None


def pixel_url(message_id: int) -> str:
    return f"{settings.public_base_url.rstrip('/')}/t/o/{make_token(message_id)}.gif"


def inject_pixel(html_body: str, message_id: int) -> str:
    img = (
        f'<img src="{pixel_url(message_id)}" width="1" height="1" '
        'alt="" style="display:block;border:0;outline:none" />'
    )
    if "</div>" in html_body:
        head, _, tail = html_body.rpartition("</div>")
        return f"{head}{img}</div>{tail}"
    return html_body + img
