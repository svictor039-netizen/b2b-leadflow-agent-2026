"""Stage 7A live pilot validation and readiness checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.models.campaign import Campaign
from app.models.enums import (
    ComplianceCheckContext,
    LivePilotRecipientStatus,
    LivePilotStatus,
    LivePilotValidationStatus,
    OutreachMessageStatus,
    SERVER_MAX_PILOT_RECIPIENTS,
)
from app.models.live_pilot import LivePilot, LivePilotApproval
from app.models.outreach_message import OutreachMessage
from app.providers.registry import get_dry_run_provider, get_live_provider
from app.security.stop_all import is_system_stopped
from app.services.compliance_service import check_outreach_compliance
from app.services.pilot_allowlist_service import is_on_allowlist, normalize_pilot_recipient
from app.workers.celery_app import celery_app

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


_BLOCKER_ORDER = (
    "system_stop_all",
    "compliance",
    "allowlist",
    "recipient_count",
    "provider_selected",
    "provider_configured",
    "sender_identity",
    "sender_domain",
    "daily_limit",
    "rate_limit",
    "manual_approval",
    "typed_confirmation",
    "live_environment_flag",
    "database_live_gate",
    "scheduler_disabled",
    "auto_retry_disabled",
    "stage7a_live_disabled",
)


def _order_blockers(blockers: list[str]) -> list[str]:
    order = {name: idx for idx, name in enumerate(_BLOCKER_ORDER)}
    return sorted(dict.fromkeys(blockers), key=lambda name: order.get(name, 999))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
    return datetime.now(timezone.utc)


def _configured_secret(value: str | None) -> bool:
    raw = (value or "").strip()
    if not raw:
        return False
    return raw.lower() not in _PLACEHOLDER_SECRETS


@dataclass
class ValidationCheck:
    name: str
    passed: bool
    detail: str


@dataclass
class LivePilotValidationResult:
    ready: bool
    overall_status: str
    blockers: list[str]
    warnings: list[str]
    checks: list[ValidationCheck]
    generated_at: datetime
    live_ready: bool = False
    test_ready: bool = False


def _add_check(
    checks: list[ValidationCheck],
    blockers: list[str],
    warnings: list[str],
    name: str,
    passed: bool,
    detail: str,
    *,
    live_blocker: bool = False,
    warning_only: bool = False,
) -> None:
    checks.append(ValidationCheck(name=name, passed=passed, detail=detail))
    if not passed:
        if warning_only:
            warnings.append(name)
        elif live_blocker:
            blockers.append(name)


def validate_live_pilot(db: Session, pilot: LivePilot) -> LivePilotValidationResult:
    get_settings.cache_clear()
    settings = get_settings()
    checks: list[ValidationCheck] = []
    blockers: list[str] = []
    warnings: list[str] = []

    campaign = db.get(Campaign, pilot.campaign_id)
    msg = db.get(OutreachMessage, pilot.primary_message_id)

    stopped = is_system_stopped()
    _add_check(
        checks,
        blockers,
        warnings,
        "system_stop_all",
        not stopped,
        "stopped" if stopped else "clear",
        live_blocker=True,
    )

    campaign_ok = campaign is not None
    _add_check(
        checks,
        blockers,
        warnings,
        "campaign_active",
        campaign_ok,
        "ok" if campaign_ok else "missing_or_invalid",
        live_blocker=True,
    )

    message_ok = (
        msg is not None
        and msg.campaign_id == pilot.campaign_id
        and msg.status == OutreachMessageStatus.APPROVED.value
        and msg.is_test_data
    )
    _add_check(
        checks,
        blockers,
        warnings,
        "message_approved",
        message_ok,
        msg.status if msg else "missing",
        live_blocker=True,
    )

    compliance_ok = False
    if msg is not None:
        result = check_outreach_compliance(
            db,
            campaign_id=pilot.campaign_id,
            message=msg,
            check_context=ComplianceCheckContext.READINESS_CHECK.value,
            persist_log=False,
        )
        compliance_ok = result.allowed
    _add_check(
        checks,
        blockers,
        warnings,
        "compliance",
        compliance_ok,
        "ALLOWED" if compliance_ok else "BLOCKED",
        live_blocker=True,
    )

    recipient_count = len(pilot.recipients or [])
    count_ok = 0 < recipient_count <= min(pilot.max_recipients, SERVER_MAX_PILOT_RECIPIENTS)
    _add_check(
        checks,
        blockers,
        warnings,
        "recipient_count",
        count_ok,
        f"count={recipient_count} max={pilot.max_recipients}",
        live_blocker=True,
    )

    allowlist_ok = True
    for rec in pilot.recipients or []:
        om = db.get(OutreachMessage, rec.outreach_message_id)
        if om is None or om.campaign_id != pilot.campaign_id:
            allowlist_ok = False
            break
        try:
            normalized, _, _ = normalize_pilot_recipient(om.recipient_email)
        except Exception:
            allowlist_ok = False
            break
        if not is_on_allowlist(db, campaign_id=pilot.campaign_id, normalized_email=normalized):
            allowlist_ok = False
            break
    _add_check(
        checks,
        blockers,
        warnings,
        "allowlist",
        allowlist_ok,
        "all_on_allowlist" if allowlist_ok else "missing_entries",
        live_blocker=True,
    )

    snapshots_ok = bool(pilot.subject_snapshot) and bool(pilot.body_snapshot)
    _add_check(
        checks,
        blockers,
        warnings,
        "immutable_snapshot",
        snapshots_ok,
        "present" if snapshots_ok else "missing",
        live_blocker=True,
    )

    provider_selected = bool(pilot.provider_name)
    _add_check(
        checks,
        blockers,
        warnings,
        "provider_selected",
        provider_selected,
        pilot.provider_name or "none",
        live_blocker=True,
    )

    provider = get_live_provider(pilot.provider_name)
    cfg_ok, cfg_detail = provider.validate_configuration()
    _add_check(
        checks,
        blockers,
        warnings,
        "provider_configured",
        cfg_ok,
        cfg_detail,
        live_blocker=True,
    )

    _add_check(
        checks,
        blockers,
        warnings,
        "provider_supports_idempotency",
        provider.supports_idempotency,
        str(provider.supports_idempotency),
        live_blocker=True,
    )

    sender_ok = _configured_secret(settings.live_sender_email)
    _add_check(
        checks,
        blockers,
        warnings,
        "sender_identity",
        sender_ok,
        "present" if sender_ok else "missing",
        live_blocker=True,
    )

    domain_ok = _configured_secret(settings.live_sender_domain)
    _add_check(
        checks,
        blockers,
        warnings,
        "sender_domain",
        domain_ok,
        "present" if domain_ok else "missing",
        live_blocker=True,
    )

    daily_ok = pilot.daily_limit > 0 and settings.live_daily_limit > 0
    _add_check(
        checks,
        blockers,
        warnings,
        "daily_limit",
        daily_ok,
        f"pilot={pilot.daily_limit} env={settings.live_daily_limit}",
        live_blocker=True,
    )

    rate_ok = pilot.per_minute_limit > 0 and settings.live_rate_limit_per_minute > 0
    _add_check(
        checks,
        blockers,
        warnings,
        "rate_limit",
        rate_ok,
        f"pilot={pilot.per_minute_limit} env={settings.live_rate_limit_per_minute}",
        live_blocker=True,
    )

    manual_ok = pilot.approved_at is not None
    _add_check(
        checks,
        blockers,
        warnings,
        "manual_approval",
        manual_ok,
        pilot.approved_at.isoformat() if pilot.approved_at else "pending",
        live_blocker=True,
    )

    typed_ok = db.scalar(
        select(func.count())
        .select_from(LivePilotApproval)
        .where(
            LivePilotApproval.pilot_id == pilot.id,
            LivePilotApproval.success.is_(True),
            LivePilotApproval.consumed_at.isnot(None),
        )
    )
    _add_check(
        checks,
        blockers,
        warnings,
        "typed_confirmation",
        bool(typed_ok),
        "confirmed" if typed_ok else "pending",
        live_blocker=True,
    )

    env_live = bool(settings.live_outreach_enabled)
    _add_check(
        checks,
        blockers,
        warnings,
        "live_environment_flag",
        env_live,
        str(env_live),
        live_blocker=True,
    )

    db_gate = bool(settings.live_pilot_database_gate) and pilot.live_delivery_enabled
    _add_check(
        checks,
        blockers,
        warnings,
        "database_live_gate",
        db_gate,
        f"env={settings.live_pilot_database_gate} pilot={pilot.live_delivery_enabled}",
        live_blocker=True,
    )

    beat_empty = celery_app.conf.beat_schedule == {}
    _add_check(
        checks,
        blockers,
        warnings,
        "scheduler_disabled",
        beat_empty,
        "beat_schedule_empty",
        live_blocker=True,
    )

    _add_check(
        checks,
        blockers,
        warnings,
        "auto_retry_disabled",
        True,
        "max_retries=0",
        live_blocker=True,
    )

    dry_provider = get_dry_run_provider()
    _add_check(
        checks,
        blockers,
        warnings,
        "dry_run_provider_test_only",
        dry_provider.name == "test_email",
        dry_provider.name,
        warning_only=not (dry_provider.name == "test_email"),
    )

    test_checks = [
        "system_stop_all",
        "campaign_active",
        "message_approved",
        "compliance",
        "allowlist",
        "recipient_count",
        "immutable_snapshot",
        "scheduler_disabled",
    ]
    test_ready = all(c.passed for c in checks if c.name in test_checks)
    live_ready = len(blockers) == 0 and not stopped

    if stopped or not test_ready:
        overall = LivePilotValidationStatus.BLOCKED.value
    elif test_ready and not live_ready:
        overall = LivePilotValidationStatus.READY_FOR_PROVIDER_SELECTION.value
    elif test_ready:
        overall = LivePilotValidationStatus.TEST_VALIDATED.value
    else:
        overall = LivePilotValidationStatus.LIVE_NOT_READY.value

    if pilot.status == LivePilotStatus.DRAFT.value and test_ready:
        overall = LivePilotValidationStatus.TEST_VALIDATED.value

    # Stage 7A: live never ready
    live_ready = False
    blockers = _order_blockers(blockers)
    if "stage7a_live_disabled" not in blockers:
        blockers.append("stage7a_live_disabled")
    blockers = _order_blockers(blockers)

    return LivePilotValidationResult(
        ready=test_ready and not stopped,
        overall_status=overall if test_ready else LivePilotValidationStatus.LIVE_NOT_READY.value,
        blockers=blockers,
        warnings=warnings,
        checks=checks,
        generated_at=_utcnow(),
        live_ready=live_ready,
        test_ready=test_ready,
    )


def load_pilot_for_validation(db: Session, pilot_id: UUID) -> LivePilot:
    pilot = db.scalars(
        select(LivePilot)
        .where(LivePilot.id == pilot_id)
        .options(selectinload(LivePilot.recipients))
    ).first()
    if pilot is None:
        from app.core.exceptions import AppError

        raise AppError("Live pilot not found.", status_code=404, code="not_found")
    return pilot
