"""Stage 5: safe test campaign execution orchestration.

Reuses Stage 4 outreach_service.send_message — does not call TestEmailProvider directly.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import Select, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models.campaign import Campaign
from app.models.campaign_lead import CampaignLead
from app.models.company import Company
from app.models.enums import (
    DELIVERY_OUTCOME_UNKNOWN,
    EXECUTION_ACTIVE_STATUSES,
    EXECUTION_TERMINAL_STATUSES,
    ITEM_TERMINAL_STATUSES,
    MAX_EXECUTION_BATCH_SIZE,
    MAX_EXECUTION_LIST_LIMIT,
    MAX_EXECUTION_MESSAGES,
    MIN_EXECUTION_BATCH_SIZE,
    MIN_EXECUTION_MESSAGES,
    PROCESSING_ITEM_STALE_AFTER_SECONDS,
    ExecutionItemStatus,
    ExecutionMode,
    ExecutionRunStatus,
    OutreachMessageStatus,
    ReviewDecision,
    SendAttemptStatus,
)
from app.models.execution_item import CampaignExecutionItem
from app.models.execution_run import CampaignExecutionRun
from app.models.outreach_message import OutreachMessage
from app.models.outreach_sequence import OutreachSequence, OutreachSequenceStep
from app.models.send_attempt import SendAttempt
from app.schemas.execution import (
    CampaignAnalyticsRead,
    ExecutionItemListResponse,
    ExecutionItemRead,
    ExecutionRunCreate,
    ExecutionRunListResponse,
    ExecutionRunRead,
)
from app.security.stop_all import is_system_stopped
from app.services import outreach_service
from app.services.outreach_service import SENDING_PENDING_STALE_AFTER, send_idempotency_key

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _get_campaign(db: Session, campaign_id: UUID) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise AppError("Campaign not found.", status_code=404, code="not_found")
    return campaign


def _run_to_read(run: CampaignExecutionRun, *, matched_existing: bool = False) -> ExecutionRunRead:
    data = ExecutionRunRead.model_validate(run)
    return data.model_copy(update={"matched_existing": matched_existing})


def _item_to_read(
    item: CampaignExecutionItem,
    *,
    message_status: str | None = None,
    company_name: str | None = None,
) -> ExecutionItemRead:
    data = ExecutionItemRead.model_validate(item)
    return data.model_copy(
        update={"message_status": message_status, "company_name": company_name}
    )


def _build_idempotency_key(
    campaign_id: UUID,
    sequence_id: UUID,
    message_ids: list[UUID],
    max_messages: int,
    client_request_id: str | None,
) -> str:
    if client_request_id:
        return f"exec:req:{campaign_id}:{client_request_id.strip()}"
    digest = hashlib.sha256(
        (",".join(str(i) for i in sorted(message_ids)) + f":{max_messages}").encode()
    ).hexdigest()[:32]
    return f"exec:{campaign_id}:{sequence_id}:{digest}"


def _eligible_messages(
    db: Session,
    campaign_id: UUID,
    sequence_id: UUID,
    message_ids: list[UUID] | None,
    max_messages: int,
) -> list[OutreachMessage]:
    steps = {
        s.id: s.step_number
        for s in db.scalars(
            select(OutreachSequenceStep).where(OutreachSequenceStep.sequence_id == sequence_id)
        ).all()
    }
    q = select(OutreachMessage).where(
        OutreachMessage.campaign_id == campaign_id,
        OutreachMessage.sequence_id == sequence_id,
        OutreachMessage.is_test_data.is_(True),
        OutreachMessage.status == OutreachMessageStatus.APPROVED.value,
    )
    if message_ids:
        q = q.where(OutreachMessage.id.in_(message_ids))
    rows = list(db.scalars(q).all())

    eligible: list[OutreachMessage] = []
    for msg in rows:
        try:
            outreach_service.validate_test_recipient(msg.recipient_email)
        except AppError:
            continue
        if msg.error_message == DELIVERY_OUTCOME_UNKNOWN:
            continue
        if msg.sequence_step_id not in steps:
            continue
        eligible.append(msg)

    eligible.sort(
        key=lambda m: (
            steps.get(m.sequence_step_id, 999),
            m.created_at or _utcnow(),
            str(m.id),
        )
    )
    return eligible[:max_messages]


def create_execution_run(
    db: Session,
    campaign_id: UUID,
    data: ExecutionRunCreate,
) -> ExecutionRunRead:
    _get_campaign(db, campaign_id)
    if data.is_test_data is False:
        raise AppError("is_test_data must be true", status_code=422, code="test_data_required")
    # execution_mode is always TEST_MANUAL_ONLY — not client-selectable
    seq = db.get(OutreachSequence, data.sequence_id)
    if seq is None or seq.campaign_id != campaign_id:
        raise AppError("Sequence not found.", status_code=404, code="not_found")
    if not seq.is_active:
        raise AppError("Sequence is inactive", status_code=409, code="inactive_sequence")

    if data.max_messages < MIN_EXECUTION_MESSAGES or data.max_messages > MAX_EXECUTION_MESSAGES:
        raise AppError("Invalid max_messages", status_code=422, code="invalid_max_messages")
    if data.batch_size < MIN_EXECUTION_BATCH_SIZE or data.batch_size > MAX_EXECUTION_BATCH_SIZE:
        raise AppError("Invalid batch_size", status_code=422, code="invalid_batch_size")

    active = db.scalars(
        select(CampaignExecutionRun).where(
            CampaignExecutionRun.campaign_id == campaign_id,
            CampaignExecutionRun.sequence_id == data.sequence_id,
            CampaignExecutionRun.status.in_(list(EXECUTION_ACTIVE_STATUSES)),
        )
    ).first()

    messages = _eligible_messages(
        db, campaign_id, data.sequence_id, data.message_ids, data.max_messages
    )
    if not messages:
        raise AppError(
            "No eligible APPROVED test messages for this sequence",
            status_code=409,
            code="empty_eligible_messages",
        )

    if data.message_ids:
        found = {m.id for m in messages}
        for mid in data.message_ids:
            msg = db.get(OutreachMessage, mid)
            if msg is None or msg.campaign_id != campaign_id:
                raise AppError("Message not found for campaign.", status_code=404, code="not_found")
            if msg.sequence_id != data.sequence_id:
                raise AppError("Message belongs to another sequence", status_code=409, code="wrong_sequence")
            if mid not in found:
                raise AppError(
                    "Message is not eligible (must be APPROVED test @example.test)",
                    status_code=409,
                    code="message_not_eligible",
                )

    key = _build_idempotency_key(
        campaign_id,
        data.sequence_id,
        [m.id for m in messages],
        data.max_messages,
        data.client_request_id,
    )
    existing = db.scalars(
        select(CampaignExecutionRun).where(CampaignExecutionRun.idempotency_key == key)
    ).first()
    if existing is not None:
        return _run_to_read(existing, matched_existing=True)

    if active is not None:
        raise AppError(
            "An active execution run already exists for this campaign sequence",
            status_code=409,
            code="active_run_exists",
        )

    run = CampaignExecutionRun(
        campaign_id=campaign_id,
        sequence_id=data.sequence_id,
        status=ExecutionRunStatus.DRAFT.value,
        execution_mode=ExecutionMode.TEST_MANUAL_ONLY.value,
        max_messages=data.max_messages,
        batch_size=data.batch_size,
        planned_count=len(messages),
        idempotency_key=key,
        is_test_data=True,
    )
    nested = db.begin_nested()
    try:
        db.add(run)
        db.flush()
        for pos, msg in enumerate(messages, start=1):
            db.add(
                CampaignExecutionItem(
                    execution_run_id=run.id,
                    outreach_message_id=msg.id,
                    position=pos,
                    status=ExecutionItemStatus.PENDING.value,
                    is_test_data=True,
                )
            )
        db.flush()
        nested.commit()
    except IntegrityError:
        nested.rollback()
        again = db.scalars(
            select(CampaignExecutionRun).where(CampaignExecutionRun.idempotency_key == key)
        ).first()
        if again is not None:
            return _run_to_read(again, matched_existing=True)
        active_again = db.scalars(
            select(CampaignExecutionRun).where(
                CampaignExecutionRun.campaign_id == campaign_id,
                CampaignExecutionRun.sequence_id == data.sequence_id,
                CampaignExecutionRun.status.in_(list(EXECUTION_ACTIVE_STATUSES)),
            )
        ).first()
        if active_again is not None:
            raise AppError(
                "An active execution run already exists for this campaign sequence",
                status_code=409,
                code="active_run_exists",
            ) from None
        raise AppError("Execution run conflict", status_code=409, code="run_conflict") from None

    run.status = ExecutionRunStatus.PENDING.value
    db.commit()
    db.refresh(run)
    return _run_to_read(run)


def list_execution_runs(
    db: Session,
    campaign_id: UUID,
    *,
    limit: int = 50,
    offset: int = 0,
) -> ExecutionRunListResponse:
    _get_campaign(db, campaign_id)
    if limit < 1 or limit > MAX_EXECUTION_LIST_LIMIT:
        raise AppError("Invalid limit", status_code=422, code="invalid_limit")
    if offset < 0:
        raise AppError("Invalid offset", status_code=422, code="invalid_offset")
    total = db.scalar(
        select(func.count())
        .select_from(CampaignExecutionRun)
        .where(CampaignExecutionRun.campaign_id == campaign_id)
    ) or 0
    rows = db.scalars(
        select(CampaignExecutionRun)
        .where(CampaignExecutionRun.campaign_id == campaign_id)
        .order_by(CampaignExecutionRun.created_at.asc(), CampaignExecutionRun.id.asc())
        .limit(limit)
        .offset(offset)
    ).all()
    return ExecutionRunListResponse(
        items=[_run_to_read(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def get_execution_run(db: Session, campaign_id: UUID, run_id: UUID) -> ExecutionRunRead:
    _get_campaign(db, campaign_id)
    run = db.get(CampaignExecutionRun, run_id)
    if run is None or run.campaign_id != campaign_id:
        raise AppError("Execution run not found.", status_code=404, code="not_found")
    return _run_to_read(run)


def list_execution_items(
    db: Session,
    campaign_id: UUID,
    run_id: UUID,
    *,
    limit: int = 50,
    offset: int = 0,
) -> ExecutionItemListResponse:
    get_execution_run(db, campaign_id, run_id)
    if limit < 1 or limit > MAX_EXECUTION_LIST_LIMIT:
        raise AppError("Invalid limit", status_code=422, code="invalid_limit")
    if offset < 0:
        raise AppError("Invalid offset", status_code=422, code="invalid_offset")
    total = db.scalar(
        select(func.count())
        .select_from(CampaignExecutionItem)
        .where(CampaignExecutionItem.execution_run_id == run_id)
    ) or 0
    stmt: Select = (
        select(CampaignExecutionItem, OutreachMessage.status, Company.name)
        .join(OutreachMessage, OutreachMessage.id == CampaignExecutionItem.outreach_message_id)
        .join(CampaignLead, CampaignLead.id == OutreachMessage.campaign_lead_id)
        .join(Company, Company.id == CampaignLead.company_id)
        .where(CampaignExecutionItem.execution_run_id == run_id)
        .order_by(CampaignExecutionItem.position.asc(), CampaignExecutionItem.id.asc())
        .limit(limit)
        .offset(offset)
    )
    rows = db.execute(stmt).all()
    items = [
        _item_to_read(item, message_status=mstatus, company_name=cname)
        for item, mstatus, cname in rows
    ]
    return ExecutionItemListResponse(items=items, total=total, limit=limit, offset=offset)


def _recompute_counters(db: Session, run_id: UUID) -> None:
    """Idempotent counter rebuild from items (safe after redelivery)."""
    rows = db.execute(
        select(CampaignExecutionItem.status, func.count())
        .where(CampaignExecutionItem.execution_run_id == run_id)
        .group_by(CampaignExecutionItem.status)
    ).all()
    counts = {status: n for status, n in rows}
    processed = sum(counts.get(s, 0) for s in ITEM_TERMINAL_STATUSES)
    db.execute(
        update(CampaignExecutionRun)
        .where(CampaignExecutionRun.id == run_id)
        .values(
            sent_count=counts.get(ExecutionItemStatus.SENT.value, 0),
            failed_count=counts.get(ExecutionItemStatus.FAILED.value, 0),
            blocked_count=counts.get(ExecutionItemStatus.BLOCKED.value, 0),
            skipped_count=counts.get(ExecutionItemStatus.SKIPPED.value, 0),
            unknown_count=counts.get(ExecutionItemStatus.UNKNOWN.value, 0),
            processed_count=processed,
        )
    )


def _maybe_complete_run(db: Session, run: CampaignExecutionRun) -> CampaignExecutionRun:
    pending = db.scalar(
        select(func.count())
        .select_from(CampaignExecutionItem)
        .where(
            CampaignExecutionItem.execution_run_id == run.id,
            CampaignExecutionItem.status.in_(
                [
                    ExecutionItemStatus.PENDING.value,
                    ExecutionItemStatus.PROCESSING.value,
                ]
            ),
        )
    ) or 0
    if pending == 0 and run.status == ExecutionRunStatus.RUNNING.value:
        _recompute_counters(db, run.id)
        db.execute(
            update(CampaignExecutionRun)
            .where(
                CampaignExecutionRun.id == run.id,
                CampaignExecutionRun.status == ExecutionRunStatus.RUNNING.value,
            )
            .values(
                status=ExecutionRunStatus.COMPLETED.value,
                finished_at=_utcnow(),
            )
        )
        db.commit()
        db.refresh(run)
    else:
        _recompute_counters(db, run.id)
        db.commit()
        db.refresh(run)
    return run


def start_execution_run(
    db: Session,
    campaign_id: UUID,
    run_id: UUID,
    *,
    async_mode: bool = True,
) -> ExecutionRunRead:
    run = db.get(CampaignExecutionRun, run_id)
    if run is None or run.campaign_id != campaign_id:
        raise AppError("Execution run not found.", status_code=404, code="not_found")

    if run.status in EXECUTION_TERMINAL_STATUSES:
        return _run_to_read(run)
    if run.status == ExecutionRunStatus.RUNNING.value:
        return _run_to_read(run)
    if run.status == ExecutionRunStatus.PAUSED.value:
        raise AppError("Use resume for paused runs", status_code=409, code="use_resume")
    if run.status not in {ExecutionRunStatus.DRAFT.value, ExecutionRunStatus.PENDING.value}:
        raise AppError("Invalid state transition", status_code=409, code="invalid_transition")

    if is_system_stopped():
        now = _utcnow()
        db.execute(
            update(CampaignExecutionRun)
            .where(
                CampaignExecutionRun.id == run.id,
                CampaignExecutionRun.status.in_(
                    [ExecutionRunStatus.DRAFT.value, ExecutionRunStatus.PENDING.value]
                ),
            )
            .values(
                status=ExecutionRunStatus.BLOCKED.value,
                finished_at=now,
                error_message="SYSTEM_STOP_ALL active",
            )
        )
        db.commit()
        db.refresh(run)
        return _run_to_read(run)

    # DRAFT → PENDING then claim
    if run.status == ExecutionRunStatus.DRAFT.value:
        db.execute(
            update(CampaignExecutionRun)
            .where(
                CampaignExecutionRun.id == run.id,
                CampaignExecutionRun.status == ExecutionRunStatus.DRAFT.value,
            )
            .values(status=ExecutionRunStatus.PENDING.value)
        )
        db.commit()

    now = _utcnow()
    db.refresh(run)
    claim = db.execute(
        update(CampaignExecutionRun)
        .where(
            CampaignExecutionRun.id == run.id,
            CampaignExecutionRun.status == ExecutionRunStatus.PENDING.value,
        )
        .values(
            status=ExecutionRunStatus.RUNNING.value,
            started_at=func.coalesce(CampaignExecutionRun.started_at, now),
        )
    )
    db.commit()
    db.refresh(run)
    if claim.rowcount == 0:
        return _run_to_read(run)

    if async_mode:
        from app.workers.tasks import process_test_campaign_execution_task

        process_test_campaign_execution_task.delay(str(run.id))
    else:
        process_execution_run(db, run.id, allow_enqueue=False)
        db.refresh(run)
    return _run_to_read(run)


def pause_execution_run(db: Session, campaign_id: UUID, run_id: UUID) -> ExecutionRunRead:
    run = db.get(CampaignExecutionRun, run_id)
    if run is None or run.campaign_id != campaign_id:
        raise AppError("Execution run not found.", status_code=404, code="not_found")
    if run.status == ExecutionRunStatus.PAUSED.value:
        return _run_to_read(run)
    if run.status in EXECUTION_TERMINAL_STATUSES:
        raise AppError("Cannot pause terminal run", status_code=409, code="terminal_run")
    if run.status != ExecutionRunStatus.RUNNING.value:
        raise AppError("Pause only from RUNNING", status_code=409, code="invalid_transition")
    now = _utcnow()
    result = db.execute(
        update(CampaignExecutionRun)
        .where(
            CampaignExecutionRun.id == run.id,
            CampaignExecutionRun.status == ExecutionRunStatus.RUNNING.value,
        )
        .values(
            status=ExecutionRunStatus.PAUSED.value,
            paused_at=func.coalesce(CampaignExecutionRun.paused_at, now),
        )
    )
    db.commit()
    db.refresh(run)
    if result.rowcount == 0:
        db.refresh(run)
    return _run_to_read(run)


def resume_execution_run(
    db: Session,
    campaign_id: UUID,
    run_id: UUID,
    *,
    async_mode: bool = True,
) -> ExecutionRunRead:
    run = db.get(CampaignExecutionRun, run_id)
    if run is None or run.campaign_id != campaign_id:
        raise AppError("Execution run not found.", status_code=404, code="not_found")
    if run.status == ExecutionRunStatus.RUNNING.value:
        return _run_to_read(run)
    if run.status in EXECUTION_TERMINAL_STATUSES:
        raise AppError("Cannot resume terminal run", status_code=409, code="terminal_run")
    if run.status != ExecutionRunStatus.PAUSED.value:
        raise AppError("Resume only from PAUSED", status_code=409, code="invalid_transition")

    if is_system_stopped():
        now = _utcnow()
        db.execute(
            update(CampaignExecutionRun)
            .where(
                CampaignExecutionRun.id == run.id,
                CampaignExecutionRun.status == ExecutionRunStatus.PAUSED.value,
            )
            .values(
                status=ExecutionRunStatus.BLOCKED.value,
                finished_at=now,
                error_message="SYSTEM_STOP_ALL active",
            )
        )
        db.commit()
        db.refresh(run)
        return _run_to_read(run)

    now = _utcnow()
    claim = db.execute(
        update(CampaignExecutionRun)
        .where(
            CampaignExecutionRun.id == run.id,
            CampaignExecutionRun.status == ExecutionRunStatus.PAUSED.value,
        )
        .values(
            status=ExecutionRunStatus.RUNNING.value,
            resumed_at=now,
        )
    )
    db.commit()
    db.refresh(run)
    if claim.rowcount == 0:
        return _run_to_read(run)

    if async_mode:
        from app.workers.tasks import process_test_campaign_execution_task

        process_test_campaign_execution_task.delay(str(run.id))
    else:
        process_execution_run(db, run.id, allow_enqueue=False)
        db.refresh(run)
    return _run_to_read(run)


def cancel_execution_run(db: Session, campaign_id: UUID, run_id: UUID) -> ExecutionRunRead:
    run = db.get(CampaignExecutionRun, run_id)
    if run is None or run.campaign_id != campaign_id:
        raise AppError("Execution run not found.", status_code=404, code="not_found")
    if run.status == ExecutionRunStatus.CANCELLED.value:
        return _run_to_read(run)
    if run.status in {
        ExecutionRunStatus.COMPLETED.value,
        ExecutionRunStatus.FAILED.value,
        ExecutionRunStatus.BLOCKED.value,
    }:
        raise AppError("Cannot cancel terminal run", status_code=409, code="terminal_run")
    if run.status not in EXECUTION_ACTIVE_STATUSES:
        raise AppError("Invalid state transition", status_code=409, code="invalid_transition")

    now = _utcnow()
    result = db.execute(
        update(CampaignExecutionRun)
        .where(
            CampaignExecutionRun.id == run.id,
            CampaignExecutionRun.status.in_(list(EXECUTION_ACTIVE_STATUSES)),
        )
        .values(
            status=ExecutionRunStatus.CANCELLED.value,
            cancelled_at=func.coalesce(CampaignExecutionRun.cancelled_at, now),
            finished_at=func.coalesce(CampaignExecutionRun.finished_at, now),
        )
    )
    if result.rowcount == 0:
        db.refresh(run)
        return _run_to_read(run)
    db.execute(
        update(CampaignExecutionItem)
        .where(
            CampaignExecutionItem.execution_run_id == run.id,
            CampaignExecutionItem.status == ExecutionItemStatus.PENDING.value,
        )
        .values(
            status=ExecutionItemStatus.CANCELLED.value,
            finished_at=now,
        )
    )
    _recompute_counters(db, run.id)
    db.commit()
    db.refresh(run)
    return _run_to_read(run)


def _map_message_to_item(
    msg: OutreachMessage,
) -> tuple[str, str | None]:
    if msg.status == OutreachMessageStatus.SENT.value:
        return ExecutionItemStatus.SENT.value, None
    if msg.status == OutreachMessageStatus.BLOCKED.value:
        return ExecutionItemStatus.BLOCKED.value, msg.error_message
    if msg.status == OutreachMessageStatus.FAILED.value:
        if msg.error_message == DELIVERY_OUTCOME_UNKNOWN:
            return ExecutionItemStatus.UNKNOWN.value, DELIVERY_OUTCOME_UNKNOWN
        return ExecutionItemStatus.FAILED.value, msg.error_message
    if msg.status == OutreachMessageStatus.SENDING.value:
        return ExecutionItemStatus.UNKNOWN.value, DELIVERY_OUTCOME_UNKNOWN
    return ExecutionItemStatus.FAILED.value, msg.error_message or "unexpected_message_status"


def _attempt_age(attempt: SendAttempt) -> timedelta:
    attempted = attempt.attempted_at or _utcnow()
    if attempted.tzinfo is None:
        attempted = attempted.replace(tzinfo=timezone.utc)
    return _utcnow() - attempted


def _recover_stale_processing(db: Session, item: CampaignExecutionItem) -> bool:
    """Recover stuck PROCESSING. True if item status changed (terminal or reset PENDING).

    Never calls provider. False SENT is forbidden. Fresh in-flight attempts are left alone.
    """
    if item.status != ExecutionItemStatus.PROCESSING.value:
        return False
    claimed = item.claimed_at or _utcnow()
    if claimed.tzinfo is None:
        claimed = claimed.replace(tzinfo=timezone.utc)
    item_age = _utcnow() - claimed

    msg = db.get(OutreachMessage, item.outreach_message_id)
    if msg is None:
        if item_age < timedelta(seconds=PROCESSING_ITEM_STALE_AFTER_SECONDS):
            return False
        item.status = ExecutionItemStatus.FAILED.value
        item.error_message = "message_missing"
        item.finished_at = _utcnow()
        return True

    # Confirmed terminal outcomes — mirror without waiting for staleness.
    if msg.status == OutreachMessageStatus.SENT.value:
        item.status = ExecutionItemStatus.SENT.value
        item.error_message = None
        item.finished_at = _utcnow()
        return True
    if msg.status == OutreachMessageStatus.BLOCKED.value:
        item.status = ExecutionItemStatus.BLOCKED.value
        item.error_message = msg.error_message
        item.finished_at = _utcnow()
        return True
    if msg.status == OutreachMessageStatus.FAILED.value:
        status, err = _map_message_to_item(msg)
        item.status = status
        item.error_message = err
        item.finished_at = _utcnow()
        return True
    if msg.status == OutreachMessageStatus.REJECTED.value:
        item.status = ExecutionItemStatus.SKIPPED.value
        item.error_message = "message_rejected"
        item.finished_at = _utcnow()
        return True

    key = send_idempotency_key(msg.id)
    attempt = db.scalars(select(SendAttempt).where(SendAttempt.idempotency_key == key)).first()

    if attempt is not None and attempt.status == SendAttemptStatus.SUCCESS.value:
        item.status = ExecutionItemStatus.SENT.value
        item.finished_at = _utcnow()
        return True

    if attempt is not None and attempt.status == SendAttemptStatus.PENDING.value:
        if _attempt_age(attempt) < SENDING_PENDING_STALE_AFTER:
            # Fresh in-flight Stage 4 send — do not touch.
            return False
        # Stale pending outbox → UNKNOWN, never provider retry from orchestrator.
        item.status = ExecutionItemStatus.UNKNOWN.value
        item.error_message = DELIVERY_OUTCOME_UNKNOWN
        item.finished_at = _utcnow()
        return True

    if attempt is not None and attempt.status == SendAttemptStatus.FAILED.value:
        if msg.error_message == DELIVERY_OUTCOME_UNKNOWN:
            item.status = ExecutionItemStatus.UNKNOWN.value
            item.error_message = DELIVERY_OUTCOME_UNKNOWN
        else:
            item.status = ExecutionItemStatus.FAILED.value
            item.error_message = attempt.safe_error_message or msg.error_message
        item.finished_at = _utcnow()
        return True

    # Message still APPROVED/SENDING and no attempt, or unknown attempt state.
    if item_age < timedelta(seconds=PROCESSING_ITEM_STALE_AFTER_SECONDS):
        return False

    if (
        msg.status == OutreachMessageStatus.APPROVED.value
        and attempt is None
    ):
        # Proven: provider was never reserved — safe reset for one claim.
        item.status = ExecutionItemStatus.PENDING.value
        item.claimed_at = None
        item.error_message = None
        return True

    # Doubt (e.g. SENDING without attempt row, or unexpected state) → UNKNOWN.
    item.status = ExecutionItemStatus.UNKNOWN.value
    item.error_message = DELIVERY_OUTCOME_UNKNOWN
    item.finished_at = _utcnow()
    return True


def _process_one_item(db: Session, run: CampaignExecutionRun, item: CampaignExecutionItem) -> None:
    db.refresh(run)
    if run.status == ExecutionRunStatus.PAUSED.value:
        return
    if run.status == ExecutionRunStatus.CANCELLED.value:
        if item.status == ExecutionItemStatus.PENDING.value:
            item.status = ExecutionItemStatus.CANCELLED.value
            item.finished_at = _utcnow()
            db.commit()
        return
    if run.status == ExecutionRunStatus.BLOCKED.value:
        return
    if run.status != ExecutionRunStatus.RUNNING.value:
        return

    if is_system_stopped():
        now = _utcnow()
        db.execute(
            update(CampaignExecutionRun)
            .where(
                CampaignExecutionRun.id == run.id,
                CampaignExecutionRun.status == ExecutionRunStatus.RUNNING.value,
            )
            .values(
                status=ExecutionRunStatus.BLOCKED.value,
                finished_at=now,
                error_message="SYSTEM_STOP_ALL active",
            )
        )
        db.commit()
        return

    if item.status == ExecutionItemStatus.PROCESSING.value:
        if _recover_stale_processing(db, item):
            db.commit()
        return

    if item.status != ExecutionItemStatus.PENDING.value:
        return

    # Stage 6: compliance before item claim — blocks item only (not whole run)
    msg_pre = db.get(OutreachMessage, item.outreach_message_id)
    if msg_pre is not None and msg_pre.status == OutreachMessageStatus.APPROVED.value:
        from app.models.enums import ComplianceCheckContext
        from app.services import compliance_service

        compliance = compliance_service.check_outreach_compliance(
            db,
            campaign_id=run.campaign_id,
            message=msg_pre,
            execution_run_id=run.id,
            check_context=ComplianceCheckContext.EXECUTION_ITEM.value,
            persist_log=True,
        )
        if not compliance.allowed:
            compliance_service.apply_message_suppression_block(db, msg_pre, compliance)
            item.status = ExecutionItemStatus.BLOCKED.value
            item.error_message = compliance.reason_code
            item.finished_at = _utcnow()
            db.commit()
            return

    now = _utcnow()
    claim = db.execute(
        update(CampaignExecutionItem)
        .where(
            CampaignExecutionItem.id == item.id,
            CampaignExecutionItem.status == ExecutionItemStatus.PENDING.value,
        )
        .values(status=ExecutionItemStatus.PROCESSING.value, claimed_at=now)
    )
    db.commit()
    if claim.rowcount == 0:
        return

    db.refresh(item)
    msg = db.get(OutreachMessage, item.outreach_message_id)
    if msg is None:
        item.status = ExecutionItemStatus.FAILED.value
        item.error_message = "message_missing"
        item.finished_at = _utcnow()
        db.commit()
        return

    # Already terminal on message — skip provider
    if msg.status == OutreachMessageStatus.SENT.value:
        item.status = ExecutionItemStatus.SKIPPED.value
        item.finished_at = _utcnow()
        item.error_message = "already_sent"
        db.commit()
        return
    if msg.status in {
        OutreachMessageStatus.FAILED.value,
        OutreachMessageStatus.BLOCKED.value,
        OutreachMessageStatus.REJECTED.value,
    }:
        status, err = _map_message_to_item(msg)
        item.status = status
        item.error_message = err
        item.finished_at = _utcnow()
        db.commit()
        return
    if msg.status != OutreachMessageStatus.APPROVED.value:
        item.status = ExecutionItemStatus.SKIPPED.value
        item.error_message = f"message_status_{msg.status}"
        item.finished_at = _utcnow()
        db.commit()
        return

    if is_system_stopped():
        now = _utcnow()
        item.status = ExecutionItemStatus.BLOCKED.value
        item.error_message = "SYSTEM_STOP_ALL active"
        item.finished_at = now
        db.execute(
            update(CampaignExecutionRun)
            .where(
                CampaignExecutionRun.id == run.id,
                CampaignExecutionRun.status == ExecutionRunStatus.RUNNING.value,
            )
            .values(
                status=ExecutionRunStatus.BLOCKED.value,
                finished_at=now,
                error_message="SYSTEM_STOP_ALL active",
            )
        )
        db.commit()
        return

    try:
        result = outreach_service.send_message(db, run.campaign_id, msg.id)
        status, err = _map_message_to_item(result)
        item.status = status
        item.error_message = err
        item.finished_at = _utcnow()
        db.commit()
    except AppError as exc:
        if exc.code == "sending":
            # Concurrent Stage 4 send — leave PROCESSING for stale recovery
            return
        item.status = ExecutionItemStatus.FAILED.value
        item.error_message = exc.code
        item.finished_at = _utcnow()
        db.commit()
    except Exception:  # noqa: BLE001
        item.status = ExecutionItemStatus.FAILED.value
        item.error_message = "processing_error"
        item.finished_at = _utcnow()
        db.commit()
        logger.warning("Execution item failed run_id=%s item_id=%s", run.id, item.id)


def _count_items(db: Session, run_id: UUID, *statuses: str) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(CampaignExecutionItem)
            .where(
                CampaignExecutionItem.execution_run_id == run_id,
                CampaignExecutionItem.status.in_(list(statuses)),
            )
        )
        or 0
    )


def process_execution_run(
    db: Session,
    run_id: UUID,
    *,
    allow_enqueue: bool = True,
) -> CampaignExecutionRun:
    """Process one batch (Celery) or drain (sync).

    Concurrent RUNNING workers are safe: items are claimed atomically.
    Next-batch enqueue happens only after counters commit when PENDING remain.
    """
    run = db.get(CampaignExecutionRun, run_id)
    if run is None:
        raise AppError("Execution run not found.", status_code=404, code="not_found")

    max_loops = MAX_EXECUTION_MESSAGES + 2
    for _ in range(max_loops):
        db.refresh(run)
        if run.status in EXECUTION_TERMINAL_STATUSES:
            return run
        if run.status == ExecutionRunStatus.PAUSED.value:
            return run
        if run.status != ExecutionRunStatus.RUNNING.value:
            return run

        if is_system_stopped():
            now = _utcnow()
            db.execute(
                update(CampaignExecutionRun)
                .where(
                    CampaignExecutionRun.id == run.id,
                    CampaignExecutionRun.status == ExecutionRunStatus.RUNNING.value,
                )
                .values(
                    status=ExecutionRunStatus.BLOCKED.value,
                    finished_at=func.coalesce(CampaignExecutionRun.finished_at, now),
                    error_message="SYSTEM_STOP_ALL active",
                )
            )
            db.commit()
            db.refresh(run)
            return run

        processing = db.scalars(
            select(CampaignExecutionItem)
            .where(
                CampaignExecutionItem.execution_run_id == run.id,
                CampaignExecutionItem.status == ExecutionItemStatus.PROCESSING.value,
            )
            .order_by(CampaignExecutionItem.position.asc())
        ).all()
        recovered = False
        for item in processing:
            if _recover_stale_processing(db, item):
                recovered = True
        if recovered:
            db.commit()

        items = db.scalars(
            select(CampaignExecutionItem)
            .where(
                CampaignExecutionItem.execution_run_id == run.id,
                CampaignExecutionItem.status == ExecutionItemStatus.PENDING.value,
            )
            .order_by(CampaignExecutionItem.position.asc(), CampaignExecutionItem.id.asc())
            .limit(run.batch_size)
        ).all()

        if not items:
            pending = _count_items(db, run.id, ExecutionItemStatus.PENDING.value)
            processing_n = _count_items(db, run.id, ExecutionItemStatus.PROCESSING.value)
            if pending == 0 and processing_n == 0:
                return _maybe_complete_run(db, run)
            # Fresh PROCESSING only — do not busy-loop or false-complete.
            _recompute_counters(db, run.id)
            db.commit()
            db.refresh(run)
            return run

        for item in items:
            db.refresh(run)
            if run.status != ExecutionRunStatus.RUNNING.value:
                break
            _process_one_item(db, run, item)

        run = _maybe_complete_run(db, run)
        db.refresh(run)
        if run.status != ExecutionRunStatus.RUNNING.value:
            return run

        remaining = _count_items(db, run.id, ExecutionItemStatus.PENDING.value)
        if remaining == 0:
            processing_n = _count_items(db, run.id, ExecutionItemStatus.PROCESSING.value)
            if processing_n == 0:
                return _maybe_complete_run(db, run)
            return run
        if allow_enqueue:
            from app.workers.tasks import process_test_campaign_execution_task

            # Enqueue only after batch counters were committed in _maybe_complete_run.
            process_test_campaign_execution_task.delay(str(run.id))
            return run
        # sync drain: continue loop

    return run


def get_campaign_analytics(db: Session, campaign_id: UUID) -> CampaignAnalyticsRead:
    _get_campaign(db, campaign_id)

    approved_leads = db.scalar(
        select(func.count())
        .select_from(CampaignLead)
        .where(
            CampaignLead.campaign_id == campaign_id,
            CampaignLead.review_decision == ReviewDecision.APPROVED.value,
        )
    ) or 0

    def msg_count(status: str) -> int:
        return db.scalar(
            select(func.count())
            .select_from(OutreachMessage)
            .where(
                OutreachMessage.campaign_id == campaign_id,
                OutreachMessage.status == status,
            )
        ) or 0

    draft_messages = msg_count(OutreachMessageStatus.DRAFT.value)
    approved_messages = msg_count(OutreachMessageStatus.APPROVED.value)
    sent_messages = msg_count(OutreachMessageStatus.SENT.value)
    failed_all = db.scalars(
        select(OutreachMessage).where(
            OutreachMessage.campaign_id == campaign_id,
            OutreachMessage.status == OutreachMessageStatus.FAILED.value,
        )
    ).all()
    unknown_messages = sum(1 for m in failed_all if m.error_message == DELIVERY_OUTCOME_UNKNOWN)
    failed_messages = len(failed_all) - unknown_messages
    blocked_messages = msg_count(OutreachMessageStatus.BLOCKED.value)
    rejected_messages = msg_count(OutreachMessageStatus.REJECTED.value)

    runs_total = db.scalar(
        select(func.count())
        .select_from(CampaignExecutionRun)
        .where(CampaignExecutionRun.campaign_id == campaign_id)
    ) or 0
    runs_completed = db.scalar(
        select(func.count())
        .select_from(CampaignExecutionRun)
        .where(
            CampaignExecutionRun.campaign_id == campaign_id,
            CampaignExecutionRun.status == ExecutionRunStatus.COMPLETED.value,
        )
    ) or 0
    runs_failed = db.scalar(
        select(func.count())
        .select_from(CampaignExecutionRun)
        .where(
            CampaignExecutionRun.campaign_id == campaign_id,
            CampaignExecutionRun.status == ExecutionRunStatus.FAILED.value,
        )
    ) or 0
    runs_blocked = db.scalar(
        select(func.count())
        .select_from(CampaignExecutionRun)
        .where(
            CampaignExecutionRun.campaign_id == campaign_id,
            CampaignExecutionRun.status == ExecutionRunStatus.BLOCKED.value,
        )
    ) or 0
    latest = db.scalars(
        select(CampaignExecutionRun)
        .where(CampaignExecutionRun.campaign_id == campaign_id)
        .order_by(CampaignExecutionRun.created_at.desc(), CampaignExecutionRun.id.desc())
        .limit(1)
    ).first()

    decided = sent_messages + failed_messages + blocked_messages + unknown_messages
    test_delivery_rate = (sent_messages / decided) if decided else 0.0
    failure_rate = ((failed_messages + unknown_messages + blocked_messages) / decided) if decided else 0.0

    return CampaignAnalyticsRead(
        campaign_id=campaign_id,
        is_test_data=True,
        approved_leads=approved_leads,
        draft_messages=draft_messages,
        approved_messages=approved_messages,
        sent_messages=sent_messages,
        failed_messages=failed_messages,
        blocked_messages=blocked_messages,
        unknown_messages=unknown_messages,
        rejected_messages=rejected_messages,
        execution_runs_total=runs_total,
        execution_runs_completed=runs_completed,
        execution_runs_failed=runs_failed,
        execution_runs_blocked=runs_blocked,
        latest_run_status=latest.status if latest else None,
        test_delivery_rate=round(test_delivery_rate, 4),
        failure_rate=round(failure_rate, 4),
    )
