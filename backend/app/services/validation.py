"""Shared validation helpers for Stage 1."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from email_validator import EmailNotValidError, validate_email

from app.core.exceptions import AppError

EMPTY_TO_NULL_FIELDS = frozenset(
    {
        "legal_name",
        "website",
        "domain",
        "description",
        "offer_description",
        "ideal_customer",
        "desired_cta",
        "label",
        "source_url",
        "consent_source",
        "country",
        "region",
        "city",
        "address",
        "postal_code",
    }
)

ALLOWED_URL_SCHEMES = frozenset({"http", "https"})
BLOCKED_URL_SCHEMES = frozenset({"file", "ftp", "javascript", "data", "vbscript"})

DOMAIN_RE = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$"
)


def blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None


def normalize_optional_str(value: str | None) -> str | None:
    return blank_to_none(value)


def normalize_domain(value: str | None) -> str | None:
    value = blank_to_none(value)
    if value is None:
        return None
    value = value.lower()
    value = re.sub(r"^https?://", "", value)
    value = value.split("/")[0].split("?")[0].split("#")[0]
    value = value.removeprefix("www.")
    if value and not DOMAIN_RE.match(value):
        raise AppError("Invalid domain format.", status_code=422, code="invalid_domain")
    return value or None


def normalize_website(value: str | None) -> str | None:
    value = blank_to_none(value)
    if value is None:
        return None
    assert_safe_url(value)
    return value


def assert_safe_url(value: str) -> None:
    parsed = urlparse(value.strip())
    scheme = (parsed.scheme or "").lower()
    if scheme in BLOCKED_URL_SCHEMES:
        raise AppError(
            f"URL scheme '{scheme}' is not allowed.",
            status_code=422,
            code="invalid_url_scheme",
        )
    if scheme and scheme not in ALLOWED_URL_SCHEMES:
        raise AppError(
            f"URL scheme '{scheme}' is not allowed. Use http or https.",
            status_code=422,
            code="invalid_url_scheme",
        )
    if not scheme:
        # Allow scheme-less host-like values for website? Spec says external URLs must be http/https
        raise AppError(
            "External URL must use http or https.",
            status_code=422,
            code="invalid_url_scheme",
        )
    if not parsed.netloc:
        raise AppError("Invalid URL.", status_code=422, code="invalid_url")


def validate_email_value(value: str) -> str:
    try:
        result = validate_email(value, check_deliverability=False)
        return result.normalized
    except EmailNotValidError as exc:
        raise AppError(str(exc), status_code=422, code="invalid_email") from exc
