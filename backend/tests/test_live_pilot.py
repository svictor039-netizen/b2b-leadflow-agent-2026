"""Stage 7A controlled live pilot tests."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.models.live_pilot import LivePilot, LivePilotApproval, LivePilotEvent
from app.providers.email_test import TestEmailProvider
from app.workers.celery_app import celery_app


def _campaign(client: TestClient) -> dict:
    r = client.post(
        "/api/campaigns",
        json={
            "name": f"C7 {uuid4().hex[:6]}",
            "business_type": "B2B SaaS",
            "region": "Northern Europe",
            "offer": "Demo",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _approved_message(client: TestClient, campaign_id: str) -> dict:
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
    return client.get(
        f"/api/campaigns/{campaign_id}/outreach/messages",
        params={"status": "APPROVED", "limit": 10},
    ).json()["items"][0]


def _create_pilot(client: TestClient, campaign_id: str, message_id: str, key: str | None = None) -> dict:
    r = client.post(
        "/api/live-pilots",
        json={
            "campaign_id": campaign_id,
            "message_id": message_id,
            "idempotency_key": key or f"pilot-{uuid4().hex}",
            "max_recipients": 1,
            "is_test_data": True,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _setup_ready_pilot(client: TestClient) -> tuple[dict, dict]:
    campaign = _campaign(client)
    msg = _approved_message(client, campaign["id"])
    pilot = _create_pilot(client, campaign["id"], msg["id"])
    client.post(
        f"/api/live-pilots/{pilot['id']}/recipients",
        json={
            "outreach_message_id": msg["id"],
            "idempotency_key": f"rec-{uuid4().hex}",
        },
    )
    client.post(f"/api/live-pilots/{pilot['id']}/validate")
    return campaign, client.get(f"/api/live-pilots/{pilot['id']}").json()


def test_create_pilot(client: TestClient) -> None:
    campaign = _campaign(client)
    msg = _approved_message(client, campaign["id"])
    pilot = _create_pilot(client, campaign["id"], msg["id"])
    assert pilot["status"] == "DRAFT"
    assert pilot["live_delivery_enabled"] is False
    assert pilot["daily_limit"] == 0


def test_idempotent_create(client: TestClient) -> None:
    campaign = _campaign(client)
    msg = _approved_message(client, campaign["id"])
    key = f"idem-{uuid4().hex}"
    p1 = _create_pilot(client, campaign["id"], msg["id"], key)
    p2 = _create_pilot(client, campaign["id"], msg["id"], key)
    assert p1["id"] == p2["id"]


def test_one_active_pilot_per_campaign(client: TestClient) -> None:
    campaign = _campaign(client)
    msg = _approved_message(client, campaign["id"])
    _create_pilot(client, campaign["id"], msg["id"], f"a-{uuid4().hex}")
    r = client.post(
        "/api/live-pilots",
        json={
            "campaign_id": campaign["id"],
            "message_id": msg["id"],
            "idempotency_key": f"b-{uuid4().hex}",
            "is_test_data": True,
        },
    )
    assert r.status_code == 409


def test_real_recipient_rejected(client: TestClient) -> None:
    campaign = _campaign(client)
    msg = _approved_message(client, campaign["id"])
    pilot = _create_pilot(client, campaign["id"], msg["id"])
    r = client.post(
        f"/api/live-pilots/{pilot['id']}/recipients",
        json={
            "outreach_message_id": msg["id"],
            "recipient_email": "user@gmail.com",
            "idempotency_key": f"x-{uuid4().hex}",
        },
    )
    assert r.status_code == 422


def test_example_test_allowed(client: TestClient) -> None:
    campaign = _campaign(client)
    msg = _approved_message(client, campaign["id"])
    pilot = _create_pilot(client, campaign["id"], msg["id"])
    r = client.post(
        f"/api/live-pilots/{pilot['id']}/recipients",
        json={
            "outreach_message_id": msg["id"],
            "idempotency_key": f"ok-{uuid4().hex}",
        },
    )
    assert r.status_code == 201


def test_malformed_email_rejected(client: TestClient) -> None:
    campaign = _campaign(client)
    msg = _approved_message(client, campaign["id"])
    pilot = _create_pilot(client, campaign["id"], msg["id"])
    r = client.post(
        f"/api/live-pilots/{pilot['id']}/recipients",
        json={
            "outreach_message_id": msg["id"],
            "recipient_email": "bad@",
            "idempotency_key": f"m-{uuid4().hex}",
        },
    )
    assert r.status_code == 422


def test_duplicate_recipient_idempotent(client: TestClient) -> None:
    campaign = _campaign(client)
    msg = _approved_message(client, campaign["id"])
    pilot = _create_pilot(client, campaign["id"], msg["id"])
    key = f"dup-{uuid4().hex}"
    r1 = client.post(
        f"/api/live-pilots/{pilot['id']}/recipients",
        json={"outreach_message_id": msg["id"], "idempotency_key": key},
    )
    r2 = client.post(
        f"/api/live-pilots/{pilot['id']}/recipients",
        json={"outreach_message_id": msg["id"], "idempotency_key": key},
    )
    assert r1.status_code in {200, 201}
    assert r2.status_code in {200, 201}
    assert r1.json()["id"] == r2.json()["id"]


def test_cross_campaign_blocked(client: TestClient) -> None:
    c1 = _campaign(client)
    c2 = _campaign(client)
    msg1 = _approved_message(client, c1["id"])
    msg2 = _approved_message(client, c2["id"])
    pilot = _create_pilot(client, c1["id"], msg1["id"])
    r = client.post(
        f"/api/live-pilots/{pilot['id']}/recipients",
        json={
            "outreach_message_id": msg2["id"],
            "idempotency_key": f"cross-{uuid4().hex}",
        },
    )
    assert r.status_code == 404


def test_max_recipients_enforced(client: TestClient) -> None:
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
    leads = client.get(
        f"/api/campaigns/{campaign['id']}/leads",
        params={"limit": 20},
    ).json()["items"]
    assert leads, "expected at least one lead"
    client.post(
        f"/api/campaigns/{campaign['id']}/leads/{leads[0]['id']}/review",
        json={"decision": "APPROVED"},
    )
    tmpl = client.post(
        f"/api/campaigns/{campaign['id']}/outreach/templates",
        json={
            "name": "T",
            "subject_template": "Hi {{company_name}}",
            "body_template": "Body",
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
        json={"sequence_id": seq["id"], "lead_ids": [leads[0]["id"]]},
    )
    approved = client.get(
        f"/api/campaigns/{campaign['id']}/outreach/messages",
        params={"status": "APPROVED", "limit": 10},
    ).json()["items"]
    for m in client.get(
        f"/api/campaigns/{campaign['id']}/outreach/messages",
        params={"status": "DRAFT", "limit": 10},
    ).json()["items"]:
        client.post(f"/api/campaigns/{campaign['id']}/outreach/messages/{m['id']}/approve")
    approved = client.get(
        f"/api/campaigns/{campaign['id']}/outreach/messages",
        params={"status": "APPROVED", "limit": 10},
    ).json()["items"]
    assert len(approved) >= 2
    pilot = _create_pilot(client, campaign["id"], approved[0]["id"], f"max-{uuid4().hex}")
    client.post(
        f"/api/live-pilots/{pilot['id']}/recipients",
        json={"outreach_message_id": approved[0]["id"], "idempotency_key": f"r1-{uuid4().hex}"},
    )
    r = client.post(
        f"/api/live-pilots/{pilot['id']}/recipients",
        json={"outreach_message_id": approved[1]["id"], "idempotency_key": f"r2-{uuid4().hex}"},
    )
    assert r.status_code == 422


def test_client_cannot_raise_server_maximum(client: TestClient) -> None:
    campaign = _campaign(client)
    msg = _approved_message(client, campaign["id"])
    r = client.post(
        "/api/live-pilots",
        json={
            "campaign_id": campaign["id"],
            "message_id": msg["id"],
            "idempotency_key": f"hi-{uuid4().hex}",
            "max_recipients": 99,
            "is_test_data": True,
        },
    )
    assert r.status_code == 422


def test_daily_limit_remains_zero(client: TestClient) -> None:
    _, pilot = _setup_ready_pilot(client)
    assert pilot["daily_limit"] == 0


def test_rate_limit_remains_zero(client: TestClient) -> None:
    _, pilot = _setup_ready_pilot(client)
    assert pilot["per_minute_limit"] == 0


def test_live_enabled_cannot_pass_api(client: TestClient) -> None:
    campaign = _campaign(client)
    msg = _approved_message(client, campaign["id"])
    r = client.post(
        "/api/live-pilots",
        json={
            "campaign_id": campaign["id"],
            "message_id": msg["id"],
            "idempotency_key": f"live-{uuid4().hex}",
            "live_delivery_enabled": True,
            "is_test_data": True,
        },
    )
    assert r.status_code == 422


def test_unknown_provider_rejected(client: TestClient) -> None:
    campaign = _campaign(client)
    msg = _approved_message(client, campaign["id"])
    r = client.post(
        "/api/live-pilots",
        json={
            "campaign_id": campaign["id"],
            "message_id": msg["id"],
            "idempotency_key": f"prov-{uuid4().hex}",
            "provider_name": "sendgrid",
            "is_test_data": True,
        },
    )
    assert r.status_code == 422


def test_provider_credentials_rejected(client: TestClient) -> None:
    campaign = _campaign(client)
    msg = _approved_message(client, campaign["id"])
    r = client.post(
        "/api/live-pilots",
        json={
            "campaign_id": campaign["id"],
            "message_id": msg["id"],
            "idempotency_key": f"cred-{uuid4().hex}",
            "provider_api_key": "secret-key",
            "is_test_data": True,
        },
    )
    assert r.status_code == 422


def test_validation_blockers_deterministic(client: TestClient) -> None:
    campaign = _campaign(client)
    msg = _approved_message(client, campaign["id"])
    pilot = _create_pilot(client, campaign["id"], msg["id"])
    v1 = client.post(f"/api/live-pilots/{pilot['id']}/validate").json()
    v2 = client.post(f"/api/live-pilots/{pilot['id']}/validate").json()
    assert v1["blockers"] == v2["blockers"]
    assert "recipient_count" in v1["blockers"] or not v1["test_ready"]


def test_compliance_suppression_blocks_dry_run(client: TestClient) -> None:
    campaign, pilot = _setup_ready_pilot(client)
    msg = client.get(
        f"/api/campaigns/{campaign['id']}/outreach/messages",
        params={"status": "APPROVED", "limit": 1},
    ).json()["items"][0]
    client.post(
        "/api/compliance/suppressions",
        json={
            "scope": "CAMPAIGN",
            "campaign_id": campaign["id"],
            "suppression_type": "EMAIL",
            "value": msg["recipient_email"],
            "reason": "MANUAL_BLOCK",
            "is_test_data": True,
        },
    )
    r = client.post(
        f"/api/live-pilots/{pilot['id']}/dry-run",
        json={"idempotency_key": f"block-{uuid4().hex}"},
    )
    assert r.status_code == 409


def test_inactive_suppression_ignored(client: TestClient) -> None:
    campaign = _campaign(client)
    msg = _approved_message(client, campaign["id"])
    created = client.post(
        "/api/compliance/suppressions",
        json={
            "scope": "CAMPAIGN",
            "campaign_id": campaign["id"],
            "suppression_type": "EMAIL",
            "value": msg["recipient_email"],
            "reason": "MANUAL_BLOCK",
            "is_test_data": True,
        },
    ).json()
    client.post(f"/api/compliance/suppressions/{created['id']}/deactivate")
    pilot = _create_pilot(client, campaign["id"], msg["id"])
    client.post(
        f"/api/live-pilots/{pilot['id']}/recipients",
        json={"outreach_message_id": msg["id"], "idempotency_key": f"rec-{uuid4().hex}"},
    )
    chk = client.post(
        f"/api/campaigns/{campaign['id']}/compliance/check",
        json={"message_id": msg["id"]},
    ).json()
    assert chk["allowed"] is True


def test_system_stop_all_blocks_dry_run(client: TestClient) -> None:
    _, pilot = _setup_ready_pilot(client)
    os.environ["SYSTEM_STOP_ALL"] = "true"
    get_settings.cache_clear()
    try:
        r = client.post(
            f"/api/live-pilots/{pilot['id']}/dry-run",
            json={"idempotency_key": f"stop-{uuid4().hex}"},
        )
        assert r.status_code == 409
    finally:
        os.environ["SYSTEM_STOP_ALL"] = "false"
        get_settings.cache_clear()


def test_dry_run_uses_test_provider_only(client: TestClient) -> None:
    _, pilot = _setup_ready_pilot(client)
    provider = TestEmailProvider()
    with patch(
        "app.services.live_pilot_service.get_dry_run_provider",
        return_value=provider,
    ):
        with patch.object(provider, "send", wraps=provider.send) as mock_send:
            r = client.post(
                f"/api/live-pilots/{pilot['id']}/dry-run",
                json={"idempotency_key": f"prov-{uuid4().hex}"},
            )
            assert r.status_code in {200, 201}
            assert r.json()["provider"] == "test_email"
            assert mock_send.called


def test_dry_run_provider_count_exact(client: TestClient) -> None:
    _, pilot = _setup_ready_pilot(client)
    provider = TestEmailProvider()
    with patch(
        "app.services.live_pilot_service.get_dry_run_provider",
        return_value=provider,
    ):
        with patch.object(provider, "send", wraps=provider.send) as mock_send:
            client.post(
                f"/api/live-pilots/{pilot['id']}/dry-run",
                json={"idempotency_key": f"cnt-{uuid4().hex}"},
            )
            assert mock_send.call_count == 1


def test_dry_run_does_not_increment_live_counters(client: TestClient) -> None:
    _, pilot = _setup_ready_pilot(client)
    client.post(
        f"/api/live-pilots/{pilot['id']}/dry-run",
        json={"idempotency_key": f"lc-{uuid4().hex}"},
    )
    updated = client.get(f"/api/live-pilots/{pilot['id']}").json()
    assert updated["live_sent_count"] == 0


def test_dry_run_idempotent(client: TestClient) -> None:
    _, pilot = _setup_ready_pilot(client)
    key = f"idem-dry-{uuid4().hex}"
    r1 = client.post(
        f"/api/live-pilots/{pilot['id']}/dry-run",
        json={"idempotency_key": key},
    )
    r2 = client.post(
        f"/api/live-pilots/{pilot['id']}/dry-run",
        json={"idempotency_key": key},
    )
    assert r1.status_code in {200, 201}
    assert r2.status_code in {200, 201}


def test_approval_challenge_ttl(client: TestClient, db_session) -> None:
    from app.models.enums import APPROVAL_CHALLENGE_TTL_SECONDS

    _, pilot = _setup_ready_pilot(client)
    os.environ["SYSTEM_STOP_ALL"] = "false"
    get_settings.cache_clear()
    challenge = client.post(f"/api/live-pilots/{pilot['id']}/approve", json={}).json()
    assert challenge["confirmation_token"]
    approval = db_session.scalars(
        select(LivePilotApproval).where(LivePilotApproval.pilot_id == pilot["id"])
    ).first()
    assert approval is not None
    delta = (approval.expires_at - approval.created_at).total_seconds()
    assert 0 < delta <= APPROVAL_CHALLENGE_TTL_SECONDS + 5


def test_approval_token_stored_hashed(client: TestClient, db_session) -> None:
    _, pilot = _setup_ready_pilot(client)
    raw = client.post(f"/api/live-pilots/{pilot['id']}/approve", json={}).json()
    token = raw["confirmation_token"]
    approval = db_session.scalars(
        select(LivePilotApproval).where(LivePilotApproval.pilot_id == pilot["id"])
    ).first()
    assert approval is not None
    assert token not in approval.challenge_hash


def test_approval_token_one_time(client: TestClient) -> None:
    _, pilot = _setup_ready_pilot(client)
    ch = client.post(f"/api/live-pilots/{pilot['id']}/approve", json={}).json()
    token = ch["confirmation_token"]
    ok = client.post(
        f"/api/live-pilots/{pilot['id']}/approve",
        json={"confirmation_token": token},
    )
    assert ok.status_code == 200
    again = client.post(
        f"/api/live-pilots/{pilot['id']}/approve",
        json={"confirmation_token": token},
    )
    assert again.status_code == 409


def test_wrong_token_rejected(client: TestClient) -> None:
    _, pilot = _setup_ready_pilot(client)
    client.post(f"/api/live-pilots/{pilot['id']}/approve", json={})
    r = client.post(
        f"/api/live-pilots/{pilot['id']}/approve",
        json={"confirmation_token": "wrong-token-value"},
    )
    assert r.status_code == 422


def test_approval_does_not_start_live_send(client: TestClient) -> None:
    _, pilot = _setup_ready_pilot(client)
    ch = client.post(f"/api/live-pilots/{pilot['id']}/approve", json={}).json()
    approved = client.post(
        f"/api/live-pilots/{pilot['id']}/approve",
        json={"confirmation_token": ch["confirmation_token"]},
    ).json()
    assert approved["approved"] is True
    assert "live send remains disabled" in approved["message"].lower()
    assert client.get(f"/api/live-pilots/{pilot['id']}").json()["live_sent_count"] == 0


def test_cancel_terminal(client: TestClient) -> None:
    _, pilot = _setup_ready_pilot(client)
    cancelled = client.post(f"/api/live-pilots/{pilot['id']}/cancel").json()
    assert cancelled["status"] == "CANCELLED"
    again = client.post(f"/api/live-pilots/{pilot['id']}/cancel").json()
    assert again["status"] == "CANCELLED"


def test_no_live_send_endpoint(client: TestClient) -> None:
    app = client.app
    paths = sorted(
        {
            getattr(r, "path", "")
            for r in app.routes
            if hasattr(r, "methods") and "POST" in getattr(r, "methods", set())
        }
    )
    live_post_paths = [
        p
        for p in paths
        if "/api/live-pilots" in p or p.startswith("/api/live-pilots")
    ]
    assert "/api/live-pilots" in paths or any("live-pilots" in p for p in paths)
    assert any(p.endswith("/dry-run") and "live-pilots" in p for p in paths)
    assert not any(p.endswith("/send") and "live-pilots" in p for p in paths)
    assert not any("live-send" in p for p in live_post_paths)
    forbidden = [p for p in live_post_paths if p.endswith(("/enable-live", "/send-live", "/send"))]
    assert forbidden == []


def test_live_pilot_routes_exact_set(client: TestClient) -> None:
    app = client.app
    expected = {
        ("POST", "/api/live-pilots"),
        ("GET", "/api/live-pilots"),
        ("GET", "/api/live-pilots/{pilot_id}"),
        ("POST", "/api/live-pilots/{pilot_id}/validate"),
        ("POST", "/api/live-pilots/{pilot_id}/approve"),
        ("POST", "/api/live-pilots/{pilot_id}/cancel"),
        ("POST", "/api/live-pilots/{pilot_id}/dry-run"),
        ("GET", "/api/live-pilots/{pilot_id}/readiness"),
        ("GET", "/api/live-pilots/{pilot_id}/recipients"),
        ("POST", "/api/live-pilots/{pilot_id}/recipients"),
    }
    found = set()
    for route in app.routes:
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", "")
        if not methods or not path.startswith("/api/live-pilots"):
            continue
        for method in methods:
            if method in {"GET", "POST"}:
                found.add((method, path))
    assert expected.issubset(found)


def test_no_periodic_tasks() -> None:
    from app.workers import tasks

    for name in dir(tasks):
        if name.startswith("live_pilot"):
            pytest.fail(f"Unexpected periodic live pilot task: {name}")


def test_beat_schedule_empty() -> None:
    assert celery_app.conf.beat_schedule == {}


def test_readiness_returns_live_not_ready(client: TestClient) -> None:
    _, pilot = _setup_ready_pilot(client)
    r = client.get(f"/api/live-pilots/{pilot['id']}/readiness").json()
    assert r["live_ready"] is False
    assert r["live_mode_ready"] is False
    assert "stage7a_live_disabled" in r["blockers"]


def test_test_validation_succeeds(client: TestClient) -> None:
    _, pilot = _setup_ready_pilot(client)
    v = client.post(f"/api/live-pilots/{pilot['id']}/validate").json()
    assert v["test_ready"] is True
    assert v["overall_status"] in {
        "TEST_VALIDATED",
        "READY_FOR_PROVIDER_SELECTION",
    }


def test_secret_values_absent_from_json(client: TestClient) -> None:
    _, pilot = _setup_ready_pilot(client)
    raw = json.dumps(client.get(f"/api/live-pilots/{pilot['id']}").json()).lower()
    assert "provider_api_key" not in raw
    assert "smtp_password" not in raw
    assert "changeme" not in raw


def test_placeholder_api_key_missing(client: TestClient) -> None:
    os.environ["LIVE_PROVIDER_API_KEY"] = "your-api-key"
    get_settings.cache_clear()
    try:
        _, pilot = _setup_ready_pilot(client)
        r = client.get(f"/api/live-pilots/{pilot['id']}/readiness").json()
        provider_check = next(c for c in r["checks"] if c["name"] == "provider_configured")
        assert provider_check["passed"] is False
    finally:
        os.environ.pop("LIVE_PROVIDER_API_KEY", None)
        get_settings.cache_clear()


def test_audit_contains_masked_recipient(client: TestClient, db_session) -> None:
    _, pilot = _setup_ready_pilot(client)
    events = db_session.scalars(
        select(LivePilotEvent).where(LivePilotEvent.pilot_id == pilot["id"])
    ).all()
    masked = [e for e in events if e.masked_recipient and "***" in e.masked_recipient]
    assert masked


def test_audit_excludes_body_token_credentials(client: TestClient, db_session) -> None:
    _, pilot = _setup_ready_pilot(client)
    ch = client.post(f"/api/live-pilots/{pilot['id']}/approve", json={}).json()
    token = ch["confirmation_token"]
    client.post(
        f"/api/live-pilots/{pilot['id']}/approve",
        json={"confirmation_token": token},
    )
    events = db_session.scalars(
        select(LivePilotEvent).where(LivePilotEvent.pilot_id == pilot["id"])
    ).all()
    blob = json.dumps([e.safe_detail for e in events if e.safe_detail])
    assert token not in blob
    assert "api_key" not in blob.lower()


def test_allowlist_rejects_evil_domains(client: TestClient) -> None:
    campaign = _campaign(client)
    msg = _approved_message(client, campaign["id"])
    pilot = _create_pilot(client, campaign["id"], msg["id"])
    for email in (
        "user@example.test.evil.com",
        "user@sub.example.test",
        "Real User <user@example.test>",
        "user\r@example.test",
        "usér@example.test",
    ):
        r = client.post(
            f"/api/live-pilots/{pilot['id']}/recipients",
            json={
                "outreach_message_id": msg["id"],
                "recipient_email": email,
                "idempotency_key": f"evil-{uuid4().hex}",
            },
        )
        assert r.status_code == 422, email


def test_wrong_token_does_not_change_pilot(client: TestClient) -> None:
    _, pilot = _setup_ready_pilot(client)
    before_status = pilot["status"]
    client.post(f"/api/live-pilots/{pilot['id']}/approve", json={})
    r = client.post(
        f"/api/live-pilots/{pilot['id']}/approve",
        json={"confirmation_token": "definitely-wrong-token"},
    )
    assert r.status_code == 422
    refreshed = client.get(f"/api/live-pilots/{pilot['id']}").json()
    assert refreshed["status"] == before_status
    assert refreshed.get("approved_at") is None


def test_expired_token_does_not_change_pilot(client: TestClient, db_session) -> None:
    from datetime import timedelta

    from app.models.live_pilot import LivePilotApproval

    _, pilot = _setup_ready_pilot(client)
    ch = client.post(f"/api/live-pilots/{pilot['id']}/approve", json={}).json()
    approval = db_session.scalars(
        select(LivePilotApproval).where(LivePilotApproval.pilot_id == pilot["id"])
    ).first()
    assert approval is not None
    approval.expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    db_session.commit()
    r = client.post(
        f"/api/live-pilots/{pilot['id']}/approve",
        json={"confirmation_token": ch["confirmation_token"]},
    )
    assert r.status_code == 409
    refreshed = client.get(f"/api/live-pilots/{pilot['id']}").json()
    assert refreshed.get("approved_at") is None


def test_duplicate_approve_challenge_blocked(client: TestClient) -> None:
    _, pilot = _setup_ready_pilot(client)
    first = client.post(f"/api/live-pilots/{pilot['id']}/approve", json={})
    assert first.status_code == 200
    second = client.post(f"/api/live-pilots/{pilot['id']}/approve", json={})
    assert second.status_code == 409


def test_validation_blockers_order(client: TestClient) -> None:
    _, pilot = _setup_ready_pilot(client)
    r = client.get(f"/api/live-pilots/{pilot['id']}/readiness").json()
    blockers = r["blockers"]
    if len(blockers) >= 2:
        order = {
            "system_stop_all": 0,
            "compliance": 1,
            "allowlist": 2,
            "recipient_count": 3,
            "provider_selected": 4,
            "stage7a_live_disabled": 99,
        }
        indices = [order.get(b, 50) for b in blockers if b in order]
        assert indices == sorted(indices)


def test_concurrent_dry_run_single_provider_call(client: TestClient) -> None:
    """Sequential duplicate idempotency key must not invoke provider twice."""
    _, pilot = _setup_ready_pilot(client)
    provider = TestEmailProvider()
    key = f"concurrent-{uuid4().hex}"
    with patch(
        "app.services.live_pilot_service.get_dry_run_provider",
        return_value=provider,
    ):
        with patch.object(provider, "send", wraps=provider.send) as mock_send:
            r1 = client.post(
                f"/api/live-pilots/{pilot['id']}/dry-run",
                json={"idempotency_key": key},
            )
            r2 = client.post(
                f"/api/live-pilots/{pilot['id']}/dry-run",
                json={"idempotency_key": key},
            )
            assert r1.status_code in {200, 201}
            assert r2.status_code in {200, 201}
            assert mock_send.call_count == 1
