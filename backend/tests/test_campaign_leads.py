from fastapi.testclient import TestClient


def test_attach_company_approved_for_email_false(client: TestClient) -> None:
    campaign = client.post(
        "/api/campaigns",
        json={
            "name": "Lead Link Campaign",
            "business_type": "SaaS",
            "region": "EU",
            "offer": "Pilot",
            "max_companies": 3,
        },
    ).json()
    company = client.post("/api/companies", json={"name": "Linked Co"}).json()

    link = client.post(f"/api/campaigns/{campaign['id']}/companies/{company['id']}")
    assert link.status_code == 201
    assert link.json()["approved_for_email"] is False
    assert link.json()["status"] == "NEW"


def test_duplicate_attach_returns_409(client: TestClient) -> None:
    campaign = client.post(
        "/api/campaigns",
        json={
            "name": "Dup Campaign",
            "business_type": "SaaS",
            "region": "EU",
            "offer": "Pilot",
            "max_companies": 3,
        },
    ).json()
    company = client.post("/api/companies", json={"name": "Dup Co"}).json()
    assert (
        client.post(f"/api/campaigns/{campaign['id']}/companies/{company['id']}").status_code
        == 201
    )
    dup = client.post(f"/api/campaigns/{campaign['id']}/companies/{company['id']}")
    assert dup.status_code == 409


def test_exceed_max_companies(client: TestClient) -> None:
    campaign = client.post(
        "/api/campaigns",
        json={
            "name": "Full Campaign",
            "business_type": "SaaS",
            "region": "EU",
            "offer": "Pilot",
            "max_companies": 1,
        },
    ).json()
    c1 = client.post("/api/companies", json={"name": "C1"}).json()
    c2 = client.post("/api/companies", json={"name": "C2"}).json()
    assert client.post(f"/api/campaigns/{campaign['id']}/companies/{c1['id']}").status_code == 201
    full = client.post(f"/api/campaigns/{campaign['id']}/companies/{c2['id']}")
    assert full.status_code == 400
    assert full.json()["error"]["code"] == "campaign_full"


def test_detach_keeps_company(client: TestClient) -> None:
    campaign = client.post(
        "/api/campaigns",
        json={
            "name": "Detach Campaign",
            "business_type": "SaaS",
            "region": "EU",
            "offer": "Pilot",
            "max_companies": 5,
        },
    ).json()
    company = client.post("/api/companies", json={"name": "Keep Me"}).json()
    client.post(f"/api/campaigns/{campaign['id']}/companies/{company['id']}")

    deleted = client.delete(f"/api/campaigns/{campaign['id']}/companies/{company['id']}")
    assert deleted.status_code == 204

    still = client.get(f"/api/companies/{company['id']}")
    assert still.status_code == 200
    assert still.json()["name"] == "Keep Me"

    missing = client.delete(f"/api/campaigns/{campaign['id']}/companies/{company['id']}")
    assert missing.status_code == 404
