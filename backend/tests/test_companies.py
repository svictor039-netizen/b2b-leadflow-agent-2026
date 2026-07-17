from uuid import uuid4

from fastapi.testclient import TestClient


def test_create_company(client: TestClient) -> None:
    response = client.post(
        "/api/companies",
        json={
            "name": "Acme Demo",
            "website": "https://acme.example.com",
            "domain": "acme.example.com",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Acme Demo"
    assert data["status"] == "UNKNOWN"
    assert data["locations"] == []
    assert data["contacts"] == []


def test_company_detail_and_list_filters(client: TestClient) -> None:
    created = client.post(
        "/api/companies",
        json={"name": "Filterable Co", "status": "ACTIVE", "domain": "filter.example.com"},
    ).json()
    client.post(
        f"/api/companies/{created['id']}/locations",
        json={"city": "Berlin", "is_primary": True},
    )

    detail = client.get(f"/api/companies/{created['id']}")
    assert detail.status_code == 200
    assert len(detail.json()["locations"]) == 1

    listed = client.get("/api/companies", params={"search": "Filterable", "status": "ACTIVE"})
    assert listed.status_code == 200
    assert listed.json()["total"] >= 1

    by_city = client.get("/api/companies", params={"city": "Berlin"})
    assert by_city.status_code == 200
    assert any(i["id"] == created["id"] for i in by_city.json()["items"])


def test_company_patch(client: TestClient) -> None:
    created = client.post("/api/companies", json={"name": "Patch Me"}).json()
    patched = client.patch(
        f"/api/companies/{created['id']}",
        json={"description": "Updated", "status": "ACTIVE"},
    )
    assert patched.status_code == 200
    assert patched.json()["description"] == "Updated"
    assert patched.json()["status"] == "ACTIVE"


def test_create_location(client: TestClient) -> None:
    company = client.post("/api/companies", json={"name": "Loc Co"}).json()
    loc = client.post(
        f"/api/companies/{company['id']}/locations",
        json={"city": "Tallinn", "country": "EE"},
    )
    assert loc.status_code == 201
    assert loc.json()["city"] == "Tallinn"


def test_create_email_contact_defaults(client: TestClient) -> None:
    company = client.post("/api/companies", json={"name": "Mail Co"}).json()
    contact = client.post(
        f"/api/companies/{company['id']}/contacts",
        json={
            "contact_type": "EMAIL",
            "value": "info@mail.example.com",
            "source_url": "https://mail.example.com/contact",
        },
    )
    assert contact.status_code == 201
    data = contact.json()
    assert data["consent_status"] == "UNKNOWN"
    assert data["do_not_contact"] is False
    assert data["verification_status"] == "UNVERIFIED"


def test_invalid_email(client: TestClient) -> None:
    company = client.post("/api/companies", json={"name": "Bad Mail"}).json()
    response = client.post(
        f"/api/companies/{company['id']}/contacts",
        json={"contact_type": "EMAIL", "value": "not-an-email"},
    )
    assert response.status_code == 422


def test_forbidden_url_scheme(client: TestClient) -> None:
    company = client.post("/api/companies", json={"name": "URL Co"}).json()
    response = client.post(
        f"/api/companies/{company['id']}/contacts",
        json={
            "contact_type": "EMAIL",
            "value": "ok@example.com",
            "source_url": "javascript:alert(1)",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_url_scheme"


def test_company_404(client: TestClient) -> None:
    assert client.get(f"/api/companies/{uuid4()}").status_code == 404
