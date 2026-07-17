"""Stage 3 review hardening — atomic claim, isolation, mid-run failure, PII."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import sessionmaker

from app.models import (
    Campaign,
    CampaignLead,
    CampaignStatus,
    Company,
    CompanySourceRecord,
    DataSource,
    DataSourceType,
    LeadScoreSnapshot,
    QualificationRun,
    QualificationRunStatus,
    ResearchRun,
    ResearchRunStatus,
    ReviewDecision,
    SendingMode,
)
from app.providers.email_test import TestEmailProvider
from app.schemas.qualification import LeadReviewRequest, QualificationRunCreate
from app.services.qualification_service import (
    create_qualification_run,
    execute_qualification_run,
    review_lead,
    start_qualification,
)
from app.services.sanitize import sanitize_payload
from app.services.scoring import score_company


def _campaign_research(client: TestClient) -> tuple[dict, dict]:
    campaign = client.post(
        "/api/campaigns",
        json={
            "name": f"Rev {uuid4().hex[:6]}",
            "business_type": "B2B SaaS",
            "region": "Northern Europe",
            "offer": "O",
        },
    ).json()
    research = client.post(
        "/api/research/runs",
        json={
            "query": "SaaS",
            "industry": "B2B SaaS",
            "location": "Northern Europe",
            "adapter": "test_source",
            "limit": 5,
            "campaign_id": campaign["id"],
        },
    ).json()
    return campaign, research


def test_atomic_claim_same_qualification_run(db_engine) -> None:
    """Two workers claim the same PENDING run — only one processes."""
    from app.schemas.campaign import CampaignCreate
    from app.schemas.research import ResearchRunCreate
    from app.services.campaign_service import create_campaign
    from app.services.research_service import start_research

    SessionLocal = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    setup = SessionLocal()
    try:
        campaign = create_campaign(
            setup,
            CampaignCreate(
                name=f"Claim {uuid4().hex[:6]}",
                business_type="B2B SaaS",
                region="Northern Europe",
                offer="O",
            ),
        )
        research = start_research(
            setup,
            ResearchRunCreate(
                query="SaaS",
                industry="B2B SaaS",
                location="Northern Europe",
                adapter="test_source",
                limit=3,
                campaign_id=campaign.id,
            ),
        )
        run = create_qualification_run(
            setup,
            QualificationRunCreate(campaign_id=campaign.id, research_run_id=research.id),
        )
        run_id = run.id
        campaign_id = campaign.id
        research_id = research.id
        setup.commit()
    finally:
        setup.close()

    def worker() -> str:
        session = SessionLocal()
        try:
            result = execute_qualification_run(session, run_id)
            return f"{result.status.value}:{result.scored_count}:{result.created_leads_count}"
        finally:
            session.close()

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = [f.result() for f in as_completed([pool.submit(worker) for _ in range(4)])]

        session = SessionLocal()
        try:
            row = session.get(QualificationRun, run_id)
            assert row is not None
            assert row.status == QualificationRunStatus.COMPLETED.value
            snaps = session.scalar(
                select(func.count())
                .select_from(LeadScoreSnapshot)
                .where(LeadScoreSnapshot.qualification_run_id == run_id)
            )
            assert snaps == row.scored_count
            assert row.scored_count >= 1
            completed = [o for o in outcomes if o.startswith("COMPLETED")]
            assert len(completed) >= 1
            scored_vals = {o.split(":")[1] for o in completed}
            assert len(scored_vals) == 1
        finally:
            session.close()
    finally:
        session = SessionLocal()
        try:
            session.execute(
                delete(LeadScoreSnapshot).where(LeadScoreSnapshot.qualification_run_id == run_id)
            )
            session.execute(delete(QualificationRun).where(QualificationRun.id == run_id))
            session.execute(delete(CampaignLead).where(CampaignLead.campaign_id == campaign_id))
            company_ids = list(
                session.scalars(
                    select(CompanySourceRecord.company_id).where(
                        CompanySourceRecord.research_run_id == research_id
                    )
                ).all()
            )
            session.execute(
                delete(CompanySourceRecord).where(CompanySourceRecord.research_run_id == research_id)
            )
            if company_ids:
                from app.models import CompanyLocation

                session.execute(
                    delete(CompanyLocation).where(CompanyLocation.company_id.in_(company_ids))
                )
                session.execute(delete(Company).where(Company.id.in_(company_ids)))
            session.execute(delete(ResearchRun).where(ResearchRun.id == research_id))
            session.execute(delete(Campaign).where(Campaign.id == campaign_id))
            session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()


def test_company_from_other_research_excluded(client: TestClient, db_session) -> None:
    campaign, research_a = _campaign_research(client)
    # Second research with different query may still hit same demo companies;
    # create an orphan company + provenance for a different completed research.
    other = ResearchRun(
        status=ResearchRunStatus.COMPLETED.value,
        adapter="test_source",
        query="Other",
        limit=1,
        is_test_data=True,
        result_items=[],
        found_count=1,
    )
    alien = Company(name="Alien Co", domain=f"alien-{uuid4().hex[:6]}.example", status="UNKNOWN")
    source = db_session.scalar(select(DataSource).where(DataSource.name == "test_source"))
    if source is None:
        source = DataSource(name="test_source", source_type=DataSourceType.TEST.value, enabled=True)
        db_session.add(source)
        db_session.flush()
    db_session.add_all([other, alien])
    db_session.flush()
    db_session.add(
        CompanySourceRecord(
            company_id=alien.id,
            data_source_id=source.id,
            research_run_id=other.id,
            external_id="alien-1",
            is_test_data=True,
            raw_payload={"name": "Alien Co", "domain": alien.domain},
        )
    )
    db_session.flush()

    q = client.post(
        "/api/qualification/runs",
        json={"campaign_id": campaign["id"], "research_run_id": research_a["id"]},
    ).json()
    assert q["status"] == "COMPLETED"
    leads = client.get(f"/api/campaigns/{campaign['id']}/leads").json()["items"]
    domains = {l["company_domain"] for l in leads}
    assert alien.domain not in domains


def test_non_test_research_rejected(client: TestClient, db_session) -> None:
    campaign = client.post(
        "/api/campaigns",
        json={
            "name": "NonTest",
            "business_type": "SaaS",
            "region": "EU",
            "offer": "O",
        },
    ).json()
    research = ResearchRun(
        status=ResearchRunStatus.COMPLETED.value,
        adapter="test_source",
        query="SaaS",
        limit=1,
        is_test_data=False,
        result_items=[],
    )
    db_session.add(research)
    db_session.flush()
    resp = client.post(
        "/api/qualification/runs",
        json={"campaign_id": campaign["id"], "research_run_id": str(research.id)},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "non_test_research"


def test_empty_research_zero_counters(client: TestClient, db_session) -> None:
    campaign = client.post(
        "/api/campaigns",
        json={
            "name": "EmptyRes",
            "business_type": "SaaS",
            "region": "EU",
            "offer": "O",
        },
    ).json()
    research = ResearchRun(
        status=ResearchRunStatus.COMPLETED.value,
        adapter="test_source",
        query="empty-niche-xyz",
        limit=1,
        is_test_data=True,
        result_items=[],
        found_count=0,
    )
    db_session.add(research)
    db_session.flush()
    resp = client.post(
        "/api/qualification/runs",
        json={"campaign_id": campaign["id"], "research_run_id": str(research.id)},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "COMPLETED"
    assert data["found_count"] == 0
    assert data["created_leads_count"] == 0
    assert data["scored_count"] == 0
    assert data["finished_at"] is not None


def test_mid_run_failure_all_or_nothing(db_session) -> None:
    from app.schemas.campaign import CampaignCreate
    from app.schemas.research import ResearchRunCreate
    from app.services.campaign_service import create_campaign
    from app.services.research_service import start_research
    from app.services import scoring as scoring_mod

    campaign = create_campaign(
        db_session,
        CampaignCreate(
            name="MidFail",
            business_type="SaaS",
            region="Europe",
            offer="O",
        ),
    )
    # location "Europe" matches multiple demo regions → ≥2 companies
    research = start_research(
        db_session,
        ResearchRunCreate(
            query="Europe",
            industry="Misc",
            location="Europe",
            adapter="test_source",
            limit=5,
            campaign_id=campaign.id,
        ),
    )
    assert research.found_count >= 2
    pending = create_qualification_run(
        db_session,
        QualificationRunCreate(campaign_id=campaign.id, research_run_id=research.id),
    )
    run_id = pending.id
    calls = {"n": 0}

    def boom(**kwargs):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise RuntimeError("fail after first")
        return scoring_mod.score_company(**kwargs)

    with patch("app.services.qualification_service.score_company", side_effect=boom):
        try:
            execute_qualification_run(db_session, run_id)
            raise AssertionError("expected failure")
        except Exception:
            pass

    db_session.expire_all()
    row = db_session.get(QualificationRun, run_id)
    assert row is not None
    assert row.status == QualificationRunStatus.FAILED.value
    assert row.finished_at is not None
    assert calls["n"] >= 2
    # All-or-nothing: no leads/snapshots from this failed run remain.
    snaps = db_session.scalar(
        select(func.count())
        .select_from(LeadScoreSnapshot)
        .where(LeadScoreSnapshot.qualification_run_id == run_id)
    )
    assert snaps == 0
    leads = db_session.scalar(
        select(func.count())
        .select_from(CampaignLead)
        .where(CampaignLead.campaign_id == campaign.id)
    )
    assert leads == 0


def test_review_preserves_score_and_idempotent_timestamp(client: TestClient) -> None:
    campaign, research = _campaign_research(client)
    client.post(
        "/api/qualification/runs",
        json={"campaign_id": campaign["id"], "research_run_id": research["id"]},
    )
    lead = client.get(f"/api/campaigns/{campaign['id']}/leads").json()["items"][0]
    score = lead["qualification_score"]
    qstatus = lead["qualification_status"]
    r1 = client.post(
        f"/api/campaigns/{campaign['id']}/leads/{lead['id']}/review",
        json={"decision": "APPROVED", "note": "ok"},
    ).json()
    assert r1["qualification_score"] == score
    assert r1["qualification_status"] == qstatus
    reviewed_at = r1["reviewed_at"]
    r2 = client.post(
        f"/api/campaigns/{campaign['id']}/leads/{lead['id']}/review",
        json={"decision": "APPROVED", "note": "ok"},
    ).json()
    assert r2["reviewed_at"] == reviewed_at


def test_review_allowed_under_system_stop_all(client: TestClient, monkeypatch) -> None:
    campaign, research = _campaign_research(client)
    client.post(
        "/api/qualification/runs",
        json={"campaign_id": campaign["id"], "research_run_id": research["id"]},
    )
    lead = client.get(f"/api/campaigns/{campaign['id']}/leads").json()["items"][0]
    monkeypatch.setenv("SYSTEM_STOP_ALL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
        with patch.object(TestEmailProvider, "send", autospec=True) as mock_send:
            resp = client.post(
                f"/api/campaigns/{campaign['id']}/leads/{lead['id']}/review",
                json={"decision": "REJECTED"},
            )
            assert resp.status_code == 200
            assert resp.json()["review_decision"] == "REJECTED"
            mock_send.assert_not_called()
    finally:
        monkeypatch.setenv("SYSTEM_STOP_ALL", "false")
        get_settings.cache_clear()


def test_review_wrong_campaign_404(client: TestClient) -> None:
    c1, research = _campaign_research(client)
    c2 = client.post(
        "/api/campaigns",
        json={"name": "OtherCamp", "business_type": "SaaS", "region": "EU", "offer": "O"},
    ).json()
    client.post(
        "/api/qualification/runs",
        json={"campaign_id": c1["id"], "research_run_id": research["id"]},
    )
    lead = client.get(f"/api/campaigns/{c1['id']}/leads").json()["items"][0]
    resp = client.post(
        f"/api/campaigns/{c2['id']}/leads/{lead['id']}/review",
        json={"decision": "APPROVED"},
    )
    assert resp.status_code == 404


def test_scoring_order_independent(db_session) -> None:
    campaign = Campaign(
        name="Ord",
        business_type="B2B SaaS",
        region="Northern Europe",
        offer="O",
        status=CampaignStatus.DRAFT.value,
        sending_mode=SendingMode.TEST.value,
    )
    domain = f"order-ind-{uuid4().hex[:8]}.example"
    company = Company(
        name="Nordic SaaS Labs",
        domain=domain,
        website=f"https://{domain}",
        description="Demo SaaS company for stage testing.",
        status="UNKNOWN",
    )
    db_session.add_all([campaign, company])
    db_session.flush()
    from app.models import CompanyLocation

    db_session.add(CompanyLocation(company_id=company.id, region="Northern Europe", is_primary=True))
    source = DataSource(name=f"src-{uuid4().hex[:6]}", source_type=DataSourceType.TEST.value)
    db_session.add(source)
    db_session.flush()
    r1 = CompanySourceRecord(
        company_id=company.id,
        data_source_id=source.id,
        external_id="b",
        is_test_data=True,
        raw_payload={"domain": domain},
    )
    r2 = CompanySourceRecord(
        company_id=company.id,
        data_source_id=source.id,
        external_id="a",
        is_test_data=True,
        raw_payload={"domain": domain},
    )
    db_session.add_all([r1, r2])
    db_session.flush()
    db_session.refresh(company)

    a = score_company(campaign=campaign, company=company, provenance_records=[r1, r2])
    b = score_company(campaign=campaign, company=company, provenance_records=[r2, r1])
    assert a.score == b.score
    assert [r.code for r in a.reasons] == [r.code for r in b.reasons]
    assert 0 <= a.score <= 100


def test_snapshot_pii_redacted(client: TestClient, db_session) -> None:
    campaign, research = _campaign_research(client)
    # Inject nested PII into an existing provenance payload before qualify
    rec = db_session.scalar(
        select(CompanySourceRecord).where(CompanySourceRecord.research_run_id == research["id"])
    )
    assert rec is not None
    rec.raw_payload = {
        **(rec.raw_payload or {}),
        "Email": "person@example.com",
        "nested": {"API_KEY": "secret", "list": [{"Password": "x"}]},
        "domain": (rec.raw_payload or {}).get("domain"),
    }
    db_session.flush()

    run = client.post(
        "/api/qualification/runs",
        json={"campaign_id": campaign["id"], "research_run_id": research["id"]},
    ).json()
    snap = db_session.scalar(
        select(LeadScoreSnapshot).where(LeadScoreSnapshot.qualification_run_id == run["id"])
    )
    assert snap is not None
    blob = str(snap.input_snapshot).lower()
    assert "person@example.com" not in blob
    assert "api_key" not in blob or "***redacted***" in str(snap.input_snapshot).lower()
    # sanitize nested sample
    cleaned = sanitize_payload(
        {"Email": "a@b.c", "nested": {"TOKEN": "t", "ok": 1}, "cookie": "c"}
    )
    assert cleaned["Email"] == "***REDACTED***"
    assert cleaned["nested"]["TOKEN"] == "***REDACTED***"
    assert cleaned["cookie"] == "***REDACTED***"
    assert cleaned["nested"]["ok"] == 1


def test_scoring_does_not_erase_review(client: TestClient, db_session) -> None:
    campaign, research = _campaign_research(client)
    client.post(
        "/api/qualification/runs",
        json={"campaign_id": campaign["id"], "research_run_id": research["id"]},
    )
    lead = client.get(f"/api/campaigns/{campaign['id']}/leads").json()["items"][0]
    client.post(
        f"/api/campaigns/{campaign['id']}/leads/{lead['id']}/review",
        json={"decision": "APPROVED", "note": "keep-me"},
    )
    client.post(
        "/api/qualification/runs",
        json={"campaign_id": campaign["id"], "research_run_id": research["id"]},
    )
    again = client.get(f"/api/campaigns/{campaign['id']}/leads").json()["items"]
    target = next(x for x in again if x["id"] == lead["id"])
    assert target["review_decision"] == "APPROVED"
    assert target["review_note"] == "keep-me"


def test_counter_invariants(client: TestClient) -> None:
    campaign, research = _campaign_research(client)
    data = client.post(
        "/api/qualification/runs",
        json={"campaign_id": campaign["id"], "research_run_id": research["id"]},
    ).json()
    assert data["found_count"] == (
        data["created_leads_count"] + data["matched_leads_count"] + data["skipped_count"]
    )
    assert data["scored_count"] == (
        data["qualified_count"] + data["review_count"] + data["disqualified_count"]
    )
    # conflict_count is a scored subset flag, not an exclusive bucket
    assert data["conflict_count"] <= data["scored_count"]


def test_invalid_domain_no_domain_points() -> None:
    campaign = Campaign(
        name="D",
        business_type="SaaS",
        region="EU",
        offer="O",
        status=CampaignStatus.DRAFT.value,
        sending_mode=SendingMode.TEST.value,
    )
    company = Company(name="NoDot", domain="localhost", status="UNKNOWN")
    result = score_company(campaign=campaign, company=company, provenance_records=[])
    assert not any(r.code == "DOMAIN_PRESENT" for r in result.reasons)
    assert any(r.code == "DOMAIN_SUSPICIOUS" for r in result.reasons)
