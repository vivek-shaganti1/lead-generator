"""SMTP-level mailbox verification — does this specific mailbox actually exist?

Why MX checking is not enough
-----------------------------
The existing validator checks that a domain has MX records. Every one of the 42
addresses that hard-bounced on the live account passed that check, because most
of them were ``@gmail.com`` — a domain with impeccable MX records and no such
mailbox. ``reyesboxinggym@gmail.com`` resolves MX perfectly and does not exist.

MX answers "can this domain receive mail". It cannot answer "does this mailbox
exist", and that second question is the one that decides whether we bounce.

How this works
--------------
We open an SMTP conversation with the domain's mail exchanger and get as far as
``RCPT TO`` — the point at which the receiving server tells us whether it will
accept mail for that address — then send ``QUIT``. We never send ``DATA``, so no
message is ever delivered or queued. This is the same handshake any mail server
performs before relaying, and it is what commercial verification services do.

The four verdicts
-----------------
``DELIVERABLE``     server accepted the recipient (2xx).
``UNDELIVERABLE``   server rejected it permanently (5xx) — never mail this.
``RISKY_CATCH_ALL`` server accepts *everything*, including an address we invented,
                    so its acceptance proves nothing.
``UNKNOWN``         greylisted (4xx), blocked, timed out, or port 25 unreachable.

Only ``DELIVERABLE`` is treated as verified. ``UNKNOWN`` is deliberately *not*
optimistic: an address we could not confirm does not get mailed, because the
whole point of this module is that unconfirmed addresses are what bounce.

Operational caveat
------------------
Many residential ISPs block outbound port 25. If that is the case here, every
probe returns ``UNKNOWN`` and :func:`port25_available` reports it once, loudly,
rather than letting the pipeline silently believe it is verifying anything.
"""
from __future__ import annotations

import random
import smtplib
import socket
import string
import threading
import time
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache

import dns.exception
import dns.resolver

from app.config import settings
from app.logging_config import get_logger

log = get_logger(__name__)

SMTP_PORT = 25
DEFAULT_TIMEOUT = 12.0

# Be a polite client: one probe at a time per receiving domain, spaced out.
# Hammering a mail server with RCPT probes is how a prober gets blocklisted.
_MIN_INTERVAL_PER_DOMAIN = 3.0
_domain_locks: dict[str, threading.Lock] = {}
_domain_last: dict[str, float] = {}
_registry_lock = threading.Lock()


class Verdict(str, Enum):
    DELIVERABLE = "DELIVERABLE"
    UNDELIVERABLE = "UNDELIVERABLE"
    RISKY_CATCH_ALL = "RISKY_CATCH_ALL"
    UNKNOWN = "UNKNOWN"


@dataclass(slots=True)
class MailboxCheck:
    email: str
    verdict: Verdict
    code: int | None = None
    message: str = ""
    mx_host: str | None = None
    catch_all: bool = False

    @property
    def safe_to_send(self) -> bool:
        """Only a positive confirmation clears an address for sending."""
        return self.verdict is Verdict.DELIVERABLE

    def as_dict(self) -> dict:
        return {
            "email": self.email,
            "verdict": self.verdict.value,
            "code": self.code,
            "message": self.message[:200],
            "mx_host": self.mx_host,
            "catch_all": self.catch_all,
        }


@lru_cache(maxsize=2048)
def mx_hosts(domain: str) -> tuple[str, ...]:
    """Mail exchangers for *domain*, best preference first.

    Falls back to the domain's A record: RFC 5321 says a host with an address
    record but no MX accepts its own mail.
    """
    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=6.0)
        ranked = sorted(answers, key=lambda r: r.preference)
        return tuple(str(r.exchange).rstrip(".") for r in ranked)
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
        try:
            dns.resolver.resolve(domain, "A", lifetime=5.0)
            return (domain,)
        except dns.exception.DNSException:
            return ()
    except dns.exception.DNSException:
        return ()


def _throttle(domain: str) -> None:
    """Space probes to the same receiving domain."""
    with _registry_lock:
        lock = _domain_locks.setdefault(domain, threading.Lock())
    with lock:
        last = _domain_last.get(domain)
        if last is not None:
            delta = time.monotonic() - last
            if delta < _MIN_INTERVAL_PER_DOMAIN:
                time.sleep(_MIN_INTERVAL_PER_DOMAIN - delta)
        _domain_last[domain] = time.monotonic()


