from uuid import uuid4

from fastapi.testclient import TestClient


def _create_campaign(client: TestClient, **overrides) -> dict:
    payload = {
        "name": "Test Campaign Alpha",
        "business_type": "SaaS",
        "region": "EU",
        "offer": "Pilot",
        "max_companies": 5,
        "max_emails_per_lead": 2,
    }
    payload.update(overrides)
    response = client.post("/api/campaigns", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_campaign(client: TestClient) -> None:
    data = _create_campaign(client)
    assert data["status"] == "DRAFT"
    assert data["sending_mode"] == "MANUAL_APPROVAL"
    assert data["lead_count"] == 0
    assert data["free_slots"] == 5


def test_create_campaign_max_companies_over_limit(client: TestClient) -> None:
    response = client.post(
        "/api/campaigns",
        json={
            "name": "Too Many Companies",
            "business_type": "SaaS",
            "region": "EU",
            "offer": "Pilot",
            "max_companies": 31,
        },
    )
    assert response.status_code == 422


def test_create_campaign_max_emails_over_limit(client: TestClient) -> None:
    response = client.post(
        "/api/campaigns",
        json={
            "name": "Too Many Emails",
            "business_type": "SaaS",
            "region": "EU",
            "offer": "Pilot",
            "max_emails_per_lead": 4,
        },
    )
    assert response.status_code == 422


def test_list_campaigns_pagination_and_search(client: TestClient) -> None:
    _create_campaign(client, name="Searchable Nordic SaaS")
    _create_campaign(client, name="Other Campaign XYZ")

    listed = client.get("/api/campaigns", params={"page": 1, "page_size": 1})
    assert listed.status_code == 200
    body = listed.json()
    assert body["page_size"] == 1
    assert body["total"] >= 2
    assert len(body["items"]) == 1

    search = client.get("/api/campaigns", params={"search": "Nordic"})
    assert search.status_code == 200
    assert any("Nordic" in i["name"] for i in search.json()["items"])


def test_campaign_detail(client: TestClient) -> None:
    created = _create_campaign(client)
    detail = client.get(f"/api/campaigns/{created['id']}")
    assert detail.status_code == 200
    assert detail.json()["id"] == created["id"]
    assert "lead_status_counts" in detail.json()


def test_campaign_patch(client: TestClient) -> None:
    created = _create_campaign(client)
    patched = client.patch(
        f"/api/campaigns/{created['id']}",
        json={"name": "Renamed Campaign", "status": "PAUSED"},
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Renamed Campaign"
    assert patched.json()["status"] == "PAUSED"


def test_campaign_forbidden_status(client: TestClient) -> None:
    created = _create_campaign(client)
    response = client.patch(
        f"/api/campaigns/{created['id']}",
        json={"status": "RUNNING"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "forbidden_status"


def test_campaign_max_companies_below_lead_count(client: TestClient) -> None:
    created = _create_campaign(client, max_companies=2)
    company = client.post("/api/companies", json={"name": "Lead Co"}).json()
    company2 = client.post("/api/companies", json={"name": "Lead Co 2"}).json()
    assert (
        client.post(f"/api/campaigns/{created['id']}/companies/{company['id']}").status_code
        == 201
    )
    assert (
        client.post(f"/api/campaigns/{created['id']}/companies/{company2['id']}").status_code
        == 201
    )

    response = client.patch(
        f"/api/campaigns/{created['id']}",
        json={"max_companies": 1},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "max_companies_too_low"


def test_campaign_404(client: TestClient) -> None:
    response = client.get(f"/api/campaigns/{uuid4()}")
    assert response.status_code == 404
