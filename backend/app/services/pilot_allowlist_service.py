"""Stage 7A pilot allowlist — exact email matching, no wildcards."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models.enums import TEST_EMAIL_DOMAIN
from app.models.live_pilot import LivePilotAllowlistEntry
from app.services.suppression_normalizer import mask_email

_CTRL = re.compile(r"[\x00-\x1f\x7f]")
_LOCAL_PART_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._+-]{0,62}[a-z0-9])?$", re.IGNORECASE)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def recipient_fingerprint(normalized_email: str) -> str:
    return hashlib.sha256(normalized_email.encode("utf-8")).hexdigest()


def normalize_pilot_recipient(raw: str) -> tuple[str, str, str]:
    """Normalize pilot allowlist email — Stage 7A accepts only @example.test."""
    if raw is None or not isinstance(raw, str):
        raise AppError("Invalid recipient", status_code=422, code="invalid_recipient")
    if _CTRL.search(raw):
        raise AppError("Control characters forbidden", status_code=422, code="invalid_recipient")
    if any(ch in raw for ch in ('<', '>', '"', ',', ';')):
        raise AppError("Display-name syntax forbidden", status_code=422, code="invalid_recipient")
    cleaned = raw.strip().lower()
    if " " in cleaned or "\t" in cleaned or "\r" in cleaned or "\n" in cleaned:
        raise AppError("Invalid recipient", status_code=422, code="invalid_recipient")
    try:
        cleaned.encode("ascii")
    except UnicodeEncodeError as exc:
        raise AppError(
            "Unicode spoof forbidden",
            status_code=422,
            code="invalid_recipient",
        ) from exc
    if cleaned.count("@") != 1:
        raise AppError("Invalid recipient", status_code=422, code="invalid_recipient")
    local, domain = cleaned.split("@", 1)
    if not local or not _LOCAL_PART_RE.fullmatch(local):
        raise AppError("Invalid recipient", status_code=422, code="invalid_recipient")
    if domain != TEST_EMAIL_DOMAIN:
        raise AppError(
            f"Stage 7A allows only @{TEST_EMAIL_DOMAIN}",
            status_code=422,
            code="real_email_forbidden",
        )
    normalized = f"{local}@{domain}"
    return normalized, mask_email(normalized), recipient_fingerprint(normalized)


def _entry_active(entry: LivePilotAllowlistEntry, now: datetime) -> bool:
    if not entry.is_active:
        return False
    if entry.expires_at is None:
        return True
    exp = entry.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp > now


def ensure_allowlist_entry(
    db: Session,
    *,
    campaign_id: UUID,
    email: str,
    created_by: str = "manual",
) -> LivePilotAllowlistEntry:
    normalized, masked, fingerprint = normalize_pilot_recipient(email)
    existing = db.scalars(
        select(LivePilotAllowlistEntry).where(
            LivePilotAllowlistEntry.campaign_id == campaign_id,
            LivePilotAllowlistEntry.recipient_fingerprint == fingerprint,
            LivePilotAllowlistEntry.is_active.is_(True),
        )
    ).first()
    if existing is not None:
        return existing

    entry = LivePilotAllowlistEntry(
        campaign_id=campaign_id,
        recipient_fingerprint=fingerprint,
        recipient_masked=masked,
        is_active=True,
        confirmed_by_owner=False,
        is_test_data=True,
        created_by=created_by,
        notes=f"auto-allowlist {normalized.split('@')[0]}@***",
    )
    nested = db.begin_nested()
    try:
        db.add(entry)
        db.flush()
        nested.commit()
    except IntegrityError:
        nested.rollback()
        again = db.scalars(
            select(LivePilotAllowlistEntry).where(
                LivePilotAllowlistEntry.campaign_id == campaign_id,
                LivePilotAllowlistEntry.recipient_fingerprint == fingerprint,
                LivePilotAllowlistEntry.is_active.is_(True),
            )
        ).first()
        if again is not None:
            return again
        raise AppError("Allowlist conflict", status_code=409, code="allowlist_conflict") from None
    return entry


def is_on_allowlist(db: Session, *, campaign_id: UUID, normalized_email: str) -> bool:
    fingerprint = recipient_fingerprint(normalized_email)
    entry = db.scalars(
        select(LivePilotAllowlistEntry).where(
            LivePilotAllowlistEntry.campaign_id == campaign_id,
            LivePilotAllowlistEntry.recipient_fingerprint == fingerprint,
            LivePilotAllowlistEntry.is_active.is_(True),
        )
    ).first()
    if entry is None:
        return False
    return _entry_active(entry, _utcnow())


def validate_recipient_on_allowlist(
    db: Session,
    *,
    campaign_id: UUID,
    email: str,
) -> tuple[str, str, str]:
    normalized, masked, fingerprint = normalize_pilot_recipient(email)
    if not is_on_allowlist(db, campaign_id=campaign_id, normalized_email=normalized):
        ensure_allowlist_entry(db, campaign_id=campaign_id, email=normalized)
    if not is_on_allowlist(db, campaign_id=campaign_id, normalized_email=normalized):
        raise AppError(
            "Recipient not on pilot allowlist",
            status_code=422,
            code="not_on_allowlist",
        )
    return normalized, masked, fingerprint
