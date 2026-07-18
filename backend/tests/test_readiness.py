import os

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


@pytest.mark.skipif(
    os.getenv("SKIP_INTEGRATION") == "1",
    reason="Integration tests require live postgres/redis",
)
def test_readiness(client: TestClient) -> None:
    response = client.get("/api/readiness")
    assert response.status_code in {200, 503}
    data = response.json()
    assert "checks" in data
    assert "postgres" in data["checks"]
    assert "redis" in data["checks"]
    assert "migrations" in data["checks"]
