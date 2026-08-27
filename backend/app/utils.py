"""Small pure helpers. Kept dependency-light so they are trivial to unit test."""
from __future__ import annotations

import hashlib
import re
import secrets
import unicodedata
from datetime import date, datetime, timezone
from urllib.parse import urlparse

# Words that carry no identity for a business name; stripping them makes
# "Cafe Roma Ltd." and "Café Roma" collapse onto the same dedupe key.
_LEGAL_SUFFIXES = {
    "ltd", "limited", "llc", "inc", "incorporated", "corp", "corporation", "gmbh",
    "bv", "nv", "plc", "pvt", "private", "pte", "srl", "sarl", "sa", "ag", "oy",
    "ab", "as", "aps", "kft", "sp", "zoo", "co", "company", "the", "and",
}
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,24}"
)
ROLE_LOCALPARTS = {
    "info", "contact", "hello", "office", "admin", "sales", "support", "mail",
    "enquiries", "inquiries", "reception", "booking", "bookings", "reservations",
    "team", "help", "service", "kontakt", "post", "shop", "orders",
}
# Addresses that are never a human we want to pitch.
UNSAFE_LOCALPARTS = {
    "noreply", "no-reply", "donotreply", "do-not-reply", "postmaster", "abuse",
    "mailer-daemon", "bounce", "bounces", "unsubscribe", "privacy", "dpo",
    "webmaster", "hostmaster", "spam", "security",
}
FREE_MAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "hotmail.com",
    "outlook.com", "live.com", "aol.com", "icloud.com", "me.com", "gmx.de",
    "gmx.net", "web.de", "mail.ru", "yandex.ru", "protonmail.com", "proton.me",
    "rediffmail.com", "qq.com", "163.com",
}
# Sites that are a social profile, not a real website. A business whose only
# "website" is one of these is still a prospect for us.
SOCIAL_HOSTS = {
    "facebook.com", "m.facebook.com", "fb.com", "fb.me", "instagram.com",
    "linktr.ee", "linkedin.com", "twitter.com", "x.com", "tiktok.com",
    "wa.me", "api.whatsapp.com", "t.me", "youtube.com", "yelp.com",
    "tripadvisor.com", "zomato.com", "swiggy.com", "justdial.com",
    "sites.google.com", "business.site", "wixsite.com", "google.com",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def today_str(now: datetime | None = None) -> str:
    return (now or utcnow()).astimezone(timezone.utc).date().isoformat()


def parse_day(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def strip_accents(value: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c)
    )


def normalize_name(name: str) -> str:
    """Lowercase, de-accent, drop legal suffixes and punctuation."""
    if not name:
        return ""
    # Elide apostrophes rather than splitting on them, so "Rossi's" stays one token.
    without_apostrophes = re.sub(r"['\u2018\u2019\u02bc]", "", strip_accents(name).lower())
    cleaned = _NON_ALNUM.sub(" ", without_apostrophes)
    tokens = [t for t in cleaned.split() if t and t not in _LEGAL_SUFFIXES]
    return " ".join(tokens)


def normalize_phone(phone: str | None) -> str | None:
    """Keep digits only, drop leading zeros/IDD prefix so formats collapse."""
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    digits = re.sub(r"^00", "", digits)
    if len(digits) < 6:
        return None
    return digits[-10:] if len(digits) > 10 else digits


def geo_bucket(lat: float | None, lon: float | None, precision: int = 2) -> str:
    """Round coordinates into a ~1km cell for proximity dedupe.

    Rounding always has cell edges, so two providers can straddle one. We use a
    coarse cell deliberately: the name must match too, and two businesses with
    the same normalised name inside a kilometre are the same business.
    """
    if lat is None or lon is None:
        return "nogeo"
    return f"{round(lat, precision)}:{round(lon, precision)}"


def dedupe_key(name: str, lat: float | None, lon: float | None, phone: str | None = None) -> str:
    """Stable identity for a place across providers.

    Phone is the strongest signal when present; otherwise name+location.
    """
    norm = normalize_name(name)
    phone_norm = normalize_phone(phone)
    basis = f"tel:{phone_norm}" if phone_norm else f"{norm}|{geo_bucket(lat, lon)}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:32]


def domain_of(email_or_url: str | None) -> str | None:
    if not email_or_url:
        return None
    value = email_or_url.strip().lower()
    if "@" in value and "://" not in value:
        return value.rsplit("@", 1)[-1] or None
    if "://" not in value:
        value = "http://" + value
    try:
        host = urlparse(value).netloc.split(":")[0]
        return host.lstrip("www.") or None
    except Exception:
        return None


parse_domain = domain_of


def is_social_only(url: str | None) -> bool:
    """True when the 'website' is really just a social/aggregator profile."""
    host = domain_of(url)
    if not host:
        return False
    return any(host == s or host.endswith("." + s) for s in SOCIAL_HOSTS)


def is_role_account(email: str) -> bool:
    return email.split("@", 1)[0].lower() in ROLE_LOCALPARTS


def is_unsafe_address(email: str) -> bool:
    local = email.split("@", 1)[0].lower()
    if local in UNSAFE_LOCALPARTS:
        return True
    return any(local.startswith(p) for p in ("noreply", "no-reply", "donotreply"))


def is_free_mail(email: str) -> bool:
    return (domain_of(email) or "") in FREE_MAIL_DOMAINS


def extract_emails(text: str) -> list[str]:
    """Pull unique, lowercased addresses out of arbitrary text, order preserved."""
    seen: dict[str, None] = {}
    for match in _EMAIL_RE.findall(text or ""):
        cleaned = match.lower().strip(".")
        # image filenames and sentry keys look like emails often enough to matter
        if cleaned.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")):
            continue
        seen.setdefault(cleaned, None)
    return list(seen)


def new_token(nbytes: int = 24) -> str:
    return secrets.token_urlsafe(nbytes)


def truncate(text: str | None, limit: int = 500) -> str:
    if not text:
        return ""
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def coerce_aware(dt: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; normalise everything to UTC-aware."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
