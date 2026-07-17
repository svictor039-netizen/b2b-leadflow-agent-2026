"""Stage 2 smoke: research run twice, prove no company duplicates."""

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
    payload = {
        "query": "SaaS",
        "industry": "B2B SaaS",
        "location": "Northern Europe",
        "limit": 5,
        "adapter": "test_source",
    }
    print("1. research run #1")
    code, r1 = call("POST", "/api/research/runs", payload)
    assert code == 201, r1
    assert r1["status"] == "COMPLETED"
    assert r1["adapter"] == "test_source"
    created1 = r1["created_count"]
    print("   created", created1, "found", r1["found_count"])

    print("2. research run #2 (same params)")
    code, r2 = call("POST", "/api/research/runs", payload)
    assert code == 201, r2
    assert r2["status"] == "COMPLETED"
    assert r2["created_count"] == 0
    print("   created", r2["created_count"], "(expect 0)")

    print("3. companies list")
    code, companies = call("GET", "/api/companies?page_size=100&search=Nordic")
    assert code == 200
    print("   nordic matches", companies["total"])

    print("SMOKE_STAGE2_OK", {"run1": r1["id"], "run2": r2["id"]})
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.HTTPError as exc:
        print("HTTPError", exc.code, exc.read().decode())
        raise
