"""Stage 3 qualification, scoring, review, and safety tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import sessionmaker

from app.models import (
    Campaign,
    CampaignLead,
    Company,
    LeadScoreSnapshot,
    QualificationRun,
    QualificationRunStatus,
    SCORING_VERSION,
)
from app.models.enums import QualificationStatus, ReviewDecision
from app.providers.email_test import TestEmailProvider
from app.schemas.qualification import QualificationRunCreate
from app.services.qualification_service import (
    create_qualification_run,
    execute_qualification_run,
    start_qualification,
)
from app.services.scoring import classify_score, score_company
from app.services.sanitize import sanitize_payload


def _make_campaign(client: TestClient, **overrides) -> dict:
    payload = {
        "name": "Stage3 Campaign",
        "business_type": "B2B SaaS",
        "region": "Northern Europe",
        "offer": "Demo offer",
        **overrides,
    }
    r = client.post("/api/campaigns", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _make_research(client: TestClient, campaign_id: str | None = None) -> dict:
    body = {
        "query": "SaaS",
        "industry": "B2B SaaS",
        "location": "Northern Europe",
        "adapter": "test_source",
        "limit": 5,
    }
    if campaign_id:
        body["campaign_id"] = campaign_id
    r = client.post("/api/research/runs", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_successful_qualification(client: TestClient, db_session) -> None:
    campaign = _make_campaign(client)
    research = _make_research(client, campaign["id"])
    resp = client.post(
        "/api/qualification/runs",
        json={
            "campaign_id": campaign["id"],
            "research_run_id": research["id"],
            "async_mode": False,
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["status"] == "COMPLETED"
    assert data["scoring_version"] == SCORING_VERSION
    assert data["scored_count"] >= 1
    assert data["created_leads_count"] >= 1
    assert data["finished_at"] is not None
    assert data["is_test_data"] is True

    leads = client.get(f"/api/campaigns/{campaign['id']}/leads").json()
    assert leads["total"] >= 1
    lead = leads["items"][0]
    assert lead["qualification_score"] is not None
    assert 0 <= lead["qualification_score"] <= 100
    assert lead["qualification_status"] in {"QUALIFIED", "REVIEW", "DISQUALIFIED"}
    assert lead["score_reasons"]
    assert lead["source_research_run_id"] == research["id"]


def test_repeat_qualification_no_duplicate_leads(client: TestClient, db_session) -> None:
    campaign = _make_campaign(client)
    research = _make_research(client, campaign["id"])
    payload = {"campaign_id": campaign["id"], "research_run_id": research["id"]}
    r1 = client.post("/api/qualification/runs", json=payload).json()
    before = db_session.scalar(
        select(func.count()).select_from(CampaignLead).where(CampaignLead.campaign_id == campaign["id"])
    )
    r2 = client.post("/api/qualification/runs", json=payload).json()
    after = db_session.scalar(
        select(func.count()).select_from(CampaignLead).where(CampaignLead.campaign_id == campaign["id"])
    )
    assert after == before
    assert r2["created_leads_count"] == 0
    assert r2["matched_leads_count"] >= 1
    assert r1["scored_count"] == r2["scored_count"]


def test_unique_campaign_company(db_session) -> None:
    from app.models import Campaign, CampaignStatus, SendingMode

    campaign = Campaign(
        name="U",
        business_type="SaaS",
        region="EU",
        offer="O",
        status=CampaignStatus.DRAFT.value,
        sending_mode=SendingMode.TEST.value,
    )
    company = Company(name="C", domain=None, status="UNKNOWN")
    db_session.add_all([campaign, company])
    db_session.flush()
    db_session.add(CampaignLead(campaign_id=campaign.id, company_id=company.id))
    db_session.flush()
    nested = db_session.begin_nested()
    try:
        db_session.add(CampaignLead(campaign_id=campaign.id, company_id=company.id))
        db_session.flush()
        raise AssertionError("expected IntegrityError")
    except Exception:
        nested.rollback()
    count = db_session.scalar(
        select(func.count()).select_from(CampaignLead).where(
            CampaignLead.campaign_id == campaign.id,
            CampaignLead.company_id == company.id,
        )
    )
    assert count == 1


def test_snapshot_unique_per_run_lead(client: TestClient, db_session) -> None:
    campaign = _make_campaign(client)
    research = _make_research(client, campaign["id"])
    run = client.post(
        "/api/qualification/runs",
        json={"campaign_id": campaign["id"], "research_run_id": research["id"]},
    ).json()
    snaps = db_session.scalars(
        select(LeadScoreSnapshot).where(LeadScoreSnapshot.qualification_run_id == run["id"])
    ).all()
    assert len(snaps) >= 1
    pairs = {(s.qualification_run_id, s.campaign_lead_id) for s in snaps}
    assert len(pairs) == len(snaps)


def test_deterministic_score_and_thresholds() -> None:
    assert classify_score(70) == QualificationStatus.QUALIFIED
    assert classify_score(69) == QualificationStatus.REVIEW
    assert classify_score(40) == QualificationStatus.REVIEW
    assert classify_score(39) == QualificationStatus.DISQUALIFIED
    assert classify_score(0) == QualificationStatus.DISQUALIFIED
    assert classify_score(100) == QualificationStatus.QUALIFIED


def test_score_company_reasons_and_clamp(db_session) -> None:
    from app.models import Campaign, CampaignStatus, SendingMode

    campaign = Campaign(
        name="Score Camp",
        business_type="B2B SaaS",
        region="Northern Europe",
        offer="O",
        status=CampaignStatus.DRAFT.value,
        sending_mode=SendingMode.TEST.value,
    )
    company = Company(
        name="Nordic SaaS Labs",
        domain="nordicsaas.example",
        website="https://nordicsaas.example",
        description="Demo SaaS company for stage 0 testing.",
        status="UNKNOWN",
    )
    db_session.add_all([campaign, company])
    db_session.flush()
    from app.models import CompanyLocation

    db_session.add(CompanyLocation(company_id=company.id, region="Northern Europe", is_primary=True))
    db_session.flush()
    db_session.refresh(company)

    a = score_company(campaign=campaign, company=company, provenance_records=[])
    b = score_company(campaign=campaign, company=company, provenance_records=[])
    assert a.score == b.score
    assert 0 <= a.score <= 100
    assert a.reasons
    assert any(r.code == "DOMAIN_PRESENT" for r in a.reasons)

    conflicted = score_company(
        campaign=campaign,
        company=company,
        provenance_records=[],
        has_domain_conflict=True,
    )
    assert conflicted.score <= a.score
    assert any(r.code == "DOMAIN_CONFLICT" for r in conflicted.reasons)


def test_research_not_completed_rejected(client: TestClient, db_session) -> None:
    campaign = _make_campaign(client)
    from app.models import ResearchRun, ResearchRunStatus

    pending = ResearchRun(
        status=ResearchRunStatus.PENDING.value,
        adapter="test_source",
        query="SaaS",
        limit=5,
        is_test_data=True,
        result_items=[],
    )
    db_session.add(pending)
    db_session.flush()
    resp = client.post(
        "/api/qualification/runs",
        json={"campaign_id": campaign["id"], "research_run_id": str(pending.id)},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "research_not_completed"


def test_research_campaign_mismatch(client: TestClient, db_session) -> None:
    c1 = _make_campaign(client, name="Camp A")
    c2 = _make_campaign(client, name="Camp B")
    research = _make_research(client, c1["id"])
    resp = client.post(
        "/api/qualification/runs",
        json={"campaign_id": c2["id"], "research_run_id": research["id"]},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "research_campaign_mismatch"


def test_unknown_ids_404(client: TestClient) -> None:
    missing = str(uuid4())
    assert client.post(
        "/api/qualification/runs",
        json={"campaign_id": missing, "research_run_id": missing},
    ).status_code == 404
    campaign = _make_campaign(client)
    assert client.post(
        "/api/qualification/runs",
        json={"campaign_id": campaign["id"], "research_run_id": missing},
    ).status_code == 404
    assert client.get(f"/api/qualification/runs/{missing}").status_code == 404
    assert client.get(f"/api/campaigns/{missing}/leads").status_code == 404
    assert (
        client.post(
            f"/api/campaigns/{campaign['id']}/leads/{missing}/review",
            json={"decision": "APPROVED"},
        ).status_code
        == 404
    )


def test_system_stop_all_blocks(client: TestClient, monkeypatch) -> None:
    campaign = _make_campaign(client)
    research = _make_research(client, campaign["id"])
    monkeypatch.setenv("SYSTEM_STOP_ALL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
        with patch("app.services.qualification_service.score_company") as mock_score:
            resp = client.post(
                "/api/qualification/runs",
                json={"campaign_id": campaign["id"], "research_run_id": research["id"]},
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["status"] == "BLOCKED"
            assert data["finished_at"] is not None
            assert "SYSTEM_STOP_ALL" in (data["error_message"] or "")
            mock_score.assert_not_called()
    finally:
        monkeypatch.setenv("SYSTEM_STOP_ALL", "false")
        get_settings.cache_clear()


def test_no_email_provider_on_qualify_or_review(client: TestClient) -> None:
    campaign = _make_campaign(client)
    research = _make_research(client, campaign["id"])
    with patch.object(TestEmailProvider, "send", autospec=True) as mock_send:
        q = client.post(
            "/api/qualification/runs",
            json={"campaign_id": campaign["id"], "research_run_id": research["id"]},
        )
        assert q.status_code == 201
        leads = client.get(f"/api/campaigns/{campaign['id']}/leads").json()["items"]
        assert leads
        rev = client.post(
            f"/api/campaigns/{campaign['id']}/leads/{leads[0]['id']}/review",
            json={"decision": "APPROVED", "note": "ok"},
        )
        assert rev.status_code == 200
        mock_send.assert_not_called()


def test_scoring_error_marks_failed(db_session) -> None:
    from app.schemas.research import ResearchRunCreate
    from app.services.research_service import start_research
    from app.schemas.campaign import CampaignCreate
    from app.services.campaign_service import create_campaign

    campaign = create_campaign(
        db_session,
        CampaignCreate(
            name="Fail Camp",
            business_type="SaaS",
            region="EU",
            offer="O",
        ),
    )
    research = start_research(
        db_session,
        ResearchRunCreate(
            query="SaaS",
            industry="B2B SaaS",
            location="Northern Europe",
            adapter="test_source",
            limit=3,
            campaign_id=campaign.id,
        ),
    )
    pending = create_qualification_run(
        db_session,
        QualificationRunCreate(campaign_id=campaign.id, research_run_id=research.id),
    )
    run_id = pending.id
    with patch(
        "app.services.qualification_service.score_company",
        side_effect=RuntimeError("score boom"),
    ):
        try:
            execute_qualification_run(db_session, run_id)
            raise AssertionError("expected AppError")
        except Exception:
            pass
    db_session.expire_all()
    row = db_session.get(QualificationRun, run_id)
    assert row is not None
    assert row.status == QualificationRunStatus.FAILED.value
    assert row.finished_at is not None
    assert "Traceback" not in (row.error_message or "")


def test_celery_redelivery_noop(db_session) -> None:
    from app.schemas.campaign import CampaignCreate
    from app.schemas.research import ResearchRunCreate
    from app.services.campaign_service import create_campaign
    from app.services.research_service import start_research

    campaign = create_campaign(
        db_session,
        CampaignCreate(name="Celery Q", business_type="B2B SaaS", region="Northern Europe", offer="O"),
    )
    research = start_research(
        db_session,
        ResearchRunCreate(
            query="SaaS",
            industry="B2B SaaS",
            location="Northern Europe",
            adapter="test_source",
            limit=3,
            campaign_id=campaign.id,
        ),
    )
    result = start_qualification(
        db_session,
        QualificationRunCreate(campaign_id=campaign.id, research_run_id=research.id),
    )
    again = execute_qualification_run(db_session, result.id)
    assert again.scored_count == result.scored_count
    assert again.created_leads_count == result.created_leads_count


def test_manual_review_flow(client: TestClient) -> None:
    campaign = _make_campaign(client)
    research = _make_research(client, campaign["id"])
    client.post(
        "/api/qualification/runs",
        json={"campaign_id": campaign["id"], "research_run_id": research["id"]},
    )
    lead = client.get(f"/api/campaigns/{campaign['id']}/leads").json()["items"][0]
    approved = client.post(
        f"/api/campaigns/{campaign['id']}/leads/{lead['id']}/review",
        json={"decision": "APPROVED", "note": "manual"},
    )
    assert approved.status_code == 200
    assert approved.json()["review_decision"] == "APPROVED"
    again = client.post(
        f"/api/campaigns/{campaign['id']}/leads/{lead['id']}/review",
        json={"decision": "APPROVED", "note": "manual"},
    )
    assert again.status_code == 200
    rejected = client.post(
        f"/api/campaigns/{campaign['id']}/leads/{lead['id']}/review",
        json={"decision": "REJECTED"},
    )
    assert rejected.json()["review_decision"] == "REJECTED"
    pending = client.post(
        f"/api/campaigns/{campaign['id']}/leads/{lead['id']}/review",
        json={"decision": "PENDING"},
    )
    assert pending.json()["review_decision"] == "PENDING"


def test_invalid_review_decision(client: TestClient) -> None:
    campaign = _make_campaign(client)
    research = _make_research(client, campaign["id"])
    client.post(
        "/api/qualification/runs",
        json={"campaign_id": campaign["id"], "research_run_id": research["id"]},
    )
    lead = client.get(f"/api/campaigns/{campaign['id']}/leads").json()["items"][0]
    resp = client.post(
        f"/api/campaigns/{campaign['id']}/leads/{lead['id']}/review",
        json={"decision": "SEND_EMAIL"},
    )
    assert resp.status_code == 422


def test_score_filters_validation(client: TestClient) -> None:
    campaign = _make_campaign(client)
    assert (
        client.get(f"/api/campaigns/{campaign['id']}/leads?min_score=150").status_code == 422
    )
    assert (
        client.get(f"/api/campaigns/{campaign['id']}/leads?min_score=80&max_score=10").status_code
        == 422
    )


def test_null_domains_multiple_leads_ok(client: TestClient, db_session) -> None:
    campaign = _make_campaign(client)
    c1 = client.post("/api/companies", json={"name": "Null Dom A"}).json()
    c2 = client.post("/api/companies", json={"name": "Null Dom B"}).json()
    client.post(f"/api/campaigns/{campaign['id']}/companies/{c1['id']}")
    client.post(f"/api/campaigns/{campaign['id']}/companies/{c2['id']}")
    count = db_session.scalar(
        select(func.count()).select_from(CampaignLead).where(CampaignLead.campaign_id == campaign["id"])
    )
    assert count == 2


def test_input_snapshot_sanitized(client: TestClient, db_session) -> None:
    campaign = _make_campaign(client)
    research = _make_research(client, campaign["id"])
    run = client.post(
        "/api/qualification/runs",
        json={"campaign_id": campaign["id"], "research_run_id": research["id"]},
    ).json()
    snap = db_session.scalar(
        select(LeadScoreSnapshot).where(LeadScoreSnapshot.qualification_run_id == run["id"])
    )
    assert snap is not None
    cleaned = sanitize_payload({"Email": "a@b.c", "nested": {"token": "x"}, **(snap.input_snapshot or {})})
    blob = str(snap.input_snapshot).lower()
    assert "@" not in blob or "example" in blob  # domains may contain dots; no personal emails
    assert "password" not in blob
    assert cleaned["Email"] == "***REDACTED***"


def test_is_test_data_not_user_controllable(client: TestClient) -> None:
    campaign = _make_campaign(client)
    research = _make_research(client, campaign["id"])
    resp = client.post(
        "/api/qualification/runs",
        json={
            "campaign_id": campaign["id"],
            "research_run_id": research["id"],
            "is_test_data": False,
        },
    )
    assert resp.status_code == 422


def test_error_response_no_traceback(client: TestClient) -> None:
    campaign = _make_campaign(client)
    research = _make_research(client, campaign["id"])
    with patch(
        "app.services.qualification_service.score_company",
        side_effect=RuntimeError("secret boom"),
    ):
        resp = client.post(
            "/api/qualification/runs",
            json={"campaign_id": campaign["id"], "research_run_id": research["id"]},
        )
    assert resp.status_code == 500
    assert "Traceback" not in str(resp.json())
    assert "secret boom" not in str(resp.json()).lower()


def test_concurrent_lead_create(db_engine) -> None:
    from app.models import Campaign, CampaignStatus, ResearchRun, ResearchRunStatus, SendingMode
    from app.services.qualification_service import _get_or_create_lead

    SessionLocal = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    setup = SessionLocal()
    try:
        campaign = Campaign(
            name=f"Conc {uuid4().hex[:6]}",
            business_type="SaaS",
            region="EU",
            offer="O",
            status=CampaignStatus.DRAFT.value,
            sending_mode=SendingMode.TEST.value,
            max_companies=30,
        )
        company = Company(name="Concurrent Co", domain=f"conc-{uuid4().hex[:8]}.example", status="UNKNOWN")
        research = ResearchRun(
            status=ResearchRunStatus.COMPLETED.value,
            adapter="test_source",
            query="SaaS",
            limit=5,
            is_test_data=True,
            result_items=[],
        )
        setup.add_all([campaign, company, research])
        setup.commit()
        campaign_id = campaign.id
        company_id = company.id
        research_run_id = research.id
    finally:
        setup.close()

    def worker() -> str:
        session = SessionLocal()
        try:
            camp = session.get(Campaign, campaign_id)
            comp = session.get(Company, company_id)
            lead, outcome = _get_or_create_lead(
                session,
                campaign=camp,
                company=comp,
                research_run_id=research_run_id,
            )
            session.commit()
            return f"{lead.id}:{outcome.value}"
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = [f.result() for f in as_completed([pool.submit(worker) for _ in range(4)])]
        ids = {r.split(":")[0] for r in results}
        assert len(ids) == 1
        session = SessionLocal()
        try:
            count = session.scalar(
                select(func.count()).select_from(CampaignLead).where(
                    CampaignLead.campaign_id == campaign_id,
                    CampaignLead.company_id == company_id,
                )
            )
            assert count == 1
        finally:
            session.close()
    finally:
        session = SessionLocal()
        try:
            session.execute(delete(CampaignLead).where(CampaignLead.campaign_id == campaign_id))
            session.execute(delete(Company).where(Company.id == company_id))
            session.execute(delete(Campaign).where(Campaign.id == campaign_id))
            session.execute(delete(ResearchRun).where(ResearchRun.id == research_run_id))
            session.commit()
        finally:
            session.close()
