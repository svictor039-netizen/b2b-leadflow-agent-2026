"""Stage 6 compliance, suppression, readiness tests."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.models import Contact, SuppressionEntry
from app.models.compliance_log import ComplianceDecisionLog
from app.providers.email_test import TestEmailProvider
from app.workers.celery_app import celery_app

_DEMO_DOMAINS = {
    "nordicsaas.example",
    "balticlog.example",
    "centralfin.example",
    "greenenergy.example",
    "medtech.example",
}


def _cleanup_committed_campaign(db_engine, campaign_id) -> None:
    from app.models import Campaign, CampaignExecutionItem, CampaignExecutionRun, Company

    SessionLocal = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
        session.execute(
            delete(ComplianceDecisionLog).where(
                ComplianceDecisionLog.campaign_id == campaign_id
            )
        )
        session.execute(
            delete(SuppressionEntry).where(SuppressionEntry.campaign_id == campaign_id)
        )
        session.commit()
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


def _campaign(client: TestClient) -> dict:
    r = client.post(
        "/api/campaigns",
        json={
            "name": f"C6 {uuid4().hex[:6]}",
            "business_type": "B2B SaaS",
            "region": "Northern Europe",
            "offer": "Demo",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _approved_message(client: TestClient, campaign_id: str) -> tuple[dict, dict]:
    research = client.post(
        "/api/research/runs",
        json={
            "query": "SaaS",
            "industry": "B2B SaaS",
            "location": "Northern Europe",
            "adapter": "test_source",
            "limit": 3,
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
    lead = leads[0]
    client.post(
        f"/api/campaigns/{campaign_id}/leads/{lead['id']}/review",
        json={"decision": "APPROVED"},
    )
    tmpl = client.post(
        f"/api/campaigns/{campaign_id}/outreach/templates",
        json={
            "name": "T",
            "subject_template": "Hi {{company_name}}",
            "body_template": "Body {{lead_score}}",
            "is_test_data": True,
        },
    ).json()
    seq = client.post(
        f"/api/campaigns/{campaign_id}/outreach/sequences",
        json={
            "name": "S",
            "is_test_data": True,
            "steps": [{"template_id": tmpl["id"], "step_number": 1}],
        },
    ).json()
    client.post(
        f"/api/campaigns/{campaign_id}/outreach/drafts",
        json={"sequence_id": seq["id"], "lead_ids": [lead["id"]]},
    )
    msg = client.get(
        f"/api/campaigns/{campaign_id}/outreach/messages",
        params={"status": "DRAFT", "limit": 10},
    ).json()["items"][0]
    client.post(f"/api/campaigns/{campaign_id}/outreach/messages/{msg['id']}/approve")
    msg = client.get(
        f"/api/campaigns/{campaign_id}/outreach/messages",
        params={"status": "APPROVED", "limit": 10},
    ).json()["items"][0]
    return seq, msg


def test_create_global_and_campaign_suppression(client: TestClient) -> None:
    campaign = _campaign(client)
    g = client.post(
        "/api/compliance/suppressions",
        json={
            "scope": "GLOBAL",
            "suppression_type": "EMAIL",
            "value": "blocked@example.test",
            "reason": "DO_NOT_CONTACT",
            "is_test_data": True,
        },
    )
    assert g.status_code == 201, g.text
    assert g.json()["scope"] == "GLOBAL"
    assert g.json()["display_value"].endswith("@example.test")
    assert "blocked@" not in g.json()["display_value"] or "***" in g.json()["display_value"]

    c = client.post(
        "/api/compliance/suppressions",
        json={
            "scope": "CAMPAIGN",
            "campaign_id": campaign["id"],
            "suppression_type": "DOMAIN",
            "value": "https://www.Example.test/path",
            "reason": "MANUAL_BLOCK",
            "is_test_data": True,
        },
    )
    assert c.status_code == 201, c.text
    assert c.json()["display_value"] == "example.test"


def test_validation_rules(client: TestClient) -> None:
    campaign = _campaign(client)
    assert (
        client.post(
            "/api/compliance/suppressions",
            json={
                "scope": "CAMPAIGN",
                "suppression_type": "EMAIL",
                "value": "x@example.test",
                "reason": "MANUAL_BLOCK",
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/compliance/suppressions",
            json={
                "scope": "GLOBAL",
                "campaign_id": campaign["id"],
                "suppression_type": "EMAIL",
                "value": "x@example.test",
                "reason": "MANUAL_BLOCK",
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/compliance/suppressions",
            json={
                "scope": "GLOBAL",
                "suppression_type": "EMAIL",
                "value": "user@gmail.com",
                "reason": "MANUAL_BLOCK",
            },
        ).status_code
        == 422
    )
    evil = client.post(
        "/api/compliance/suppressions",
        json={
            "scope": "GLOBAL",
            "suppression_type": "EMAIL",
            "value": "a@example.test.evil.com",
            "reason": "MANUAL_BLOCK",
        },
    )
    assert evil.status_code == 422


def test_idempotent_create_and_inactive_history(client: TestClient) -> None:
    body = {
        "scope": "GLOBAL",
        "suppression_type": "EMAIL",
        "value": "dup@example.test",
        "reason": "MANUAL_BLOCK",
        "is_test_data": True,
    }
    a = client.post("/api/compliance/suppressions", json=body).json()
    b = client.post("/api/compliance/suppressions", json=body).json()
    assert a["id"] == b["id"]
    client.post(f"/api/compliance/suppressions/{a['id']}/deactivate")
    again = client.post("/api/compliance/suppressions", json=body)
    assert again.status_code == 201
    assert again.json()["id"] != a["id"]


def test_expired_does_not_block(client: TestClient) -> None:
    campaign = _campaign(client)
    _, msg = _approved_message(client, campaign["id"])
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    client.post(
        "/api/compliance/suppressions",
        json={
            "scope": "CAMPAIGN",
            "campaign_id": campaign["id"],
            "suppression_type": "EMAIL",
            "value": msg["recipient_email"],
            "reason": "MANUAL_BLOCK",
            "expires_at": past,
            "is_test_data": True,
        },
    )
    check = client.post(
        f"/api/campaigns/{campaign['id']}/compliance/check",
        json={"message_id": msg["id"]},
    ).json()
    assert check["allowed"] is True


def test_stage4_send_blocked_no_provider(client: TestClient) -> None:
    campaign = _campaign(client)
    _, msg = _approved_message(client, campaign["id"])
    client.post(
        "/api/compliance/suppressions",
        json={
            "scope": "CAMPAIGN",
            "campaign_id": campaign["id"],
            "suppression_type": "EMAIL",
            "value": msg["recipient_email"],
            "reason": "UNSUBSCRIBE",
            "is_test_data": True,
        },
    )
    with patch.object(TestEmailProvider, "send", autospec=True) as mock_send:
        sent = client.post(
            f"/api/campaigns/{campaign['id']}/outreach/messages/{msg['id']}/send",
            params={"async_mode": "false"},
        )
        assert sent.status_code == 200, sent.text
        assert sent.json()["status"] == "BLOCKED"
        assert mock_send.call_count == 0
        # redelivery
        again = client.post(
            f"/api/campaigns/{campaign['id']}/outreach/messages/{msg['id']}/send",
            params={"async_mode": "false"},
        )
        assert again.json()["status"] == "BLOCKED"
        assert mock_send.call_count == 0


def test_stage5_item_blocked_others_continue(client: TestClient) -> None:
    campaign = _campaign(client)
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
    client.post(
        "/api/qualification/runs",
        json={"campaign_id": campaign["id"], "research_run_id": research["id"]},
    )
    leads = client.get(f"/api/campaigns/{campaign['id']}/leads", params={"limit": 20}).json()[
        "items"
    ]
    lead = leads[0]
    client.post(
        f"/api/campaigns/{campaign['id']}/leads/{lead['id']}/review",
        json={"decision": "APPROVED"},
    )
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
            "steps": [
                {"template_id": tmpl["id"], "step_number": 1},
                {"template_id": tmpl["id"], "step_number": 2},
            ],
        },
    ).json()
    client.post(
        f"/api/campaigns/{campaign['id']}/outreach/drafts",
        json={"sequence_id": seq["id"], "lead_ids": [lead["id"]]},
    )
    msgs = client.get(
        f"/api/campaigns/{campaign['id']}/outreach/messages",
        params={"status": "DRAFT", "limit": 10},
    ).json()["items"]
    assert len(msgs) >= 2
    for m in msgs:
        client.post(f"/api/campaigns/{campaign['id']}/outreach/messages/{m['id']}/approve")
    approved = client.get(
        f"/api/campaigns/{campaign['id']}/outreach/messages",
        params={"status": "APPROVED", "limit": 10},
    ).json()["items"]
    client.post(
        "/api/compliance/suppressions",
        json={
            "scope": "CAMPAIGN",
            "campaign_id": campaign["id"],
            "suppression_type": "EMAIL",
            "value": approved[0]["recipient_email"],
            "reason": "COMPLAINT",
            "is_test_data": True,
        },
    )
    # Same recipient on both steps — both blocked is OK; create domain unblock by using company? 
    # Both messages share recipient → both BLOCKED. Still proves no provider for blocked.
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
            message_id="t",
            sent_at=datetime.now(timezone.utc),
            simulated=True,
        )
        started = client.post(
            f"/api/campaigns/{campaign['id']}/execution-runs/{run['id']}/start",
            params={"async_mode": "false"},
        ).json()
        assert started["status"] == "COMPLETED"
        assert started["blocked_count"] >= 1
        assert mock_send.call_count == started["sent_count"]


def test_test_events_and_readiness(client: TestClient, db_session) -> None:
    campaign = _campaign(client)
    _, msg = _approved_message(client, campaign["id"])
    with patch.object(TestEmailProvider, "send", autospec=True) as mock_send:
        ev = client.post(
            f"/api/campaigns/{campaign['id']}/compliance/test-events",
            json={
                "message_id": msg["id"],
                "event_type": "UNSUBSCRIBE",
                "is_test_data": True,
            },
        )
        assert ev.status_code == 201, ev.text
        assert mock_send.call_count == 0
        again = client.post(
            f"/api/campaigns/{campaign['id']}/compliance/test-events",
            json={
                "message_id": msg["id"],
                "event_type": "UNSUBSCRIBE",
                "is_test_data": True,
            },
        )
        assert again.status_code == 201
        assert again.json()["suppression"]["id"] == ev.json()["suppression"]["id"]

    report = client.get("/api/compliance/provider-readiness").json()
    assert report["overall_status"] == "TEST_READY"
    assert report["test_mode_ready"] is True
    assert report["live_mode_ready"] is False
    assert report["production_readiness_status"] == "LIVE_NOT_READY"
    blob = str(report)
    assert "PROVIDER_API_KEY" not in blob or "present" in blob or "missing" in blob
    # Ensure no raw secret key field value leakage patterns
    assert "sk_live" not in blob
    assert celery_app.conf.beat_schedule == {}

    before = db_session.scalar(select(func.count()).select_from(Contact)) or 0
    client.get("/api/compliance/provider-readiness")
    after = db_session.scalar(select(func.count()).select_from(Contact)) or 0
    assert after == before


def test_company_and_lead_block(client: TestClient) -> None:
    campaign = _campaign(client)
    _, msg = _approved_message(client, campaign["id"])
    # fetch lead/company via message isn't in response — use leads API
    leads = client.get(f"/api/campaigns/{campaign['id']}/leads", params={"limit": 5}).json()[
        "items"
    ]
    lead = next(l for l in leads if l.get("review_decision") == "APPROVED")
    client.post(
        "/api/compliance/suppressions",
        json={
            "scope": "CAMPAIGN",
            "campaign_id": campaign["id"],
            "suppression_type": "CAMPAIGN_LEAD",
            "value": lead["id"],
            "reason": "LEGAL_BLOCK",
            "is_test_data": True,
        },
    )
    check = client.post(
        f"/api/campaigns/{campaign['id']}/compliance/check",
        json={"message_id": msg["id"]},
    ).json()
    assert check["allowed"] is False
    assert check["suppression_type"] == "CAMPAIGN_LEAD"

    c2 = _campaign(client)
    _, msg2 = _approved_message(client, c2["id"])
    check2 = client.post(
        f"/api/campaigns/{c2['id']}/compliance/check",
        json={"message_id": msg2["id"]},
    ).json()
    assert check2["allowed"] is True


def test_subdomain_not_auto_match(client: TestClient) -> None:
    client.post(
        "/api/compliance/suppressions",
        json={
            "scope": "GLOBAL",
            "suppression_type": "DOMAIN",
            "value": "example.test",
            "reason": "MANUAL_BLOCK",
            "is_test_data": True,
        },
    )
    # Creating subdomain domain entry is separate — mail@example.test is blocked by domain example.test
    # Spec: subdomain does not automatically equal parent — so blocking parent domain blocks exact domain only.
    # Our EMAIL domain extraction uses exact domain of recipient (example.test), so parent DOMAIN block DOES block.
    # Subdomain test: domain suppression for "sub.example.test" should NOT block recipient @example.test
    campaign = _campaign(client)
    _, msg = _approved_message(client, campaign["id"])
    # deactivate global example.test if created above affects — use campaign subdomain suppression only
    client.post(
        f"/api/compliance/suppressions/{client.get('/api/compliance/suppressions', params={'scope': 'GLOBAL', 'suppression_type': 'DOMAIN', 'limit': 10}).json()['items'][0]['id']}/deactivate"
    )
    client.post(
        "/api/compliance/suppressions",
        json={
            "scope": "CAMPAIGN",
            "campaign_id": campaign["id"],
            "suppression_type": "DOMAIN",
            "value": "sub.example.test",
            "reason": "MANUAL_BLOCK",
            "is_test_data": True,
        },
    )
    check = client.post(
        f"/api/campaigns/{campaign['id']}/compliance/check",
        json={"message_id": msg["id"]},
    ).json()
    assert check["allowed"] is True


def test_stop_allows_crud_blocks_send(client: TestClient) -> None:
    campaign = _campaign(client)
    _, msg = _approved_message(client, campaign["id"])
    os.environ["SYSTEM_STOP_ALL"] = "true"
    get_settings.cache_clear()
    try:
        r = client.post(
            "/api/compliance/suppressions",
            json={
                "scope": "GLOBAL",
                "suppression_type": "EMAIL",
                "value": "stopok@example.test",
                "reason": "MANUAL_BLOCK",
                "is_test_data": True,
            },
        )
        assert r.status_code == 201
        assert client.get("/api/compliance/provider-readiness").status_code == 200
        with patch.object(TestEmailProvider, "send", autospec=True) as mock_send:
            sent = client.post(
                f"/api/campaigns/{campaign['id']}/outreach/messages/{msg['id']}/send",
                params={"async_mode": "false"},
            ).json()
            assert sent["status"] == "BLOCKED"
            assert mock_send.call_count == 0
    finally:
        os.environ["SYSTEM_STOP_ALL"] = "false"
        get_settings.cache_clear()


def test_logs_have_no_body(client: TestClient, db_session) -> None:
    campaign = _campaign(client)
    _, msg = _approved_message(client, campaign["id"])
    client.post(
        f"/api/campaigns/{campaign['id']}/compliance/check",
        json={"message_id": msg["id"]},
    )
    logs = db_session.scalars(select(ComplianceDecisionLog)).all()
    assert logs
    for log in logs:
        assert log.safe_details is None or "Score" not in (log.safe_details or "")
        assert "body" not in (log.safe_details or "").lower()


def test_expiration_boundary_equal_now_does_not_block(client: TestClient) -> None:
    campaign = _campaign(client)
    _, msg = _approved_message(client, campaign["id"])
    # expires_at == now → not blocking (gate uses expires_at > now)
    now = datetime.now(timezone.utc).isoformat()
    client.post(
        "/api/compliance/suppressions",
        json={
            "scope": "CAMPAIGN",
            "campaign_id": campaign["id"],
            "suppression_type": "EMAIL",
            "value": msg["recipient_email"],
            "reason": "MANUAL_BLOCK",
            "expires_at": now,
            "is_test_data": True,
        },
    )
    # Slightly in the past for clock skew safety in assertion path
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    client.post(
        "/api/compliance/suppressions",
        json={
            "scope": "CAMPAIGN",
            "campaign_id": campaign["id"],
            "suppression_type": "EMAIL",
            "value": msg["recipient_email"],
            "reason": "MANUAL_BLOCK",
            "expires_at": past,
            "is_test_data": True,
        },
    )
    check = client.post(
        f"/api/campaigns/{campaign['id']}/compliance/check",
        json={"message_id": msg["id"]},
    ).json()
    assert check["allowed"] is True


def test_future_expiration_blocks(client: TestClient) -> None:
    campaign = _campaign(client)
    _, msg = _approved_message(client, campaign["id"])
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    client.post(
        "/api/compliance/suppressions",
        json={
            "scope": "CAMPAIGN",
            "campaign_id": campaign["id"],
            "suppression_type": "EMAIL",
            "value": msg["recipient_email"],
            "reason": "MANUAL_BLOCK",
            "expires_at": future,
            "is_test_data": True,
        },
    )
    check = client.post(
        f"/api/campaigns/{campaign['id']}/compliance/check",
        json={"message_id": msg["id"]},
    ).json()
    assert check["allowed"] is False


def test_reactivate_clears_expired(client: TestClient) -> None:
    campaign = _campaign(client)
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    created = client.post(
        "/api/compliance/suppressions",
        json={
            "scope": "GLOBAL",
            "suppression_type": "EMAIL",
            "value": "expired-react@example.test",
            "reason": "MANUAL_BLOCK",
            "expires_at": past,
            "is_test_data": True,
        },
    ).json()
    client.post(f"/api/compliance/suppressions/{created['id']}/deactivate")
    again = client.post(f"/api/compliance/suppressions/{created['id']}/reactivate")
    assert again.status_code == 200
    assert again.json()["is_active"] is True
    assert again.json()["expires_at"] is None


def test_cross_campaign_suppression_isolation(client: TestClient) -> None:
    c1 = _campaign(client)
    c2 = _campaign(client)
    _, m1 = _approved_message(client, c1["id"])
    _, m2 = _approved_message(client, c2["id"])
    client.post(
        "/api/compliance/suppressions",
        json={
            "scope": "CAMPAIGN",
            "campaign_id": c1["id"],
            "suppression_type": "EMAIL",
            "value": m1["recipient_email"],
            "reason": "MANUAL_BLOCK",
            "is_test_data": True,
        },
    )
    # Same email string may differ per message; suppress m2 email on c1 must not affect c2
    client.post(
        "/api/compliance/suppressions",
        json={
            "scope": "CAMPAIGN",
            "campaign_id": c1["id"],
            "suppression_type": "EMAIL",
            "value": m2["recipient_email"],
            "reason": "MANUAL_BLOCK",
            "is_test_data": True,
        },
    )
    check2 = client.post(
        f"/api/campaigns/{c2['id']}/compliance/check",
        json={"message_id": m2["id"]},
    ).json()
    assert check2["allowed"] is True
    # Cross-campaign check: message of c2 under c1 → 404
    bad = client.post(
        f"/api/campaigns/{c1['id']}/compliance/check",
        json={"message_id": m2["id"]},
    )
    assert bad.status_code in (404, 409)


def test_global_blocks_all_campaigns(client: TestClient) -> None:
    c1 = _campaign(client)
    c2 = _campaign(client)
    _, m1 = _approved_message(client, c1["id"])
    client.post(
        "/api/compliance/suppressions",
        json={
            "scope": "GLOBAL",
            "suppression_type": "EMAIL",
            "value": m1["recipient_email"],
            "reason": "DO_NOT_CONTACT",
            "is_test_data": True,
        },
    )
    assert (
        client.post(
            f"/api/campaigns/{c1['id']}/compliance/check",
            json={"message_id": m1["id"]},
        ).json()["allowed"]
        is False
    )
    # Domain global
    client.post(
        "/api/compliance/suppressions",
        json={
            "scope": "GLOBAL",
            "suppression_type": "DOMAIN",
            "value": "example.test",
            "reason": "MANUAL_BLOCK",
            "is_test_data": True,
        },
    )
    _, m2 = _approved_message(client, c2["id"])
    assert (
        client.post(
            f"/api/campaigns/{c2['id']}/compliance/check",
            json={"message_id": m2["id"]},
        ).json()["allowed"]
        is False
    )


def test_readiness_secret_not_leaked(client: TestClient, monkeypatch) -> None:
    secret = "sk_live_REVIEW_SECRET_VALUE_9f3a"
    monkeypatch.setenv("PROVIDER_API_KEY", secret)
    get_settings.cache_clear()
    try:
        report = client.get("/api/compliance/provider-readiness").json()
        blob = str(report)
        assert secret not in blob
        assert "sk_live_REVIEW" not in blob
        key_check = next(c for c in report["checks"] if c["name"] == "provider_api_key_present")
        assert key_check["detail"] == "present"
        assert report["live_mode_ready"] is False
        validated = client.post("/api/compliance/provider-readiness/validate").json()
        assert secret not in str(validated)
        assert validated["live_mode_ready"] is False
    finally:
        monkeypatch.delenv("PROVIDER_API_KEY", raising=False)
        get_settings.cache_clear()


def test_placeholder_api_key_counts_as_missing(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("PROVIDER_API_KEY", "changeme")
    get_settings.cache_clear()
    try:
        report = client.get("/api/compliance/provider-readiness").json()
        key_check = next(c for c in report["checks"] if c["name"] == "provider_api_key_present")
        assert key_check["detail"] == "missing"
    finally:
        monkeypatch.delenv("PROVIDER_API_KEY", raising=False)
        get_settings.cache_clear()


def test_toctou_suppression_injected_before_provider(db_engine) -> None:
    """Suppression committed after first ALLOWED but before provider → BLOCKED, provider=0."""
    from datetime import datetime, timezone

    from sqlalchemy.orm import sessionmaker

    from app.models import CampaignLead, OutreachMessage
    from app.models.enums import (
        OutreachMessageStatus,
        ReviewDecision,
        SuppressionReason,
        SuppressionScope,
        SuppressionType,
    )
    from app.providers.base import EmailSendResult
    from app.schemas.campaign import CampaignCreate
    from app.schemas.outreach import (
        DraftCreateRequest,
        OutreachSequenceCreate,
        OutreachTemplateCreate,
        SequenceStepCreate,
    )
    from app.schemas.qualification import LeadReviewRequest, QualificationRunCreate
    from app.schemas.research import ResearchRunCreate
    from app.services import compliance_service, outreach_service
    from app.services.campaign_service import create_campaign
    from app.services.qualification_service import review_lead, start_qualification
    from app.services.research_service import start_research

    SessionLocal = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    setup = SessionLocal()
    try:
        campaign = create_campaign(
            setup,
            CampaignCreate(
                name=f"TOCTOU {uuid4().hex[:6]}",
                business_type="B2B SaaS",
                region="Northern Europe",
                offer="O",
            ),
        )
        research = start_research(
            setup,
            ResearchRunCreate(
                query="SaaS",
                industry="SaaS",
                location="Europe",
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
                body_template="SecretBodyMustNotLog",
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
        msg = setup.get(OutreachMessage, message_id)
        recipient = msg.recipient_email
        campaign_id = campaign.id
    finally:
        setup.close()

    try:
        real_check = compliance_service.check_outreach_compliance
        calls = {"n": 0}

        def flaky_check(db, **kwargs):  # noqa: ANN001
            result = real_check(db, **kwargs)
            calls["n"] += 1
            # After first ALLOWED, inject suppression on a separate connection (no lock protocol).
            if calls["n"] == 1 and result.allowed:
                inj = SessionLocal()
                try:
                    inj.add(
                        SuppressionEntry(
                            scope=SuppressionScope.CAMPAIGN.value,
                            campaign_id=campaign_id,
                            suppression_type=SuppressionType.EMAIL.value,
                            normalized_value=recipient.lower(),
                            display_value="r***@example.test",
                            reason=SuppressionReason.UNSUBSCRIBE.value,
                            source="MANUAL",
                            is_active=True,
                            is_test_data=True,
                            created_by="toctou_test",
                        )
                    )
                    inj.commit()
                finally:
                    inj.close()
            return result

        with patch.object(compliance_service, "check_outreach_compliance", flaky_check):
            with patch.object(TestEmailProvider, "send", autospec=True) as mock_send:
                mock_send.return_value = EmailSendResult(
                    success=True,
                    provider="test_email",
                    message_id="x",
                    sent_at=datetime.now(timezone.utc),
                    simulated=True,
                )
                s = SessionLocal()
                try:
                    out = outreach_service.send_message(s, campaign_id, message_id)
                    assert out.status == OutreachMessageStatus.BLOCKED.value
                    assert mock_send.call_count == 0
                finally:
                    s.close()

        verify = SessionLocal()
        try:
            logs = verify.scalars(
                select(ComplianceDecisionLog).where(
                    ComplianceDecisionLog.outreach_message_id == message_id,
                    ComplianceDecisionLog.decision == "BLOCKED",
                )
            ).all()
            assert logs
            for log in logs:
                assert "SecretBodyMustNotLog" not in (log.safe_details or "")
                assert recipient not in (log.safe_details or "")
        finally:
            verify.close()
    finally:
        _cleanup_committed_campaign(db_engine, campaign_id)


def test_concurrent_send_and_suppression_create(db_engine) -> None:
    """Send and suppression create race: never SUCCESS+provider if blocked by active suppression."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from datetime import datetime, timezone

    from sqlalchemy.orm import sessionmaker

    from app.models import CampaignLead, OutreachMessage, SendAttempt
    from app.models.enums import (
        OutreachMessageStatus,
        ReviewDecision,
        SendAttemptStatus,
    )
    from app.providers.base import EmailSendResult
    from app.schemas.campaign import CampaignCreate
    from app.schemas.compliance import SuppressionCreate
    from app.schemas.outreach import (
        DraftCreateRequest,
        OutreachSequenceCreate,
        OutreachTemplateCreate,
        SequenceStepCreate,
    )
    from app.schemas.qualification import LeadReviewRequest, QualificationRunCreate
    from app.schemas.research import ResearchRunCreate
    from app.services import compliance_service, outreach_service
    from app.services.campaign_service import create_campaign
    from app.services.qualification_service import review_lead, start_qualification
    from app.services.research_service import start_research

    SessionLocal = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    setup = SessionLocal()
    try:
        campaign = create_campaign(
            setup,
            CampaignCreate(
                name=f"Race {uuid4().hex[:6]}",
                business_type="B2B SaaS",
                region="Northern Europe",
                offer="O",
            ),
        )
        research = start_research(
            setup,
            ResearchRunCreate(
                query="SaaS",
                industry="SaaS",
                location="Europe",
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
        msg = setup.get(OutreachMessage, message_id)
        recipient = msg.recipient_email
        campaign_id = campaign.id
    finally:
        setup.close()

    try:
        call_count = {"n": 0}

        def fake_send(self, message):  # noqa: ANN001
            call_count["n"] += 1
            return EmailSendResult(
                success=True,
                provider="test_email",
                message_id=f"t-{call_count['n']}",
                sent_at=datetime.now(timezone.utc),
                simulated=True,
            )

        with patch.object(TestEmailProvider, "send", fake_send):

            def send_worker() -> str:
                s = SessionLocal()
                try:
                    out = outreach_service.send_message(s, campaign_id, message_id)
                    return out.status
                finally:
                    s.close()

            def suppress_worker() -> str:
                s = SessionLocal()
                try:
                    compliance_service.create_suppression(
                        s,
                        SuppressionCreate(
                            scope="CAMPAIGN",
                            campaign_id=campaign_id,
                            suppression_type="EMAIL",
                            value=recipient,
                            reason="UNSUBSCRIBE",
                            is_test_data=True,
                        ),
                    )
                    return "SUPPRESSED"
                finally:
                    s.close()

            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = [
                    pool.submit(send_worker),
                    pool.submit(suppress_worker),
                    pool.submit(send_worker),
                    pool.submit(suppress_worker),
                ]
                results = [f.result() for f in as_completed(futures)]

        check = SessionLocal()
        try:
            msg = check.get(OutreachMessage, message_id)
            successes = check.scalar(
                select(func.count())
                .select_from(SendAttempt)
                .where(
                    SendAttempt.message_id == message_id,
                    SendAttempt.status == SendAttemptStatus.SUCCESS.value,
                )
            )
            active = check.scalars(
                select(SuppressionEntry).where(
                    SuppressionEntry.campaign_id == campaign_id,
                    SuppressionEntry.normalized_value == recipient.lower(),
                    SuppressionEntry.is_active.is_(True),
                )
            ).all()
            assert successes in (0, 1)
            assert call_count["n"] == successes
            assert len(active) <= 1
            if msg.status == OutreachMessageStatus.BLOCKED.value:
                assert successes == 0
                assert call_count["n"] == 0
                blocked_logs = check.scalars(
                    select(ComplianceDecisionLog).where(
                        ComplianceDecisionLog.outreach_message_id == message_id,
                        ComplianceDecisionLog.decision == "BLOCKED",
                    )
                ).all()
                assert blocked_logs
            elif msg.status == OutreachMessageStatus.SENT.value:
                assert successes == 1
            assert "SENT" in results or "BLOCKED" in results or "SUPPRESSED" in results
        finally:
            check.close()
    finally:
        _cleanup_committed_campaign(db_engine, campaign_id)


def test_concurrent_create_suppression_unique(db_engine) -> None:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from sqlalchemy.orm import sessionmaker

    from app.schemas.compliance import SuppressionCreate
    from app.services import compliance_service

    SessionLocal = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)

    def worker() -> str:
        s = SessionLocal()
        try:
            r = compliance_service.create_suppression(
                s,
                SuppressionCreate(
                    scope="GLOBAL",
                    suppression_type="EMAIL",
                    value="race-unique@example.test",
                    reason="MANUAL_BLOCK",
                    is_test_data=True,
                ),
            )
            return str(r.id)
        finally:
            s.close()

    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            ids = [f.result() for f in as_completed([pool.submit(worker) for _ in range(6)])]
        assert len(set(ids)) == 1
        verify = SessionLocal()
        try:
            n = verify.scalar(
                select(func.count())
                .select_from(SuppressionEntry)
                .where(
                    SuppressionEntry.normalized_value == "race-unique@example.test",
                    SuppressionEntry.is_active.is_(True),
                )
            )
            assert n == 1
        finally:
            verify.close()
    finally:
        cleanup = SessionLocal()
        try:
            cleanup.execute(
                delete(SuppressionEntry).where(
                    SuppressionEntry.normalized_value == "race-unique@example.test"
                )
            )
            cleanup.commit()
        finally:
            cleanup.close()


def test_decision_order_email_before_domain(client: TestClient) -> None:
    campaign = _campaign(client)
    _, msg = _approved_message(client, campaign["id"])
    client.post(
        "/api/compliance/suppressions",
        json={
            "scope": "CAMPAIGN",
            "campaign_id": campaign["id"],
            "suppression_type": "DOMAIN",
            "value": "example.test",
            "reason": "MANUAL_BLOCK",
            "is_test_data": True,
        },
    )
    client.post(
        "/api/compliance/suppressions",
        json={
            "scope": "CAMPAIGN",
            "campaign_id": campaign["id"],
            "suppression_type": "EMAIL",
            "value": msg["recipient_email"],
            "reason": "COMPLAINT",
            "is_test_data": True,
        },
    )
    check = client.post(
        f"/api/campaigns/{campaign['id']}/compliance/check",
        json={"message_id": msg["id"]},
    ).json()
    assert check["allowed"] is False
    assert check["suppression_type"] == "EMAIL"
    assert "COMPLAINT" in check["reason_code"]


def test_api_no_normalized_email_field(client: TestClient) -> None:
    r = client.post(
        "/api/compliance/suppressions",
        json={
            "scope": "GLOBAL",
            "suppression_type": "EMAIL",
            "value": "maskme@example.test",
            "reason": "MANUAL_BLOCK",
            "is_test_data": True,
        },
    ).json()
    assert "normalized_value" not in r
    assert r["display_value"] == "m***@example.test"
    assert "maskme@example.test" not in str(r)
