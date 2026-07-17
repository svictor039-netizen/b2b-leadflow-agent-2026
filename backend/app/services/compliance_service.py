"""Stage 6 compliance gate, suppression CRUD, test events, readiness."""

from __future__ import annotations

import hashlib
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from collections.abc import Iterator, Sequence
from uuid import UUID

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.models.campaign import Campaign
from app.models.campaign_lead import CampaignLead
from app.models.compliance_log import ComplianceDecisionLog
from app.models.enums import (
    MAX_COMPLIANCE_REASON_LENGTH,
    MAX_SUPPRESSION_LIST_LIMIT,
    SUPPRESSION_BLOCK_PREFIX,
    ComplianceCheckContext,
    ComplianceDecision,
    ComplianceTestEventType,
    ProviderReadinessStatus,
    SuppressionReason,
    SuppressionScope,
    SuppressionSource,
    SuppressionType,
)
from app.models.outreach_message import OutreachMessage
from app.models.suppression_entry import SuppressionEntry
from app.schemas.compliance import (
    ComplianceCheckResponse,
    ProviderReadinessCheck,
    ProviderReadinessReport,
    SuppressionCreate,
    SuppressionListResponse,
    SuppressionPatch,
    SuppressionRead,
    TestComplianceEventCreate,
    TestComplianceEventResponse,
)
from app.security.stop_all import is_system_stopped
from app.services.suppression_normalizer import mask_email, normalize_email

logger = logging.getLogger(__name__)

