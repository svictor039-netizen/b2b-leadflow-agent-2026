"""Stage 3 safe lead qualification — deterministic scoring, no email."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import AppError
from app.models import (
    Campaign,
    CampaignLead,
    CampaignLeadStatus,
    Company,
    CompanySourceRecord,
    LeadScoreSnapshot,
    QualificationItemOutcome,
    QualificationRun,
    QualificationRunStatus,
    QualificationStatus,
    ResearchRun,
    ResearchRunStatus,
    ReviewDecision,
    SCORING_VERSION,
)
from app.models.enums import MAX_REVIEW_NOTE_LENGTH
from app.schemas.qualification import (
    LeadReviewRequest,
    QualificationLeadListResponse,
    QualificationLeadRead,
    QualificationRunCreate,
    QualificationRunRead,
)
from app.security.stop_all import SystemStopAllError, assert_outbound_allowed
from app.services.sanitize import sanitize_payload
from app.services.scoring import score_company

logger = logging.getLogger(__name__)

_TERMINAL = frozenset(
    {
        QualificationRunStatus.COMPLETED.value,
        QualificationRunStatus.FAILED.value,
        QualificationRunStatus.BLOCKED.value,
    }
)

# Mid-run failure semantics (Stage 3): ALL-OR-NOTHING for the processing
# transaction. On error, uncommitted lead/snapshot work is rolled back, then the
# run is marked FAILED in a separate transaction. Retry = new QualificationRun
# (unique campaign+company / run+snapshot keep data safe). FAILED is terminal.


def _to_run_read(run: QualificationRun) -> QualificationRunRead:
    return QualificationRunRead(
        id=run.id,
        campaign_id=run.campaign_id,
        research_run_id=run.research_run_id,
        status=QualificationRunStatus(run.status),
        scoring_version=run.scoring_version,
        found_count=run.found_count,
        created_leads_count=run.created_leads_count,
        matched_leads_count=run.matched_leads_count,
        scored_count=run.scored_count,
        qualified_count=run.qualified_count,
        review_count=run.review_count,
        disqualified_count=run.disqualified_count,
        conflict_count=run.conflict_count,
        skipped_count=run.skipped_count,
        celery_task_id=run.celery_task_id,
        error_message=run.error_message,
        is_test_data=run.is_test_data,
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _lead_read(lead: CampaignLead) -> QualificationLeadRead:
    company = lead.company
    return QualificationLeadRead(
        id=lead.id,
        campaign_id=lead.campaign_id,
        company_id=lead.company_id,
        company_name=company.name if company else None,
        company_domain=company.domain if company else None,
        qualification_score=lead.qualification_score,
        qualification_status=lead.qualification_status,
        review_decision=lead.review_decision,
        score_version=lead.score_version,
        scored_at=lead.scored_at,
        score_reasons=lead.score_reasons or [],
        source_research_run_id=lead.source_research_run_id,
        is_test_data=lead.is_test_data,
        reviewed_at=lead.reviewed_at,
        review_note=lead.review_note,
        status=lead.status,
        approved_for_email=lead.approved_for_email,
        created_at=lead.created_at,
        updated_at=lead.updated_at,
    )


def create_qualification_run(db: Session, data: QualificationRunCreate) -> QualificationRun:
    campaign = db.get(Campaign, data.campaign_id)
    if campaign is None:
        raise AppError("Campaign not found.", status_code=404, code="not_found")

    research = db.get(ResearchRun, data.research_run_id)
    if research is None:
        raise AppError("Research run not found.", status_code=404, code="not_found")

    if research.status != ResearchRunStatus.COMPLETED.value:
        raise AppError(
            "Research run must be COMPLETED before qualification.",
            status_code=409,
            code="research_not_completed",
        )
    if not research.is_test_data:
        raise AppError(
            "Only test research runs are allowed on Stage 3.",
            status_code=400,
            code="non_test_research",
        )
    if research.campaign_id is not None and research.campaign_id != data.campaign_id:
        raise AppError(
            "Research run is linked to a different campaign.",
            status_code=409,
            code="research_campaign_mismatch",
        )

    run = QualificationRun(
        campaign_id=data.campaign_id,
        research_run_id=data.research_run_id,
        status=QualificationRunStatus.PENDING.value,
        scoring_version=SCORING_VERSION,
        is_test_data=True,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _companies_from_research(db: Session, research_run_id: UUID) -> list[Company]:
    """Companies linked ONLY via provenance for this research_run_id, stable order."""
    company_ids = sorted(
        {
            cid
            for cid in db.scalars(
                select(CompanySourceRecord.company_id).where(
                    CompanySourceRecord.research_run_id == research_run_id
                )
            ).all()
        },
        key=str,
    )
    if not company_ids:
        return []
    return list(
        db.scalars(
            select(Company)
            .where(Company.id.in_(company_ids))
            .options(selectinload(Company.locations), selectinload(Company.source_records))
            .order_by(Company.id)
        ).all()
    )


def _provenance_for_run(
    company: Company,
    research_run_id: UUID,
) -> list[CompanySourceRecord]:
    records = [
        r for r in (company.source_records or []) if r.research_run_id == research_run_id
    ]
    records.sort(key=lambda r: (str(r.data_source_id), r.external_id or "", str(r.id)))
    return records


def _has_domain_conflict(company: Company, provenance: list[CompanySourceRecord]) -> bool:
    company_domain = (company.domain or "").lower().rstrip(".")
    if not company_domain:
        return False
    for rec in provenance:
        payload = rec.raw_payload or {}
        pdata = payload.get("domain")
        if not pdata:
            continue
        if str(pdata).lower().rstrip(".") != company_domain:
            return True
    return False


def _get_or_create_lead(
    db: Session,
    *,
    campaign: Campaign,
    company: Company,
    research_run_id: UUID,
) -> tuple[CampaignLead, QualificationItemOutcome]:
    existing = db.scalar(
        select(CampaignLead).where(
            CampaignLead.campaign_id == campaign.id,
            CampaignLead.company_id == company.id,
        )
    )
    if existing is not None:
        # Never wipe review fields; only fill blank provenance link.
        if not existing.source_research_run_id:
            existing.source_research_run_id = research_run_id
        existing.is_test_data = True
        return existing, QualificationItemOutcome.MATCHED_EXISTING

    lead_count = db.scalar(
        select(func.count()).select_from(CampaignLead).where(CampaignLead.campaign_id == campaign.id)
    ) or 0
    if lead_count >= campaign.max_companies:
        raise AppError("campaign_full", status_code=400, code="campaign_full")

    nested = db.begin_nested()
    try:
        lead = CampaignLead(
            campaign_id=campaign.id,
            company_id=company.id,
            status=CampaignLeadStatus.SCORED.value,
            approved_for_research=False,
            approved_for_email=False,
            source_research_run_id=research_run_id,
            is_test_data=True,
            review_decision=ReviewDecision.PENDING.value,
        )
        db.add(lead)
        db.flush()
        nested.commit()
        return lead, QualificationItemOutcome.CREATED
    except IntegrityError:
        nested.rollback()
        raced = db.scalar(
            select(CampaignLead).where(
                CampaignLead.campaign_id == campaign.id,
                CampaignLead.company_id == company.id,
            )
        )
        if raced is None:
            raise
        if not raced.source_research_run_id:
            raced.source_research_run_id = research_run_id
        raced.is_test_data = True
        return raced, QualificationItemOutcome.MATCHED_EXISTING


def _ensure_snapshot(
    db: Session,
    *,
    run: QualificationRun,
    lead: CampaignLead,
    score: int,
    status: str,
    reasons: list[dict],
    input_snapshot: dict,
) -> bool:
    existing = db.scalar(
        select(LeadScoreSnapshot).where(
            LeadScoreSnapshot.qualification_run_id == run.id,
            LeadScoreSnapshot.campaign_lead_id == lead.id,
        )
    )
    if existing is not None:
        return False

    nested = db.begin_nested()
    try:
        db.add(
            LeadScoreSnapshot(
                qualification_run_id=run.id,
                campaign_lead_id=lead.id,
                score=score,
                scoring_version=run.scoring_version,
                qualification_status=status,
                reasons=reasons,
                input_snapshot=sanitize_payload(input_snapshot),
                is_test_data=True,
            )
        )
        db.flush()
        nested.commit()
        return True
    except IntegrityError:
        nested.rollback()
        return False


def _claim_pending_run(db: Session, run_id: UUID) -> QualificationRun | None:
    """Atomically PENDING → RUNNING. Only one worker wins (rowcount == 1)."""
    now = datetime.now(timezone.utc)
    result = db.execute(
        update(QualificationRun)
        .where(
            QualificationRun.id == run_id,
            QualificationRun.status == QualificationRunStatus.PENDING.value,
        )
        .values(
            status=QualificationRunStatus.RUNNING.value,
            started_at=now,
            error_message=None,
        )
    )
    db.commit()
    if result.rowcount != 1:
        return None
    return db.get(QualificationRun, run_id)


def _block_pending_run(db: Session, run_id: UUID, message: str) -> QualificationRun | None:
    """Atomically PENDING → BLOCKED when SYSTEM_STOP_ALL is on."""
    now = datetime.now(timezone.utc)
    result = db.execute(
        update(QualificationRun)
        .where(
            QualificationRun.id == run_id,
            QualificationRun.status == QualificationRunStatus.PENDING.value,
        )
        .values(
            status=QualificationRunStatus.BLOCKED.value,
            error_message=message,
            finished_at=now,
            started_at=now,
        )
    )
    db.commit()
    if result.rowcount != 1:
        return None
    return db.get(QualificationRun, run_id)


def _mark_failed(db: Session, run_id: UUID, message: str) -> None:
    """Persist FAILED after processing rollback (separate transaction)."""
    now = datetime.now(timezone.utc)
    db.execute(
        update(QualificationRun)
        .where(QualificationRun.id == run_id)
        .values(
            status=QualificationRunStatus.FAILED.value,
            error_message=message,
            finished_at=now,
        )
    )
    db.commit()


def execute_qualification_run(db: Session, run_id: UUID) -> QualificationRunRead:
    run = db.get(QualificationRun, run_id)
    if run is None:
        raise AppError("Qualification run not found.", status_code=404, code="not_found")

    # Terminal short-circuit (COMPLETED / FAILED / BLOCKED).
    if run.status in _TERMINAL and run.finished_at is not None:
        return _to_run_read(run)

    # RUNNING without recovery: do not re-enter (second Celery delivery).
    if run.status == QualificationRunStatus.RUNNING.value:
        return _to_run_read(run)

    # Kill switch immediately before claim — no scoring / lead creation.
    try:
        assert_outbound_allowed("qualification run")
    except SystemStopAllError as exc:
        blocked = _block_pending_run(db, run_id, str(exc))
        if blocked is not None:
            return _to_run_read(blocked)
        run = db.get(QualificationRun, run_id)
        if run is None:
            raise AppError("Qualification run not found.", status_code=404, code="not_found")
        return _to_run_read(run)

    claimed = _claim_pending_run(db, run_id)
    if claimed is None:
        run = db.get(QualificationRun, run_id)
        if run is None:
            raise AppError("Qualification run not found.", status_code=404, code="not_found")
        return _to_run_read(run)
    run = claimed

    # All-or-nothing processing inside a SAVEPOINT so failure does not require
    # session.rollback() (which would wipe outer test transactions / claim).
    nested = db.begin_nested()
    try:
        campaign = db.get(Campaign, run.campaign_id)
        research = db.get(ResearchRun, run.research_run_id)
        if campaign is None or research is None:
            raise AppError("Campaign or research run missing.", status_code=404, code="not_found")
        if research.status != ResearchRunStatus.COMPLETED.value or not research.is_test_data:
            raise AppError(
                "Research run is not eligible for qualification.",
                status_code=409,
                code="research_not_eligible",
            )
        if research.campaign_id is not None and research.campaign_id != run.campaign_id:
            raise AppError(
                "Research run is linked to a different campaign.",
                status_code=409,
                code="research_campaign_mismatch",
            )

        companies = _companies_from_research(db, run.research_run_id)
        created = matched = scored = qualified = review_n = disqualified = conflicts = skipped = 0

        for company in companies:
            provenance = _provenance_for_run(company, run.research_run_id)
            has_conflict = _has_domain_conflict(company, provenance)

            try:
                lead, outcome = _get_or_create_lead(
                    db,
                    campaign=campaign,
                    company=company,
                    research_run_id=run.research_run_id,
                )
            except AppError as exc:
                if exc.code == "campaign_full":
                    skipped += 1
                    continue
                raise

            if outcome == QualificationItemOutcome.CREATED:
                created += 1
            else:
                matched += 1

            result = score_company(
                campaign=campaign,
                company=company,
                provenance_records=provenance,
                has_domain_conflict=has_conflict,
            )
            reasons = [r.as_dict() for r in result.reasons]

            # Update score fields only — never clear review_decision / review_note.
            lead.qualification_score = result.score
            lead.qualification_status = result.qualification_status.value
            lead.score_version = result.scoring_version
            lead.scored_at = datetime.now(timezone.utc)
            lead.score_reasons = reasons
            lead.source_research_run_id = lead.source_research_run_id or run.research_run_id
            lead.is_test_data = True
            if lead.review_decision == ReviewDecision.PENDING.value and lead.status in {
                CampaignLeadStatus.NEW.value,
                CampaignLeadStatus.ENRICHED.value,
            }:
                lead.status = CampaignLeadStatus.SCORED.value
            db.flush()

            _ensure_snapshot(
                db,
                run=run,
                lead=lead,
                score=result.score,
                status=result.qualification_status.value,
                reasons=reasons,
                input_snapshot=result.input_snapshot,
            )

            scored += 1
            if result.qualification_status == QualificationStatus.QUALIFIED:
                qualified += 1
            elif result.qualification_status == QualificationStatus.REVIEW:
                review_n += 1
            else:
                disqualified += 1

            if has_conflict:
                conflicts += 1

        # found = created + matched + skipped (conflict_count is a scored subset flag)
        run.found_count = len(companies)
        run.created_leads_count = created
        run.matched_leads_count = matched
        run.scored_count = scored
        run.qualified_count = qualified
        run.review_count = review_n
        run.disqualified_count = disqualified
        run.conflict_count = conflicts
        run.skipped_count = skipped
        run.status = QualificationRunStatus.COMPLETED.value
        run.finished_at = datetime.now(timezone.utc)
        db.flush()
        nested.commit()
        db.commit()
        db.refresh(run)
        logger.info(
            "Qualification run completed",
            extra={
                "qualification_run_id": str(run.id),
                "scored_count": scored,
                "created_leads": created,
            },
        )
        return _to_run_read(run)
    except AppError:
        nested.rollback()
        _mark_failed(db, run_id, "Qualification validation error.")
        raise
    except Exception as exc:
        logger.exception(
            "Qualification run failed",
            extra={"qualification_run_id": str(run_id)},
        )
        try:
            nested.rollback()
            _mark_failed(db, run_id, "Qualification scoring error.")
        except Exception:
            logger.exception("Could not persist FAILED status for qualification run")
        raise AppError(
            "Qualification run failed due to a scoring error.",
            status_code=500,
            code="qualification_failed",
        ) from exc


def start_qualification(db: Session, data: QualificationRunCreate) -> QualificationRunRead:
    run = create_qualification_run(db, data)
    if data.async_mode:
        from app.workers.tasks import run_qualification_task

        # Task still respects SYSTEM_STOP_ALL inside execute (cannot bypass).
        async_result = run_qualification_task.delay(str(run.id))
        run.celery_task_id = async_result.id
        db.commit()
        db.refresh(run)
        return _to_run_read(run)
    return execute_qualification_run(db, run.id)


def get_qualification_run(db: Session, run_id: UUID) -> QualificationRunRead:
    run = db.get(QualificationRun, run_id)
    if run is None:
        raise AppError("Qualification run not found.", status_code=404, code="not_found")
    return _to_run_read(run)


def list_campaign_leads(
    db: Session,
    campaign_id: UUID,
    *,
    qualification_status: str | None = None,
    review_decision: str | None = None,
    min_score: int | None = None,
    max_score: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> QualificationLeadListResponse:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise AppError("Campaign not found.", status_code=404, code="not_found")

    if min_score is not None and (min_score < 0 or min_score > 100):
        raise AppError("min_score must be 0–100", status_code=422, code="invalid_score_filter")
    if max_score is not None and (max_score < 0 or max_score > 100):
        raise AppError("max_score must be 0–100", status_code=422, code="invalid_score_filter")
    if min_score is not None and max_score is not None and min_score > max_score:
        raise AppError("min_score cannot exceed max_score", status_code=422, code="invalid_score_filter")

    filters = [CampaignLead.campaign_id == campaign_id]
    if qualification_status:
        filters.append(CampaignLead.qualification_status == qualification_status)
    if review_decision:
        filters.append(CampaignLead.review_decision == review_decision)
    if min_score is not None:
        filters.append(CampaignLead.qualification_score >= min_score)
    if max_score is not None:
        filters.append(CampaignLead.qualification_score <= max_score)

    total = db.scalar(select(func.count()).select_from(CampaignLead).where(*filters)) or 0
    leads = list(
        db.scalars(
            select(CampaignLead)
            .where(*filters)
            .options(selectinload(CampaignLead.company))
            .order_by(
                CampaignLead.qualification_score.desc().nullslast(),
                CampaignLead.id.asc(),
            )
            .offset(offset)
            .limit(limit)
        ).all()
    )
    return QualificationLeadListResponse(
        items=[_lead_read(lead) for lead in leads],
        total=total,
        limit=limit,
        offset=offset,
    )


def review_lead(
    db: Session,
    campaign_id: UUID,
    lead_id: UUID,
    data: LeadReviewRequest,
) -> QualificationLeadRead:
    """Manual local classification. Allowed under SYSTEM_STOP_ALL (no outbound)."""
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise AppError("Campaign not found.", status_code=404, code="not_found")

    lead = db.scalar(
        select(CampaignLead)
        .where(CampaignLead.id == lead_id, CampaignLead.campaign_id == campaign_id)
        .options(selectinload(CampaignLead.company))
    )
    if lead is None:
        raise AppError("Lead not found for this campaign.", status_code=404, code="not_found")

    # Idempotent identical decision — do not bump reviewed_at.
    same_note = (data.note or None) == (lead.review_note or None)
    if lead.review_decision == data.decision.value and same_note:
        return _lead_read(lead)

    previous_score = lead.qualification_score
    previous_qstatus = lead.qualification_status

    lead.review_decision = data.decision.value
    lead.reviewed_at = datetime.now(timezone.utc)
    if data.note is not None:
        lead.review_note = data.note.strip()[:MAX_REVIEW_NOTE_LENGTH] or None
    # Score / qualification_status never changed by review.
    lead.qualification_score = previous_score
    lead.qualification_status = previous_qstatus

    if data.decision == ReviewDecision.APPROVED:
        lead.status = CampaignLeadStatus.APPROVED.value
    elif data.decision == ReviewDecision.REJECTED:
        lead.status = CampaignLeadStatus.REJECTED.value
    elif data.decision == ReviewDecision.PENDING:
        if lead.qualification_status:
            lead.status = CampaignLeadStatus.SCORED.value
        else:
            lead.status = CampaignLeadStatus.NEW.value

    db.commit()
    db.refresh(lead)
    return _lead_read(lead)
