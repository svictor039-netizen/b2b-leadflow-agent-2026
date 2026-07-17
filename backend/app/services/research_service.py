"""Stage 2 safe research pipeline — TestSourceAdapter only."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import (
    ALLOWED_RESEARCH_ADAPTERS,
    Company,
    CompanyLocation,
    CompanySourceRecord,
    CompanyStatus,
    DataSource,
    DataSourceType,
    ResearchItemOutcome,
    ResearchRun,
    ResearchRunStatus,
)
from app.providers.base import CompanyRecord
from app.providers.registry import get_source_adapter
from app.schemas.research import ResearchItemResult, ResearchRunCreate, ResearchRunRead
from app.security.stop_all import SystemStopAllError, assert_outbound_allowed
from app.services.dedup import (
    find_by_domain,
    find_by_source_external,
    merge_company_fields,
    resolve_match,
)
from app.services.normalize import normalize_domain_for_match, normalize_source_id
from app.services.sanitize import sanitize_payload

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = frozenset(
    {
        ResearchRunStatus.COMPLETED.value,
        ResearchRunStatus.FAILED.value,
        ResearchRunStatus.BLOCKED.value,
    }
)


def _ensure_test_data_source(db: Session, adapter_name: str) -> DataSource:
    source = db.scalar(select(DataSource).where(DataSource.name == adapter_name))
    if source is None:
        nested = db.begin_nested()
        try:
            source = DataSource(
                name=adapter_name,
                source_type=DataSourceType.TEST.value,
                base_url="https://test-source.example",
                enabled=True,
            )
            db.add(source)
            db.flush()
            nested.commit()
        except IntegrityError:
            nested.rollback()
            source = db.scalar(select(DataSource).where(DataSource.name == adapter_name))
            if source is None:
                raise
    return source


def _safe_payload(record: CompanyRecord, query: str) -> dict:
    """Normalized snapshot without secrets or personal emails."""
    snapshot = {
        "name": record.name,
        "domain": record.domain,
        "region": record.region,
        "niche": record.niche,
        "description": record.description,
        "website": record.website,
        "source_record_id": record.source_record_id,
        "source_url": record.source_url,
        "is_test_data": True,
        "query": query,
        "has_contact_email": bool(record.contact_email),
        # Intentionally omit contact_email / phone values.
    }
    return sanitize_payload(snapshot)


def _item_dict(
    *,
    outcome: ResearchItemOutcome,
    company: Company | None,
    record: CompanyRecord,
    reason: str | None,
) -> dict:
    return {
        "outcome": outcome.value,
        "company_id": str(company.id) if company else None,
        "company_name": company.name if company else record.name,
        "domain": company.domain if company else normalize_domain_for_match(record.domain),
        "source_record_id": record.source_record_id,
        "source_url": record.source_url,
        "reason": reason,
        "is_test_data": True,
    }


def _to_read(run: ResearchRun) -> ResearchRunRead:
    items: list[ResearchItemResult] = []
    for raw in run.result_items or []:
        items.append(ResearchItemResult.model_validate(raw))
    return ResearchRunRead(
        id=run.id,
        campaign_id=run.campaign_id,
        status=ResearchRunStatus(run.status),
        adapter=run.adapter,
        query=run.query,
        industry=run.industry,
        location=run.location,
        limit=run.limit,
        found_count=run.found_count,
        created_count=run.created_count,
        matched_count=run.matched_count,
        updated_count=run.updated_count,
        skipped_count=run.skipped_count,
        conflict_count=run.conflict_count,
        celery_task_id=run.celery_task_id,
        error_message=run.error_message,
        result_items=items,
        is_test_data=run.is_test_data,
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def create_research_run(db: Session, data: ResearchRunCreate) -> ResearchRun:
    adapter_name = (data.adapter or "").strip().lower()
    if adapter_name not in ALLOWED_RESEARCH_ADAPTERS:
        raise AppError(
            f"Adapter '{data.adapter}' is not allowed on Stage 2.",
            status_code=400,
            code="adapter_not_allowed",
        )
    if not data.query or not data.query.strip():
        raise AppError("query must not be empty", status_code=422, code="empty_query")

    industry = data.industry or data.query
    location = data.location or data.query

    run = ResearchRun(
        campaign_id=data.campaign_id,
        status=ResearchRunStatus.PENDING.value,
        adapter=adapter_name,
        query=data.query.strip(),
        industry=industry,
        location=location,
        limit=data.limit,
        is_test_data=True,
        result_items=[],
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def execute_research_run(db: Session, run_id: UUID) -> ResearchRunRead:
    """Execute research synchronously. Never calls EmailProvider. Idempotent for terminal runs."""
    run = db.get(ResearchRun, run_id)
    if run is None:
        raise AppError("Research run not found.", status_code=404, code="not_found")

    # Celery redelivery / double-submit: do not re-process finished runs.
    if run.status in _TERMINAL_STATUSES and run.finished_at is not None:
        return _to_read(run)

    try:
        assert_outbound_allowed("research run")
    except SystemStopAllError as exc:
        run.status = ResearchRunStatus.BLOCKED.value
        run.error_message = str(exc)
        run.finished_at = datetime.now(timezone.utc)
        if run.started_at is None:
            run.started_at = run.finished_at
        db.commit()
        db.refresh(run)
        return _to_read(run)

    run.status = ResearchRunStatus.RUNNING.value
    run.started_at = datetime.now(timezone.utc)
    run.error_message = None
    db.commit()

    try:
        adapter = get_source_adapter(run.adapter)
        data_source = _ensure_test_data_source(db, adapter.name)
        records = adapter.search(
            niche=run.industry or run.query,
            region=run.location or run.query,
            limit=run.limit,
        )

        items: list[dict] = []
        created = matched = updated = skipped = conflicts = 0

        for record in records:
            item = _ingest_record(db, run, data_source, record)
            items.append(item)
            outcome = item["outcome"]
            if outcome == ResearchItemOutcome.CREATED.value:
                created += 1
            elif outcome == ResearchItemOutcome.MATCHED_EXISTING.value:
                matched += 1
            elif outcome == ResearchItemOutcome.UPDATED.value:
                updated += 1
            elif outcome == ResearchItemOutcome.SKIPPED.value:
                skipped += 1
            elif outcome == ResearchItemOutcome.CONFLICT.value:
                conflicts += 1

        run.found_count = len(records)
        run.created_count = created
        run.matched_count = matched
        run.updated_count = updated
        run.skipped_count = skipped
        run.conflict_count = conflicts
        run.result_items = items
        run.status = ResearchRunStatus.COMPLETED.value
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(run)
        logger.info(
            "Research run completed",
            extra={
                "research_run_id": str(run.id),
                "found_count": run.found_count,
                "companies_created": created,
                "adapter_name": run.adapter,
            },
        )
        return _to_read(run)
    except AppError:
        run.status = ResearchRunStatus.FAILED.value
        run.error_message = "Research validation error."
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(run)
        raise
    except Exception as exc:
        logger.exception("Research run failed", extra={"research_run_id": str(run_id)})
        # Prefer marking FAILED on the same session. Avoid session.rollback() here:
        # under the test SAVEPOINT fixture a full rollback wipes already-committed
        # PENDING/RUNNING rows. Nested savepoints already isolate ingest races.
        try:
            run = db.get(ResearchRun, run_id)
            if run is not None:
                run.status = ResearchRunStatus.FAILED.value
                run.error_message = "Research adapter error."
                run.finished_at = datetime.now(timezone.utc)
                db.commit()
                db.refresh(run)
        except Exception:
            logger.exception(
                "Could not persist FAILED status",
                extra={"research_run_id": str(run_id)},
            )
            try:
                db.rollback()
            except Exception:
                pass
        raise AppError(
            "Research run failed due to an adapter error.",
            status_code=500,
            code="research_failed",
        ) from exc


def _create_company_atomic(db: Session, record: CompanyRecord) -> tuple[Company, ResearchItemOutcome]:
    """Insert company; on unique domain race, re-read existing row."""
    domain = normalize_domain_for_match(record.domain)
    nested = db.begin_nested()
    try:
        company = Company(
            name=record.name.strip(),
            domain=domain,
            website=(record.website or None),
            description=record.description or None,
            status=CompanyStatus.UNKNOWN.value,
            source_confidence=0.5,
        )
        db.add(company)
        db.flush()
        if record.region:
            db.add(
                CompanyLocation(
                    company_id=company.id,
                    region=record.region,
                    is_primary=True,
                )
            )
            db.flush()
        # Stage 2: do NOT persist contact_email from adapter into contacts.
        nested.commit()
        return company, ResearchItemOutcome.CREATED
    except IntegrityError:
        nested.rollback()
        existing = find_by_domain(db, domain) if domain else None
        if existing is None:
            raise
        return existing, ResearchItemOutcome.MATCHED_EXISTING


def _ensure_source_record(
    db: Session,
    *,
    run: ResearchRun,
    data_source: DataSource,
    company: Company,
    record: CompanyRecord,
    collected_at: datetime,
    outcome: ResearchItemOutcome,
) -> ResearchItemOutcome:
    external_id = normalize_source_id(record.source_record_id)
    existing_src = find_by_source_external(db, data_source.id, external_id)

    if existing_src is not None:
        if existing_src.company_id != company.id:
            # Same source record already linked to another company — conflict
            return ResearchItemOutcome.CONFLICT
        existing_src.research_run_id = run.id
        existing_src.query_text = run.query
        existing_src.is_test_data = True
        if record.source_url and not existing_src.source_url:
            existing_src.source_url = record.source_url
        if not existing_src.raw_payload:
            existing_src.raw_payload = _safe_payload(record, run.query)
        else:
            existing_src.raw_payload = sanitize_payload(existing_src.raw_payload)
        if outcome in {ResearchItemOutcome.MATCHED_EXISTING, ResearchItemOutcome.CREATED}:
            return ResearchItemOutcome.SKIPPED
        return outcome

    nested = db.begin_nested()
    try:
        db.add(
            CompanySourceRecord(
                company_id=company.id,
                data_source_id=data_source.id,
                research_run_id=run.id,
                external_id=external_id,
                source_url=record.source_url,
                query_text=run.query,
                is_test_data=True,
                raw_payload=_safe_payload(record, run.query),
                collected_at=collected_at,
            )
        )
        db.flush()
        nested.commit()
    except IntegrityError:
        nested.rollback()
        raced = find_by_source_external(db, data_source.id, external_id)
        if raced is None:
            raise
        if raced.company_id != company.id:
            return ResearchItemOutcome.CONFLICT
        raced.research_run_id = run.id
        raced.query_text = run.query
        return ResearchItemOutcome.SKIPPED
    return outcome


def _ingest_record(
    db: Session,
    run: ResearchRun,
    data_source: DataSource,
    record: CompanyRecord,
) -> dict:
    collected_at = datetime.now(timezone.utc)
    match = resolve_match(db, record, data_source)

    if match.outcome_hint == ResearchItemOutcome.CONFLICT:
        return _item_dict(
            outcome=ResearchItemOutcome.CONFLICT,
            company=match.company,
            record=record,
            reason=match.reason,
        )

    company = match.company
    outcome = match.outcome_hint

    if company is None:
        company, outcome = _create_company_atomic(db, record)
    else:
        incoming_domain = normalize_domain_for_match(record.domain)
        # Filling a blank domain must not steal another company's unique domain.
        if incoming_domain and not company.domain:
            other = find_by_domain(db, incoming_domain)
            if other is not None and other.id != company.id:
                return _item_dict(
                    outcome=ResearchItemOutcome.CONFLICT,
                    company=company,
                    record=record,
                    reason="domain_owned_by_other",
                )
        nested = db.begin_nested()
        try:
            changed = merge_company_fields(company, record)
            db.flush()
            nested.commit()
        except IntegrityError:
            nested.rollback()
            return _item_dict(
                outcome=ResearchItemOutcome.CONFLICT,
                company=company,
                record=record,
                reason="domain_unique_conflict",
            )
        if changed:
            outcome = ResearchItemOutcome.UPDATED
        else:
            outcome = ResearchItemOutcome.MATCHED_EXISTING

    outcome = _ensure_source_record(
        db,
        run=run,
        data_source=data_source,
        company=company,
        record=record,
        collected_at=collected_at,
        outcome=outcome,
    )

    if outcome == ResearchItemOutcome.CONFLICT:
        return _item_dict(
            outcome=ResearchItemOutcome.CONFLICT,
            company=company,
            record=record,
            reason="source_record_company_mismatch",
        )

    return _item_dict(outcome=outcome, company=company, record=record, reason=match.reason)


def get_research_run(db: Session, run_id: UUID) -> ResearchRunRead:
    run = db.get(ResearchRun, run_id)
    if run is None:
        raise AppError("Research run not found.", status_code=404, code="not_found")
    return _to_read(run)


def list_research_runs(
    db: Session,
    *,
    status: str | None = None,
    limit: int = 20,
) -> list[ResearchRunRead]:
    stmt = select(ResearchRun).order_by(ResearchRun.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(ResearchRun.status == status)
    return [_to_read(run) for run in db.scalars(stmt).all()]


def start_research(db: Session, data: ResearchRunCreate) -> ResearchRunRead:
    run = create_research_run(db, data)
    if data.async_mode:
        from app.workers.tasks import run_research_task

        async_result = run_research_task.delay(str(run.id))
        run.celery_task_id = async_result.id
        db.commit()
        db.refresh(run)
        return _to_read(run)
    return execute_research_run(db, run.id)