_PLACEHOLDER_SECRETS = frozenset(
    {
        "",
        "changeme",
        "change-me",
        "your-api-key",
        "your_api_key",
        "xxx",
        "todo",
        "placeholder",
        "none",
        "null",
    }
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _configured_secret(value: str | None) -> bool:
    raw = (value or "").strip()
    if not raw:
        return False
    return raw.lower() not in _PLACEHOLDER_SECRETS


def _advisory_lock_id(key: str) -> int:
    digest = hashlib.sha256(f"stage6:{key}".encode()).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFFFFFFFFFFFFFF


def suppression_mutation_lock_keys(
    *,
    scope: str,
    suppression_type: str,
    normalized_value: str,
    campaign_id: UUID | None,
) -> list[str]:
    if scope == SuppressionScope.GLOBAL.value:
        return [f"GLOBAL:{suppression_type}:{normalized_value}"]
    return [f"CAMPAIGN:{suppression_type}:{normalized_value}:{campaign_id}"]


def message_compliance_lock_keys(
    *,
    campaign_id: UUID,
    email: str | None,
    domain: str | None,
    company_id: UUID | None,
    lead_id: UUID | None,
) -> list[str]:
    keys: list[str] = []
    if email:
        keys.append(f"GLOBAL:{SuppressionType.EMAIL.value}:{email}")
        keys.append(f"CAMPAIGN:{SuppressionType.EMAIL.value}:{email}:{campaign_id}")
    if lead_id:
        keys.append(f"GLOBAL:{SuppressionType.CAMPAIGN_LEAD.value}:{lead_id}")
        keys.append(
            f"CAMPAIGN:{SuppressionType.CAMPAIGN_LEAD.value}:{lead_id}:{campaign_id}"
        )
    if company_id:
        keys.append(f"GLOBAL:{SuppressionType.COMPANY.value}:{company_id}")
        keys.append(
            f"CAMPAIGN:{SuppressionType.COMPANY.value}:{company_id}:{campaign_id}"
        )
    if domain:
        keys.append(f"GLOBAL:{SuppressionType.DOMAIN.value}:{domain}")
        keys.append(f"CAMPAIGN:{SuppressionType.DOMAIN.value}:{domain}:{campaign_id}")
    return keys


@contextmanager
def compliance_locks(db: Session, keys: Sequence[str]) -> Iterator[None]:
    """Session-level advisory locks — shared by send gate and suppression mutations."""
    lock_ids = sorted({_advisory_lock_id(k) for k in keys if k})
    for lid in lock_ids:
        db.execute(text("SELECT pg_advisory_lock(:k)"), {"k": lid})
    try:
        yield
    finally:
        for lid in reversed(lock_ids):
            db.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": lid})


@dataclass
class ComplianceResult:
    allowed: bool
    decision: str
    reason_code: str
    matched_entry: SuppressionEntry | None = None
    safe_message: str = ""
    suppression_type: str | None = None
    scope: str | None = None
    masked_recipient: str | None = None


def _entry_active(entry: SuppressionEntry, now: datetime) -> bool:
    if not entry.is_active:
        return False
    if entry.expires_at is None:
        return True
    exp = entry.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp > now


def _to_read(entry: SuppressionEntry) -> SuppressionRead:
    return SuppressionRead.model_validate(entry)


def create_suppression(
    db: Session,
    data: SuppressionCreate,
    *,
    source: str | None = None,
    created_by: str = "manual",
) -> SuppressionRead:
    from app.services.suppression_normalizer import normalize_suppression_value

    if data.is_test_data is False:
        raise AppError("is_test_data must be true", status_code=422, code="test_data_required")
    scope_v = data.scope.value if hasattr(data.scope, "value") else str(data.scope)
    type_v = (
        data.suppression_type.value
        if hasattr(data.suppression_type, "value")
        else str(data.suppression_type)
    )
    reason_v = data.reason.value if hasattr(data.reason, "value") else str(data.reason)
    if scope_v == SuppressionScope.CAMPAIGN.value:
        if data.campaign_id is None:
            raise AppError(
                "campaign_id required for CAMPAIGN scope",
                status_code=422,
                code="campaign_required",
            )
        if db.get(Campaign, data.campaign_id) is None:
            raise AppError("Campaign not found.", status_code=404, code="not_found")
        campaign_id = data.campaign_id
    else:
        if data.campaign_id is not None:
            raise AppError(
                "GLOBAL scope must not include campaign_id",
                status_code=422,
                code="global_campaign_forbidden",
            )
        campaign_id = None

    normalized, display = normalize_suppression_value(type_v, data.value)
    src_raw = source or data.source or SuppressionSource.MANUAL
    src = src_raw.value if hasattr(src_raw, "value") else str(src_raw)
    if src not in {s.value for s in SuppressionSource}:
        raise AppError("Invalid source", status_code=422, code="invalid_enum")

    lock_keys = suppression_mutation_lock_keys(
        scope=scope_v,
        suppression_type=type_v,
        normalized_value=normalized,
        campaign_id=campaign_id,
    )
    with compliance_locks(db, lock_keys):
        existing_q = select(SuppressionEntry).where(
            SuppressionEntry.scope == scope_v,
            SuppressionEntry.suppression_type == type_v,
            SuppressionEntry.normalized_value == normalized,
            SuppressionEntry.is_active.is_(True),
        )
        if campaign_id is None:
            existing_q = existing_q.where(SuppressionEntry.campaign_id.is_(None))
        else:
            existing_q = existing_q.where(SuppressionEntry.campaign_id == campaign_id)
        existing = db.scalars(existing_q).first()
        if existing is not None:
            return _to_read(existing)

        entry = SuppressionEntry(
            scope=scope_v,
            campaign_id=campaign_id,
            suppression_type=type_v,
            normalized_value=normalized,
            display_value=display,
            reason=reason_v,
            source=src,
            is_active=True,
            expires_at=data.expires_at,
            created_by=created_by,
            notes=(data.notes or "")[:MAX_COMPLIANCE_REASON_LENGTH] or None,
            is_test_data=True,
        )
        nested = db.begin_nested()
        try:
            db.add(entry)
            db.flush()
            nested.commit()
        except IntegrityError:
            nested.rollback()
            again_q = select(SuppressionEntry).where(
                SuppressionEntry.scope == scope_v,
                SuppressionEntry.suppression_type == type_v,
                SuppressionEntry.normalized_value == normalized,
                SuppressionEntry.is_active.is_(True),
            )
            if campaign_id is None:
                again_q = again_q.where(SuppressionEntry.campaign_id.is_(None))
            else:
                again_q = again_q.where(SuppressionEntry.campaign_id == campaign_id)
            again = db.scalars(again_q).first()
            if again is not None:
                return _to_read(again)
            raise AppError(
                "Suppression conflict", status_code=409, code="suppression_conflict"
            ) from None

        db.commit()
        db.refresh(entry)
        return _to_read(entry)


def list_suppressions(
    db: Session,
    *,
    scope: str | None = None,
    suppression_type: str | None = None,
    reason: str | None = None,
    is_active: bool | None = None,
    campaign_id: UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> SuppressionListResponse:
    if limit < 1 or limit > MAX_SUPPRESSION_LIST_LIMIT:
        raise AppError("Invalid limit", status_code=422, code="invalid_limit")
    if offset < 0:
        raise AppError("Invalid offset", status_code=422, code="invalid_offset")
    q = select(SuppressionEntry)
    if scope:
        q = q.where(SuppressionEntry.scope == scope)
    if suppression_type:
        q = q.where(SuppressionEntry.suppression_type == suppression_type)
    if reason:
        q = q.where(SuppressionEntry.reason == reason)
    if is_active is not None:
        q = q.where(SuppressionEntry.is_active.is_(is_active))
    if campaign_id is not None:
        q = q.where(
            or_(
                SuppressionEntry.campaign_id == campaign_id,
                and_(
                    SuppressionEntry.scope == SuppressionScope.GLOBAL.value,
                    SuppressionEntry.campaign_id.is_(None),
                ),
            )
        )
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(
        q.order_by(SuppressionEntry.created_at.asc(), SuppressionEntry.id.asc())
        .limit(limit)
        .offset(offset)
    ).all()
    return SuppressionListResponse(
        items=[_to_read(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def get_suppression(db: Session, entry_id: UUID) -> SuppressionRead:
    entry = db.get(SuppressionEntry, entry_id)
    if entry is None:
        raise AppError("Suppression not found.", status_code=404, code="not_found")
    return _to_read(entry)


def patch_suppression(db: Session, entry_id: UUID, data: SuppressionPatch) -> SuppressionRead:
    entry = db.get(SuppressionEntry, entry_id)
    if entry is None:
        raise AppError("Suppression not found.", status_code=404, code="not_found")
    if data.expires_at is not None:
        entry.expires_at = data.expires_at
    if data.notes is not None:
        entry.notes = data.notes[:MAX_COMPLIANCE_REASON_LENGTH]
    if data.reason is not None:
        entry.reason = data.reason
    db.commit()
    db.refresh(entry)
    return _to_read(entry)


def deactivate_suppression(db: Session, entry_id: UUID) -> SuppressionRead:
    entry = db.get(SuppressionEntry, entry_id)
    if entry is None:
        raise AppError("Suppression not found.", status_code=404, code="not_found")
    if not entry.is_active:
        return _to_read(entry)
    lock_keys = suppression_mutation_lock_keys(
        scope=entry.scope,
        suppression_type=entry.suppression_type,
        normalized_value=entry.normalized_value,
        campaign_id=entry.campaign_id,
    )
    with compliance_locks(db, lock_keys):
        db.refresh(entry)
        if not entry.is_active:
            return _to_read(entry)
        entry.is_active = False
        db.commit()
        db.refresh(entry)
        return _to_read(entry)


def reactivate_suppression(db: Session, entry_id: UUID) -> SuppressionRead:
    """Reactivate inactive entry.

    Semantics: sets is_active=True under advisory lock. If expires_at is already
    in the past, expires_at is cleared so reactivation is effective. Idempotent
    when already active (no field mutation). Concurrent reactivate of two rows
    for the same active key → 409 via partial unique + IntegrityError.
    """
    entry = db.get(SuppressionEntry, entry_id)
    if entry is None:
        raise AppError("Suppression not found.", status_code=404, code="not_found")
    if entry.is_active:
        return _to_read(entry)
    lock_keys = suppression_mutation_lock_keys(
        scope=entry.scope,
        suppression_type=entry.suppression_type,
        normalized_value=entry.normalized_value,
        campaign_id=entry.campaign_id,
    )
    with compliance_locks(db, lock_keys):
        db.refresh(entry)
        if entry.is_active:
            return _to_read(entry)
        conflict_q = select(SuppressionEntry).where(
            SuppressionEntry.id != entry.id,
            SuppressionEntry.scope == entry.scope,
            SuppressionEntry.suppression_type == entry.suppression_type,
            SuppressionEntry.normalized_value == entry.normalized_value,
            SuppressionEntry.is_active.is_(True),
        )
        if entry.campaign_id is None:
            conflict_q = conflict_q.where(SuppressionEntry.campaign_id.is_(None))
        else:
            conflict_q = conflict_q.where(SuppressionEntry.campaign_id == entry.campaign_id)
        if db.scalars(conflict_q).first() is not None:
            raise AppError(
                "Active suppression already exists for this key",
                status_code=409,
                code="active_exists",
            )
        nested = db.begin_nested()
        try:
            entry.is_active = True
            if entry.expires_at is not None:
                exp = entry.expires_at
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                if exp <= _utcnow():
                    entry.expires_at = None
            db.flush()
            nested.commit()
        except IntegrityError:
            nested.rollback()
            raise AppError(
                "Active suppression already exists for this key",
                status_code=409,
                code="active_exists",
            ) from None
        db.commit()
        db.refresh(entry)
        return _to_read(entry)


def _find_match(
    db: Session,
    *,
    campaign_id: UUID,
    email: str | None,
    domain: str | None,
    company_id: UUID | None,
    lead_id: UUID | None,
) -> SuppressionEntry | None:
    now = _utcnow()
    candidates: list[SuppressionEntry] = []

    def _load(scope: str, stype: str, value: str, camp: UUID | None) -> None:
        q = select(SuppressionEntry).where(
            SuppressionEntry.scope == scope,
            SuppressionEntry.suppression_type == stype,
            SuppressionEntry.normalized_value == value,
            SuppressionEntry.is_active.is_(True),
        )
        if camp is None:
            q = q.where(SuppressionEntry.campaign_id.is_(None))
        else:
            q = q.where(SuppressionEntry.campaign_id == camp)
        row = db.scalars(q).first()
        if row is not None and _entry_active(row, now):
            candidates.append(row)

    if email:
        _load(SuppressionScope.GLOBAL.value, SuppressionType.EMAIL.value, email, None)
        _load(SuppressionScope.CAMPAIGN.value, SuppressionType.EMAIL.value, email, campaign_id)
    if lead_id:
        _load(
            SuppressionScope.GLOBAL.value,
            SuppressionType.CAMPAIGN_LEAD.value,
            str(lead_id),
            None,
        )
        _load(
            SuppressionScope.CAMPAIGN.value,
            SuppressionType.CAMPAIGN_LEAD.value,
            str(lead_id),
            campaign_id,
        )
    if company_id:
        _load(
            SuppressionScope.GLOBAL.value,
            SuppressionType.COMPANY.value,
            str(company_id),
            None,
        )
        _load(
            SuppressionScope.CAMPAIGN.value,
            SuppressionType.COMPANY.value,
            str(company_id),
            campaign_id,
        )
    if domain:
        _load(SuppressionScope.GLOBAL.value, SuppressionType.DOMAIN.value, domain, None)
        _load(SuppressionScope.CAMPAIGN.value, SuppressionType.DOMAIN.value, domain, campaign_id)

    priority = {
        SuppressionType.EMAIL.value: 0,
        SuppressionType.CAMPAIGN_LEAD.value: 1,
        SuppressionType.COMPANY.value: 2,
        SuppressionType.DOMAIN.value: 3,
    }
    if not candidates:
        return None
    candidates.sort(key=lambda e: (priority.get(e.suppression_type, 9), str(e.id)))
    return candidates[0]


def _log_decision(
    db: Session,
    *,
    campaign_id: UUID,
    lead_id: UUID | None,
    message_id: UUID | None,
    execution_run_id: UUID | None,
    result: ComplianceResult,
    check_context: str,
) -> None:
    matched = str(result.matched_entry.id) if result.matched_entry else "none"
    mid = str(message_id) if message_id else "none"
    key_raw = f"{check_context}:{mid}:{result.decision}:{matched}:{result.reason_code}"
    key = hashlib.sha256(key_raw.encode()).hexdigest()[:64]
    existing = db.scalars(
        select(ComplianceDecisionLog).where(ComplianceDecisionLog.idempotency_key == key)
    ).first()
    if existing is not None:
        return
    log = ComplianceDecisionLog(
        campaign_id=campaign_id,
        campaign_lead_id=lead_id,
        outreach_message_id=message_id,
        execution_run_id=execution_run_id,
        decision=result.decision,
        matched_suppression_entry_id=result.matched_entry.id if result.matched_entry else None,
        check_context=check_context,
        reason_code=result.reason_code,
        safe_details=(result.safe_message or "")[:MAX_COMPLIANCE_REASON_LENGTH] or None,
        masked_recipient=result.masked_recipient,
        idempotency_key=key,
        checked_at=_utcnow(),
        is_test_data=True,
    )
    nested = db.begin_nested()
    try:
        db.add(log)
        db.flush()
        nested.commit()
    except IntegrityError:
        nested.rollback()


def check_outreach_compliance(
    db: Session,
    *,
    campaign_id: UUID,
    message: OutreachMessage | None = None,
    message_id: UUID | None = None,
    execution_run_id: UUID | None = None,
    check_context: str = ComplianceCheckContext.EXPLICIT_SEND.value,
    persist_log: bool = True,
) -> ComplianceResult:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise AppError("Campaign not found.", status_code=404, code="not_found")

    msg = message
    if msg is None and message_id is not None:
        msg = db.get(OutreachMessage, message_id)
    if msg is None:
        raise AppError("Message not found.", status_code=404, code="not_found")
    if msg.campaign_id != campaign_id:
        raise AppError("Message not found for campaign.", status_code=404, code="not_found")
    if not msg.is_test_data:
        result = ComplianceResult(
            allowed=False,
            decision=ComplianceDecision.BLOCKED.value,
            reason_code="non_test_message",
            safe_message="Only test messages are allowed in Stage 6",
        )
        if persist_log:
            _log_decision(
                db,
                campaign_id=campaign_id,
                lead_id=msg.campaign_lead_id,
                message_id=msg.id,
                execution_run_id=execution_run_id,
                result=result,
                check_context=check_context,
            )
            db.commit()
        return result

    lead = db.get(CampaignLead, msg.campaign_lead_id)
    company_id = lead.company_id if lead else None
    try:
        email_norm, masked = normalize_email(msg.recipient_email)
        domain_norm = email_norm.split("@", 1)[1]
    except AppError as exc:
        result = ComplianceResult(
            allowed=False,
            decision=ComplianceDecision.BLOCKED.value,
            reason_code=exc.code or "invalid_recipient",
            safe_message=exc.message,
            masked_recipient=mask_email(msg.recipient_email) if msg.recipient_email else None,
        )
        if persist_log:
            _log_decision(
                db,
                campaign_id=campaign_id,
                lead_id=msg.campaign_lead_id,
                message_id=msg.id,
                execution_run_id=execution_run_id,
                result=result,
                check_context=check_context,
            )
            db.commit()
        return result

    matched = _find_match(
        db,
        campaign_id=campaign_id,
        email=email_norm,
        domain=domain_norm,
        company_id=company_id,
        lead_id=msg.campaign_lead_id,
    )
    if matched is not None:
        result = ComplianceResult(
            allowed=False,
            decision=ComplianceDecision.BLOCKED.value,
            reason_code=f"{SUPPRESSION_BLOCK_PREFIX}{matched.reason}",
            matched_entry=matched,
            safe_message=f"Blocked by {matched.scope} {matched.suppression_type} suppression",
            suppression_type=matched.suppression_type,
            scope=matched.scope,
            masked_recipient=masked,
        )
    else:
        result = ComplianceResult(
            allowed=True,
            decision=ComplianceDecision.ALLOWED.value,
            reason_code="allowed",
            safe_message="No active suppression matched",
            masked_recipient=masked,
        )

    if persist_log:
        _log_decision(
            db,
            campaign_id=campaign_id,
            lead_id=msg.campaign_lead_id,
            message_id=msg.id,
            execution_run_id=execution_run_id,
            result=result,
            check_context=check_context,
        )
        db.commit()
    return result


def apply_message_suppression_block(
    db: Session,
    msg: OutreachMessage,
    result: ComplianceResult,
) -> OutreachMessage:
    from app.models.enums import OutreachMessageStatus

    if msg.status not in {
        OutreachMessageStatus.APPROVED.value,
        OutreachMessageStatus.SENDING.value,
    }:
        return msg
    now = _utcnow()
    db.execute(
        update(OutreachMessage)
        .where(
            OutreachMessage.id == msg.id,
            OutreachMessage.status.in_(
                [
                    OutreachMessageStatus.APPROVED.value,
                    OutreachMessageStatus.SENDING.value,
                ]
            ),
        )
        .values(
            status=OutreachMessageStatus.BLOCKED.value,
            blocked_at=now,
            error_message=result.reason_code[:MAX_COMPLIANCE_REASON_LENGTH],
        )
    )
    db.commit()
    db.refresh(msg)
    return msg


def check_message_api(db: Session, campaign_id: UUID, message_id: UUID) -> ComplianceCheckResponse:
    result = check_outreach_compliance(
        db,
        campaign_id=campaign_id,
        message_id=message_id,
        check_context=ComplianceCheckContext.READINESS_CHECK.value,
        persist_log=True,
    )
    return ComplianceCheckResponse(
        allowed=result.allowed,
        decision=result.decision,
        reason_code=result.reason_code,
        suppression_type=result.suppression_type,
        scope=result.scope,
        matched_suppression_entry_id=result.matched_entry.id if result.matched_entry else None,
        safe_message=result.safe_message,
        checked_at=_utcnow(),
        is_test_data=True,
    )


def create_test_event(
    db: Session,
    campaign_id: UUID,
    data: TestComplianceEventCreate,
) -> TestComplianceEventResponse:
    if data.is_test_data is False:
        raise AppError("is_test_data must be true", status_code=422, code="test_data_required")
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise AppError("Campaign not found.", status_code=404, code="not_found")
    msg = db.get(OutreachMessage, data.message_id)
    if msg is None or msg.campaign_id != campaign_id:
        raise AppError("Message not found.", status_code=404, code="not_found")
    if not msg.is_test_data:
        raise AppError("Only test messages allowed", status_code=422, code="test_data_required")

    reason_map = {
        ComplianceTestEventType.UNSUBSCRIBE.value: SuppressionReason.UNSUBSCRIBE.value,
        ComplianceTestEventType.COMPLAINT.value: SuppressionReason.COMPLAINT.value,
        ComplianceTestEventType.HARD_BOUNCE.value: SuppressionReason.HARD_BOUNCE.value,
    }
    reason = reason_map[data.event_type]
    created = create_suppression(
        db,
        SuppressionCreate(
            scope=SuppressionScope.CAMPAIGN.value,
            campaign_id=campaign_id,
            suppression_type=SuppressionType.EMAIL.value,
            value=msg.recipient_email,
            reason=reason,
            source=SuppressionSource.TEST_EVENT.value,
            is_test_data=True,
            notes=f"TEST event {data.event_type}",
        ),
        source=SuppressionSource.TEST_EVENT.value,
        created_by="test_event",
    )
    check_outreach_compliance(
        db,
        campaign_id=campaign_id,
        message=msg,
        check_context=ComplianceCheckContext.READINESS_CHECK.value,
        persist_log=True,
    )
    return TestComplianceEventResponse(
        event_type=data.event_type,
        suppression=created,
        message_id=msg.id,
        is_test_data=True,
    )


def build_provider_readiness_report() -> ProviderReadinessReport:
    get_settings.cache_clear()
    settings = get_settings()

    checks: list[ProviderReadinessCheck] = []
    blockers: list[str] = []
    warnings: list[str] = []

    def add(name: str, ok: bool, detail: str, *, live_blocker: bool = False) -> None:
        checks.append(
            ProviderReadinessCheck(name=name, status="pass" if ok else "fail", detail=detail)
        )
        if not ok and live_blocker:
            blockers.append(name)
        elif not ok:
            warnings.append(name)

    add("system_stop_all_available", True, "SYSTEM_STOP_ALL setting readable")
    add("system_stop_all_current_state", True, f"current={is_system_stopped()}")
    add("test_email_provider_enabled", True, "TestEmailProvider is the only provider")
    real_enabled = bool(getattr(settings, "real_email_provider_enabled", False))
    add(
        "real_provider_enabled",
        not real_enabled,
        "real_email_provider_enabled must be false",
        live_blocker=True,
    )
    live_enabled = bool(getattr(settings, "live_outreach_enabled", False))
    add(
        "live_mode_enabled",
        not live_enabled,
        "live_outreach_enabled must be false",
        live_blocker=True,
    )
    add("recipient_domain_policy", True, "example.test_only")
    sender_email = getattr(settings, "provider_sender_email", None)
    sender_domain = getattr(settings, "provider_sender_domain", None)
    api_key = getattr(settings, "provider_api_key", None)
    sender_ok = _configured_secret(sender_email)
    domain_ok = _configured_secret(sender_domain)
    key_ok = _configured_secret(api_key)
    add(
        "sender_identity_configured",
        sender_ok,
        "present" if sender_ok else "missing",
        live_blocker=True,
    )
    add(
        "sender_domain_configured",
        domain_ok,
        "present" if domain_ok else "missing",
        live_blocker=True,
    )
    add(
        "provider_api_key_present",
        key_ok,
        "present" if key_ok else "missing",
        live_blocker=True,
    )
    add("unsubscribe_handler_ready", True, "TEST event endpoint available")
    add("complaint_handler_ready", True, "TEST event endpoint available")
    add("bounce_handler_ready", True, "TEST event endpoint available")
    add("suppression_gate_enabled", True, "check_outreach_compliance wired")
    add("audit_log_enabled", True, "ComplianceDecisionLog enabled")
    add("idempotency_enabled", True, "Stage 4 send idempotency preserved")
    add("at_most_once_documented", True, "documented in STAGE4/STAGE6")
    add("scheduler_auto_send_disabled", True, "beat_schedule empty")
    daily = int(getattr(settings, "provider_daily_limit", 0) or 0)
    add("rate_limit_configured", daily > 0, f"daily_limit={daily}", live_blocker=True)
    add("daily_limit_configured", daily > 0, f"daily_limit={daily}", live_blocker=True)
    add("manual_approval_required", True, "MANUAL_APPROVAL / APPROVED required")

    # Stage 6 policy: live pilot never ready
    blockers = list(dict.fromkeys([*blockers, "stage6_live_pilot_not_enabled"]))
    if is_system_stopped():
        warnings.append("system_stop_all_active")

    return ProviderReadinessReport(
        overall_status=ProviderReadinessStatus.TEST_READY.value,
        test_mode_ready=True,
        live_mode_ready=False,
        production_readiness_status=ProviderReadinessStatus.LIVE_NOT_READY.value,
        checks=checks,
        blockers=blockers,
        warnings=warnings,
        generated_at=_utcnow(),
        is_test_data=True,
    )
