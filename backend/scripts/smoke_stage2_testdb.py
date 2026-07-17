"""Smoke against leadflow_test — idempotent research + SYSTEM_STOP_ALL."""

from __future__ import annotations

import os

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import Company, CompanySourceRecord
from app.schemas.research import ResearchRunCreate
from app.services.research_service import execute_research_run, start_research


def main() -> None:
    db = SessionLocal()
    try:
        payload = ResearchRunCreate(
            query="SaaS",
            industry="B2B SaaS",
            location="Northern Europe",
            limit=5,
            adapter="test_source",
        )
        r1 = start_research(db, payload)
        print("run1", r1.status.value, "created", r1.created_count, "found", r1.found_count)
        assert r1.status.value == "COMPLETED"
        assert r1.created_count >= 1

        r2 = start_research(
            db,
            ResearchRunCreate(
                query="SaaS",
                industry="B2B SaaS",
                location="Northern Europe",
                limit=5,
                adapter="test_source",
            ),
        )
        print("run2", r2.status.value, "created", r2.created_count)
        assert r2.status.value == "COMPLETED"
        assert r2.created_count == 0

        companies = db.scalar(select(func.count()).select_from(Company))
        sources = db.scalar(select(func.count()).select_from(CompanySourceRecord))
        print("companies", companies, "source_records", sources)
        assert companies == sources

        again = execute_research_run(db, r1.id)
        print("redelivery", again.status.value, "created", again.created_count)
        assert again.created_count == r1.created_count

        os.environ["SYSTEM_STOP_ALL"] = "true"
        get_settings.cache_clear()
        blocked = start_research(
            db,
            ResearchRunCreate(query="SaaS", adapter="test_source", limit=2),
        )
        print(
            "blocked",
            blocked.status.value,
            bool(blocked.finished_at),
            (blocked.error_message or "")[:80],
        )
        assert blocked.status.value == "BLOCKED"
        assert blocked.finished_at is not None
    finally:
        os.environ["SYSTEM_STOP_ALL"] = "false"
        get_settings.cache_clear()
        db.close()
    print("SMOKE_TEST_DB_OK")


if __name__ == "__main__":
    main()
