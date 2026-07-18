"""Stage 7A live pilot CRUD, approval, dry-run, audit."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.models.campaign import Campaign
from app.models.enums import (
    APPROVAL_CHALLENGE_TTL_SECONDS,
    ComplianceCheckContext,
    DEFAULT_PILOT_DAILY_LIMIT,
    DEFAULT_PILOT_RATE_LIMIT,
    LIVE_PILOT_CONFIRMATION_PHRASE_PREFIX,
    LIVE_PILOT_TERMINAL_STATUSES,
    LivePilotEventType,
    LivePilotRecipientStatus,
    LivePilotStatus,
    LivePilotValidationStatus,
    MAX_LIVE_PILOT_LIST_LIMIT,
    MAX_PILOT_BODY_SNAPSHOT,
    MAX_PILOT_EVENT_DETAIL,
    MAX_PILOT_SUBJECT_SNAPSHOT,
    OutreachMessageStatus,
    SERVER_MAX_PILOT_RECIPIENTS,
)
from app.models.live_pilot import LivePilot, LivePilotApproval, LivePilotEvent, LivePilotRecipient
from app.models.outreach_message import OutreachMessage
from app.providers.base import EmailMessage
from app.providers.email_test import TestEmailProvider, clear_test_email_idempotency_cache
from app.providers.registry import get_dry_run_provider
from app.schemas.live_pilot import (
    LivePilotApprovalResponse,
    LivePilotCreate,
    LivePilotDryRunResponse,
    LivePilotListResponse,
    LivePilotRead,
    LivePilotReadinessResponse,
    LivePilotRecipientCreate,
    LivePilotRecipientListResponse,
    LivePilotRecipientRead,
    LivePilotValidationResponse,
    LivePilotValidationCheck,
)
from app.security.stop_all import SystemStopAllError, assert_outbound_allowed, is_system_stopped
from app.services.compliance_service import check_outreach_compliance
from app.services.live_pilot_validation_service import (
    load_pilot_for_validation,
    validate_live_pilot,
)
from app.services.pilot_allowlist_service import (
    ensure_allowlist_entry,
    normalize_pilot_recipient,
    validate_recipient_on_allowlist,
)

logger = logging.getLogger(__name__)

_FORBIDDEN_PAYLOAD_KEYS = frozenset(
    {
        "provider_api_key",
        "live_provider_api_key",
        "api_key",
        "password",
        "smtp_password",
        "credentials",
        "authorization",
    }
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _clamp_max_recipients(value: int | None) -> int:
    settings = get_settings()
    server_max = min(SERVER_MAX_PILOT_RECIPIENTS, max(1, settings.live_pilot_max_recipients))
    if value is None:
        return min(1, server_max)
    return max(1, min(value, server_max))


def _reject_forbidden_fields(data: dict) -> None:
    for key in data:
        if key.lower() in _FORBIDDEN_PAYLOAD_KEYS:
            raise AppError(
                "Credentials cannot be submitted via API",
                status_code=422,
                code="credentials_forbidden",
            )


def _to_read(pilot: LivePilot) -> LivePilotRead:
    return LivePilotRead.model_validate(pilot)


def _to_recipient_read(rec: LivePilotRecipient) -> LivePilotRecipientRead:
    return LivePilotRecipientRead.model_validate(rec)


def _log_event(
    db: Session,
    *,
    pilot_id: UUID,
    event_type: str,
    idempotency_key: str,
    safe_detail: str | None = None,
    masked_recipient: str | None = None,
    correlation_id: str | None = None,
) -> None:
    existing = db.scalars(
        select(LivePilotEvent).where(LivePilotEvent.idempotency_key == idempotency_key)
    ).first()
    if existing is not None:
        return
    event = LivePilotEvent(
        pilot_id=pilot_id,
        event_type=event_type,
        safe_detail=(safe_detail or "")[:MAX_PILOT_EVENT_DETAIL] or None,
        masked_recipient=masked_recipient,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
    )
    nested = db.begin_nested()
    try:
        db.add(event)
        db.flush()
        nested.commit()
    except IntegrityError:
        nested.rollback()


def create_live_pilot(db: Session, data: LivePilotCreate) -> LivePilotRead:
    raw = data.model_dump()
    _reject_forbidden_fields(raw)
    if data.is_test_data is False:
        raise AppError("is_test_data must be true", status_code=422, code="test_data_required")
    if data.live_delivery_enabled:
        raise AppError(
            "live_delivery_enabled cannot be enabled on Stage 7A",
            status_code=422,
            code="live_delivery_forbidden",
        )
    if data.provider_name and data.provider_name not in {"disabled_live"}:
        raise AppError("Unknown provider", status_code=422, code="unknown_provider")

    campaign = db.get(Campaign, data.campaign_id)
    if campaign is None:
        raise AppError("Campaign not found.", status_code=404, code="not_found")

    msg = db.get(OutreachMessage, data.message_id)
    if msg is None or msg.campaign_id != data.campaign_id:
        raise AppError("Message not found.", status_code=404, code="not_found")
    if msg.status != OutreachMessageStatus.APPROVED.value:
        raise AppError("Message must be APPROVED", status_code=409, code="invalid_state")
    if not msg.is_test_data:
        raise AppError("Only test messages allowed", status_code=422, code="test_data_required")

    idem = data.idempotency_key.strip()
    existing = db.scalars(
        select(LivePilot).where(LivePilot.idempotency_key == idem)
    ).first()
    if existing is not None:
        return _to_read(existing)

    max_recipients = _clamp_max_recipients(data.max_recipients)
    if data.max_recipients is not None and data.max_recipients > SERVER_MAX_PILOT_RECIPIENTS:
        raise AppError(
            f"max_recipients cannot exceed {SERVER_MAX_PILOT_RECIPIENTS}",
            status_code=422,
            code="limit_exceeded",
        )

    pilot = LivePilot(
        campaign_id=data.campaign_id,
        status=LivePilotStatus.DRAFT.value,
        provider_name=data.provider_name or "disabled_live",
        subject_snapshot=(msg.subject_rendered or "")[:MAX_PILOT_SUBJECT_SNAPSHOT],
        body_snapshot=(msg.body_rendered or "")[:MAX_PILOT_BODY_SNAPSHOT],
        max_recipients=max_recipients,
        daily_limit=DEFAULT_PILOT_DAILY_LIMIT,
        per_minute_limit=DEFAULT_PILOT_RATE_LIMIT,
        live_delivery_enabled=False,
        idempotency_key=idem,
        primary_message_id=msg.id,
        is_test_data=True,
        created_by="manual",
    )
    nested = db.begin_nested()
    try:
        db.add(pilot)
        db.flush()
        nested.commit()
    except IntegrityError:
        nested.rollback()
        again = db.scalars(select(LivePilot).where(LivePilot.idempotency_key == idem)).first()
        if again is not None:
            return _to_read(again)
        active = db.scalars(
            select(LivePilot).where(
                LivePilot.campaign_id == data.campaign_id,
                LivePilot.status.notin_(list(LIVE_PILOT_TERMINAL_STATUSES)),
            )
        ).first()
        if active is not None:
            raise AppError(
                "Active pilot already exists for campaign",
                status_code=409,
                code="active_pilot_exists",
            ) from None
        raise AppError("Pilot conflict", status_code=409, code="pilot_conflict") from None

    _log_event(
        db,
        pilot_id=pilot.id,
        event_type=LivePilotEventType.CREATED.value,
        idempotency_key=f"event:created:{pilot.id}",
        safe_detail=f"status={pilot.status}",
    )
    db.commit()
    db.refresh(pilot)
    return _to_read(pilot)


def list_live_pilots(
    db: Session,
    *,
    campaign_id: UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> LivePilotListResponse:
    if limit < 1 or limit > MAX_LIVE_PILOT_LIST_LIMIT:
        raise AppError("Invalid limit", status_code=422, code="invalid_limit")
    if offset < 0:
        raise AppError("Invalid offset", status_code=422, code="invalid_offset")
    q = select(LivePilot)
    if campaign_id is not None:
        q = q.where(LivePilot.campaign_id == campaign_id)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(
        q.order_by(LivePilot.created_at.desc(), LivePilot.id.asc()).limit(limit).offset(offset)
    ).all()
    return LivePilotListResponse(
        items=[_to_read(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def get_live_pilot(db: Session, pilot_id: UUID) -> LivePilotRead:
    pilot = db.get(LivePilot, pilot_id)
    if pilot is None:
        raise AppError("Live pilot not found.", status_code=404, code="not_found")
    return _to_read(pilot)


def _get_pilot_or_404(db: Session, pilot_id: UUID) -> LivePilot:
    pilot = db.scalars(
        select(LivePilot)
        .where(LivePilot.id == pilot_id)
        .options(selectinload(LivePilot.recipients))
    ).first()
    if pilot is None:
        raise AppError("Live pilot not found.", status_code=404, code="not_found")
    return pilot


def add_recipient(
    db: Session,
    pilot_id: UUID,
    data: LivePilotRecipientCreate,
) -> LivePilotRecipientRead:
    raw = data.model_dump()
    _reject_forbidden_fields(raw)
    pilot = _get_pilot_or_404(db, pilot_id)
    if pilot.status in LIVE_PILOT_TERMINAL_STATUSES:
        raise AppError("Pilot is terminal", status_code=409, code="invalid_state")

    msg = db.get(OutreachMessage, data.outreach_message_id)
    if msg is None or msg.campaign_id != pilot.campaign_id:
        raise AppError("Message not found.", status_code=404, code="not_found")
    if msg.status != OutreachMessageStatus.APPROVED.value:
        raise AppError("Message must be APPROVED", status_code=409, code="invalid_state")

    normalized, masked, fingerprint = validate_recipient_on_allowlist(
        db,
        campaign_id=pilot.campaign_id,
        email=data.recipient_email or msg.recipient_email,
    )
    msg_norm, _, _ = normalize_pilot_recipient(msg.recipient_email)
    if normalized != msg_norm:
        raise AppError(
            "Recipient must match message test address",
            status_code=409,
            code="cross_campaign_blocked",
        )

    idem = data.idempotency_key.strip()
    existing = db.scalars(
        select(LivePilotRecipient).where(LivePilotRecipient.idempotency_key == idem)
    ).first()
    if existing is not None:
        return _to_recipient_read(existing)

    current_count = len(pilot.recipients or [])
    if current_count >= pilot.max_recipients:
        raise AppError(
            f"Max recipients ({pilot.max_recipients}) reached",
            status_code=422,
            code="limit_exceeded",
        )

    position = current_count + 1
    rec = LivePilotRecipient(
        pilot_id=pilot.id,
        outreach_message_id=msg.id,
        recipient_masked=masked,
        recipient_fingerprint=fingerprint,
        position=position,
        idempotency_key=idem,
        status=LivePilotRecipientStatus.PENDING.value,
    )
    nested = db.begin_nested()
    try:
        db.add(rec)
        db.flush()
        nested.commit()
    except IntegrityError:
        nested.rollback()
        again = db.scalars(
            select(LivePilotRecipient).where(LivePilotRecipient.idempotency_key == idem)
        ).first()
        if again is not None:
            return _to_recipient_read(again)
        dup = db.scalars(
            select(LivePilotRecipient).where(
                LivePilotRecipient.pilot_id == pilot.id,
                LivePilotRecipient.outreach_message_id == msg.id,
            )
        ).first()
        if dup is not None:
            return _to_recipient_read(dup)
        raise AppError("Recipient conflict", status_code=409, code="recipient_conflict") from None

    ensure_allowlist_entry(db, campaign_id=pilot.campaign_id, email=normalized)
    _log_event(
        db,
        pilot_id=pilot.id,
        event_type=LivePilotEventType.RECIPIENT_ADDED.value,
        idempotency_key=f"event:recipient:{rec.id}",
        masked_recipient=masked,
        safe_detail=f"position={position}",
    )
    db.commit()
    db.refresh(rec)
    return _to_recipient_read(rec)


def list_recipients(db: Session, pilot_id: UUID) -> LivePilotRecipientListResponse:
    pilot = _get_pilot_or_404(db, pilot_id)
    rows = sorted(pilot.recipients or [], key=lambda r: (r.position, str(r.id)))
    return LivePilotRecipientListResponse(
        items=[_to_recipient_read(r) for r in rows],
        total=len(rows),
    )


def validate_pilot(db: Session, pilot_id: UUID) -> LivePilotValidationResponse:
    pilot = load_pilot_for_validation(db, pilot_id)
    pilot.status = LivePilotStatus.VALIDATING.value
    result = validate_live_pilot(db, pilot)
    if result.test_ready and not is_system_stopped():
        pilot.status = LivePilotStatus.READY_FOR_APPROVAL.value
    elif not result.test_ready:
        pilot.status = LivePilotStatus.BLOCKED.value if is_system_stopped() else LivePilotStatus.DRAFT.value
    _log_event(
        db,
        pilot_id=pilot.id,
        event_type=LivePilotEventType.VALIDATION.value,
        idempotency_key=f"event:validate:{pilot.id}:{result.generated_at.isoformat()}",
        safe_detail=result.overall_status,
    )
    db.commit()
    db.refresh(pilot)
    return _validation_response(result)


def get_readiness(db: Session, pilot_id: UUID) -> LivePilotReadinessResponse:
    pilot = load_pilot_for_validation(db, pilot_id)
    result = validate_live_pilot(db, pilot)
    _log_event(
        db,
        pilot_id=pilot.id,
        event_type=LivePilotEventType.READINESS_CHECK.value,
        idempotency_key=f"event:readiness:{pilot.id}:{int(result.generated_at.timestamp())}",
        safe_detail=result.overall_status,
    )
    db.commit()
    resp = _validation_response(result)
    return LivePilotReadinessResponse(
        **resp.model_dump(),
        live_mode_ready=False,
        production_status=LivePilotValidationStatus.LIVE_NOT_READY.value,
    )


def _validation_response(result) -> LivePilotValidationResponse:
    return LivePilotValidationResponse(
        ready=result.ready,
        overall_status=result.overall_status,
        blockers=result.blockers,
        warnings=result.warnings,
        checks=[
            LivePilotValidationCheck(name=c.name, passed=c.passed, detail=c.detail)
            for c in result.checks
        ],
        generated_at=result.generated_at,
        test_ready=result.test_ready,
        live_ready=result.live_ready,
        is_test_data=True,
    )


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _verify_token(raw: str, expected_hash: str) -> bool:
    actual = _hash_token(raw.strip())
    return hmac.compare_digest(actual, expected_hash)


def _dry_run_replay_event(db: Session, idempotency_key: str) -> LivePilotEvent | None:
    event = db.scalars(
        select(LivePilotEvent).where(LivePilotEvent.idempotency_key == f"dry-run:{idempotency_key}")
    ).first()
    if event is not None and (event.safe_detail or "").startswith("processed="):
        return event
    return None


def _claim_dry_run_idempotency(
    db: Session,
    *,
    pilot_id: UUID,
    idempotency_key: str,
    correlation_id: str,
) -> bool:
    """Return True if this call claimed the dry-run key; False if already claimed."""
    key = f"dry-run:{idempotency_key}"
    existing = db.scalars(select(LivePilotEvent).where(LivePilotEvent.idempotency_key == key)).first()
    if existing is not None:
        return False
    event = LivePilotEvent(
        pilot_id=pilot_id,
        event_type=LivePilotEventType.DRY_RUN_RESULT.value,
        safe_detail="in_progress",
        correlation_id=correlation_id,
        idempotency_key=key,
    )
    nested = db.begin_nested()
    try:
        db.add(event)
        db.flush()
        nested.commit()
        return True
    except IntegrityError:
        nested.rollback()
        return False


def approve_pilot(
    db: Session,
    pilot_id: UUID,
    *,
    confirmation_token: str | None = None,
) -> LivePilotApprovalResponse:
    pilot = _get_pilot_or_404(db, pilot_id)
    if pilot.status in {LivePilotStatus.CANCELLED.value, LivePilotStatus.COMPLETED.value}:
        raise AppError("Pilot is terminal", status_code=409, code="invalid_state")

    if is_system_stopped():
        raise AppError(
            "SYSTEM_STOP_ALL blocks approval that enables send path",
            status_code=409,
            code="system_stopped",
        )

    if not confirmation_token:
        pending_existing = db.scalars(
            select(LivePilotApproval)
            .where(
                LivePilotApproval.pilot_id == pilot.id,
                LivePilotApproval.consumed_at.is_(None),
                LivePilotApproval.success.is_(False),
            )
            .order_by(LivePilotApproval.created_at.desc())
        ).first()
        if pending_existing is not None:
            exp = pending_existing.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if _utcnow() <= exp:
                raise AppError(
                    "Approval challenge already pending",
                    status_code=409,
                    code="challenge_pending",
                )

        phrase = f"{LIVE_PILOT_CONFIRMATION_PHRASE_PREFIX}-{secrets.token_hex(4).upper()}"
        raw_token = secrets.token_urlsafe(32)
        approval = LivePilotApproval(
            pilot_id=pilot.id,
            challenge_hash=_hash_token(raw_token),
            confirmation_phrase=phrase,
            expires_at=_utcnow() + timedelta(seconds=APPROVAL_CHALLENGE_TTL_SECONDS),
            approved_by="manual",
            success=False,
        )
        db.add(approval)
        db.flush()
        _log_event(
            db,
            pilot_id=pilot.id,
            event_type=LivePilotEventType.APPROVAL_CHALLENGE.value,
            idempotency_key=f"event:challenge:{approval.id}",
            safe_detail=phrase,
        )
        db.commit()
        return LivePilotApprovalResponse(
            pilot_id=pilot.id,
            status=pilot.status,
            confirmation_phrase=phrase,
            confirmation_token=raw_token,
            expires_at=approval.expires_at,
            approved=False,
            message="Enter the confirmation phrase exactly to approve (does not send email)",
            is_test_data=True,
        )

    pending = db.scalars(
        select(LivePilotApproval)
        .where(
            LivePilotApproval.pilot_id == pilot.id,
            LivePilotApproval.consumed_at.is_(None),
            LivePilotApproval.success.is_(False),
        )
        .order_by(LivePilotApproval.created_at.desc())
    ).first()
    if pending is None:
        raise AppError("No pending approval challenge", status_code=409, code="no_challenge")

    now = _utcnow()
    exp = pending.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if now > exp:
        _log_event(
            db,
            pilot_id=pilot.id,
            event_type=LivePilotEventType.APPROVAL_FAILURE.value,
            idempotency_key=f"event:approval_fail:expired:{pending.id}",
            safe_detail="challenge_expired",
        )
        db.commit()
        raise AppError("Approval challenge expired", status_code=409, code="challenge_expired")

    if not _verify_token(confirmation_token, pending.challenge_hash):
        _log_event(
            db,
            pilot_id=pilot.id,
            event_type=LivePilotEventType.APPROVAL_FAILURE.value,
            idempotency_key=f"event:approval_fail:wrong:{pending.id}",
            safe_detail="wrong_token",
        )
        db.commit()
        raise AppError("Wrong confirmation token", status_code=422, code="wrong_token")

    pending.consumed_at = now
    pending.success = True
    pilot.approved_at = now
    pilot.status = LivePilotStatus.APPROVED.value
    _log_event(
        db,
        pilot_id=pilot.id,
        event_type=LivePilotEventType.APPROVAL_SUCCESS.value,
        idempotency_key=f"event:approval_ok:{pending.id}",
        safe_detail="approved_no_live_send",
    )
    db.commit()
    db.refresh(pilot)
    return LivePilotApprovalResponse(
        pilot_id=pilot.id,
        status=pilot.status,
        confirmation_phrase=pending.confirmation_phrase,
        confirmation_token=None,
        expires_at=pending.expires_at,
        approved=True,
        message="Pilot approved — live send remains disabled on Stage 7A",
        is_test_data=True,
    )


def cancel_pilot(db: Session, pilot_id: UUID) -> LivePilotRead:
    pilot = _get_pilot_or_404(db, pilot_id)
    if pilot.status in LIVE_PILOT_TERMINAL_STATUSES:
        return _to_read(pilot)
    now = _utcnow()
    pilot.status = LivePilotStatus.CANCELLED.value
    pilot.cancelled_at = now
    for rec in pilot.recipients or []:
        if rec.status not in {
            LivePilotRecipientStatus.DRY_RUN_SENT.value,
            LivePilotRecipientStatus.CANCELLED.value,
        }:
            rec.status = LivePilotRecipientStatus.CANCELLED.value
    _log_event(
        db,
        pilot_id=pilot.id,
        event_type=LivePilotEventType.CANCEL.value,
        idempotency_key=f"event:cancel:{pilot.id}",
        safe_detail="cancelled",
    )
    db.commit()
    db.refresh(pilot)
    return _to_read(pilot)


def dry_run_pilot(
    db: Session,
    pilot_id: UUID,
    *,
    idempotency_key: str,
) -> LivePilotDryRunResponse:
    pilot = _get_pilot_or_404(db, pilot_id)
    if pilot.status == LivePilotStatus.CANCELLED.value:
        raise AppError("Pilot cancelled", status_code=409, code="invalid_state")

    correlation = idempotency_key[:32]
    completed = _dry_run_replay_event(db, idempotency_key)
    if completed is not None:
        db.refresh(pilot)
        return LivePilotDryRunResponse(
            pilot_id=pilot.id,
            status=pilot.status,
            dry_run=True,
            simulated=True,
            provider="test_email",
            recipients_processed=pilot.dry_run_sent_count,
            live_sent_count=pilot.live_sent_count,
            message="Idempotent dry-run replay",
            is_test_data=True,
        )

    try:
        assert_outbound_allowed("pilot dry-run")
    except SystemStopAllError as exc:
        raise AppError(str(exc), status_code=409, code="system_stopped") from exc

    validation = validate_live_pilot(db, pilot)
    if not validation.test_ready:
        raise AppError(
            "Pilot not ready for dry-run",
            status_code=409,
            code="not_ready",
        )

    provider = get_dry_run_provider()
    if provider.name != "test_email":
        raise AppError("Dry-run requires TestEmailProvider", status_code=409, code="invalid_provider")

    if not _claim_dry_run_idempotency(
        db,
        pilot_id=pilot.id,
        idempotency_key=idempotency_key,
        correlation_id=correlation,
    ):
        db.refresh(pilot)
        done = _dry_run_replay_event(db, idempotency_key)
        if done is not None:
            return LivePilotDryRunResponse(
                pilot_id=pilot.id,
                status=pilot.status,
                dry_run=True,
                simulated=True,
                provider="test_email",
                recipients_processed=pilot.dry_run_sent_count,
                live_sent_count=pilot.live_sent_count,
                message="Idempotent dry-run replay",
                is_test_data=True,
            )
        raise AppError(
            "Dry-run already in progress",
            status_code=409,
            code="dry_run_in_progress",
        )

    processed = 0
    _log_event(
        db,
        pilot_id=pilot.id,
        event_type=LivePilotEventType.DRY_RUN_START.value,
        idempotency_key=f"dry-run:start:{idempotency_key}",
        correlation_id=correlation,
        safe_detail="test_email_only",
    )

    for rec in sorted(pilot.recipients or [], key=lambda r: r.position):
        if rec.status == LivePilotRecipientStatus.DRY_RUN_SENT.value:
            processed += 1
            continue
        msg = db.get(OutreachMessage, rec.outreach_message_id)
        if msg is None:
            rec.status = LivePilotRecipientStatus.DRY_RUN_FAILED.value
            rec.error_code = "message_missing"
            continue
        compliance = check_outreach_compliance(
            db,
            campaign_id=pilot.campaign_id,
            message=msg,
            check_context=ComplianceCheckContext.EXPLICIT_SEND.value,
            persist_log=True,
        )
        _log_event(
            db,
            pilot_id=pilot.id,
            event_type=LivePilotEventType.COMPLIANCE_RESULT.value,
            idempotency_key=f"dry-run:compliance:{rec.id}:{idempotency_key}",
            masked_recipient=rec.recipient_masked,
            safe_detail=compliance.decision,
            correlation_id=correlation,
        )
        if not compliance.allowed:
            rec.status = LivePilotRecipientStatus.BLOCKED.value
            rec.error_code = compliance.reason_code
            rec.compliance_checked_at = _utcnow()
            continue

        send_key = f"pilot:dry-run:{pilot.id}:{rec.id}:{idempotency_key}"
        email_msg = EmailMessage(
            to_address=msg.recipient_email,
            subject=pilot.subject_snapshot,
            body="[dry-run body omitted from provider payload audit]",
            metadata={"idempotency_key": send_key, "pilot_dry_run": True},
        )
        try:
            assert_outbound_allowed("pilot dry-run provider call")
            result = provider.send(email_msg)
        except SystemStopAllError as exc:
            raise AppError(str(exc), status_code=409, code="system_stopped") from exc

        if result.success and result.simulated:
            rec.status = LivePilotRecipientStatus.DRY_RUN_SENT.value
            rec.sent_at = result.sent_at
            rec.provider_message_id = result.message_id
            rec.compliance_checked_at = _utcnow()
            processed += 1
        else:
            rec.status = LivePilotRecipientStatus.DRY_RUN_FAILED.value
            rec.error_code = result.detail or "send_failed"

    pilot.dry_run_sent_count = processed
    pilot.started_at = pilot.started_at or _utcnow()
    if processed == len(pilot.recipients or []) and processed > 0:
        pilot.status = LivePilotStatus.COMPLETED.value
        pilot.completed_at = _utcnow()

    db.execute(
        update(LivePilotEvent)
        .where(LivePilotEvent.idempotency_key == f"dry-run:{idempotency_key}")
        .values(safe_detail=f"processed={processed} live_count={pilot.live_sent_count}")
    )
    _log_event(
        db,
        pilot_id=pilot.id,
        event_type=LivePilotEventType.DRY_RUN_RESULT.value,
        idempotency_key=f"dry-run:audit:{idempotency_key}",
        correlation_id=correlation,
        safe_detail=f"processed={processed} live_count={pilot.live_sent_count}",
    )
    db.commit()
    db.refresh(pilot)
    return LivePilotDryRunResponse(
        pilot_id=pilot.id,
        status=pilot.status,
        dry_run=True,
        simulated=True,
        provider=provider.name,
        recipients_processed=processed,
        live_sent_count=pilot.live_sent_count,
        message="TEST DRY-RUN complete — not live delivery",
        is_test_data=True,
    )


def clear_dry_run_caches_for_tests() -> None:
    clear_test_email_idempotency_cache()
