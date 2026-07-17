"""Stage 1 runtime smoke test — creates and cleans marked smoke data."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://localhost:8000"


def call(method: str, path: str, body: dict | None = None) -> tuple[int, dict | list | None]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            payload = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            payload = {"raw": raw}
        return exc.code, payload


def main() -> int:
    print("1. create campaign")
    code, campaign = call(
        "POST",
        "/api/campaigns",
        {
            "name": "ZZ-SMOKE Stage1 Campaign",
            "business_type": "SaaS",
            "region": "EU",
            "offer": "Smoke offer",
            "max_companies": 5,
            "max_emails_per_lead": 2,
        },
    )
    assert code == 201, (code, campaign)
    cid = campaign["id"]
    print("   ok", cid)

    print("2. create company")
    code, company = call(
        "POST",
        "/api/companies",
        {
            "name": "ZZ-SMOKE Co",
            "website": "https://zz-smoke.example.com",
            "domain": "zz-smoke.example.com",
            "status": "ACTIVE",
        },
    )
    assert code == 201, (code, company)
    coid = company["id"]
    print("   ok", coid)

    print("3. add email contact")
    code, contact = call(
        "POST",
        f"/api/companies/{coid}/contacts",
        {
            "contact_type": "EMAIL",
            "value": "zz-smoke@example.com",
            "source_url": "https://zz-smoke.example.com",
        },
    )
    assert code == 201, (code, contact)
    assert contact["consent_status"] == "UNKNOWN"
    assert contact["do_not_contact"] is False
    print("   ok consent=UNKNOWN")

    print("4. attach company to campaign")
    code, link = call("POST", f"/api/campaigns/{cid}/companies/{coid}")
    assert code == 201, (code, link)
    assert link["approved_for_email"] is False
    print("   ok approved_for_email=false")

    print("5. persistence check (read after short wait)")
    time.sleep(2)
    code, detail = call("GET", f"/api/campaigns/{cid}")
    assert code == 200 and detail["lead_count"] == 1, (code, detail)
    code, company2 = call("GET", f"/api/companies/{coid}")
    assert code == 200 and company2["name"] == "ZZ-SMOKE Co", (code, company2)
    print("   ok persisted")

    print("6. detach link")
    code, _ = call("DELETE", f"/api/campaigns/{cid}/companies/{coid}")
    assert code == 204, code
    code, company3 = call("GET", f"/api/companies/{coid}")
    assert code == 200, (code, company3)
    print("   ok company remains")

    print("7. cleanup contact")
    code, _ = call("DELETE", f"/api/contacts/{contact['id']}")
    assert code == 204, code
    # Campaign left as ZZ-SMOKE marker for optional manual cleanup; no company DELETE on stage 1.
    print("SMOKE_OK", {"campaign_id": cid, "company_id": coid})
    return 0


if __name__ == "__main__":
    sys.exit(main())
