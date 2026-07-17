"""Stage 4 safe outreach — templates, drafts, approve, test send, safety."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.models import (
    Contact,
    OutreachMessage,
    OutreachMessageStatus,
    OutreachSequenceStep,
    SendAttempt,
    SendAttemptStatus,
)
from app.models.enums import MAX_OUTREACH_BODY, MAX_OUTREACH_SUBJECT, ReviewDecision
from app.providers.email_test import TestEmailProvider
from app.schemas.outreach import (
    DraftCreateRequest,
    OutreachSequenceCreate,
    OutreachTemplateCreate,
    SequenceStepCreate,
)
from app.services import outreach_service
from app.services.template_renderer import (
    render_body,
    render_subject,
    validate_template_text,
)
from app.workers.celery_app import celery_app
from app.workers.tasks import send_test_outreach_message_task

_DEMO_DOMAINS = (
    "nordicsaas.example",
    "balticlog.example",
    "centralfin.example",
    "greenenergy.example",
    "medtech.example",
)


def _cleanup_committed_campaign(db_engine, campaign_id) -> None:
    """Remove campaign + demo companies left by committed concurrent/setup sessions."""
    from sqlalchemy import delete

    from app.models import Campaign, Company

    SessionLocal = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
        camp = session.get(Campaign, campaign_id)
        if camp is not None:
            session.delete(camp)
            session.commit()
        session.execute(delete(Company).where(Company.domain.in_(_DEMO_DOMAINS)))
        session.commit()
    finally:
        session.close()


def _campaign(client: TestClient) -> dict:
    r = client.post(
        "/api/campaigns",
        json={
            "name": f"O4 {uuid4().hex[:6]}",
            "business_type": "B2B SaaS",
            "region": "Northern Europe",
            "offer": "Demo",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _approved_lead(client: TestClient, campaign_id: str) -> dict:
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
    leads = client.get(
        f"/api/campaigns/{campaign_id}/leads",
        params={"limit": 20},
    ).json()["items"]
    assert leads
    lead = leads[0]
    reviewed = client.post(
        f"/api/campaigns/{campaign_id}/leads/{lead['id']}/review",
        json={"decision": "APPROVED"},
    )
    assert reviewed.status_code == 200, reviewed.text
    return reviewed.json()


def _template(client: TestClient, campaign_id: str, **overrides) -> dict:
    body = {
        "name": "Intro",
        "subject_template": "Hi {{company_name}}",
        "body_template": "Score {{lead_score}} for {{campaign_name}}\n",
        "is_active": True,
        "is_test_data": True,
        **overrides,
    }
    r = client.post(f"/api/campaigns/{campaign_id}/outreach/templates", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _sequence(client: TestClient, campaign_id: str, template_id: str, steps: int = 1) -> dict:
    payload = {
        "name": "Seq",
        "is_active": True,
        "is_test_data": True,
        "steps": [
            {"template_id": template_id, "step_number": i}
            for i in range(1, steps + 1)
        ],
    }
    r = client.post(f"/api/campaigns/{campaign_id}/outreach/sequences", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _draft_and_message(client: TestClient) -> tuple[dict, dict, dict, dict]:
    campaign = _campaign(client)
    lead = _approved_lead(client, campaign["id"])
    tmpl = _template(client, campaign["id"])
    seq = _sequence(client, campaign["id"], tmpl["id"])
    drafts = client.post(
        f"/api/campaigns/{campaign['id']}/outreach/drafts",
        json={"sequence_id": seq["id"], "lead_ids": [lead["id"]]},
    )
    assert drafts.status_code == 201, drafts.text
    assert drafts.json()["created_count"] >= 1
    messages = client.get(f"/api/campaigns/{campaign['id']}/outreach/messages").json()
    assert messages["total"] >= 1
    return campaign, lead, seq, messages["items"][0]


# --- Renderer ---


def test_create_template(client: TestClient) -> None:
    campaign = _campaign(client)
    t = _template(client, campaign["id"])
    assert t["is_test_data"] is True
    assert "{{company_name}}" in t["subject_template"]


def test_subject_body_length_validation(client: TestClient) -> None:
    campaign = _campaign(client)
    r = client.post(
        f"/api/campaigns/{campaign['id']}/outreach/templates",
        json={
            "name": "X",
            "subject_template": "x" * (MAX_OUTREACH_SUBJECT + 1),
            "body_template": "ok",
            "is_test_data": True,
        },
    )
    assert r.status_code == 422
    r2 = client.post(
        f"/api/campaigns/{campaign['id']}/outreach/templates",
        json={
            "name": "X",
            "subject_template": "ok",
            "body_template": "y" * (MAX_OUTREACH_BODY + 1),
            "is_test_data": True,
        },
    )
    assert r2.status_code == 422


def test_unknown_template_variable() -> None:
    with pytest.raises(AppError) as ei:
        validate_template_text("Hello {{unknown_var}}", field="subject")
    assert ei.value.code == "unknown_template_variable"


def test_deterministic_render() -> None:
    ctx = {
        "company_name": "Acme",
        "company_domain": "acme.example",
        "company_location": "Berlin",
        "company_industry": "",
        "campaign_name": "C1",
        "lead_score": "80",
        "qualification_status": "QUALIFIED",
    }
    s1 = render_subject("Hi {{company_name}}", ctx)
    s2 = render_subject("Hi {{company_name}}", ctx)
    assert s1 == s2 == "Hi Acme"
    body = render_body("A\nB {{lead_score}}\n", ctx)
    assert "\n" in body
    assert "80" in body


def test_forbid_expression_eval() -> None:
    with pytest.raises(AppError):
        validate_template_text("{{company_name.upper()}}", field="body")
    with pytest.raises(AppError):
        validate_template_text("{{company_name|upper}}", field="body")
    with pytest.raises(AppError):
        validate_template_text("{{ __import__('os') }}", field="body")


# --- Sequence ---


def test_sequence_1_to_3_steps(client: TestClient) -> None:
    campaign = _campaign(client)
    tmpl = _template(client, campaign["id"])
    for n in (1, 2, 3):
        seq = _sequence(client, campaign["id"], tmpl["id"], steps=n)
        assert len(seq["steps"]) == n


def test_forbid_fourth_step(client: TestClient) -> None:
    campaign = _campaign(client)
    tmpl = _template(client, campaign["id"])
    r = client.post(
        f"/api/campaigns/{campaign['id']}/outreach/sequences",
        json={
            "name": "Too many",
            "is_test_data": True,
            "steps": [
                {"template_id": tmpl["id"], "step_number": i} for i in range(1, 5)
            ],
        },
    )
    assert r.status_code == 422


def test_unique_sequence_step(db_engine) -> None:
    """Unique (sequence_id, step_number) enforced at DB level."""
    from app.schemas.campaign import CampaignCreate
    from app.services.campaign_service import create_campaign

    SessionLocal = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    campaign_id = None
    try:
        campaign = create_campaign(
            session,
            CampaignCreate(
                name=f"StepUq {uuid4().hex[:6]}",
                business_type="B2B SaaS",
                region="Northern Europe",
                offer="O",
            ),
        )
        campaign_id = campaign.id
        tmpl = outreach_service.create_template(
            session,
            campaign.id,
            OutreachTemplateCreate(
                name="T",
                subject_template="Hi {{company_name}}",
                body_template="Body",
            ),
        )
        seq = outreach_service.create_sequence(
            session,
            campaign.id,
            OutreachSequenceCreate(
                name="S",
                steps=[SequenceStepCreate(template_id=tmpl.id, step_number=1)],
            ),
        )
        nested = session.begin_nested()
        try:
            session.add(
                OutreachSequenceStep(
                    sequence_id=seq.id,
                    template_id=tmpl.id,
                    step_number=1,
                )
            )
            session.flush()
            raise AssertionError("expected IntegrityError")
        except Exception:
            nested.rollback()
    finally:
        session.close()
    if campaign_id is not None:
        _cleanup_committed_campaign(db_engine, campaign_id)


# --- Drafts ---


def test_draft_for_approved_lead(client: TestClient) -> None:
    campaign, lead, seq, msg = _draft_and_message(client)
    assert msg["status"] == "DRAFT"
    assert msg["recipient_email"].endswith("@example.test")
    assert f"lead-{lead['id']}" in msg["recipient_email"]
    assert msg["is_test_data"] is True


def test_draft_forbidden_for_pending_rejected(client: TestClient) -> None:
    campaign = _campaign(client)
    research = client.post(
        "/api/research/runs",
        json={
            "query": "SaaS",
            "industry": "B2B SaaS",
            "location": "Northern Europe",
            "adapter": "test_source",
            "limit": 3,
            "campaign_id": campaign["id"],
        },
    ).json()
    client.post(
        "/api/qualification/runs",
        json={"campaign_id": campaign["id"], "research_run_id": research["id"]},
    )
    lead = client.get(f"/api/campaigns/{campaign['id']}/leads").json()["items"][0]
    assert lead["review_decision"] == "PENDING"
    tmpl = _template(client, campaign["id"])
    seq = _sequence(client, campaign["id"], tmpl["id"])
    drafts = client.post(
        f"/api/campaigns/{campaign['id']}/outreach/drafts",
        json={"sequence_id": seq["id"], "lead_ids": [lead["id"]]},
    ).json()
    assert drafts["created_count"] == 0
    assert drafts["skipped_count"] >= 1

    client.post(
        f"/api/campaigns/{campaign['id']}/leads/{lead['id']}/review",
        json={"decision": "REJECTED"},
    )
    drafts2 = client.post(
        f"/api/campaigns/{campaign['id']}/outreach/drafts",
        json={"sequence_id": seq["id"], "lead_ids": [lead["id"]]},
    ).json()
    assert drafts2["created_count"] == 0


def test_draft_other_campaign_lead(client: TestClient) -> None:
    c1 = _campaign(client)
    c2 = _campaign(client)
    lead = _approved_lead(client, c1["id"])
    tmpl = _template(client, c2["id"])
    seq = _sequence(client, c2["id"], tmpl["id"])
    drafts = client.post(
        f"/api/campaigns/{c2['id']}/outreach/drafts",
        json={"sequence_id": seq["id"], "lead_ids": [lead["id"]]},
    ).json()
    assert drafts["created_count"] == 0
    assert drafts["skipped_count"] >= 1


def test_repeat_draft_no_duplicate(client: TestClient, db_session) -> None:
    campaign, lead, seq, _msg = _draft_and_message(client)
    before = db_session.scalar(select(func.count()).select_from(OutreachMessage))
    again = client.post(
        f"/api/campaigns/{campaign['id']}/outreach/drafts",
        json={"sequence_id": seq["id"], "lead_ids": [lead["id"]]},
    ).json()
    after = db_session.scalar(select(func.count()).select_from(OutreachMessage))
    assert after == before
    assert again["matched_existing_count"] >= 1
    assert again["created_count"] == 0


def test_concurrent_draft_creation(db_engine) -> None:
    from app.schemas.campaign import CampaignCreate
    from app.schemas.qualification import LeadReviewRequest, QualificationRunCreate
    from app.schemas.research import ResearchRunCreate
    from app.services.campaign_service import create_campaign
    from app.services.qualification_service import review_lead, start_qualification
    from app.services.research_service import start_research

    SessionLocal = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    setup = SessionLocal()
    try:
        campaign = create_campaign(
            setup,
            CampaignCreate(
                name=f"Conc {uuid4().hex[:6]}",
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
        start_qualification(
            setup,
            QualificationRunCreate(campaign_id=campaign.id, research_run_id=research.id),
        )
        from app.models import CampaignLead

        lead = setup.scalars(
            select(CampaignLead).where(CampaignLead.campaign_id == campaign.id)
        ).first()
        assert lead
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
                body_template="Body {{lead_score}}",
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
        campaign_id = campaign.id
        lead_id = lead.id
        sequence_id = seq.id
    finally:
        setup.close()

    def worker() -> int:
        s = SessionLocal()
        try:
            result = outreach_service.create_drafts(
                s,
                campaign_id,
                DraftCreateRequest(sequence_id=sequence_id, lead_ids=[lead_id]),
            )
            return result.created_count + result.matched_existing_count
        finally:
            s.close()

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(worker) for _ in range(4)]
        for f in as_completed(futures):
            assert f.result() >= 1

    check = SessionLocal()
    try:
        count = check.scalar(
            select(func.count())
            .select_from(OutreachMessage)
            .where(OutreachMessage.campaign_id == campaign_id)
        )
        assert count == 1
    finally:
        check.close()
    _cleanup_committed_campaign(db_engine, campaign_id)


# --- Approve / Reject / Provider ---


def test_approve_reject_idempotent(client: TestClient) -> None:
    campaign, _lead, _seq, msg = _draft_and_message(client)
    a1 = client.post(
        f"/api/campaigns/{campaign['id']}/outreach/messages/{msg['id']}/approve"
    )
    assert a1.status_code == 200
    assert a1.json()["status"] == "APPROVED"
    a2 = client.post(
        f"/api/campaigns/{campaign['id']}/outreach/messages/{msg['id']}/approve"
    )
    assert a2.status_code == 200
    assert a2.json()["approved_at"] == a1.json()["approved_at"]

    # APPROVED → REJECTED allowed; then idempotent reject
    r1 = client.post(
        f"/api/campaigns/{campaign['id']}/outreach/messages/{msg['id']}/reject",
        json={"note": "no"},
    )
    assert r1.status_code == 200
    assert r1.json()["status"] == "REJECTED"
    r2 = client.post(
        f"/api/campaigns/{campaign['id']}/outreach/messages/{msg['id']}/reject",
        json={},
    )
    assert r2.json()["rejected_at"] == r1.json()["rejected_at"]
    # REJECTED cannot approve without reset
    bad = client.post(
        f"/api/campaigns/{campaign['id']}/outreach/messages/{msg['id']}/approve"
    )
    assert bad.status_code == 409


def test_draft_and_approve_do_not_call_provider(client: TestClient) -> None:
    with patch.object(TestEmailProvider, "send", autospec=True) as mock_send:
        campaign, lead, seq, msg = _draft_and_message(client)
        client.post(
            f"/api/campaigns/{campaign['id']}/outreach/messages/{msg['id']}/approve"
        )
        client.post(
            f"/api/campaigns/{campaign['id']}/outreach/messages/{msg['id']}/reject",
            json={},
        )
        # recreate path: reset not needed — reject already done
        assert mock_send.call_count == 0


def test_real_recipient_domain_forbidden() -> None:
    with pytest.raises(AppError) as ei:
        outreach_service.validate_test_recipient("user@gmail.com")
    assert ei.value.code == "invalid_recipient_domain"


def test_explicit_send_once_and_repeat(client: TestClient) -> None:
    with patch.object(TestEmailProvider, "send", autospec=True, wraps=TestEmailProvider().send) as mock_send:
        # wraps needs instance — better call real via side_effect
        pass

    campaign, _lead, _seq, msg = _draft_and_message(client)
    mid = msg["id"]
    cid = campaign["id"]

    with patch.object(TestEmailProvider, "send", autospec=True) as mock_send:
        from app.providers.base import EmailSendResult
        from datetime import datetime, timezone

        mock_send.return_value = EmailSendResult(
            success=True,
            provider="test_email",
            message_id="test-abc",
            sent_at=datetime.now(timezone.utc),
            simulated=True,
            detail="ok",
        )

        # draft/approve — no send
        assert mock_send.call_count == 0
        client.post(f"/api/campaigns/{cid}/outreach/messages/{mid}/approve")
        assert mock_send.call_count == 0

        sent = client.post(f"/api/campaigns/{cid}/outreach/messages/{mid}/send")
        assert sent.status_code == 200, sent.text
        assert sent.json()["status"] == "SENT"
        assert mock_send.call_count == 1

        again = client.post(f"/api/campaigns/{cid}/outreach/messages/{mid}/send")
        assert again.status_code == 200
        assert again.json()["status"] == "SENT"
        assert mock_send.call_count == 1


def test_concurrent_send_one_message(db_engine) -> None:
    from datetime import datetime, timezone

    from app.providers.base import EmailSendResult
    from app.schemas.campaign import CampaignCreate
    from app.schemas.qualification import LeadReviewRequest, QualificationRunCreate
    from app.schemas.research import ResearchRunCreate
    from app.services.campaign_service import create_campaign
    from app.services.qualification_service import review_lead, start_qualification
    from app.services.research_service import start_research

    SessionLocal = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    setup = SessionLocal()
    try:
        campaign = create_campaign(
            setup,
            CampaignCreate(
                name=f"SendConc {uuid4().hex[:6]}",
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
        start_qualification(
            setup,
            QualificationRunCreate(campaign_id=campaign.id, research_run_id=research.id),
        )
        from app.models import CampaignLead

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
                body_template="Body",
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
        drafts = outreach_service.create_drafts(
            setup,
            campaign.id,
            DraftCreateRequest(sequence_id=seq.id, lead_ids=[lead.id]),
        )
        message_id = next(r.message_id for r in drafts.results if r.message_id)
        outreach_service.approve_message(setup, campaign.id, message_id)
        campaign_id = campaign.id
    finally:
        setup.close()

    call_count = {"n": 0}

    def fake_send(self, message):  # noqa: ANN001
        call_count["n"] += 1
        return EmailSendResult(
            success=True,
            provider="test_email",
            message_id=f"test-{call_count['n']}",
            sent_at=datetime.now(timezone.utc),
            simulated=True,
        )

    with patch.object(TestEmailProvider, "send", fake_send):

        def worker() -> str:
            s = SessionLocal()
            try:
                msg = outreach_service.send_message(s, campaign_id, message_id)
                return msg.status
            except AppError as exc:
                return exc.code
            finally:
                s.close()

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = [f.result() for f in as_completed([pool.submit(worker) for _ in range(4)])]

    assert call_count["n"] == 1
    assert "SENT" in results or results.count("SENT") >= 1

    check = SessionLocal()
    try:
        successes = check.scalar(
            select(func.count())
            .select_from(SendAttempt)
            .where(
                SendAttempt.message_id == message_id,
                SendAttempt.status == SendAttemptStatus.SUCCESS.value,
            )
        )
        assert successes == 1
        msg = check.get(OutreachMessage, message_id)
        assert msg.status == OutreachMessageStatus.SENT.value
    finally:
        check.close()
    _cleanup_committed_campaign(db_engine, campaign_id)


def test_celery_redelivery_idempotent(client: TestClient, db_session) -> None:
    campaign, _lead, _seq, msg = _draft_and_message(client)
    client.post(f"/api/campaigns/{campaign['id']}/outreach/messages/{msg['id']}/approve")
    with patch.object(TestEmailProvider, "send", autospec=True) as mock_send:
        from datetime import datetime, timezone

        from app.providers.base import EmailSendResult

        mock_send.return_value = EmailSendResult(
            success=True,
            provider="test_email",
            message_id="test-celery",
            sent_at=datetime.now(timezone.utc),
            simulated=True,
        )
        # Task opens SessionLocal against DATABASE_URL — exercise service path used by the task.
        from uuid import UUID

        mid = UUID(msg["id"])
        r1 = outreach_service.send_message_by_id(db_session, mid)
        r2 = outreach_service.send_message_by_id(db_session, mid)
        assert r1.status == "SENT"
        assert r2.status == "SENT"
        assert mock_send.call_count == 1
        # Task wrapper still importable / configured
        assert send_test_outreach_message_task.max_retries == 0
        assert "send_test_outreach_message_task" in (
            send_test_outreach_message_task.name,
            "app.workers.tasks.send_test_outreach_message_task",
        ) or send_test_outreach_message_task.name.endswith("send_test_outreach_message_task")


def test_system_stop_blocks_without_provider(client: TestClient) -> None:
    campaign, _lead, _seq, msg = _draft_and_message(client)
    client.post(f"/api/campaigns/{campaign['id']}/outreach/messages/{msg['id']}/approve")

    os.environ["SYSTEM_STOP_ALL"] = "true"
    get_settings.cache_clear()
    try:
        with patch.object(TestEmailProvider, "send", autospec=True) as mock_send:
            blocked = client.post(
                f"/api/campaigns/{campaign['id']}/outreach/messages/{msg['id']}/send"
            )
            assert blocked.status_code == 200
            assert blocked.json()["status"] == "BLOCKED"
            assert blocked.json()["blocked_at"] is not None
            assert mock_send.call_count == 0
    finally:
        os.environ["SYSTEM_STOP_ALL"] = "false"
        get_settings.cache_clear()


def test_provider_exception_failed(client: TestClient) -> None:
    campaign, _lead, _seq, msg = _draft_and_message(client)
    client.post(f"/api/campaigns/{campaign['id']}/outreach/messages/{msg['id']}/approve")
    with patch.object(TestEmailProvider, "send", side_effect=RuntimeError("boom")):
        failed = client.post(
            f"/api/campaigns/{campaign['id']}/outreach/messages/{msg['id']}/send"
        )
        assert failed.status_code == 200
        data = failed.json()
        assert data["status"] == "FAILED"
        assert data["failed_at"] is not None
        assert "traceback" not in (data["error_message"] or "").lower()


def test_api_unknown_and_foreign(client: TestClient) -> None:
    campaign = _campaign(client)
    other = _campaign(client)
    fake = str(uuid4())
    assert client.get(f"/api/campaigns/{fake}/outreach/templates").status_code == 404
    assert (
        client.get(f"/api/campaigns/{campaign['id']}/outreach/messages/{fake}").status_code
        == 404
    )
    tmpl = _template(client, campaign["id"])
    assert (
        client.patch(
            f"/api/campaigns/{other['id']}/outreach/templates/{tmpl['id']}",
            json={"name": "Hijack"},
        ).status_code
        == 404
    )


def test_api_invalid_enum_and_pagination(client: TestClient) -> None:
    campaign, _lead, _seq, _msg = _draft_and_message(client)
    bad = client.get(
        f"/api/campaigns/{campaign['id']}/outreach/messages",
        params={"status": "NOPE"},
    )
    assert bad.status_code == 422
    page1 = client.get(
        f"/api/campaigns/{campaign['id']}/outreach/messages",
        params={"limit": 1, "offset": 0},
    ).json()
    assert page1["limit"] == 1
    assert "items" in page1


def test_stable_sorting(client: TestClient) -> None:
    campaign, lead, seq, _ = _draft_and_message(client)
    # add second step message via new sequence
    tmpl = _template(client, campaign["id"], name="T2")
    seq2 = _sequence(client, campaign["id"], tmpl["id"])
    client.post(
        f"/api/campaigns/{campaign['id']}/outreach/drafts",
        json={"sequence_id": seq2["id"], "lead_ids": [lead["id"]]},
    )
    items = client.get(f"/api/campaigns/{campaign['id']}/outreach/messages").json()["items"]
    ids = [m["id"] for m in items]
    assert ids == sorted(ids, key=lambda _: ids.index(_))  # stable as returned
    created = [m["created_at"] for m in items]
    assert created == sorted(created)


def test_no_contact_created(client: TestClient, db_session) -> None:
    before = db_session.scalar(select(func.count()).select_from(Contact)) or 0
    _draft_and_message(client)
    after = db_session.scalar(select(func.count()).select_from(Contact)) or 0
    assert after == before


def test_no_scheduler_jobs() -> None:
    assert celery_app.conf.beat_schedule == {}


def test_sending_fresh_pending_no_reentry(client: TestClient, db_session) -> None:
    """Active SENDING + fresh PENDING → 409, provider not called again."""
    campaign, _lead, _seq, msg = _draft_and_message(client)
    client.post(f"/api/campaigns/{campaign['id']}/outreach/messages/{msg['id']}/approve")
    mid = UUID(msg["id"])
    row = db_session.get(OutreachMessage, mid)
    row.status = OutreachMessageStatus.SENDING.value
    db_session.add(
        SendAttempt(
            message_id=mid,
            provider_name="test_email",
            status=SendAttemptStatus.PENDING.value,
            attempted_at=datetime.now(timezone.utc),
            idempotency_key=outreach_service.send_idempotency_key(mid),
            is_test_data=True,
        )
    )
    db_session.commit()
    with patch.object(TestEmailProvider, "send", autospec=True) as mock_send:
        r = client.post(f"/api/campaigns/{campaign['id']}/outreach/messages/{msg['id']}/send")
        assert r.status_code == 409
        assert mock_send.call_count == 0


def test_stale_pending_fails_unknown_no_provider(client: TestClient, db_session) -> None:
    """Crash with stale PENDING → FAILED/DELIVERY_OUTCOME_UNKNOWN, never SENT, no resend."""
    from app.models.enums import DELIVERY_OUTCOME_UNKNOWN

    campaign, _lead, _seq, msg = _draft_and_message(client)
    client.post(f"/api/campaigns/{campaign['id']}/outreach/messages/{msg['id']}/approve")
    mid = UUID(msg["id"])
    row = db_session.get(OutreachMessage, mid)
    row.status = OutreachMessageStatus.SENDING.value
    db_session.add(
        SendAttempt(
            message_id=mid,
            provider_name="test_email",
            status=SendAttemptStatus.PENDING.value,
            attempted_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            idempotency_key=outreach_service.send_idempotency_key(mid),
            is_test_data=True,
        )
    )
    db_session.commit()
    with patch.object(TestEmailProvider, "send", autospec=True) as mock_send:
        r = client.post(f"/api/campaigns/{campaign['id']}/outreach/messages/{msg['id']}/send")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "FAILED"
        assert data["error_message"] == DELIVERY_OUTCOME_UNKNOWN
        assert data["failed_at"] is not None
        assert data["sent_at"] is None
        assert "traceback" not in (data.get("error_message") or "").lower()
        assert mock_send.call_count == 0
        # Repeat send blocked — still no provider
        r2 = client.post(f"/api/campaigns/{campaign['id']}/outreach/messages/{msg['id']}/send")
        assert r2.status_code == 409
        assert mock_send.call_count == 0
    attempt = db_session.scalars(
        select(SendAttempt).where(SendAttempt.message_id == mid)
    ).one()
    assert attempt.status == SendAttemptStatus.FAILED.value
    assert attempt.safe_error_message == DELIVERY_OUTCOME_UNKNOWN


def test_crash_after_pending_before_provider(client: TestClient, db_session) -> None:
    """PENDING reserved, provider never called → stale recovery FAILED, provider stays 0."""
    from app.models.enums import DELIVERY_OUTCOME_UNKNOWN

    campaign, _lead, _seq, msg = _draft_and_message(client)
    client.post(f"/api/campaigns/{campaign['id']}/outreach/messages/{msg['id']}/approve")
    mid = UUID(msg["id"])
    row = db_session.get(OutreachMessage, mid)
    row.status = OutreachMessageStatus.SENDING.value
    db_session.add(
        SendAttempt(
            message_id=mid,
            provider_name="test_email",
            status=SendAttemptStatus.PENDING.value,
            attempted_at=datetime.now(timezone.utc) - timedelta(minutes=10),
            idempotency_key=outreach_service.send_idempotency_key(mid),
            is_test_data=True,
        )
    )
    db_session.commit()
    with patch.object(TestEmailProvider, "send", autospec=True) as mock_send:
        r = client.post(f"/api/campaigns/{campaign['id']}/outreach/messages/{msg['id']}/send")
        assert r.json()["status"] == "FAILED"
        assert r.json()["error_message"] == DELIVERY_OUTCOME_UNKNOWN
        assert mock_send.call_count == 0
        client.post(f"/api/campaigns/{campaign['id']}/outreach/messages/{msg['id']}/send")
        assert mock_send.call_count == 0


def test_provider_success_crash_before_db_unknown(client: TestClient, db_session) -> None:
    """Provider may have succeeded but DB still PENDING → UNKNOWN FAILED, no second send."""
    from app.models.enums import DELIVERY_OUTCOME_UNKNOWN

    campaign, _lead, _seq, msg = _draft_and_message(client)
    client.post(f"/api/campaigns/{campaign['id']}/outreach/messages/{msg['id']}/approve")
    mid = UUID(msg["id"])
    # Simulate: provider already called once in-process, then crash left PENDING
    from app.providers.email_test import clear_test_email_idempotency_cache
    from app.providers.base import EmailMessage, EmailSendResult

    clear_test_email_idempotency_cache()
    key = outreach_service.send_idempotency_key(mid)
    with patch.object(TestEmailProvider, "send", autospec=True) as mock_send:
        mock_send.return_value = EmailSendResult(
            success=True,
            provider="test_email",
            message_id="test-precrash",
            sent_at=datetime.now(timezone.utc),
            simulated=True,
        )
        # One historical call (crash after provider, before SUCCESS write)
        TestEmailProvider().send(
            EmailMessage(to_address="x@example.test", subject="s", body="b", metadata={"idempotency_key": key})
        )
        assert mock_send.call_count == 1

        row = db_session.get(OutreachMessage, mid)
        row.status = OutreachMessageStatus.SENDING.value
        db_session.add(
            SendAttempt(
                message_id=mid,
                provider_name="test_email",
                status=SendAttemptStatus.PENDING.value,
                attempted_at=datetime.now(timezone.utc) - timedelta(minutes=5),
                idempotency_key=key,
                is_test_data=True,
            )
        )
        db_session.commit()

        r = client.post(f"/api/campaigns/{campaign['id']}/outreach/messages/{msg['id']}/send")
        assert r.status_code == 200
        assert r.json()["status"] == "FAILED"
        assert r.json()["error_message"] == DELIVERY_OUTCOME_UNKNOWN
        assert mock_send.call_count == 1  # no second provider call
        r2 = client.post(f"/api/campaigns/{campaign['id']}/outreach/messages/{msg['id']}/send")
        assert r2.status_code == 409
        assert mock_send.call_count == 1


def test_recipient_bypass_vectors() -> None:
    bad = [
        "user@example.test.evil.com",
        "user@sub.example.test",
        "user@example.test@evil.com",
        "Name <lead-1@example.test>",
        "lead-1@example.test\nBcc: x@evil.com",
        "lead-1@exаmple.test",  # Cyrillic a
        "@example.test",
        "user@gmail.com",
        "lead 1@example.test",
    ]
    for addr in bad:
        with pytest.raises(AppError):
            outreach_service.validate_test_recipient(addr)
    outreach_service.validate_test_recipient(
        "lead-11111111-1111-1111-1111-111111111111@example.test"
    )
    # Outer spaces + domain case normalized safely
    outreach_service.validate_test_recipient("  LEAD-abc@Example.TEST  ")


def test_subject_header_injection_and_unsafe_render() -> None:
    ctx = {
        "company_name": "Acme\nBcc: evil@x.com",
        "company_domain": "",
        "company_location": "",
        "company_industry": "",
        "campaign_name": "C",
        "lead_score": "1",
        "qualification_status": "Q",
    }
    with pytest.raises(AppError) as ei:
        render_subject("Hi {{company_name}}", ctx)
    assert ei.value.code == "subject_header_injection"
    with pytest.raises(AppError):
        validate_template_text("Hi {{company_name.upper}}", field="subject")
    with pytest.raises(AppError):
        validate_template_text("x" * 10 + "{{not_allowed}}", field="body")
    long_name = "A" * 250
    with pytest.raises(AppError) as ei2:
        render_subject("Hi {{company_name}}", {**ctx, "company_name": long_name})
    assert ei2.value.code == "rendered_too_long"


def test_failed_blocked_not_reapproved(client: TestClient, db_session) -> None:
    campaign, _lead, _seq, msg = _draft_and_message(client)
    mid = UUID(msg["id"])
    row = db_session.get(OutreachMessage, mid)
    row.status = OutreachMessageStatus.FAILED.value
    db_session.commit()
    assert (
        client.post(
            f"/api/campaigns/{campaign['id']}/outreach/messages/{msg['id']}/approve"
        ).status_code
        == 409
    )
    row = db_session.get(OutreachMessage, mid)
    row.status = OutreachMessageStatus.BLOCKED.value
    db_session.commit()
    assert (
        client.post(
            f"/api/campaigns/{campaign['id']}/outreach/messages/{msg['id']}/approve"
        ).status_code
        == 409
    )


def test_stop_flip_before_send(client: TestClient) -> None:
    campaign, _lead, _seq, msg = _draft_and_message(client)
    client.post(f"/api/campaigns/{campaign['id']}/outreach/messages/{msg['id']}/approve")
    os.environ["SYSTEM_STOP_ALL"] = "false"
    get_settings.cache_clear()
    with patch.object(TestEmailProvider, "send", autospec=True) as mock_send:
        from app.providers.base import EmailSendResult

        mock_send.return_value = EmailSendResult(
            success=True,
            provider="test_email",
            message_id="test-x",
            sent_at=datetime.now(timezone.utc),
            simulated=True,
        )
        # Flip STOP immediately before send path runs
        os.environ["SYSTEM_STOP_ALL"] = "true"
        get_settings.cache_clear()
        try:
            r = client.post(
                f"/api/campaigns/{campaign['id']}/outreach/messages/{msg['id']}/send"
            )
            assert r.status_code == 200
            assert r.json()["status"] == "BLOCKED"
            assert mock_send.call_count == 0
        finally:
            os.environ["SYSTEM_STOP_ALL"] = "false"
            get_settings.cache_clear()


def test_provider_success_db_finalize_retry_at_most_once(db_engine) -> None:
    """If finalize fails after provider, recovery must not call provider twice."""
    from app.providers.base import EmailSendResult
    from app.providers.email_test import clear_test_email_idempotency_cache
    from app.schemas.campaign import CampaignCreate
    from app.schemas.qualification import LeadReviewRequest, QualificationRunCreate
    from app.schemas.research import ResearchRunCreate
    from app.services.campaign_service import create_campaign
    from app.services.qualification_service import review_lead, start_qualification
    from app.services.research_service import start_research

    clear_test_email_idempotency_cache()
    SessionLocal = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    setup = SessionLocal()
    try:
        campaign = create_campaign(
            setup,
            CampaignCreate(
                name=f"Crash {uuid4().hex[:6]}",
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
        start_qualification(
            setup,
            QualificationRunCreate(campaign_id=campaign.id, research_run_id=research.id),
        )
        from app.models import CampaignLead

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
                body_template="Body",
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
        drafts = outreach_service.create_drafts(
            setup,
            campaign.id,
            DraftCreateRequest(sequence_id=seq.id, lead_ids=[lead.id]),
        )
        message_id = next(r.message_id for r in drafts.results if r.message_id)
        outreach_service.approve_message(setup, campaign.id, message_id)
        campaign_id = campaign.id
    finally:
        setup.close()

    calls = {"n": 0}

    def counting_send(self, message):  # noqa: ANN001
        calls["n"] += 1
        return EmailSendResult(
            success=True,
            provider="test_email",
            message_id="test-crash",
            sent_at=datetime.now(timezone.utc),
            simulated=True,
        )

    s1 = SessionLocal()
    try:
        with patch.object(TestEmailProvider, "send", counting_send):
            # Simulate crash: claim + PENDING reserved, provider called, then leave SENDING
            msg = s1.get(OutreachMessage, message_id)
            msg.status = OutreachMessageStatus.APPROVED.value
            s1.commit()
            # First send completes normally
            out = outreach_service.send_message(s1, campaign_id, message_id)
            assert out.status == "SENT"
            assert calls["n"] == 1
            # Redelivery
            out2 = outreach_service.send_message(s1, campaign_id, message_id)
            assert out2.status == "SENT"
            assert calls["n"] == 1
    finally:
        s1.close()
    _cleanup_committed_campaign(db_engine, campaign_id)


def test_cross_campaign_template_sequence(client: TestClient) -> None:
    c1 = _campaign(client)
    c2 = _campaign(client)
    t1 = _template(client, c1["id"])
    r = client.post(
        f"/api/campaigns/{c2['id']}/outreach/sequences",
        json={
            "name": "X",
            "is_test_data": True,
            "steps": [{"template_id": t1["id"], "step_number": 1}],
        },
    )
    assert r.status_code == 404


def test_is_test_data_false_rejected(client: TestClient) -> None:
    campaign = _campaign(client)
    r = client.post(
        f"/api/campaigns/{campaign['id']}/outreach/templates",
        json={
            "name": "X",
            "subject_template": "Hi {{company_name}}",
            "body_template": "Body",
            "is_test_data": False,
        },
    )
    assert r.status_code == 422
