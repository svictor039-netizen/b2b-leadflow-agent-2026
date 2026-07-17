"""Stage 4 safe outreach: templates, sequences, drafts, approve, test send."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import Select, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import AppError
from app.models.campaign import Campaign
from app.models.campaign_lead import CampaignLead
from app.models.company import Company, CompanyLocation
from app.models.enums import (
    ALLOWED_OUTREACH_PROVIDER,
    DELIVERY_OUTCOME_UNKNOWN,
    MAX_OUTREACH_BODY,
    MAX_OUTREACH_LIST_LIMIT,
    MAX_OUTREACH_REJECT_NOTE,
    MAX_OUTREACH_SEQUENCE_NAME,
    MAX_OUTREACH_SEQUENCE_STEPS,
    MAX_OUTREACH_SUBJECT,
    MAX_OUTREACH_TEMPLATE_NAME,
    TEST_EMAIL_DOMAIN,
    DraftItemOutcome,
    OutreachApprovalDecision,
    OutreachMessageStatus,
    ReviewDecision,
    SendAttemptStatus,
)
from app.models.outreach_message import OutreachMessage
from app.models.outreach_sequence import OutreachSequence, OutreachSequenceStep
from app.models.outreach_template import OutreachTemplate
from app.models.send_attempt import SendAttempt
from app.providers.base import EmailMessage
from app.providers.email_test import TestEmailProvider
from app.schemas.outreach import (
    DraftCreateRequest,
    DraftCreateResponse,
    DraftItemResult,
    OutreachMessageListResponse,
    OutreachMessageRead,
    OutreachSequenceCreate,
    OutreachSequenceRead,
    OutreachSequenceUpdate,
    OutreachTemplateCreate,
    OutreachTemplateRead,
    OutreachTemplateUpdate,
    RejectMessageRequest,
    SequenceStepRead,
)
from app.security.stop_all import is_system_stopped
from app.services.template_renderer import render_body, render_subject, validate_template_text

logger = logging.getLogger(__name__)

APPROVAL_AUDIT_MARKER = "manual_ui"
# Fresh PENDING outbox means another worker may still be inside provider.send.
# Only stale PENDING is recovered without a second provider call (at-most-once).
SENDING_PENDING_STALE_AFTER = timedelta(seconds=30)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _safe_error(exc: BaseException) -> str:
    msg = str(exc)[:240]
    for token in ("traceback", "secret", "password", "token", "api_key"):
        if token in msg.lower():
            return "Provider error (details suppressed)"
    return msg or "Provider error"


_LOCAL_PART_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._+-]{0,62}[a-z0-9])?$", re.IGNORECASE)


def test_recipient_for_lead(lead_id: UUID) -> str:
    return f"lead-{lead_id}@{TEST_EMAIL_DOMAIN}"


def validate_test_recipient(email: str) -> None:
    """Strict server-side test recipient: exactly local@example.test (ASCII)."""
    if email is None or not isinstance(email, str):
        raise AppError("Invalid test recipient", status_code=422, code="invalid_recipient")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in email):
        raise AppError("Invalid test recipient", status_code=422, code="invalid_recipient")
    if any(ch in email for ch in ('<', '>', '"', ',', ';')):
        raise AppError("Invalid test recipient", status_code=422, code="invalid_recipient")
    # Only outer whitespace is stripped; internal spaces remain invalid.
    cleaned = email.strip().lower()
    if " " in cleaned or "\t" in cleaned:
        raise AppError("Invalid test recipient", status_code=422, code="invalid_recipient")
    try:
        cleaned.encode("ascii")
    except UnicodeEncodeError as exc:
        raise AppError(
            "Recipient must be ASCII @example.test",
            status_code=422,
            code="invalid_recipient_domain",
        ) from exc
    if cleaned.count("@") != 1:
        raise AppError("Invalid test recipient", status_code=422, code="invalid_recipient")
    local, domain = cleaned.split("@")
    if not local or not _LOCAL_PART_RE.fullmatch(local):
        raise AppError("Invalid test recipient", status_code=422, code="invalid_recipient")
    # Exact domain only — rejects sub.example.test and example.test.evil.com
    if domain != TEST_EMAIL_DOMAIN:
        raise AppError(
            f"Recipient domain must be @{TEST_EMAIL_DOMAIN}",
            status_code=422,
            code="invalid_recipient_domain",
        )


def message_idempotency_key(lead_id: UUID, step_id: UUID) -> str:
    return f"outreach:lead:{lead_id}:step:{step_id}"


def send_idempotency_key(message_id: UUID) -> str:
    return f"outreach:send:{message_id}"


def _get_campaign(db: Session, campaign_id: UUID) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise AppError("Campaign not found.", status_code=404, code="not_found")
    return campaign


def _location_str(company: Company) -> str:
    locations = list(company.locations or [])
    primary = next((loc for loc in locations if loc.is_primary), None)
    loc = primary or (locations[0] if locations else None)
    if loc is None:
        return ""
    parts = [p for p in (loc.city, loc.region, loc.country) if p]
    return ", ".join(parts)


def build_render_context(
    campaign: Campaign,
    lead: CampaignLead,
    company: Company,
) -> dict[str, str]:
    score = lead.qualification_score
    return {
        "company_name": company.name or "",
        "company_domain": company.domain or "",
        "company_location": _location_str(company),
        "company_industry": "",  # Company has no industry column
        "campaign_name": campaign.name or "",
        "lead_score": "" if score is None else str(score),
        "qualification_status": lead.qualification_status or "",
    }


def _template_to_read(t: OutreachTemplate) -> OutreachTemplateRead:
    return OutreachTemplateRead.model_validate(t)


def _sequence_to_read(seq: OutreachSequence) -> OutreachSequenceRead:
    steps = sorted(seq.steps, key=lambda s: s.step_number)
    return OutreachSequenceRead(
        id=seq.id,
        campaign_id=seq.campaign_id,
        name=seq.name,
        is_active=seq.is_active,
        is_test_data=seq.is_test_data,
        created_at=seq.created_at,
        updated_at=seq.updated_at,
        steps=[
            SequenceStepRead(
                id=s.id,
                sequence_id=s.sequence_id,
                template_id=s.template_id,
                step_number=s.step_number,
                created_at=s.created_at,
            )
            for s in steps
        ],
    )


def _message_to_read(msg: OutreachMessage, *, company_name: str | None = None) -> OutreachMessageRead:
    data = OutreachMessageRead.model_validate(msg)
    if company_name is not None:
        data = data.model_copy(update={"company_name": company_name})
    return data


# ----- Templates -----


def create_template(
    db: Session,
    campaign_id: UUID,
    data: OutreachTemplateCreate,
) -> OutreachTemplateRead:
    _get_campaign(db, campaign_id)
    if data.is_test_data is False:
        raise AppError("is_test_data must be true", status_code=422, code="test_data_required")
    name = data.name.strip()
    if not name or len(name) > MAX_OUTREACH_TEMPLATE_NAME:
        raise AppError("Invalid template name", status_code=422, code="invalid_name")
    if len(data.subject_template) > MAX_OUTREACH_SUBJECT:
        raise AppError("subject_template too long", status_code=422, code="subject_too_long")
    if len(data.body_template) > MAX_OUTREACH_BODY:
        raise AppError("body_template too long", status_code=422, code="body_too_long")
    validate_template_text(data.subject_template, field="subject_template")
    validate_template_text(data.body_template, field="body_template")

    tmpl = OutreachTemplate(
        campaign_id=campaign_id,
        name=name,
        subject_template=data.subject_template,
        body_template=data.body_template,
        is_active=data.is_active,
        is_test_data=True,
    )
    db.add(tmpl)
    db.commit()
    db.refresh(tmpl)
    return _template_to_read(tmpl)


def list_templates(db: Session, campaign_id: UUID) -> list[OutreachTemplateRead]:
    _get_campaign(db, campaign_id)
    rows = db.scalars(
        select(OutreachTemplate)
        .where(OutreachTemplate.campaign_id == campaign_id)
        .order_by(OutreachTemplate.created_at.asc(), OutreachTemplate.id.asc())
    ).all()
    return [_template_to_read(r) for r in rows]


def update_template(
    db: Session,
    campaign_id: UUID,
    template_id: UUID,
    data: OutreachTemplateUpdate,
) -> OutreachTemplateRead:
    _get_campaign(db, campaign_id)
    tmpl = db.get(OutreachTemplate, template_id)
    if tmpl is None or tmpl.campaign_id != campaign_id:
        raise AppError("Template not found.", status_code=404, code="not_found")
    if data.name is not None:
        name = data.name.strip()
        if not name or len(name) > MAX_OUTREACH_TEMPLATE_NAME:
            raise AppError("Invalid template name", status_code=422, code="invalid_name")
        tmpl.name = name
    if data.subject_template is not None:
        if len(data.subject_template) > MAX_OUTREACH_SUBJECT:
            raise AppError("subject_template too long", status_code=422, code="subject_too_long")
        validate_template_text(data.subject_template, field="subject_template")
        tmpl.subject_template = data.subject_template
    if data.body_template is not None:
        if len(data.body_template) > MAX_OUTREACH_BODY:
            raise AppError("body_template too long", status_code=422, code="body_too_long")
        validate_template_text(data.body_template, field="body_template")
        tmpl.body_template = data.body_template
    if data.is_active is not None:
        tmpl.is_active = data.is_active
    db.commit()
    db.refresh(tmpl)
    return _template_to_read(tmpl)


# ----- Sequences -----


def create_sequence(
    db: Session,
    campaign_id: UUID,
    data: OutreachSequenceCreate,
) -> OutreachSequenceRead:
    _get_campaign(db, campaign_id)
    if data.is_test_data is False:
        raise AppError("is_test_data must be true", status_code=422, code="test_data_required")
    name = data.name.strip()
    if not name or len(name) > MAX_OUTREACH_SEQUENCE_NAME:
        raise AppError("Invalid sequence name", status_code=422, code="invalid_name")
    if not data.steps or len(data.steps) > MAX_OUTREACH_SEQUENCE_STEPS:
        raise AppError(
            f"Sequence must have 1–{MAX_OUTREACH_SEQUENCE_STEPS} steps",
            status_code=422,
            code="invalid_step_count",
        )
    numbers = [s.step_number for s in data.steps]
    if len(set(numbers)) != len(numbers):
        raise AppError("Duplicate step_number", status_code=422, code="duplicate_step")
    if sorted(numbers) != list(range(1, len(numbers) + 1)):
        raise AppError("step_number must be contiguous starting at 1", status_code=422, code="invalid_steps")

    for step in data.steps:
        tmpl = db.get(OutreachTemplate, step.template_id)
        if tmpl is None or tmpl.campaign_id != campaign_id:
            raise AppError("Template not found for step.", status_code=404, code="not_found")
        if not tmpl.is_active:
            raise AppError("Template is inactive", status_code=409, code="inactive_template")

    seq = OutreachSequence(
        campaign_id=campaign_id,
        name=name,
        is_active=data.is_active,
        is_test_data=True,
    )
    db.add(seq)
    db.flush()
    for step in data.steps:
        db.add(
            OutreachSequenceStep(
                sequence_id=seq.id,
                template_id=step.template_id,
                step_number=step.step_number,
            )
        )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError("Sequence step conflict", status_code=409, code="step_conflict") from None
    db.refresh(seq)
    seq = db.scalars(
        select(OutreachSequence)
        .where(OutreachSequence.id == seq.id)
        .options(selectinload(OutreachSequence.steps))
    ).one()
    return _sequence_to_read(seq)


def list_sequences(db: Session, campaign_id: UUID) -> list[OutreachSequenceRead]:
    _get_campaign(db, campaign_id)
    rows = db.scalars(
        select(OutreachSequence)
        .where(OutreachSequence.campaign_id == campaign_id)
        .options(selectinload(OutreachSequence.steps))
        .order_by(OutreachSequence.created_at.asc(), OutreachSequence.id.asc())
    ).all()
    return [_sequence_to_read(r) for r in rows]


def update_sequence(
    db: Session,
    campaign_id: UUID,
    sequence_id: UUID,
    data: OutreachSequenceUpdate,
) -> OutreachSequenceRead:
    _get_campaign(db, campaign_id)
    seq = db.scalars(
        select(OutreachSequence)
        .where(OutreachSequence.id == sequence_id, OutreachSequence.campaign_id == campaign_id)
        .options(selectinload(OutreachSequence.steps))
    ).first()
    if seq is None:
        raise AppError("Sequence not found.", status_code=404, code="not_found")
    if data.name is not None:
        name = data.name.strip()
        if not name or len(name) > MAX_OUTREACH_SEQUENCE_NAME:
            raise AppError("Invalid sequence name", status_code=422, code="invalid_name")
        seq.name = name
    if data.is_active is not None:
        seq.is_active = data.is_active
    db.commit()
    db.refresh(seq)
    seq = db.scalars(
        select(OutreachSequence)
        .where(OutreachSequence.id == seq.id)
        .options(selectinload(OutreachSequence.steps))
    ).one()
    return _sequence_to_read(seq)


# ----- Drafts -----


def create_drafts(
    db: Session,
    campaign_id: UUID,
    data: DraftCreateRequest,
) -> DraftCreateResponse:
    campaign = _get_campaign(db, campaign_id)
    seq = db.scalars(
        select(OutreachSequence)
        .where(OutreachSequence.id == data.sequence_id, OutreachSequence.campaign_id == campaign_id)
        .options(
            selectinload(OutreachSequence.steps).selectinload(OutreachSequenceStep.template),
        )
    ).first()
    if seq is None:
        raise AppError("Sequence not found.", status_code=404, code="not_found")
    if not seq.is_active:
        raise AppError("Sequence is inactive", status_code=409, code="inactive_sequence")
    steps = sorted(seq.steps, key=lambda s: s.step_number)
    if not steps or len(steps) > MAX_OUTREACH_SEQUENCE_STEPS:
        raise AppError("Sequence must have 1–3 steps", status_code=409, code="invalid_sequence")

    if not data.lead_ids:
        raise AppError("lead_ids required", status_code=422, code="empty_leads")

    results: list[DraftItemResult] = []
    created = matched = skipped = conflict = failed = 0

    for lead_id in data.lead_ids:
        lead = db.get(CampaignLead, lead_id)
        if lead is None or lead.campaign_id != campaign_id:
            results.append(
                DraftItemResult(
                    lead_id=lead_id,
                    sequence_step_id=None,
                    message_id=None,
                    outcome=DraftItemOutcome.SKIPPED.value,
                    detail="lead_not_in_campaign",
                )
            )
            skipped += 1
            continue
        if not lead.is_test_data:
            results.append(
                DraftItemResult(
                    lead_id=lead_id,
                    sequence_step_id=None,
                    message_id=None,
                    outcome=DraftItemOutcome.SKIPPED.value,
                    detail="not_test_data",
                )
            )
            skipped += 1
            continue
        if lead.review_decision != ReviewDecision.APPROVED.value:
            results.append(
                DraftItemResult(
                    lead_id=lead_id,
                    sequence_step_id=None,
                    message_id=None,
                    outcome=DraftItemOutcome.SKIPPED.value,
                    detail="lead_not_approved",
                )
            )
            skipped += 1
            continue

        company = db.get(Company, lead.company_id)
        if company is None:
            results.append(
                DraftItemResult(
                    lead_id=lead_id,
                    sequence_step_id=None,
                    message_id=None,
                    outcome=DraftItemOutcome.FAILED.value,
                    detail="company_missing",
                )
            )
            failed += 1
            continue

        # Load locations for render context
        _ = db.scalars(
            select(CompanyLocation).where(CompanyLocation.company_id == company.id)
        ).all()
        company = db.scalars(
            select(Company)
            .where(Company.id == company.id)
            .options(selectinload(Company.locations))
        ).one()

        ctx = build_render_context(campaign, lead, company)
        recipient = test_recipient_for_lead(lead.id)
        validate_test_recipient(recipient)

        for step in steps:
            template = step.template
            if template is None or not template.is_active:
                results.append(
                    DraftItemResult(
                        lead_id=lead_id,
                        sequence_step_id=step.id,
                        message_id=None,
                        outcome=DraftItemOutcome.FAILED.value,
                        detail="template_inactive",
                    )
                )
                failed += 1
                continue

            existing = db.scalars(
                select(OutreachMessage).where(
                    OutreachMessage.campaign_lead_id == lead.id,
                    OutreachMessage.sequence_step_id == step.id,
                )
            ).first()
            if existing is not None:
                results.append(
                    DraftItemResult(
                        lead_id=lead_id,
                        sequence_step_id=step.id,
                        message_id=existing.id,
                        outcome=DraftItemOutcome.MATCHED_EXISTING.value,
                    )
                )
                matched += 1
                continue

            try:
                subject = render_subject(template.subject_template, ctx)
                body = render_body(template.body_template, ctx)
            except AppError as exc:
                results.append(
                    DraftItemResult(
                        lead_id=lead_id,
                        sequence_step_id=step.id,
                        message_id=None,
                        outcome=DraftItemOutcome.FAILED.value,
                        detail=exc.code,
                    )
                )
                failed += 1
                continue

            key = message_idempotency_key(lead.id, step.id)
            msg = OutreachMessage(
                campaign_id=campaign_id,
                campaign_lead_id=lead.id,
                sequence_id=seq.id,
                sequence_step_id=step.id,
                template_id=template.id,
                recipient_email=recipient,
                subject_rendered=subject,
                body_rendered=body,
                status=OutreachMessageStatus.DRAFT.value,
                approval_decision=OutreachApprovalDecision.PENDING.value,
                idempotency_key=key,
                is_test_data=True,
            )
            nested = db.begin_nested()
            try:
                db.add(msg)
                db.flush()
                nested.commit()
                results.append(
                    DraftItemResult(
                        lead_id=lead_id,
                        sequence_step_id=step.id,
                        message_id=msg.id,
                        outcome=DraftItemOutcome.CREATED.value,
                    )
                )
                created += 1
            except IntegrityError:
                nested.rollback()
                again = db.scalars(
                    select(OutreachMessage).where(
                        OutreachMessage.campaign_lead_id == lead.id,
                        OutreachMessage.sequence_step_id == step.id,
                    )
                ).first()
                if again is not None:
                    results.append(
                        DraftItemResult(
                            lead_id=lead_id,
                            sequence_step_id=step.id,
                            message_id=again.id,
                            outcome=DraftItemOutcome.MATCHED_EXISTING.value,
                        )
                    )
                    matched += 1
                else:
                    results.append(
                        DraftItemResult(
                            lead_id=lead_id,
                            sequence_step_id=step.id,
                            message_id=None,
                            outcome=DraftItemOutcome.CONFLICT.value,
                            detail="integrity_conflict",
                        )
                    )
                    conflict += 1

    db.commit()
    return DraftCreateResponse(
        campaign_id=campaign_id,
        sequence_id=seq.id,
        created_count=created,
        matched_existing_count=matched,
        skipped_count=skipped,
        conflict_count=conflict,
        failed_count=failed,
        results=results,
    )


# ----- Messages list / get -----


def list_messages(
    db: Session,
    campaign_id: UUID,
    *,
    status: str | None = None,
    approval_decision: str | None = None,
    sequence_id: UUID | None = None,
    lead_id: UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> OutreachMessageListResponse:
    _get_campaign(db, campaign_id)
    if limit < 1 or limit > MAX_OUTREACH_LIST_LIMIT:
        raise AppError(
            f"limit must be 1–{MAX_OUTREACH_LIST_LIMIT}",
            status_code=422,
            code="invalid_limit",
        )
    if offset < 0:
        raise AppError("offset must be >= 0", status_code=422, code="invalid_offset")

    if status is not None:
        try:
            OutreachMessageStatus(status)
        except ValueError as exc:
            raise AppError("Invalid status", status_code=422, code="invalid_enum") from exc
    if approval_decision is not None:
        try:
            OutreachApprovalDecision(approval_decision)
        except ValueError as exc:
            raise AppError("Invalid approval_decision", status_code=422, code="invalid_enum") from exc

    filters = [OutreachMessage.campaign_id == campaign_id]
    if status:
        filters.append(OutreachMessage.status == status)
    if approval_decision:
        filters.append(OutreachMessage.approval_decision == approval_decision)
    if sequence_id:
        filters.append(OutreachMessage.sequence_id == sequence_id)
    if lead_id:
        filters.append(OutreachMessage.campaign_lead_id == lead_id)

    total = db.scalar(select(func.count()).select_from(OutreachMessage).where(*filters)) or 0
    stmt: Select = (
        select(OutreachMessage, Company.name)
        .join(CampaignLead, CampaignLead.id == OutreachMessage.campaign_lead_id)
        .join(Company, Company.id == CampaignLead.company_id)
        .where(*filters)
        .order_by(OutreachMessage.created_at.asc(), OutreachMessage.id.asc())
        .limit(limit)
        .offset(offset)
    )
    rows = db.execute(stmt).all()
    items = [_message_to_read(msg, company_name=cname) for msg, cname in rows]
    return OutreachMessageListResponse(items=items, total=total, limit=limit, offset=offset)


def get_message(db: Session, campaign_id: UUID, message_id: UUID) -> OutreachMessageRead:
    _get_campaign(db, campaign_id)
    row = db.execute(
        select(OutreachMessage, Company.name)
        .join(CampaignLead, CampaignLead.id == OutreachMessage.campaign_lead_id)
        .join(Company, Company.id == CampaignLead.company_id)
        .where(
            OutreachMessage.id == message_id,
            OutreachMessage.campaign_id == campaign_id,
        )
    ).first()
    if row is None:
        raise AppError("Message not found.", status_code=404, code="not_found")
    msg, cname = row
    return _message_to_read(msg, company_name=cname)


# ----- Approve / Reject / Reset -----


def approve_message(db: Session, campaign_id: UUID, message_id: UUID) -> OutreachMessageRead:
    _get_campaign(db, campaign_id)
    msg = db.get(OutreachMessage, message_id)
    if msg is None or msg.campaign_id != campaign_id:
        raise AppError("Message not found.", status_code=404, code="not_found")
    if not msg.is_test_data:
        raise AppError("Non-test message cannot be approved", status_code=409, code="not_test_data")
    validate_test_recipient(msg.recipient_email)

    lead = db.get(CampaignLead, msg.campaign_lead_id)
    if lead is None or lead.campaign_id != campaign_id:
        raise AppError("Lead not found.", status_code=404, code="not_found")
    if lead.review_decision != ReviewDecision.APPROVED.value:
        raise AppError("Lead is not APPROVED", status_code=409, code="lead_not_approved")
    if not lead.is_test_data:
        raise AppError("Lead is not test data", status_code=409, code="not_test_data")

    if msg.status == OutreachMessageStatus.SENT.value:
        raise AppError("Cannot approve a SENT message", status_code=409, code="terminal_sent")
    if msg.status == OutreachMessageStatus.SENDING.value:
        raise AppError("Cannot approve while SENDING", status_code=409, code="sending")
    if msg.status in {
        OutreachMessageStatus.FAILED.value,
        OutreachMessageStatus.BLOCKED.value,
    }:
        raise AppError(
            "FAILED/BLOCKED require reset workflow before approve",
            status_code=409,
            code="invalid_status",
        )

    # Idempotent approve
    if (
        msg.status == OutreachMessageStatus.APPROVED.value
        and msg.approval_decision == OutreachApprovalDecision.APPROVED.value
    ):
        return get_message(db, campaign_id, message_id)

    # Official transitions: DRAFT → APPROVED (REJECTED → use reset to DRAFT first)
    if msg.status != OutreachMessageStatus.DRAFT.value:
        raise AppError("Message cannot be approved in current status", status_code=409, code="invalid_status")

    now = _utcnow()
    msg.status = OutreachMessageStatus.APPROVED.value
    msg.approval_decision = OutreachApprovalDecision.APPROVED.value
    if msg.approved_at is None:
        msg.approved_at = now
    msg.approved_by = APPROVAL_AUDIT_MARKER
    msg.rejected_at = None
    msg.reject_note = None
    msg.error_message = None
    db.commit()
    return get_message(db, campaign_id, message_id)


def reject_message(
    db: Session,
    campaign_id: UUID,
    message_id: UUID,
    data: RejectMessageRequest | None = None,
) -> OutreachMessageRead:
    _get_campaign(db, campaign_id)
    msg = db.get(OutreachMessage, message_id)
    if msg is None or msg.campaign_id != campaign_id:
        raise AppError("Message not found.", status_code=404, code="not_found")
    if msg.status == OutreachMessageStatus.SENT.value:
        raise AppError("Cannot reject a SENT message", status_code=409, code="terminal_sent")
    if msg.status == OutreachMessageStatus.SENDING.value:
        raise AppError("Cannot reject while SENDING", status_code=409, code="sending")
    if msg.status in {
        OutreachMessageStatus.FAILED.value,
        OutreachMessageStatus.BLOCKED.value,
    }:
        raise AppError(
            "FAILED/BLOCKED cannot be rejected without recovery",
            status_code=409,
            code="invalid_status",
        )

    note = (data.note if data else None)
    if note is not None:
        note = note.strip()
        if note == "":
            note = None
    if note is not None and len(note) > MAX_OUTREACH_REJECT_NOTE:
        raise AppError("reject note too long", status_code=422, code="note_too_long")

    if (
        msg.status == OutreachMessageStatus.REJECTED.value
        and msg.approval_decision == OutreachApprovalDecision.REJECTED.value
    ):
        return get_message(db, campaign_id, message_id)

    if msg.status not in {
        OutreachMessageStatus.DRAFT.value,
        OutreachMessageStatus.APPROVED.value,
    }:
        raise AppError("Message cannot be rejected in current status", status_code=409, code="invalid_status")

    now = _utcnow()
    msg.status = OutreachMessageStatus.REJECTED.value
    msg.approval_decision = OutreachApprovalDecision.REJECTED.value
    if msg.rejected_at is None:
        msg.rejected_at = now
    if note is not None:
        msg.reject_note = note
    db.commit()
    return get_message(db, campaign_id, message_id)


def reset_message_to_draft(db: Session, campaign_id: UUID, message_id: UUID) -> OutreachMessageRead:
    """Reset APPROVED/REJECTED back to DRAFT. Not allowed for SENT/SENDING/FAILED/BLOCKED."""
    _get_campaign(db, campaign_id)
    msg = db.get(OutreachMessage, message_id)
    if msg is None or msg.campaign_id != campaign_id:
        raise AppError("Message not found.", status_code=404, code="not_found")
    if msg.status not in {
        OutreachMessageStatus.APPROVED.value,
        OutreachMessageStatus.REJECTED.value,
        OutreachMessageStatus.DRAFT.value,
    }:
        raise AppError(
            "Reset to draft only from DRAFT/APPROVED/REJECTED",
            status_code=409,
            code="invalid_status",
        )
    if msg.status == OutreachMessageStatus.DRAFT.value:
        return get_message(db, campaign_id, message_id)
    msg.status = OutreachMessageStatus.DRAFT.value
    msg.approval_decision = OutreachApprovalDecision.PENDING.value
    msg.approved_at = None
    msg.approved_by = None
    msg.rejected_at = None
    msg.reject_note = None
    db.commit()
    return get_message(db, campaign_id, message_id)


# ----- Send -----
#
# Delivery guarantee (Stage 4 / TestEmailProvider):
# - At-most-once provider call per message idempotency_key.
# - Flow: STOP check → claim APPROVED→SENDING → reserve PENDING SendAttempt
#   (unique key) → provider.send(key) → SUCCESS + SENT.
# - SENT only when provider success is confirmed and persisted.
# - Stale PENDING (crash with unknown outcome) → FAILED + DELIVERY_OUTCOME_UNKNOWN;
#   never auto-SENT; never auto-resend provider.
# - FAILED/BLOCKED are terminal for auto-send (no silent retry).


def send_message(db: Session, campaign_id: UUID, message_id: UUID) -> OutreachMessage:
    """Explicit test send via TestEmailProvider only."""
    _get_campaign(db, campaign_id)
    msg = db.get(OutreachMessage, message_id)
    if msg is None or msg.campaign_id != campaign_id:
        raise AppError("Message not found.", status_code=404, code="not_found")
    return _send_claimed_message(db, msg)


def send_message_by_id(db: Session, message_id: UUID) -> OutreachMessage:
    """Celery entry: send by message id only (campaign from row)."""
    msg = db.get(OutreachMessage, message_id)
    if msg is None:
        raise AppError("Message not found.", status_code=404, code="not_found")
    return _send_claimed_message(db, msg)


def _get_attempt_by_key(db: Session, key: str) -> SendAttempt | None:
    return db.scalars(select(SendAttempt).where(SendAttempt.idempotency_key == key)).first()


def _finalize_sent_from_attempt(
    db: Session,
    msg: OutreachMessage,
    attempt: SendAttempt,
) -> OutreachMessage:
    """Only called when SendAttempt is already SUCCESS (confirmed provider + DB)."""
    sent_at = attempt.completed_at or _utcnow()
    if msg.sent_at is not None:
        sent_at = msg.sent_at
    db.execute(
        update(OutreachMessage)
        .where(OutreachMessage.id == msg.id)
        .values(
            status=OutreachMessageStatus.SENT.value,
            sent_at=sent_at,
            error_message=None,
        )
    )
    db.commit()
    db.refresh(msg)
    return msg


def _fail_unknown_delivery(
    db: Session,
    msg: OutreachMessage,
    attempt: SendAttempt,
) -> OutreachMessage:
    """Stale PENDING: outcome unknown — FAILED, no provider retry, never SENT."""
    now = _utcnow()
    attempt.status = SendAttemptStatus.FAILED.value
    attempt.completed_at = now
    attempt.safe_error_message = DELIVERY_OUTCOME_UNKNOWN
    attempt.provider_message_id = None
    db.execute(
        update(OutreachMessage)
        .where(OutreachMessage.id == msg.id)
        .values(
            status=OutreachMessageStatus.FAILED.value,
            failed_at=now,
            error_message=DELIVERY_OUTCOME_UNKNOWN,
        )
    )
    db.commit()
    db.refresh(msg)
    logger.warning(
        "Outreach delivery outcome unknown message_id=%s code=%s",
        msg.id,
        DELIVERY_OUTCOME_UNKNOWN,
    )
    return msg


def _recover_sending(db: Session, msg: OutreachMessage) -> OutreachMessage:
    """Safe recovery for SENDING — never calls provider a second time when a slot exists."""
    attempt_key = send_idempotency_key(msg.id)
    attempt = _get_attempt_by_key(db, attempt_key)
    if attempt is None:
        # Claimed but crashed before outbox reserve — continue send once.
        return _deliver_after_claim(db, msg)

    if attempt.status == SendAttemptStatus.SUCCESS.value:
        return _finalize_sent_from_attempt(db, msg, attempt)

    if attempt.status == SendAttemptStatus.PENDING.value:
        now = _utcnow()
        attempted = attempt.attempted_at or now
        if attempted.tzinfo is None:
            attempted = attempted.replace(tzinfo=timezone.utc)
        age = now - attempted
        if age < SENDING_PENDING_STALE_AFTER:
            # Active send in another worker — do not steal the slot or call provider.
            raise AppError("Message is already SENDING", status_code=409, code="sending")
        # Stale PENDING: delivery unconfirmed — FAILED, not SENT; no auto-resend.
        return _fail_unknown_delivery(db, msg, attempt)

    if attempt.status == SendAttemptStatus.FAILED.value:
        db.execute(
            update(OutreachMessage)
            .where(OutreachMessage.id == msg.id)
            .values(
                status=OutreachMessageStatus.FAILED.value,
                failed_at=attempt.completed_at or _utcnow(),
                error_message=attempt.safe_error_message or "Send failed",
            )
        )
        db.commit()
        db.refresh(msg)
        return msg

    raise AppError("Message is already SENDING", status_code=409, code="sending")

def _reserve_pending_attempt(db: Session, msg: OutreachMessage, attempt_key: str) -> SendAttempt | None:
    """Insert PENDING outbox row. Returns None if unique key already taken."""
    now = _utcnow()
    nested = db.begin_nested()
    try:
        attempt = SendAttempt(
            message_id=msg.id,
            provider_name=ALLOWED_OUTREACH_PROVIDER,
            provider_message_id=None,
            status=SendAttemptStatus.PENDING.value,
            attempted_at=now,
            completed_at=None,
            idempotency_key=attempt_key,
            is_test_data=True,
        )
        db.add(attempt)
        db.flush()
        nested.commit()
        return attempt
    except IntegrityError:
        nested.rollback()
        return None


def _deliver_after_claim(db: Session, msg: OutreachMessage) -> OutreachMessage:
    """Reserve outbox → provider → SUCCESS/SENT (or FAILED). Caller already claimed SENDING."""
    from app.models.enums import ComplianceCheckContext
    from app.services import compliance_service
    from app.services.suppression_normalizer import normalize_email

    lead = db.get(CampaignLead, msg.campaign_lead_id)
    try:
        email_norm, _ = normalize_email(msg.recipient_email)
        domain_norm = email_norm.split("@", 1)[1]
    except AppError:
        email_norm, domain_norm = None, None
    lock_keys = compliance_service.message_compliance_lock_keys(
        campaign_id=msg.campaign_id,
        email=email_norm,
        domain=domain_norm,
        company_id=lead.company_id if lead else None,
        lead_id=msg.campaign_lead_id,
    )

    with compliance_service.compliance_locks(db, lock_keys):
        return _deliver_after_claim_locked(db, msg)


def _deliver_after_claim_locked(db: Session, msg: OutreachMessage) -> OutreachMessage:
    """Inner deliver path — caller must hold compliance advisory locks."""
    from app.models.enums import ComplianceCheckContext
    from app.services import compliance_service

    attempt_key = send_idempotency_key(msg.id)
    existing = _get_attempt_by_key(db, attempt_key)
    if existing is not None:
        if existing.status == SendAttemptStatus.SUCCESS.value:
            return _finalize_sent_from_attempt(db, msg, existing)
        if existing.status == SendAttemptStatus.PENDING.value:
            return _recover_sending(db, msg)
        if existing.status == SendAttemptStatus.FAILED.value:
            db.execute(
                update(OutreachMessage)
                .where(OutreachMessage.id == msg.id)
                .values(
                    status=OutreachMessageStatus.FAILED.value,
                    failed_at=existing.completed_at or _utcnow(),
                    error_message=existing.safe_error_message or "Send failed",
                )
            )
            db.commit()
            db.refresh(msg)
            return msg

    attempt = _reserve_pending_attempt(db, msg, attempt_key)
    if attempt is None:
        # Lost race on unique key — recover from existing row without provider.
        return _recover_sending(db, msg)

    provider = TestEmailProvider()
    assert provider.name == ALLOWED_OUTREACH_PROVIDER

    try:
        # Re-check STOP immediately before provider (kill switch flip race).
        if is_system_stopped():
            fail_time = _utcnow()
            attempt.status = SendAttemptStatus.FAILED.value
            attempt.completed_at = fail_time
            attempt.safe_error_message = "SYSTEM_STOP_ALL active"
            db.execute(
                update(OutreachMessage)
                .where(OutreachMessage.id == msg.id)
                .values(
                    status=OutreachMessageStatus.BLOCKED.value,
                    blocked_at=fail_time,
                    error_message="SYSTEM_STOP_ALL active",
                )
            )
            db.commit()
            db.refresh(msg)
            logger.info("Outreach send blocked after claim message_id=%s", msg.id)
            return msg

        # Final compliance gate under advisory locks (closes TOCTOU vs suppression).
        final = compliance_service.check_outreach_compliance(
            db,
            campaign_id=msg.campaign_id,
            message=msg,
            check_context=ComplianceCheckContext.EXPLICIT_SEND.value,
            persist_log=True,
        )
        if not final.allowed:
            fail_time = _utcnow()
            attempt.status = SendAttemptStatus.FAILED.value
            attempt.completed_at = fail_time
            attempt.safe_error_message = final.reason_code
            db.commit()
            compliance_service.apply_message_suppression_block(db, msg, final)
            db.refresh(msg)
            logger.info(
                "Outreach send blocked by compliance after claim message_id=%s",
                msg.id,
            )
            return msg

        result = provider.send(
            EmailMessage(
                to_address=msg.recipient_email,
                subject=msg.subject_rendered,
                body=msg.body_rendered,
                metadata={
                    "message_id": str(msg.id),
                    "idempotency_key": attempt_key,
                    "simulated": True,
                },
            )
        )
        completed = result.sent_at if result.sent_at.tzinfo else result.sent_at.replace(tzinfo=timezone.utc)
        attempt.status = SendAttemptStatus.SUCCESS.value
        attempt.provider_message_id = result.message_id
        attempt.completed_at = completed
        db.flush()
        db.execute(
            update(OutreachMessage)
            .where(OutreachMessage.id == msg.id)
            .values(
                status=OutreachMessageStatus.SENT.value,
                sent_at=completed,
                error_message=None,
            )
        )
        db.commit()
        db.refresh(msg)
        logger.info("Test outreach sent message_id=%s provider=%s", msg.id, provider.name)
        return msg
    except Exception as exc:  # noqa: BLE001 — map to FAILED safely
        safe = _safe_error(exc)
        fail_time = _utcnow()
        attempt.status = SendAttemptStatus.FAILED.value
        attempt.completed_at = fail_time
        attempt.safe_error_message = safe
        attempt.provider_message_id = None
        db.execute(
            update(OutreachMessage)
            .where(OutreachMessage.id == msg.id)
            .values(
                status=OutreachMessageStatus.FAILED.value,
                failed_at=fail_time,
                error_message=safe,
            )
        )
        db.commit()
        db.refresh(msg)
        logger.warning("Test outreach failed message_id=%s", msg.id)
        return msg


def _send_claimed_message(db: Session, msg: OutreachMessage) -> OutreachMessage:
    if not msg.is_test_data:
        raise AppError("Non-test message cannot be sent", status_code=409, code="not_test_data")

    db.refresh(msg)

    # Terminal SENT — idempotent no-op
    if msg.status == OutreachMessageStatus.SENT.value:
        return msg

    if msg.status == OutreachMessageStatus.BLOCKED.value:
        return msg

    if msg.status == OutreachMessageStatus.FAILED.value:
        raise AppError(
            "FAILED message cannot be sent without recovery",
            status_code=409,
            code="terminal_failed",
        )

    if msg.status == OutreachMessageStatus.SENDING.value:
        return _recover_sending(db, msg)

    if msg.status != OutreachMessageStatus.APPROVED.value:
        raise AppError("Message must be APPROVED before send", status_code=409, code="not_approved")

    validate_test_recipient(msg.recipient_email)

    lead = db.get(CampaignLead, msg.campaign_lead_id)
    if lead is None or lead.review_decision != ReviewDecision.APPROVED.value or not lead.is_test_data:
        raise AppError("Lead not eligible for send", status_code=409, code="lead_not_eligible")

    # Stage 6: advisory locks bind suppression mutations to this send until provider.
    from app.models.enums import ComplianceCheckContext
    from app.services import compliance_service
    from app.services.suppression_normalizer import normalize_email

    try:
        email_norm, _ = normalize_email(msg.recipient_email)
        domain_norm = email_norm.split("@", 1)[1]
    except AppError:
        email_norm, domain_norm = None, None
    lock_keys = compliance_service.message_compliance_lock_keys(
        campaign_id=msg.campaign_id,
        email=email_norm,
        domain=domain_norm,
        company_id=lead.company_id,
        lead_id=msg.campaign_lead_id,
    )

    with compliance_service.compliance_locks(db, lock_keys):
        # SYSTEM_STOP_ALL has priority over compliance ALLOWED
        if is_system_stopped():
            now = _utcnow()
            result = db.execute(
                update(OutreachMessage)
                .where(
                    OutreachMessage.id == msg.id,
                    OutreachMessage.status == OutreachMessageStatus.APPROVED.value,
                )
                .values(
                    status=OutreachMessageStatus.BLOCKED.value,
                    blocked_at=now,
                    error_message="SYSTEM_STOP_ALL active",
                )
            )
            db.commit()
            db.refresh(msg)
            if result.rowcount == 0:
                return msg
            logger.info("Outreach send blocked by SYSTEM_STOP_ALL message_id=%s", msg.id)
            return msg

        compliance = compliance_service.check_outreach_compliance(
            db,
            campaign_id=msg.campaign_id,
            message=msg,
            check_context=ComplianceCheckContext.EXPLICIT_SEND.value,
            persist_log=True,
        )
        if not compliance.allowed:
            return compliance_service.apply_message_suppression_block(db, msg, compliance)

        claim = db.execute(
            update(OutreachMessage)
            .where(
                OutreachMessage.id == msg.id,
                OutreachMessage.status == OutreachMessageStatus.APPROVED.value,
            )
            .values(status=OutreachMessageStatus.SENDING.value)
        )
        db.commit()
        if claim.rowcount == 0:
            db.refresh(msg)
            if msg.status == OutreachMessageStatus.SENT.value:
                return msg
            if msg.status == OutreachMessageStatus.SENDING.value:
                return _recover_sending(db, msg)
            if msg.status == OutreachMessageStatus.BLOCKED.value:
                return msg
            raise AppError(
                "Could not claim message for sending",
                status_code=409,
                code="claim_failed",
            )

        db.refresh(msg)

        # Post-claim re-check before outbox/provider (defense in depth)
        post = compliance_service.check_outreach_compliance(
            db,
            campaign_id=msg.campaign_id,
            message=msg,
            check_context=ComplianceCheckContext.EXPLICIT_SEND.value,
            persist_log=True,
        )
        if not post.allowed:
            return compliance_service.apply_message_suppression_block(db, msg, post)

        # Already holding compliance locks — avoid nested acquire here.
        return _deliver_after_claim_locked(db, msg)