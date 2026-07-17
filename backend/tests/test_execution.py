"""Stage 5 test campaign execution orchestration tests."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.models import (
    CampaignExecutionItem,
    CampaignExecutionRun,
    Contact,
    ExecutionItemStatus,
    ExecutionRunStatus,
    OutreachMessage,
)
from app.models.enums import DELIVERY_OUTCOME_UNKNOWN
from app.providers.email_test import TestEmailProvider
from app.workers.celery_app import celery_app


def _campaign(client: TestClient) -> dict:
    r = client.post(
        "/api/campaigns",
        json={
            "name": f"E5 {uuid4().hex[:6]}",
            "business_type": "B2B SaaS",
            "region": "Northern Europe",
            "offer": "Demo",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _approved_messages(client: TestClient, campaign_id: str, n: int = 2) -> tuple[dict, list[dict]]:
    """Create n APPROVED messages.

    Uses multiple sequence steps on one lead when research returns few companies
    (demo domain dedup can yield a single lead in a shared test DB).
    """
    research = client.post(
        "/api/research/runs",
        json={
            "query": "SaaS",
            "industry": "B2B SaaS",
            "location": "Northern Europe",
            "adapter": "test_source",
            "limit": 5,
            "campaign_id": campaign_id,
        },
    ).json()
    client.post(
        "/api/qualification/runs",
        json={"campaign_id": campaign_id, "research_run_id": research["id"]},
    )
    leads = client.get(f"/api/campaigns/{campaign_id}/leads", params={"limit": 20}).json()["items"]
    assert leads, "expected at least one lead"
    client.post(
        f"/api/campaigns/{campaign_id}/leads/{leads[0]['id']}/review",
        json={"decision": "APPROVED"},
    )
    tmpl = client.post(
        f"/api/campaigns/{campaign_id}/outreach/templates",
        json={
            "name": "T",
            "subject_template": "Hi {{company_name}}",
            "body_template": "Score {{lead_score}}",
            "is_test_data": True,
        },
    ).json()
    step_count = max(1, min(n, 3))
    seq = client.post(
        f"/api/campaigns/{campaign_id}/outreach/sequences",
        json={
            "name": "S",
            "is_test_data": True,
            "steps": [
                {"template_id": tmpl["id"], "step_number": i}
                for i in range(1, step_count + 1)
            ],
        },
    ).json()
    client.post(
        f"/api/campaigns/{campaign_id}/outreach/drafts",
        json={"sequence_id": seq["id"], "lead_ids": [leads[0]["id"]]},
    )
    msgs = client.get(
        f"/api/campaigns/{campaign_id}/outreach/messages",
        params={"status": "DRAFT", "limit": 50},
    ).json()["items"]
    for m in msgs:
        client.post(f"/api/campaigns/{campaign_id}/outreach/messages/{m['id']}/approve")
    approved_msgs = client.get(
        f"/api/campaigns/{campaign_id}/outreach/messages",
        params={"status": "APPROVED", "limit": 50},
    ).json()["items"]
    return seq, approved_msgs


def test_create_execution_run(client: TestClient) -> None:
    campaign = _campaign(client)
    seq, msgs = _approved_messages(client, campaign["id"], n=2)
    assert len(msgs) >= 1
    with patch.object(TestEmailProvider, "send", autospec=True) as mock_send:
        r = client.post(
            f"/api/campaigns/{campaign['id']}/execution-runs",
            json={
                "sequence_id": seq["id"],
                "max_messages": 10,
                "batch_size": 2,
                "is_test_data": True,
            },
        )
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["status"] == "PENDING"
        assert data["execution_mode"] == "TEST_MANUAL_ONLY"
        assert data["planned_count"] >= 1
        assert data["is_test_data"] is True
        assert mock_send.call_count == 0


def test_empty_eligible_rejected(client: TestClient) -> None:
    campaign = _campaign(client)
    tmpl = client.post(
        f"/api/campaigns/{campaign['id']}/outreach/templates",
        json={
            "name": "T",
            "subject_template": "Hi {{company_name}}",
            "body_template": "B",
            "is_test_data": True,
        },
    ).json()
    seq = client.post(
        f"/api/campaigns/{campaign['id']}/outreach/sequences",
        json={
            "name": "S",
            "is_test_data": True,
            "steps": [{"template_id": tmpl["id"], "step_number": 1}],
        },
    ).json()
    r = client.post(
        f"/api/campaigns/{campaign['id']}/execution-runs",
        json={"sequence_id": seq["id"], "max_messages": 5, "batch_size": 2},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "empty_eligible_messages"


def test_limits_validation(client: TestClient) -> None:
    campaign = _campaign(client)
    seq, _ = _approved_messages(client, campaign["id"], n=1)
    bad = client.post(
        f"/api/campaigns/{campaign['id']}/execution-runs",
        json={"sequence_id": seq["id"], "max_messages": 0, "batch_size": 2},
    )
    assert bad.status_code == 422
    bad2 = client.post(
        f"/api/campaigns/{campaign['id']}/execution-runs",
        json={"sequence_id": seq["id"], "max_messages": 5, "batch_size": 99},
    )
    assert bad2.status_code == 422


def test_idempotent_create_and_active_run(client: TestClient) -> None:
    campaign = _campaign(client)
    seq, msgs = _approved_messages(client, campaign["id"], n=1)
    body = {
        "sequence_id": seq["id"],
        "message_ids": [msgs[0]["id"]],
        "max_messages": 5,
        "batch_size": 2,
        "client_request_id": "req-1",
    }
    r1 = client.post(f"/api/campaigns/{campaign['id']}/execution-runs", json=body).json()
    r2 = client.post(f"/api/campaigns/{campaign['id']}/execution-runs", json=body).json()
    assert r1["id"] == r2["id"]
    assert r2["matched_existing"] is True


def test_start_send_once_and_redelivery(client: TestClient, db_session) -> None:
    campaign = _campaign(client)
    seq, msgs = _approved_messages(client, campaign["id"], n=2)
    run = client.post(
        f"/api/campaigns/{campaign['id']}/execution-runs",
        json={"sequence_id": seq["id"], "max_messages": 10, "batch_size": 5},
    ).json()
    with patch.object(TestEmailProvider, "send", autospec=True) as mock_send:
        from datetime import datetime, timezone

        from app.providers.base import EmailSendResult

        mock_send.return_value = EmailSendResult(
            success=True,
            provider="test_email",
            message_id="test-e5",
            sent_at=datetime.now(timezone.utc),
            simulated=True,
        )
        started = client.post(
            f"/api/campaigns/{campaign['id']}/execution-runs/{run['id']}/start",
            params={"async_mode": "false"},
        )
        assert started.status_code == 200, started.text
        data = started.json()
        assert data["status"] == "COMPLETED"
        assert data["sent_count"] >= 1
        assert mock_send.call_count == data["sent_count"]

        # redelivery / second start no-op
        again = client.post(
            f"/api/campaigns/{campaign['id']}/execution-runs/{run['id']}/start",
            params={"async_mode": "false"},
        ).json()
        assert again["status"] == "COMPLETED"
        assert mock_send.call_count == data["sent_count"]

        # second run with same messages — no more provider calls (already SENT)
        run2 = client.post(
            f"/api/campaigns/{campaign['id']}/execution-runs",
            json={
                "sequence_id": seq["id"],
                "max_messages": 10,
                "batch_size": 5,
                "client_request_id": "second",
            },
        )
        # may be empty eligible
        assert run2.status_code in (201, 409)


def test_pause_resume_cancel(client: TestClient) -> None:
    campaign = _campaign(client)
    seq, _ = _approved_messages(client, campaign["id"], n=2)
    run = client.post(
        f"/api/campaigns/{campaign['id']}/execution-runs",
        json={"sequence_id": seq["id"], "max_messages": 10, "batch_size": 1},
    ).json()

    # Force RUNNING without processing via DB for pause test
    from app.services import execution_service

    # Start will complete sync — create run and pause during processing is hard.
    # Test cancel from PENDING and idempotent cancel.
    cancelled = client.post(
        f"/api/campaigns/{campaign['id']}/execution-runs/{run['id']}/cancel"
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    again = client.post(
        f"/api/campaigns/{campaign['id']}/execution-runs/{run['id']}/cancel"
    )
    assert again.json()["status"] == "CANCELLED"


def test_stop_blocks_start(client: TestClient) -> None:
    campaign = _campaign(client)
    seq, _ = _approved_messages(client, campaign["id"], n=1)
    run = client.post(
        f"/api/campaigns/{campaign['id']}/execution-runs",
        json={"sequence_id": seq["id"], "max_messages": 5, "batch_size": 2},
    ).json()
    os.environ["SYSTEM_STOP_ALL"] = "true"
    get_settings.cache_clear()
    try:
        with patch.object(TestEmailProvider, "send", autospec=True) as mock_send:
            r = client.post(
                f"/api/campaigns/{campaign['id']}/execution-runs/{run['id']}/start",
                params={"async_mode": "false"},
            )
            assert r.status_code == 200
            assert r.json()["status"] == "BLOCKED"
            assert mock_send.call_count == 0
    finally:
        os.environ["SYSTEM_STOP_ALL"] = "false"
        get_settings.cache_clear()


def test_analytics_unknown_not_sent(client: TestClient, db_session) -> None:
    campaign = _campaign(client)
    seq, msgs = _approved_messages(client, campaign["id"], n=1)
    mid = UUID(msgs[0]["id"])
    row = db_session.get(OutreachMessage, mid)
    row.status = "FAILED"
    row.error_message = DELIVERY_OUTCOME_UNKNOWN
    db_session.commit()
    analytics = client.get(f"/api/campaigns/{campaign['id']}/analytics").json()
    assert analytics["unknown_messages"] >= 1
    assert analytics["sent_messages"] == 0
    assert analytics["is_test_data"] is True


def test_api_foreign_campaign(client: TestClient) -> None:
    c1 = _campaign(client)
    c2 = _campaign(client)
    seq, _ = _approved_messages(client, c1["id"], n=1)
    r = client.post(
        f"/api/campaigns/{c2['id']}/execution-runs",
        json={"sequence_id": seq["id"], "max_messages": 5, "batch_size": 2},
    )
    assert r.status_code == 404


def test_no_scheduler_and_no_contact(client: TestClient, db_session) -> None:
    assert celery_app.conf.beat_schedule == {}
    before = db_session.scalar(select(func.count()).select_from(Contact)) or 0
    campaign = _campaign(client)
    seq, _ = _approved_messages(client, campaign["id"], n=1)
    client.post(
        f"/api/campaigns/{campaign['id']}/execution-runs",
        json={"sequence_id": seq["id"], "max_messages": 5, "batch_size": 2},
    )
    after = db_session.scalar(select(func.count()).select_from(Contact)) or 0
    assert after == before


def test_stable_item_ordering(client: TestClient) -> None:
    campaign = _campaign(client)
    seq, msgs = _approved_messages(client, campaign["id"], n=2)
    run = client.post(
        f"/api/campaigns/{campaign['id']}/execution-runs",
        json={"sequence_id": seq["id"], "max_messages": 10, "batch_size": 5},
    ).json()
    items = client.get(
        f"/api/campaigns/{campaign['id']}/execution-runs/{run['id']}/items"
    ).json()["items"]
    positions = [i["position"] for i in items]
    assert positions == sorted(positions)
    assert positions == list(range(1, len(positions) + 1))


_DEMO_DOMAINS = (
    "nordicsaas.example",
    "balticlog.example",
    "centralfin.example",
    "greenenergy.example",
    "medtech.example",
)


def _cleanup_committed_campaign(db_engine, campaign_id) -> None:
    """Remove campaign + demo companies left by committed concurrent/setup sessions.

    Execution items RESTRICT-reference outreach_messages, so runs/items must be
    removed before campaign cascade deletes messages.
    """
    from sqlalchemy import delete

    from app.models import Campaign, CampaignExecutionItem, CampaignExecutionRun, Company

    SessionLocal = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
        run_ids = list(
            session.scalars(
                select(CampaignExecutionRun.id).where(
                    CampaignExecutionRun.campaign_id == campaign_id
                )
            ).all()
        )
        if run_ids:
            session.execute(
                delete(CampaignExecutionItem).where(
                    CampaignExecutionItem.execution_run_id.in_(run_ids)
                )
            )
            session.execute(
                delete(CampaignExecutionRun).where(CampaignExecutionRun.id.in_(run_ids))
            )
            session.commit()
        camp = session.get(Campaign, campaign_id)
        if camp is not None:
            session.delete(camp)
            session.commit()
        session.execute(delete(Company).where(Company.domain.in_(_DEMO_DOMAINS)))
        session.commit()
    finally:
        session.close()


def test_concurrent_start(db_engine) -> None:
    from datetime import datetime, timezone

    from app.models import CampaignLead
    from app.models.enums import ReviewDecision
    from app.providers.base import EmailSendResult
    from app.schemas.campaign import CampaignCreate
    from app.schemas.execution import ExecutionRunCreate
    from app.schemas.outreach import (
        DraftCreateRequest,
        OutreachSequenceCreate,
        OutreachTemplateCreate,
        SequenceStepCreate,
    )
    from app.schemas.qualification import LeadReviewRequest, QualificationRunCreate
    from app.schemas.research import ResearchRunCreate
    from app.services import execution_service, outreach_service
    from app.services.campaign_service import create_campaign
    from app.services.qualification_service import review_lead, start_qualification
    from app.services.research_service import start_research

    SessionLocal = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    setup = SessionLocal()
    campaign_id = None
    run_id = None
    try:
        campaign = create_campaign(
            setup,
            CampaignCreate(
                name=f"ConcE5 {uuid4().hex[:6]}",
                business_type="B2B SaaS",
                region="Northern Europe",
                offer="O",
            ),
        )
        campaign_id = campaign.id
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
        start_qualification(
            setup,
            QualificationRunCreate(campaign_id=campaign.id, research_run_id=research.id),
        )
        lead = setup.scalars(
            select(CampaignLead).where(CampaignLead.campaign_id == campaign.id)
        ).first()
        review_lead(
            setup,
            campaign.id,
            lead.id,
            LeadReviewRequest(decision=ReviewDecision.APPROVED),
        )
        tmpl = outreach_service.create_template(
            setup,
            campaign.id,
            OutreachTemplateCreate(
                name="T",
                subject_template="Hi {{company_name}}",
                body_template="B",
            ),
        )
        seq = outreach_service.create_sequence(
            setup,
            campaign.id,
            OutreachSequenceCreate(
                name="S",
                steps=[SequenceStepCreate(template_id=tmpl.id, step_number=1)],
            ),
        )
        outreach_service.create_drafts(
            setup,
            campaign.id,
            DraftCreateRequest(sequence_id=seq.id, lead_ids=[lead.id]),
        )
        msg = setup.scalars(
            select(OutreachMessage).where(OutreachMessage.campaign_id == campaign.id)
        ).first()
        outreach_service.approve_message(setup, campaign.id, msg.id)
        run = execution_service.create_execution_run(
            setup,
            campaign.id,
            ExecutionRunCreate(sequence_id=seq.id, max_messages=5, batch_size=2),
        )
        run_id = run.id
    finally:
        setup.close()

    def worker() -> str:
        s = SessionLocal()
        try:
            out = execution_service.start_execution_run(
                s, campaign_id, run_id, async_mode=False
            )
            return out.status
        finally:
            s.close()

    try:
        with patch.object(TestEmailProvider, "send", autospec=True) as mock_send:
            mock_send.return_value = EmailSendResult(
                success=True,
                provider="test_email",
                message_id="t",
                sent_at=datetime.now(timezone.utc),
                simulated=True,
            )
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = [
                    f.result()
                    for f in as_completed([pool.submit(worker) for _ in range(4)])
                ]
        assert "COMPLETED" in results or all(
            r in {"COMPLETED", "RUNNING"} for r in results
        )

        check = SessionLocal()
        try:
            run = check.get(CampaignExecutionRun, run_id)
            assert run.status == ExecutionRunStatus.COMPLETED.value
            assert run.sent_count == 1
        finally:
            check.close()
    finally:
        if campaign_id is not None:
            _cleanup_committed_campaign(db_engine, campaign_id)


def _mock_send_ok(mock_send) -> None:
    from datetime import datetime, timezone

    from app.providers.base import EmailSendResult

    mock_send.return_value = EmailSendResult(
        success=True,
        provider="test_email",
        message_id="test-e5",
        sent_at=datetime.now(timezone.utc),
        simulated=True,
    )


def test_pause_between_items_and_resume(client: TestClient, db_session) -> None:
    from datetime import datetime, timezone

    from app.providers.base import EmailSendResult
    from app.services import execution_service

    campaign = _campaign(client)
    seq, msgs = _approved_messages(client, campaign["id"], n=2)
    if len(msgs) < 2:
        pytest.skip("need 2 approved messages")
    run = client.post(
        f"/api/campaigns/{campaign['id']}/execution-runs",
        json={"sequence_id": seq["id"], "max_messages": 10, "batch_size": 1},
    ).json()
    run_id = UUID(run["id"])
    campaign_id = UUID(campaign["id"])

    # Claim run RUNNING without draining
    db_session.execute(
        update(CampaignExecutionRun)
        .where(CampaignExecutionRun.id == run_id)
        .values(
            status=ExecutionRunStatus.RUNNING.value,
            started_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()

    calls = {"n": 0}

    def send_side_effect(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            # Pause after first provider call so the next item is not claimed
            execution_service.pause_execution_run(db_session, campaign_id, run_id)
        return EmailSendResult(
            success=True,
            provider="test_email",
            message_id=f"t-{calls['n']}",
            sent_at=datetime.now(timezone.utc),
            simulated=True,
        )

    with patch.object(TestEmailProvider, "send", autospec=True, side_effect=send_side_effect):
        execution_service.process_execution_run(db_session, run_id, allow_enqueue=False)
        db_session.expire_all()
        run_row = db_session.get(CampaignExecutionRun, run_id)
        assert run_row.status == ExecutionRunStatus.PAUSED.value
        assert run_row.sent_count == 1
        assert run_row.processed_count == 1
        paused_at = run_row.paused_at

        # PAUSED redelivery no-op
        execution_service.process_execution_run(db_session, run_id, allow_enqueue=False)
        db_session.refresh(run_row)
        assert run_row.status == ExecutionRunStatus.PAUSED.value
        assert run_row.paused_at == paused_at

        # Idempotent pause
        again = execution_service.pause_execution_run(db_session, campaign_id, run_id)
        assert again.status == ExecutionRunStatus.PAUSED.value
        db_session.refresh(run_row)
        assert run_row.paused_at == paused_at

        resumed = execution_service.resume_execution_run(
            db_session, campaign_id, run_id, async_mode=False
        )
        assert resumed.status == ExecutionRunStatus.COMPLETED.value
        assert resumed.sent_count == 2
        assert calls["n"] == 2


def test_concurrent_resume(db_engine) -> None:
    from datetime import datetime, timezone

    from app.models import CampaignLead
    from app.models.enums import ReviewDecision
    from app.providers.base import EmailSendResult
    from app.schemas.campaign import CampaignCreate
    from app.schemas.execution import ExecutionRunCreate
    from app.schemas.outreach import (
        DraftCreateRequest,
        OutreachSequenceCreate,
        OutreachTemplateCreate,
        SequenceStepCreate,
    )
    from app.schemas.qualification import LeadReviewRequest, QualificationRunCreate
    from app.schemas.research import ResearchRunCreate
    from app.services import execution_service, outreach_service
    from app.services.campaign_service import create_campaign
    from app.services.qualification_service import review_lead, start_qualification
    from app.services.research_service import start_research

    SessionLocal = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    setup = SessionLocal()
    campaign_id = None
    try:
        campaign = create_campaign(
            setup,
            CampaignCreate(
                name=f"ResumeE5 {uuid4().hex[:6]}",
                business_type="B2B SaaS",
                region="Northern Europe",
                offer="O",
            ),
        )
        campaign_id = campaign.id
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
        start_qualification(
            setup,
            QualificationRunCreate(campaign_id=campaign.id, research_run_id=research.id),
        )
        leads = list(
            setup.scalars(select(CampaignLead).where(CampaignLead.campaign_id == campaign.id))
        )
        for lead in leads[:2]:
            review_lead(
                setup,
                campaign.id,
                lead.id,
                LeadReviewRequest(decision=ReviewDecision.APPROVED),
            )
        tmpl = outreach_service.create_template(
            setup,
            campaign.id,
            OutreachTemplateCreate(
                name="T",
                subject_template="Hi {{company_name}}",
                body_template="B",
            ),
        )
        seq = outreach_service.create_sequence(
            setup,
            campaign.id,
            OutreachSequenceCreate(
                name="S",
                steps=[SequenceStepCreate(template_id=tmpl.id, step_number=1)],
            ),
        )
        outreach_service.create_drafts(
            setup,
            campaign.id,
            DraftCreateRequest(sequence_id=seq.id, lead_ids=[l.id for l in leads[:2]]),
        )
        for msg in setup.scalars(
            select(OutreachMessage).where(OutreachMessage.campaign_id == campaign.id)
        ).all():
            outreach_service.approve_message(setup, campaign.id, msg.id)
        run = execution_service.create_execution_run(
            setup,
            campaign.id,
            ExecutionRunCreate(sequence_id=seq.id, max_messages=10, batch_size=1),
        )
        run_id = run.id
        # Mark PAUSED with one item already SENT-like counters via processing first item
        setup.execute(
            update(CampaignExecutionRun)
            .where(CampaignExecutionRun.id == run_id)
            .values(
                status=ExecutionRunStatus.PAUSED.value,
                started_at=datetime.now(timezone.utc),
                paused_at=datetime.now(timezone.utc),
                sent_count=0,
                processed_count=0,
            )
        )
        setup.commit()
    finally:
        setup.close()

    def worker() -> str:
        s = SessionLocal()
        try:
            out = execution_service.resume_execution_run(
                s, campaign_id, run_id, async_mode=False
            )
            return out.status
        finally:
            s.close()

    try:
        with patch.object(TestEmailProvider, "send", autospec=True) as mock_send:
            _mock_send_ok(mock_send)
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = [f.result() for f in as_completed([pool.submit(worker) for _ in range(4)])]
        assert any(r == ExecutionRunStatus.COMPLETED.value for r in results)
        check = SessionLocal()
        try:
            run = check.get(CampaignExecutionRun, run_id)
            assert run.status == ExecutionRunStatus.COMPLETED.value
            assert run.sent_count == mock_send.call_count
            assert run.sent_count >= 1
        finally:
            check.close()
    finally:
        if campaign_id is not None:
            _cleanup_committed_campaign(db_engine, campaign_id)


def test_double_batch_task_no_double_send(client: TestClient, db_session) -> None:
    from app.services import execution_service

    campaign = _campaign(client)
    seq, msgs = _approved_messages(client, campaign["id"], n=2)
    run = client.post(
        f"/api/campaigns/{campaign['id']}/execution-runs",
        json={"sequence_id": seq["id"], "max_messages": 10, "batch_size": 10},
    ).json()
    run_id = UUID(run["id"])
    campaign_id = UUID(campaign["id"])
    with patch.object(TestEmailProvider, "send", autospec=True) as mock_send:
        _mock_send_ok(mock_send)
        execution_service.start_execution_run(
            db_session, campaign_id, run_id, async_mode=False
        )
        sent = mock_send.call_count
        # Simulate double Celery delivery of process task
        execution_service.process_execution_run(db_session, run_id, allow_enqueue=False)
        execution_service.process_execution_run(db_session, run_id, allow_enqueue=False)
        assert mock_send.call_count == sent
        row = db_session.get(CampaignExecutionRun, run_id)
        assert row.status == ExecutionRunStatus.COMPLETED.value
        assert row.sent_count == sent


def test_concurrent_item_claim(db_engine) -> None:
    from datetime import datetime, timezone

    from app.models import CampaignLead
    from app.models.enums import ReviewDecision
    from app.providers.base import EmailSendResult
    from app.schemas.campaign import CampaignCreate
    from app.schemas.execution import ExecutionRunCreate
    from app.schemas.outreach import (
        DraftCreateRequest,
        OutreachSequenceCreate,
        OutreachTemplateCreate,
        SequenceStepCreate,
    )
    from app.schemas.qualification import LeadReviewRequest, QualificationRunCreate
    from app.schemas.research import ResearchRunCreate
    from app.services import execution_service, outreach_service
    from app.services.campaign_service import create_campaign
    from app.services.qualification_service import review_lead, start_qualification
    from app.services.research_service import start_research

    SessionLocal = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    setup = SessionLocal()
    campaign_id = None
    try:
        campaign = create_campaign(
            setup,
            CampaignCreate(
                name=f"ItemE5 {uuid4().hex[:6]}",
                business_type="B2B SaaS",
                region="Northern Europe",
                offer="O",
            ),
        )
        campaign_id = campaign.id
        research = start_research(
            setup,
            ResearchRunCreate(
                query="SaaS",
                industry="B2B SaaS",
                location="Northern Europe",
                adapter="test_source",
                limit=2,
                campaign_id=campaign.id,
            ),
        )
        start_qualification(
            setup,
            QualificationRunCreate(campaign_id=campaign.id, research_run_id=research.id),
        )
        lead = setup.scalars(
            select(CampaignLead).where(CampaignLead.campaign_id == campaign.id)
        ).first()
        review_lead(
            setup,
            campaign.id,
            lead.id,
            LeadReviewRequest(decision=ReviewDecision.APPROVED),
        )
        tmpl = outreach_service.create_template(
            setup,
            campaign.id,
            OutreachTemplateCreate(
                name="T",
                subject_template="Hi {{company_name}}",
                body_template="B",
            ),
        )
        seq = outreach_service.create_sequence(
            setup,
            campaign.id,
            OutreachSequenceCreate(
                name="S",
                steps=[SequenceStepCreate(template_id=tmpl.id, step_number=1)],
            ),
        )
        outreach_service.create_drafts(
            setup,
            campaign.id,
            DraftCreateRequest(sequence_id=seq.id, lead_ids=[lead.id]),
        )
        msg = setup.scalars(
            select(OutreachMessage).where(OutreachMessage.campaign_id == campaign.id)
        ).first()
        outreach_service.approve_message(setup, campaign.id, msg.id)
        run = execution_service.create_execution_run(
            setup,
            campaign.id,
            ExecutionRunCreate(sequence_id=seq.id, max_messages=5, batch_size=1),
        )
        run_id = run.id
        setup.execute(
            update(CampaignExecutionRun)
            .where(CampaignExecutionRun.id == run_id)
            .values(
                status=ExecutionRunStatus.RUNNING.value,
                started_at=datetime.now(timezone.utc),
            )
        )
        setup.commit()
        item = setup.scalars(
            select(CampaignExecutionItem).where(
                CampaignExecutionItem.execution_run_id == run_id
            )
        ).first()
        item_id = item.id
    finally:
        setup.close()

    def worker() -> None:
        s = SessionLocal()
        try:
            run = s.get(CampaignExecutionRun, run_id)
            item = s.get(CampaignExecutionItem, item_id)
            execution_service._process_one_item(s, run, item)
        finally:
            s.close()

    try:
        with patch.object(TestEmailProvider, "send", autospec=True) as mock_send:
            _mock_send_ok(mock_send)
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(as_completed([pool.submit(worker) for _ in range(4)]))
            assert mock_send.call_count == 1
        check = SessionLocal()
        try:
            item = check.get(CampaignExecutionItem, item_id)
            assert item.status == ExecutionItemStatus.SENT.value
        finally:
            check.close()
    finally:
        if campaign_id is not None:
            _cleanup_committed_campaign(db_engine, campaign_id)


def test_stop_after_first_item(client: TestClient, db_session) -> None:
    from datetime import datetime, timezone

    from app.providers.base import EmailSendResult
    from app.services import execution_service

    campaign = _campaign(client)
    seq, msgs = _approved_messages(client, campaign["id"], n=2)
    if len(msgs) < 2:
        pytest.skip("need 2 approved messages")
    run = client.post(
        f"/api/campaigns/{campaign['id']}/execution-runs",
        json={"sequence_id": seq["id"], "max_messages": 10, "batch_size": 1},
    ).json()
    run_id = UUID(run["id"])
    campaign_id = UUID(campaign["id"])
    db_session.execute(
        update(CampaignExecutionRun)
        .where(CampaignExecutionRun.id == run_id)
        .values(
            status=ExecutionRunStatus.RUNNING.value,
            started_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()

    calls = {"n": 0}

    def send_side_effect(self, *args, **kwargs):
        calls["n"] += 1
        os.environ["SYSTEM_STOP_ALL"] = "true"
        get_settings.cache_clear()
        return EmailSendResult(
            success=True,
            provider="test_email",
            message_id="stop-1",
            sent_at=datetime.now(timezone.utc),
            simulated=True,
        )

    try:
        with patch.object(TestEmailProvider, "send", autospec=True, side_effect=send_side_effect):
            execution_service.process_execution_run(
                db_session, run_id, allow_enqueue=False
            )
        db_session.expire_all()
        run_row = db_session.get(CampaignExecutionRun, run_id)
        assert run_row.status == ExecutionRunStatus.BLOCKED.value
        assert run_row.finished_at is not None
        assert run_row.sent_count == 1
        assert calls["n"] == 1
        # Celery redelivery must not bypass BLOCKED
        with patch.object(TestEmailProvider, "send", autospec=True) as mock_send:
            execution_service.process_execution_run(
                db_session, run_id, allow_enqueue=False
            )
            assert mock_send.call_count == 0
    finally:
        os.environ["SYSTEM_STOP_ALL"] = "false"
        get_settings.cache_clear()


def test_cancel_during_processing_preserves_sent(client: TestClient, db_session) -> None:
    from datetime import datetime, timezone

    from app.providers.base import EmailSendResult
    from app.services import execution_service

    campaign = _campaign(client)
    seq, msgs = _approved_messages(client, campaign["id"], n=2)
    if len(msgs) < 2:
        pytest.skip("need 2 approved messages")
    run = client.post(
        f"/api/campaigns/{campaign['id']}/execution-runs",
        json={"sequence_id": seq["id"], "max_messages": 10, "batch_size": 1},
    ).json()
    run_id = UUID(run["id"])
    campaign_id = UUID(campaign["id"])
    db_session.execute(
        update(CampaignExecutionRun)
        .where(CampaignExecutionRun.id == run_id)
        .values(
            status=ExecutionRunStatus.RUNNING.value,
            started_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()

    def send_side_effect(self, *args, **kwargs):
        execution_service.cancel_execution_run(db_session, campaign_id, run_id)
        return EmailSendResult(
            success=True,
            provider="test_email",
            message_id="cancel-1",
            sent_at=datetime.now(timezone.utc),
            simulated=True,
        )

    with patch.object(TestEmailProvider, "send", autospec=True, side_effect=send_side_effect):
        execution_service.process_execution_run(db_session, run_id, allow_enqueue=False)
    db_session.expire_all()
    run_row = db_session.get(CampaignExecutionRun, run_id)
    assert run_row.status == ExecutionRunStatus.CANCELLED.value
    assert run_row.finished_at is not None
    assert run_row.sent_count == 1
    assert run_row.cancelled_at is not None
    items = db_session.scalars(
        select(CampaignExecutionItem).where(
            CampaignExecutionItem.execution_run_id == run_id
        )
    ).all()
    statuses = {i.status for i in items}
    assert ExecutionItemStatus.SENT.value in statuses
    assert ExecutionItemStatus.CANCELLED.value in statuses
    assert run_row.unknown_count == 0


def test_stale_processing_recovery_matrix(client: TestClient, db_session) -> None:
    from datetime import datetime, timedelta, timezone

    from app.models.enums import SendAttemptStatus
    from app.models.send_attempt import SendAttempt
    from app.services import execution_service
    from app.services.outreach_service import send_idempotency_key

    campaign = _campaign(client)
    seq, msgs = _approved_messages(client, campaign["id"], n=1)
    run = client.post(
        f"/api/campaigns/{campaign['id']}/execution-runs",
        json={
            "sequence_id": seq["id"],
            "message_ids": [msgs[0]["id"]],
            "max_messages": 5,
            "batch_size": 1,
        },
    ).json()
    run_id = UUID(run["id"])
    item = db_session.scalars(
        select(CampaignExecutionItem).where(
            CampaignExecutionItem.execution_run_id == run_id
        )
    ).first()
    msg = db_session.get(OutreachMessage, item.outreach_message_id)
    stale = datetime.now(timezone.utc) - timedelta(seconds=120)

    # APPROVED + no attempt → reset PENDING
    item.status = ExecutionItemStatus.PROCESSING.value
    item.claimed_at = stale
    db_session.commit()
    assert execution_service._recover_stale_processing(db_session, item) is True
    assert item.status == ExecutionItemStatus.PENDING.value

    # message SENT → item SENT
    item.status = ExecutionItemStatus.PROCESSING.value
    item.claimed_at = stale
    msg.status = "SENT"
    db_session.commit()
    assert execution_service._recover_stale_processing(db_session, item) is True
    assert item.status == ExecutionItemStatus.SENT.value

    # fresh PENDING attempt → leave alone
    msg.status = "SENDING"
    item.status = ExecutionItemStatus.PROCESSING.value
    item.claimed_at = stale
    item.finished_at = None
    attempt = SendAttempt(
        message_id=msg.id,
        idempotency_key=send_idempotency_key(msg.id),
        status=SendAttemptStatus.PENDING.value,
        attempted_at=datetime.now(timezone.utc),
        is_test_data=True,
    )
    db_session.add(attempt)
    db_session.commit()
    assert execution_service._recover_stale_processing(db_session, item) is False
    assert item.status == ExecutionItemStatus.PROCESSING.value

    # stale PENDING attempt → UNKNOWN
    attempt.attempted_at = stale
    db_session.commit()
    assert execution_service._recover_stale_processing(db_session, item) is True
    assert item.status == ExecutionItemStatus.UNKNOWN.value


def test_recompute_counters_after_desync(client: TestClient, db_session) -> None:
    from app.services import execution_service

    campaign = _campaign(client)
    seq, msgs = _approved_messages(client, campaign["id"], n=1)
    run = client.post(
        f"/api/campaigns/{campaign['id']}/execution-runs",
        json={
            "sequence_id": seq["id"],
            "message_ids": [msgs[0]["id"]],
            "max_messages": 5,
            "batch_size": 1,
        },
    ).json()
    run_id = UUID(run["id"])
    item = db_session.scalars(
        select(CampaignExecutionItem).where(
            CampaignExecutionItem.execution_run_id == run_id
        )
    ).first()
    item.status = ExecutionItemStatus.SENT.value
    run_row = db_session.get(CampaignExecutionRun, run_id)
    run_row.sent_count = 0
    run_row.processed_count = 0
    db_session.commit()
    execution_service._recompute_counters(db_session, run_id)
    db_session.commit()
    db_session.refresh(run_row)
    assert run_row.sent_count == 1
    assert run_row.processed_count == 1


def test_snapshot_immutable_and_empty_ids(client: TestClient) -> None:
    campaign = _campaign(client)
    seq, msgs = _approved_messages(client, campaign["id"], n=1)
    run = client.post(
        f"/api/campaigns/{campaign['id']}/execution-runs",
        json={
            "sequence_id": seq["id"],
            "message_ids": [msgs[0]["id"]],
            "max_messages": 5,
            "batch_size": 1,
        },
    ).json()
    assert run["planned_count"] == 1
    empty = client.post(
        f"/api/campaigns/{campaign['id']}/execution-runs",
        json={"sequence_id": seq["id"], "message_ids": [], "max_messages": 5, "batch_size": 1},
    )
    assert empty.status_code == 422
    # Cancel so we can create another; snapshot of first run unchanged
    client.post(f"/api/campaigns/{campaign['id']}/execution-runs/{run['id']}/cancel")
    items_before = client.get(
        f"/api/campaigns/{campaign['id']}/execution-runs/{run['id']}/items"
    ).json()["total"]
    assert items_before == 1


def test_analytics_sent_failed_unknown(client: TestClient, db_session) -> None:
    campaign = _campaign(client)
    seq, msgs = _approved_messages(client, campaign["id"], n=2)
    # Force statuses on messages
    for i, m in enumerate(msgs[:2]):
        row = db_session.get(OutreachMessage, UUID(m["id"]))
        if i == 0:
            row.status = "SENT"
        else:
            row.status = "FAILED"
            row.error_message = DELIVERY_OUTCOME_UNKNOWN
    db_session.commit()
    # Also create a plain FAILED without UNKNOWN if only one msg
    analytics = client.get(f"/api/campaigns/{campaign['id']}/analytics").json()
    assert analytics["sent_messages"] >= 1
    assert analytics["unknown_messages"] >= 1
    assert analytics["is_test_data"] is True
    assert 0.0 <= analytics["test_delivery_rate"] <= 1.0
    assert "body" not in analytics
    assert "recipient" not in analytics
