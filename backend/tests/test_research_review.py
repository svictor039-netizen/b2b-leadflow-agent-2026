"""Stage 2 review hardening tests — races, sanitization, statuses, API edges."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import sessionmaker

from app.models import Company, CompanySourceRecord, Contact, ResearchRun, ResearchRunStatus
from app.models.enums import ResearchItemOutcome
from app.providers.base import CompanyRecord
from app.schemas.research import ResearchRunCreate
from app.services.research_service import (
    _create_company_atomic,
    _safe_payload,
    create_research_run,
    execute_research_run,
    start_research,
)
from app.services.sanitize import sanitize_payload


def test_sanitize_payload_nested_mixed_case() -> None:
    raw = {
        "Name": "Acme",
        "Email": "person@example.com",
        "nested": {
            "API_KEY": "secret-123",
            "list": [{"Password": "x"}, {"ok": 1}],
            "Personal-Email": "a@b.c",
            "Authorization": "Bearer tok",
        },
        "phone": "+1000",
        "TOKEN": "abc",
        "cookie": "sid=1",
        "safe": "value",
    }
    cleaned = sanitize_payload(raw)
    assert cleaned["Email"] == "***REDACTED***"
    assert cleaned["nested"]["API_KEY"] == "***REDACTED***"
    assert cleaned["nested"]["Personal-Email"] == "***REDACTED***"
    assert cleaned["nested"]["Authorization"] == "***REDACTED***"
    assert cleaned["nested"]["list"][0]["Password"] == "***REDACTED***"
    assert cleaned["nested"]["list"][1]["ok"] == 1
    assert cleaned["phone"] == "***REDACTED***"
    assert cleaned["TOKEN"] == "***REDACTED***"
    assert cleaned["cookie"] == "***REDACTED***"
    assert cleaned["safe"] == "value"
    assert cleaned["Name"] == "Acme"


def test_safe_payload_omits_email() -> None:
    record = CompanyRecord(
        name="X",
        domain="x.example",
        region="EU",
        niche="SaaS",
        contact_email="secret@example.com",
        source_record_id="src-1",
    )
    payload = _safe_payload(record, "q")
    assert "contact_email" not in payload
    assert "email" not in {k.lower() for k in payload}
    assert payload["has_contact_email"] is True
    assert "secret@example.com" not in str(payload).lower()


def test_research_does_not_store_contact_email(client: TestClient, db_session) -> None:
    response = client.post(
        "/api/research/runs",
        json={
            "query": "Logistics",
            "industry": "Logistics",
            "location": "Baltic",
            "adapter": "test_source",
            "limit": 5,
        },
    )
    assert response.status_code == 201
    contacts = db_session.scalars(select(Contact)).all()
    assert contacts == []


def test_create_company_atomic_integrity_recovery(db_session) -> None:
    record = CompanyRecord(
        name="Race Co",
        domain="race-co.example",
        region="EU",
        niche="SaaS",
        contact_email="race@example.com",
        source_record_id="race-1",
    )
    c1, o1 = _create_company_atomic(db_session, record)
    assert o1 == ResearchItemOutcome.CREATED
    c2, o2 = _create_company_atomic(db_session, record)
    assert o2 == ResearchItemOutcome.MATCHED_EXISTING
    assert c1.id == c2.id
    count = db_session.scalar(
        select(func.count()).select_from(Company).where(Company.domain == "race-co.example")
    )
    assert count == 1


def test_null_domains_allowed_multiple(db_session) -> None:
    db_session.add(Company(name="No Domain A", domain=None, status="UNKNOWN"))
    db_session.add(Company(name="No Domain B", domain=None, status="UNKNOWN"))
    db_session.flush()
    count = db_session.scalar(
        select(func.count()).select_from(Company).where(Company.domain.is_(None))
    )
    assert count >= 2


def test_unknown_run_id_404(client: TestClient) -> None:
    response = client.get(f"/api/research/runs/{uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_blocked_has_finished_at(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("SYSTEM_STOP_ALL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
        response = client.post(
            "/api/research/runs",
            json={"query": "SaaS", "adapter": "test_source", "limit": 2},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "BLOCKED"
        assert data["finished_at"] is not None
        assert "SYSTEM_STOP_ALL" in (data["error_message"] or "")
    finally:
        monkeypatch.setenv("SYSTEM_STOP_ALL", "false")
        get_settings.cache_clear()


def test_stop_all_does_not_call_adapter(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("SYSTEM_STOP_ALL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
        with patch("app.services.research_service.get_source_adapter") as mock_get:
            response = client.post(
                "/api/research/runs",
                json={"query": "SaaS", "adapter": "test_source", "limit": 2},
            )
            assert response.status_code == 201
            assert response.json()["status"] == "BLOCKED"
            mock_get.assert_not_called()
    finally:
        monkeypatch.setenv("SYSTEM_STOP_ALL", "false")
        get_settings.cache_clear()


def test_failed_finished_at_via_service(db_session) -> None:
    pending = create_research_run(
        db_session,
        ResearchRunCreate(query="FailCase", adapter="test_source", limit=2),
    )
    run_id = pending.id
    with patch("app.services.research_service.get_source_adapter") as mock_get:
        adapter = MagicMock()
        adapter.name = "test_source"
        adapter.search.side_effect = RuntimeError("boom")
        mock_get.return_value = adapter
        try:
            execute_research_run(db_session, run_id)
            raise AssertionError("expected AppError")
        except Exception:
            pass
    db_session.expire_all()
    row = db_session.get(ResearchRun, run_id)
    assert row is not None
    assert row.status == ResearchRunStatus.FAILED.value
    assert row.finished_at is not None
    assert row.error_message
    assert "Traceback" not in (row.error_message or "")
    assert "boom" not in (row.error_message or "").lower()


def test_celery_redelivery_idempotent(db_session) -> None:
    result = start_research(
        db_session,
        ResearchRunCreate(
            query="Energy",
            industry="Renewable Energy",
            location="DACH",
            adapter="test_source",
            limit=3,
        ),
    )
    assert result.status.value == "COMPLETED"
    first_created = result.created_count
    again = execute_research_run(db_session, result.id)
    assert again.status.value == "COMPLETED"
    assert again.created_count == first_created
    assert again.finished_at is not None


def test_no_duplicate_provenance(client: TestClient, db_session) -> None:
    payload = {
        "query": "FinTech",
        "industry": "FinTech",
        "location": "Central Europe",
        "adapter": "test_source",
        "limit": 5,
    }
    client.post("/api/research/runs", json=payload)
    client.post("/api/research/runs", json=payload)
    rows = db_session.scalars(
        select(CompanySourceRecord).where(
            CompanySourceRecord.external_id == "test-central-fin-1"
        )
    ).all()
    assert len(rows) == 1


def test_domain_fill_conflict(client: TestClient, db_session) -> None:
    """Company without domain must not absorb another company's domain."""
    from datetime import datetime, timezone

    from app.models import DataSource, DataSourceType, ResearchRun
    from app.services.research_service import _ingest_record

    owner = client.post(
        "/api/companies",
        json={"name": "Domain Owner", "domain": "owned-domain.example"},
    ).json()
    blank = client.post(
        "/api/companies",
        json={"name": "Blank Domain Co"},
    ).json()

    source = db_session.scalar(select(DataSource).where(DataSource.name == "test_source"))
    if source is None:
        source = DataSource(
            name="test_source",
            source_type=DataSourceType.TEST.value,
            enabled=True,
        )
        db_session.add(source)
        db_session.flush()

    db_session.add(
        CompanySourceRecord(
            company_id=blank["id"],
            data_source_id=source.id,
            external_id="fill-conflict-src-1",
            is_test_data=True,
            collected_at=datetime.now(timezone.utc),
            raw_payload={"name": "Blank Domain Co"},
        )
    )
    run = ResearchRun(
        status=ResearchRunStatus.RUNNING.value,
        adapter="test_source",
        query="domain-fill",
        limit=1,
        is_test_data=True,
        result_items=[],
    )
    db_session.add(run)
    db_session.flush()

    record = CompanyRecord(
        name="Blank Domain Co",
        domain="owned-domain.example",
        region="EU",
        niche="SaaS",
        contact_email="x@example.com",
        source_record_id="fill-conflict-src-1",
    )
    item = _ingest_record(db_session, run, source, record)
    assert item["outcome"] == ResearchItemOutcome.CONFLICT.value
    blank_row = db_session.get(Company, blank["id"])
    assert blank_row is not None
    assert blank_row.domain is None
    still = db_session.scalar(
        select(func.count()).select_from(Company).where(Company.domain == "owned-domain.example")
    )
    assert still == 1
    assert owner["id"]


