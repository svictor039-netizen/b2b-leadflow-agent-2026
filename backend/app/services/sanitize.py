"""Recursive sanitization of research payloads — strip secrets and PII."""

from __future__ import annotations

from typing import Any

# Exact keys (after lower + hyphen→underscore) that must be redacted.
SENSITIVE_EXACT_KEYS = frozenset(
    {
        "email",
        "e_mail",
        "personal_email",
        "phone",
        "mobile",
        "token",
        "api_key",
        "apikey",
        "authorization",
        "password",
        "passwd",
        "secret",
        "cookie",
        "bearer",
        "credential",
        "access_token",
        "refresh_token",
        "auth_token",
    }
)

# Token-level match: key split on "_" — redacts contact_email, API_KEY, etc.
SENSITIVE_TOKENS = frozenset(
    {
        "email",
        "phone",
        "mobile",
        "token",
        "password",
        "passwd",
        "secret",
        "cookie",
        "authorization",
        "bearer",
        "credential",
        "apikey",
    }
)

# Keys that contain sensitive tokens but are safe metadata flags (not values).
SAFE_METADATA_KEYS = frozenset(
    {
        "has_contact_email",
        "has_email",
        "email_present",
        "phone_present",
    }
)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.strip().lower().replace("-", "_")
    if normalized in SAFE_METADATA_KEYS:
        return False
    if normalized in SENSITIVE_EXACT_KEYS:
        return True
    # api_key → tokens api, key — also match joined "apikey" via exact set above
    tokens = [t for t in normalized.split("_") if t]
    if "api" in tokens and "key" in tokens:
        return True
    return any(token in SENSITIVE_TOKENS for token in tokens)


def sanitize_payload(value: Any) -> Any:
    """Recursively remove/mask sensitive keys from dict/list structures."""
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            key_str = str(key)
            if _is_sensitive_key(key_str):
                cleaned[key_str] = "***REDACTED***"
            else:
                cleaned[key_str] = sanitize_payload(item)
        return cleaned
    if isinstance(value, list):
        return [sanitize_payload(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_payload(item) for item in value]
    return value
