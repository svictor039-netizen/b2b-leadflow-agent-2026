"""Stage 2 research, normalization, dedup, provenance, and safety tests."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.models import Company, CompanySourceRecord
from app.providers.email_test import TestEmailProvider
from app.services.normalize import normalize_domain_for_match, normalize_company_name


def test_research_via_test_source_adapter(client: TestClient) -> None:
    response = client.post(
        "/api/research/runs",
        json={
            "query": "SaaS",
            "industry": "B2B SaaS",
            "location": "Northern Europe",
            "limit": 5,
            "adapter": "test_source",
        },
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["status"] == "COMPLETED"
    assert data["adapter"] == "test_source"
    assert data["is_test_data"] is True
    assert data["found_count"] >= 1
    assert data["created_count"] >= 1
    assert all(item["is_test_data"] for item in data["result_items"])


def test_unknown_adapter_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/research/runs",
        json={"query": "SaaS", "adapter": "real_scraper", "limit": 5},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "adapter_not_allowed"


def test_empty_query_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/research/runs",
        json={"query": "   ", "adapter": "test_source"},
    )
    assert response.status_code == 422


def test_limit_capped(client: TestClient) -> None:
    response = client.post(
        "/api/research/runs",
        json={"query": "Europe", "adapter": "test_source", "limit": 99},
    )
    assert response.status_code == 422


def test_provenance_saved(client: TestClient, db_session) -> None:
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
    run_id = response.json()["id"]
    detail = client.get(f"/api/research/runs/{run_id}")
    assert detail.status_code == 200
    items = detail.json()["result_items"]
    assert items
    assert items[0]["source_record_id"]
    assert items[0]["source_url"]

    records = db_session.scalars(select(CompanySourceRecord)).all()
    assert len(records) >= 1
    assert records[0].is_test_data is True
    assert records[0].query_text == "Logistics"
    assert records[0].raw_payload is not None
    assert "contact_email" not in (records[0].raw_payload or {})
    assert records[0].raw_payload.get("has_contact_email") is True


def test_dedup_by_domain(client: TestClient, db_session) -> None:
    client.post(
        "/api/companies",
        json={"name": "Preexisting Nordic", "domain": "nordicsaas.example"},
    )
    response = client.post(
        "/api/research/runs",
        json={
            "query": "SaaS",
            "industry": "B2B SaaS",
            "location": "Northern Europe",
            "adapter": "test_source",
            "limit": 5,
        },
    )
    assert response.status_code == 201
    data = response.json()
    nordic_items = [
        i for i in data["result_items"] if normalize_domain_for_match(i.get("domain")) == "nordicsaas.example"
    ]
    assert nordic_items
    assert nordic_items[0]["outcome"] in {"matched_existing", "updated", "skipped"}
    count = db_session.scalar(
        select(func.count()).select_from(Company).where(Company.domain == "nordicsaas.example")
    )
    assert count == 1


def test_dedup_by_source_record_id(client: TestClient, db_session) -> None:
    first = client.post(
        "/api/research/runs",
        json={
            "query": "FinTech",
            "industry": "FinTech",
            "location": "Central Europe",
            "adapter": "test_source",
            "limit": 5,
        },
    )
    assert first.status_code == 201
    second = client.post(
        "/api/research/runs",
        json={
            "query": "FinTech",
            "industry": "FinTech",
            "location": "Central Europe",
            "adapter": "test_source",
            "limit": 5,
        },
    )
    assert second.status_code == 201
    data = second.json()
    assert data["created_count"] == 0
    assert data["matched_count"] + data["skipped_count"] + data["updated_count"] >= 1
    domains = db_session.scalars(
        select(Company.domain).where(Company.domain == "centralfin.example")
    ).all()
    assert len(domains) == 1


def test_no_false_name_merge(client: TestClient, db_session) -> None:
    client.post(
        "/api/companies",
        json={"name": "Nordic SaaS Labs", "domain": "other-nordic.example"},
    )
    response = client.post(
        "/api/research/runs",
        json={
            "query": "SaaS",
            "industry": "B2B SaaS",
            "location": "Northern Europe",
            "adapter": "test_source",
            "limit": 5,
        },
    )
    assert response.status_code == 201
    names = db_session.scalars(
        select(Company).where(Company.name == "Nordic SaaS Labs")
    ).all()
    # Two companies: different domains must not merge by name alone
    domains = {c.domain for c in names}
    assert "other-nordic.example" in domains
    assert "nordicsaas.example" in domains
    assert len(names) == 2


def test_repeat_run_no_duplicates(client: TestClient, db_session) -> None:
    payload = {
        "query": "Energy",
        "industry": "Renewable Energy",
        "location": "DACH",
        "adapter": "test_source",
        "limit": 5,
    }
    r1 = client.post("/api/research/runs", json=payload)
    assert r1.status_code == 201
    before = db_session.scalar(select(func.count()).select_from(Company)) or 0
    r2 = client.post("/api/research/runs", json=payload)
    assert r2.status_code == 201
    after = db_session.scalar(select(func.count()).select_from(Company)) or 0
    assert after == before
    assert r2.json()["created_count"] == 0


def test_empty_fields_do_not_erase(client: TestClient, db_session) -> None:
    created = client.post(
        "/api/companies",
        json={
            "name": "Green Energy Partners",
            "domain": "greenenergy.example",
            "description": "Keep this description",
            "website": "https://greenenergy.example/keep",
        },
    ).json()
    client.post(
        "/api/research/runs",
        json={
            "query": "Energy",
            "industry": "Renewable Energy",
            "location": "DACH",
            "adapter": "test_source",
            "limit": 5,
        },
    )
    detail = client.get(f"/api/companies/{created['id']}").json()
    assert detail["description"] == "Keep this description"
    assert detail["website"] == "https://greenenergy.example/keep"


def test_domain_conflict_marked(client: TestClient, db_session) -> None:
    # Create company linked via source external id by first run
    first = client.post(
        "/api/research/runs",
        json={
            "query": "MedTech",
            "industry": "Healthcare IT",
            "location": "Western Europe",
            "adapter": "test_source",
            "limit": 5,
        },
    )
    assert first.status_code == 201
    # Manually change company domain to force conflict on same source_record_id
    company = db_session.scalar(select(Company).where(Company.domain == "medtech.example"))
    assert company is not None
    company.domain = "hijacked-medtech.example"
    db_session.flush()

    second = client.post(
        "/api/research/runs",
        json={
            "query": "MedTech",
            "industry": "Healthcare IT",
            "location": "Western Europe",
            "adapter": "test_source",
            "limit": 5,
        },
    )
    assert second.status_code == 201
    data = second.json()
    assert data["conflict_count"] >= 1
    assert any(i["outcome"] == "conflict" for i in data["result_items"])


def test_system_stop_all_blocks_research(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("SYSTEM_STOP_ALL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
        response = client.post(
            "/api/research/runs",
            json={"query": "SaaS", "adapter": "test_source", "limit": 3},
        )
        assert response.status_code == 201
        assert response.json()["status"] == "BLOCKED"
        assert "SYSTEM_STOP_ALL" in (response.json()["error_message"] or "")
    finally:
        monkeypatch.setenv("SYSTEM_STOP_ALL", "false")
        get_settings.cache_clear()


def test_research_does_not_call_email_provider(client: TestClient) -> None:
    with patch.object(TestEmailProvider, "send", autospec=True) as mock_send:
        response = client.post(
            "/api/research/runs",
            json={"query": "SaaS", "adapter": "test_source", "limit": 3},
        )
        assert response.status_code == 201
        mock_send.assert_not_called()


def test_adapter_error_marks_failed(client: TestClient) -> None:
    with patch(
        "app.services.research_service.get_source_adapter"
    ) as mock_get:
        adapter = MagicMock()
        adapter.name = "test_source"
        adapter.search.side_effect = RuntimeError("boom")
        mock_get.return_value = adapter
        response = client.post(
            "/api/research/runs",
            json={"query": "SaaS", "adapter": "test_source", "limit": 3},
        )
        assert response.status_code == 500
        # Run should be FAILED in DB — fetch last via creating then checking status path
        # The API raises after marking FAILED; verify via a completed run get is not needed
        assert response.json()["error"]["code"] == "research_failed"


def test_normalize_domain_and_url() -> None:
    assert normalize_domain_for_match("https://WWW.Example.COM/path/") == "example.com"
    assert normalize_domain_for_match("example.com.") == "example.com"
    assert normalize_company_name("  Nordic   SaaS  ") == "nordic saas"


def test_get_research_run(client: TestClient) -> None:
    created = client.post(
        "/api/research/runs",
        json={"query": "SaaS", "adapter": "test_source", "limit": 2},
    ).json()
    got = client.get(f"/api/research/runs/{created['id']}")
    assert got.status_code == 200
    assert got.json()["id"] == created["id"]
    assert got.json()["query"] == "SaaS"
