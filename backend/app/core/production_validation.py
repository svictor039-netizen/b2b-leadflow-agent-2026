"""Production configuration validation — fail-fast on unsafe settings."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from app.core.config import Settings

UNSAFE_SECRET_MARKERS: tuple[str, ...] = (
    "leadflow_dev_password",
    "leadflow:leadflow@",
    "changeme",
    "password123",
    "CHANGE_ME",
    "example.com",
    "your-secret",
    "placeholder",
)

UNSAFE_ORIGIN_HOSTS: tuple[str, ...] = (
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "[::1]",
)

MIN_PRODUCTION_SECRET_LENGTH = 16


def _contains_unsafe_marker(value: str) -> bool:
    lowered = value.lower()
    return any(marker.lower() in lowered for marker in UNSAFE_SECRET_MARKERS)


def _database_password(url: str) -> str | None:
    parsed = urlparse(url)
    return parsed.password


def _origin_host(origin: str) -> str:
    parsed = urlparse(origin)
    return (parsed.hostname or origin).lower()


def validate_production_settings(settings: Settings) -> list[str]:
    """Return human-readable validation errors; empty list means OK."""
    errors: list[str] = []

    if settings.environment.lower() != "production":
        errors.append("ENVIRONMENT must be 'production' in production runtime mode.")

    if settings.debug:
        errors.append("DEBUG must be false in production.")

    if not settings.database_url.strip():
        errors.append("DATABASE_URL is required in production.")

    if settings.database_url.strip():
        password = _database_password(settings.database_url)
        if not password:
            errors.append("DATABASE_URL must include a password in production.")
        elif len(password) < MIN_PRODUCTION_SECRET_LENGTH:
            errors.append(
                f"DATABASE_URL password must be at least {MIN_PRODUCTION_SECRET_LENGTH} characters."
            )
        elif _contains_unsafe_marker(settings.database_url):
            if settings.allow_insecure_local_production_smoke and (
                "local_smoke_password" in settings.database_url
                or "leadflow_dev_password" in settings.database_url
            ):
                pass
            else:
                errors.append("DATABASE_URL contains unsafe placeholder or dev default values.")

    if not settings.redis_url.strip():
        errors.append("REDIS_URL is required in production.")
    elif _contains_unsafe_marker(settings.redis_url):
        errors.append("REDIS_URL contains unsafe placeholder values.")

    origin_host = _origin_host(settings.frontend_origin)
    if not settings.allow_insecure_local_production_smoke:
        if origin_host in UNSAFE_ORIGIN_HOSTS:
            errors.append(
                "FRONTEND_ORIGIN must not use localhost/loopback in production "
                "(development CORS is not allowed)."
            )
        if not settings.frontend_origin.startswith("https://"):
            errors.append("FRONTEND_ORIGIN must use HTTPS in production.")
    elif not settings.frontend_origin.strip():
        errors.append("FRONTEND_ORIGIN is required.")

    if settings.real_email_provider_enabled:
        errors.append("REAL_EMAIL_PROVIDER_ENABLED must be false until Stage 7B review.")

    if settings.live_outreach_enabled:
        errors.append("LIVE_OUTREACH_ENABLED must be false until Stage 7B review.")

    if settings.provider_api_key.strip():
        errors.append("PROVIDER_API_KEY must be empty in Stage 8 production posture.")

    if settings.live_provider_name.strip() and settings.live_provider_name != "disabled_live":
        errors.append("LIVE_PROVIDER_NAME must be empty or 'disabled_live' in Stage 8.")

    if settings.live_provider_api_key.strip():
        errors.append("LIVE_PROVIDER_API_KEY must be empty in Stage 8 production posture.")

    if settings.live_daily_limit > 0 and not settings.system_stop_all:
        errors.append(
            "LIVE_DAILY_LIMIT > 0 requires explicit SYSTEM_STOP_ALL=false review (Stage 7B)."
        )

    for field_name, value in (
        ("PROVIDER_API_KEY", settings.provider_api_key),
        ("LIVE_PROVIDER_API_KEY", settings.live_provider_api_key),
    ):
        if value and _contains_unsafe_marker(value):
            errors.append(f"{field_name} contains placeholder values.")

    return errors


def format_production_validation_error(errors: list[str]) -> str:
    bullet_lines = "\n".join(f"  - {err}" for err in errors)
    return f"Production configuration validation failed:\n{bullet_lines}"
