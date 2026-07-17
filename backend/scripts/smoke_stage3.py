"""Stage 3 smoke: research → qualification → review → idempotency."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "http://localhost:8000"


def call(method: str, path: str, body: dict | None = None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode()
        return resp.status, json.loads(raw) if raw else None


def main() -> int:
    print("1. create campaign")
    code, campaign = call(
        "POST",
        "/api/campaigns",
        {
            "name": "Smoke Stage3",
            "business_type": "B2B SaaS",
            "region": "Northern Europe",
            "offer": "Smoke offer",
        },
    )
    assert code == 201, campaign
    cid = campaign["id"]

    print("2. research run")
    code, research = call(
        "POST",
        "/api/research/runs",
        {
            "query": "SaaS",
            "industry": "B2B SaaS",
            "location": "Northern Europe",
            "adapter": "test_source",
            "limit": 5,
            "campaign_id": cid,
        },
    )
    assert code == 201, research
    assert research["status"] == "COMPLETED"

    print("3. qualification #1")
    code, q1 = call(
        "POST",
        "/api/qualification/runs",
        {"campaign_id": cid, "research_run_id": research["id"], "async_mode": False},
    )
    assert code == 201, q1
    assert q1["status"] == "COMPLETED"
    assert q1["scored_count"] >= 1
    assert q1["created_leads_count"] >= 1
    print("   scored", q1["scored_count"], "created", q1["created_leads_count"])

    print("4. qualification #2 (idempotent)")
    code, q2 = call(
        "POST",
        "/api/qualification/runs",
        {"campaign_id": cid, "research_run_id": research["id"]},
    )
    assert code == 201, q2
    assert q2["created_leads_count"] == 0
    print("   created", q2["created_leads_count"], "(expect 0)")

    print("5. leads + review")
    code, leads = call("GET", f"/api/campaigns/{cid}/leads?limit=50")
    assert code == 200
    assert leads["total"] >= 1
    lead = leads["items"][0]
    assert lead["score_reasons"]
    code, reviewed = call(
        "POST",
        f"/api/campaigns/{cid}/leads/{lead['id']}/review",
        {"decision": "APPROVED", "note": "smoke"},
    )
    assert code == 200
    assert reviewed["review_decision"] == "APPROVED"

    print("SMOKE_STAGE3_OK", {"campaign": cid, "q1": q1["id"], "q2": q2["id"]})
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.HTTPError as exc:
        print("HTTPError", exc.code, exc.read().decode())
        raise
