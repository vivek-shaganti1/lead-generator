from __future__ import annotations

import pytest

from app.utils import (
    dedupe_key,
    domain_of,
    extract_emails,
    is_free_mail,
    is_role_account,
    is_social_only,
    is_unsafe_address,
    normalize_name,
    normalize_phone,
    truncate,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Rossi's Trattoria Ltd.", "rossis trattoria"),
        ("Café Roma", "cafe roma"),
        ("THE Corner Shop CO", "corner shop"),
        ("  Multiple   Spaces  ", "multiple spaces"),
        ("", ""),
    ],
)
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("+353 21 555 0100", "3215550100"),
        ("00353 21 555 0100", "3215550100"),
        ("12345", None),
        (None, None),
    ],
)
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


def test_dedupe_key_matches_across_formatting():
    a = dedupe_key("Café Roma", 51.8985, -8.4756, "+353 21 555 0100")
    b = dedupe_key("Cafe Roma Ltd", 51.8985, -8.4756, "00353 21 555 0100")
    assert a == b


def test_dedupe_key_uses_geo_when_no_phone():
    a = dedupe_key("Cafe Roma", 51.89851, -8.47561, None)
    b = dedupe_key("Cafe Roma", 51.89849, -8.47559, None)
    assert a == b
    far = dedupe_key("Cafe Roma", 52.5, -8.4, None)
    assert far != a


def test_dedupe_key_distinguishes_different_businesses():
    assert dedupe_key("Cafe Roma", 51.9, -8.4, None) != dedupe_key("Cafe Milano", 51.9, -8.4, None)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("https://facebook.com/mystore", True),
        ("https://www.instagram.com/mystore/", True),
        ("http://mystore.ie", False),
        ("https://linktr.ee/store", True),
        ("https://mystore.business.site", True),
        (None, False),
        ("", False),
    ],
)
def test_is_social_only(value, expected):
    assert is_social_only(value) is expected


def test_domain_of_handles_emails_and_urls():
    assert domain_of("Info@Example.COM") == "example.com"
    assert domain_of("https://www.example.com/path") == "example.com"
    assert domain_of("example.com") == "example.com"
    assert domain_of(None) is None


def test_role_free_and_unsafe_detection():
    assert is_role_account("info@shop.ie")
    assert not is_role_account("maria@shop.ie")
    assert is_free_mail("maria@gmail.com")
    assert not is_free_mail("maria@shop.ie")
    assert is_unsafe_address("no-reply@shop.ie")
    assert is_unsafe_address("postmaster@shop.ie")
    assert not is_unsafe_address("hello@shop.ie")


def test_extract_emails_dedupes_and_skips_images():
    text = "Write to Info@Shop.ie or info@shop.ie. Logo: hero@2x.png"
    assert extract_emails(text) == ["info@shop.ie"]


def test_truncate():
    assert truncate("abcdef", 4) == "abc…"
    assert truncate("abc", 10) == "abc"
    assert truncate(None) == ""


# ------------------------------------------------------------------ config
def test_env_file_is_anchored_to_the_repo_not_the_cwd():
    """A bare env_file=".env" resolves against the CWD, and every local
    entrypoint runs from backend/ — which silently ignored the repo-root .env
    and fell back to code defaults."""
    from pathlib import Path

    from app.config import _BACKEND_DIR, _REPO_ROOT

    assert (_REPO_ROOT / "docker-compose.yml").is_file(), "repo root misidentified"
    assert (_BACKEND_DIR / "app" / "config.py").is_file(), "backend dir misidentified"
    for candidate in (_REPO_ROOT / ".env", _BACKEND_DIR / ".env"):
        assert Path(candidate).is_absolute()


def test_test_env_ignores_the_developers_env_file():
    """The suite must not inherit a local .env, or one machine goes red alone."""
    from app.config import env_files_for

    assert env_files_for("test") is None
    for env in ("dev", "prod", None):
        assert env_files_for(env), f"{env} should still read .env"