def _random_localpart() -> str:
    seed = "".join(random.choices(string.ascii_lowercase + string.digits, k=16))
    return f"no-such-user-{seed}"


def _helo_name() -> str:
    """The name we announce ourselves as.

    Using the sender's own domain keeps the handshake consistent with the
    address in MAIL FROM, which some servers check.
    """
    sender = settings.sender_email or "postmaster@localhost"
    return sender.partition("@")[2] or "localhost"


def verify_mailbox(
    email: str, *, timeout: float = DEFAULT_TIMEOUT, detect_catch_all: bool = True
) -> MailboxCheck:
    """Ask the receiving server whether it will accept mail for *email*."""
    address = (email or "").strip().lower()
    if "@" not in address:
        return MailboxCheck(address, Verdict.UNDELIVERABLE, message="malformed address")

    domain = address.rpartition("@")[2]
    hosts = mx_hosts(domain)
    if not hosts:
        return MailboxCheck(address, Verdict.UNDELIVERABLE, message=f"no MX or A record for {domain}")

    # Without outbound port 25 there is no conversation to have. Bail out before
    # burning ~20s per address discovering that the SYN goes nowhere.
    if not port25_available():
        return MailboxCheck(
            address, Verdict.UNKNOWN, message="outbound port 25 blocked; SMTP probe unavailable"
        )

    _throttle(domain)
    sender = settings.sender_email or f"postmaster@{_helo_name()}"
    last_error = ""

    for host in hosts[:2]:  # primary, then one fallback
        server = None
        try:
            server = smtplib.SMTP(timeout=timeout, local_hostname=_helo_name())
            server.connect(host, SMTP_PORT)
            server.ehlo_or_helo_if_needed()
            server.mail(sender)

            code, raw = server.rcpt(address)
            text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)

            if 200 <= code < 300:
                catch_all = False
                if detect_catch_all:
                    # If the server also accepts an address we just invented, its
                    # acceptance of the real one carries no information.
                    probe_code, _ = server.rcpt(f"{_random_localpart()}@{domain}")
                    catch_all = 200 <= probe_code < 300
                server.quit()
                if catch_all:
                    return MailboxCheck(
                        address, Verdict.RISKY_CATCH_ALL, code, "domain accepts all recipients",
                        host, True,
                    )
                return MailboxCheck(address, Verdict.DELIVERABLE, code, text, host)

            if 500 <= code < 600:
                server.quit()
                return MailboxCheck(address, Verdict.UNDELIVERABLE, code, text, host)

            # 4xx — greylisting or a temporary refusal. Not a verdict.
            last_error = f"{code} {text}"
            server.quit()
            return MailboxCheck(address, Verdict.UNKNOWN, code, text, host)

        except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        except (socket.timeout, TimeoutError):
            last_error = "timeout"
        except OSError as exc:
            # Connection refused / network unreachable — usually blocked port 25.
            last_error = f"OSError: {exc}"
        except smtplib.SMTPException as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        finally:
            if server is not None:
                try:
                    server.close()
                except Exception:  # pragma: no cover - best effort teardown
                    pass

    log.debug("smtp_verify.unknown", email=address, error=last_error)
    return MailboxCheck(address, Verdict.UNKNOWN, message=last_error or "no response")


@lru_cache(maxsize=1)
def port25_available() -> bool:
    """Can we make outbound port-25 connections at all?

    Residential ISPs commonly block this. If they do, every probe returns
    UNKNOWN and mailbox verification is simply not available — which the
    pipeline must know about rather than mistaking "unverified" for "fine".
    """
    for host in ("gmail-smtp-in.l.google.com", "mx1.zoho.com"):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # settimeout before connect() bounds the *connect* itself. Passing a
        # timeout to create_connection does not: a silently-dropped SYN (which
        # is how port 25 blocking usually manifests) still waits out the OS
        # retry schedule, ~20s, before it gives up.
        sock.settimeout(5.0)
        try:
            sock.connect((host, SMTP_PORT))
            return True
        except OSError:
            continue
        finally:
            sock.close()
    log.warning(
        "smtp_verify.port25_blocked",
        detail="outbound TCP/25 is blocked; mailbox verification unavailable",
    )
    return False
