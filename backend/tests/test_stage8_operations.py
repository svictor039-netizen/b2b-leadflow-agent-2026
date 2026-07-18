"""Stage 8 operational endpoints, logging, and metrics tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.logging.setup import redact_secrets
from app.main import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_liveness(client: TestClient) -> None:
    response = client.get("/api/liveness")
    assert response.status_code == 200
    assert response.json()["status"] == "alive"


def test_health_unchanged(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_version_stage8(client: TestClient) -> None:
    response = client.get("/api/version")
    assert response.status_code == 200
    data = response.json()
    assert data["stage"] == "8"


def test_readiness_includes_migrations(client: TestClient) -> None:
    response = client.get("/api/readiness")
    assert response.status_code in {200, 503}
    data = response.json()
    assert "migrations" in data["checks"]
    assert "runtime" in data
    assert "system_stop_all" in data["runtime"]


def test_readiness_fails_when_postgres_unavailable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.services.readiness_service.check_database_connection", lambda: False)
    response = client.get("/api/readiness")
    assert response.status_code == 503
    assert response.json()["checks"]["postgres"] == "fail"


def test_readiness_fails_when_redis_unavailable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.services.readiness_service.check_redis_connection", lambda: False)
    response = client.get("/api/readiness")
    assert response.status_code == 503
    assert response.json()["checks"]["redis"] == "fail"


def test_readiness_fails_when_migrations_behind(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.services.readiness_service.check_migrations_current",
        lambda: (False, "behind_head"),
    )
    response = client.get("/api/readiness")
    assert response.status_code == 503
    assert response.json()["checks"]["migrations"] == "behind_head"


def test_readiness_response_has_no_secrets(client: TestClient) -> None:
    response = client.get("/api/readiness")
    body = response.text.lower()
    assert "postgresql://" not in body
    assert "password" not in body
    assert "api_key" not in body


def test_request_id_header(client: TestClient) -> None:
    response = client.get("/api/health", headers={"X-Request-ID": "test-correlation-id"})
    assert response.headers.get("X-Request-ID") == "test-correlation-id"


def test_metrics_endpoint_prometheus(client: TestClient) -> None:
    response = client.get("/api/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    body = response.text
    assert "leadflow_http_requests_total" in body
    assert "leadflow_readiness_state" in body
    assert "leadflow_successful_live_sends_total" in body
    assert "postgresql://" not in body


def test_metrics_records_http_request(client: TestClient) -> None:
    client.get("/api/health")
    response = client.get("/api/metrics")
    assert "leadflow_http_requests_total" in response.text


def test_redacts_authorization_header() -> None:
    text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    result = redact_secrets(text)
    assert "eyJhbGci" not in result
    assert "***REDACTED***" in result


def test_redacts_email_addresses_in_logs() -> None:
    text = "contact user@example.com about campaign"
    result = redact_secrets(text)
    assert "user@example.com" not in result
