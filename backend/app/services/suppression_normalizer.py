"""Stage 6 suppression value normalization — no DNS/HTTP."""

from __future__ import annotations

import re
from uuid import UUID

from app.core.exceptions import AppError
from app.models.enums import TEST_EMAIL_DOMAIN, SuppressionType

_CTRL = re.compile(r"[\x00-\x1f\x7f]")
_EMAIL_ASCII = re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+$")


def mask_email(email: str) -> str:
    parts = email.split("@", 1)
    if len(parts) != 2:
        return "***"
    local, domain = parts
    if not local:
        return f"***@{domain}"
    return f"{local[0]}***@{domain}"


def normalize_email(raw: str) -> tuple[str, str]:
    if raw is None or not str(raw).strip():
        raise AppError("Email value required", status_code=422, code="empty_value")
    value = str(raw).strip()
    if _CTRL.search(value):
        raise AppError("Control characters forbidden", status_code=422, code="invalid_email")
    if "<" in value or ">" in value or '"' in value or "," in value:
        raise AppError("Display-name syntax forbidden", status_code=422, code="invalid_email")
    if value.count("@") != 1:
        raise AppError("Email must contain exactly one @", status_code=422, code="invalid_email")
    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise AppError("Email must be ASCII", status_code=422, code="invalid_email") from exc
    local, domain = value.split("@", 1)
    local = local.lower()
    domain = domain.lower().rstrip(".")
    if not local:
        raise AppError("Local part required", status_code=422, code="invalid_email")
    normalized = f"{local}@{domain}"
    if not _EMAIL_ASCII.match(normalized):
        raise AppError("Invalid email format", status_code=422, code="invalid_email")
    if domain != TEST_EMAIL_DOMAIN:
        raise AppError(
            f"Stage 6 allows only @{TEST_EMAIL_DOMAIN}",
            status_code=422,
            code="real_email_forbidden",
        )
    if ".." in local or local.startswith(".") or local.endswith("."):
        raise AppError("Invalid local part", status_code=422, code="invalid_email")
    return normalized, mask_email(normalized)


def normalize_domain(raw: str) -> tuple[str, str]:
    if raw is None or not str(raw).strip():
        raise AppError("Domain value required", status_code=422, code="empty_value")
    value = str(raw).strip().lower()
    if _CTRL.search(value):
        raise AppError("Control characters forbidden", status_code=422, code="invalid_domain")
    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise AppError("IDN domains are rejected in Stage 6", status_code=422, code="invalid_domain") from exc
    for prefix in ("https://", "http://", "mailto:"):
        if value.startswith(prefix):
            value = value[len(prefix) :]
    if value.startswith("www."):
        value = value[4:]
    value = value.split("/")[0].split("?")[0].split("#")[0].split(":")[0]
    value = value.rstrip(".")
    if not value or "." not in value or " " in value or "@" in value:
        raise AppError("Invalid domain", status_code=422, code="invalid_domain")
    if not re.fullmatch(r"[a-z0-9.\-]+", value):
        raise AppError("Invalid domain characters", status_code=422, code="invalid_domain")
    return value, value


def normalize_uuid_value(raw: str, *, label: str) -> tuple[str, str]:
    if raw is None or not str(raw).strip():
        raise AppError(f"{label} value required", status_code=422, code="empty_value")
    try:
        uid = UUID(str(raw).strip())
    except (ValueError, TypeError) as exc:
        raise AppError(f"Invalid {label} id", status_code=422, code="invalid_uuid") from exc
    return str(uid), str(uid)


def normalize_suppression_value(
    suppression_type: str, raw: str
) -> tuple[str, str]:
    if suppression_type == SuppressionType.EMAIL.value:
        return normalize_email(raw)
    if suppression_type == SuppressionType.DOMAIN.value:
        return normalize_domain(raw)
    if suppression_type == SuppressionType.COMPANY.value:
        return normalize_uuid_value(raw, label="company")
    if suppression_type == SuppressionType.CAMPAIGN_LEAD.value:
        return normalize_uuid_value(raw, label="campaign_lead")
    raise AppError("Invalid suppression_type", status_code=422, code="invalid_enum")
