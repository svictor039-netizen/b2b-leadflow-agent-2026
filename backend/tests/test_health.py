from fastapi.testclient import TestClient


def test_health(client_no_db: TestClient) -> None:
    response = client_no_db.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "service" in data


def test_version(client_no_db: TestClient) -> None:
    response = client_no_db.get("/api/version")
    assert response.status_code == 200
    data = response.json()
    assert data["stage"] == "3"
    assert "version" in data
