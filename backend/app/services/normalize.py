"""Normalization helpers for Stage 2 research deduplication."""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlparse

from app.services.validation import blank_to_none


def normalize_company_name(value: str | None) -> str | None:
    value = blank_to_none(value)
    if value is None:
        return None
    # Unicode-safe: NFKC + collapse whitespace; keep display value separate.
    normalized = unicodedata.normalize("NFKC", value)
    normalized = re.sub(r"\s+", " ", normalized).strip().lower()
    return normalized or None


def normalize_domain_for_match(value: str | None) -> str | None:
    """Normalize domain/URL for comparison without raising on soft invalid input."""
    value = blank_to_none(value)
    if value is None:
        return None
    value = value.strip().lower()
    if "://" in value or value.startswith("www."):
        if "://" not in value:
            value = "http://" + value
        parsed = urlparse(value)
        host = (parsed.netloc or parsed.path.split("/")[0]).lower()
    else:
        host = value.split("/")[0].split("?")[0].split("#")[0]
    host = host.split("@")[-1]
    host = host.removeprefix("www.")
    host = host.rstrip(".")
    return host or None


def normalize_website_for_storage(value: str | None) -> str | None:
    value = blank_to_none(value)
    if value is None:
        return None
    return value.strip()


def normalize_location(value: str | None) -> str | None:
    value = blank_to_none(value)
    if value is None:
        return None
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip().lower()


def normalize_phone(value: str | None) -> str | None:
    value = blank_to_none(value)
    if value is None:
        return None
    digits = re.sub(r"[^\d+]", "", value)
    return digits or None


def normalize_source_id(value: str | None) -> str | None:
    value = blank_to_none(value)
    if value is None:
        return None
    return value.strip()
