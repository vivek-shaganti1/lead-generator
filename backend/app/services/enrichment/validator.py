"""Address hygiene: syntax, deliverability signals, and a confidence score.

Sending to junk addresses is the fastest way to burn a sending domain, so every
address passes through here before it can become a Lead.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import dns.exception
import dns.resolver
from email_validator import EmailNotValidError, validate_email

from app.config import settings
from app.utils import domain_of, is_free_mail, is_role_account, is_unsafe_address

# Addresses at these domains are throwaway; a business using one is not a buyer.
DISPOSABLE_DOMAINS = {
    "mailinator.com", "10minutemail.com", "guerrillamail.com", "tempmail.com",
    "trashmail.com", "yopmail.com", "sharklasers.com", "getnada.com",
    "temp-mail.org", "dispostable.com", "maildrop.cc", "throwawaymail.com",
}
# Placeholders that show up in scraped markup.
PLACEHOLDER_LOCALPARTS = {
    "example", "email", "youremail", "your-email", "name", "username",
    "test", "user", "sample", "someone", "firstname",
}
PLACEHOLDER_DOMAINS = {
    "example.com", "example.org", "example.net", "domain.com", "yourdomain.com",
    "email.com", "sentry.io", "wixpress.com", "godaddy.com",
}


@dataclass(slots=True)
class ValidationResult:
    email: str
    valid: bool
    reason: str = ""
    is_role: bool = False
    is_free: bool = False
    has_mx: bool | None = None
    confidence: float = 0.0

    def as_dict(self) -> dict:
        return {
            "email": self.email, "valid": self.valid, "reason": self.reason,
            "is_role": self.is_role, "is_free": self.is_free,
            "has_mx": self.has_mx, "confidence": round(self.confidence, 3),
        }


@lru_cache(maxsize=4096)
def _mx_lookup(domain: str) -> bool | None:
    """True/False if we got an answer, None if DNS itself failed (don't punish the lead)."""
    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=5.0)
        return len(answers) > 0
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
        # No MX is not automatically fatal - some tiny domains take mail on the A record.
        try:
            dns.resolver.resolve(domain, "A", lifetime=5.0)
            return True
        except dns.exception.DNSException:
            return False
    except dns.exception.DNSException:
        return None


def validate(email: str, check_mx: bool | None = None) -> ValidationResult:
    email = (email or "").strip().lower()
    if not email:
        return ValidationResult(email, False, "empty")

    try:
        info = validate_email(email, check_deliverability=False)
        email = info.normalized.lower()
    except EmailNotValidError as exc:
        return ValidationResult(email, False, f"syntax: {exc}")

    local, _, domain = email.partition("@")

    if is_unsafe_address(email):
        return ValidationResult(email, False, "unsafe-mailbox")
    if domain in DISPOSABLE_DOMAINS:
        return ValidationResult(email, False, "disposable-domain")
    if domain in PLACEHOLDER_DOMAINS or local in PLACEHOLDER_LOCALPARTS:
        return ValidationResult(email, False, "placeholder")
    if len(local) > 64 or len(email) > 254:
        return ValidationResult(email, False, "too-long")

    role = is_role_account(email)
    free = is_free_mail(email)

    has_mx: bool | None = None
    if settings.verify_mx if check_mx is None else check_mx:
        has_mx = _mx_lookup(domain)
        if has_mx is False:
            return ValidationResult(email, False, "no-mx", role, free, has_mx, 0.0)

    # Confidence: a branded mailbox beats a gmail; a named mailbox beats info@.
    confidence = 0.55
    if not free:
        confidence += 0.20
    if not role:
        confidence += 0.10
    if has_mx:
        confidence += 0.15
    return ValidationResult(email, True, "ok", role, free, has_mx, min(confidence, 1.0))


def pick_best(emails: list[str], business_name: str = "", check_mx: bool | None = None):
    """Choose the single best address from a scrape, preferring on-brand mailboxes."""
    scored: list[tuple[float, ValidationResult]] = []
    name_tokens = {t for t in business_name.lower().split() if len(t) > 3}
    for candidate in emails:
        result = validate(candidate, check_mx=check_mx)
        if not result.valid:
            continue
        bonus = 0.0
        domain = domain_of(candidate) or ""
        if any(token in domain for token in name_tokens):
            bonus += 0.15  # mailbox lives on the business's own domain
        if result.is_role:
            bonus += 0.05  # for cold B2B, info@ is the *right* door to knock on
        scored.append((result.confidence + bonus, result))
    if not scored:
        return None
    scored.sort(key=lambda pair: pair[0], reverse=True)
    best_score, best = scored[0]
    best.confidence = min(best_score, 1.0)
    return best