def test_concurrent_domain_inserts(db_engine) -> None:
    SessionLocal = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    domain = f"concurrent-{uuid4().hex[:10]}.example"

    def worker(suffix: str) -> str:
        session = SessionLocal()
        try:
            record = CompanyRecord(
                name=f"Concurrent {suffix}",
                domain=domain,
                region="EU",
                niche="SaaS",
                contact_email="c@example.com",
                source_record_id=f"concurrent-{suffix}-{uuid4().hex[:6]}",
            )
            company, outcome = _create_company_atomic(session, record)
            session.commit()
            return f"{company.id}:{outcome.value}"
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(worker, str(i)) for i in range(4)]
            results = [f.result() for f in as_completed(futures)]

        ids = {r.split(":")[0] for r in results}
        assert len(ids) == 1
        session = SessionLocal()
        try:
            count = session.scalar(
                select(func.count()).select_from(Company).where(Company.domain == domain)
            )
            assert count == 1
        finally:
            session.close()
    finally:
        session = SessionLocal()
        try:
            session.execute(delete(Company).where(Company.domain == domain))
            session.commit()
        finally:
            session.close()


def test_is_test_data_not_user_controllable(client: TestClient) -> None:
    response = client.post(
        "/api/research/runs",
        json={
            "query": "SaaS",
            "adapter": "test_source",
            "limit": 2,
            "is_test_data": False,
        },
    )
    assert response.status_code == 422


def test_adapter_error_response_no_traceback(client: TestClient) -> None:
    with patch("app.services.research_service.get_source_adapter") as mock_get:
        adapter = MagicMock()
        adapter.name = "test_source"
        adapter.search.side_effect = RuntimeError("secret boom traceback stuff")
        mock_get.return_value = adapter
        response = client.post(
            "/api/research/runs",
            json={"query": "SaaS", "adapter": "test_source", "limit": 2},
        )
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "research_failed"
    assert "Traceback" not in str(body)
    assert "secret boom" not in str(body).lower()
