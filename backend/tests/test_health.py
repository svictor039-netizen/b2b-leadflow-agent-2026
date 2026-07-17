import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    return TestClient(app)


def test_health(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "service" in data


def test_version(client: TestClient) -> None:
    response = client.get("/api/version")
    assert response.status_code == 200
    data = response.json()
    assert data["stage"] == "0"
    assert "version" in data
