"""Smoke against leadflow_test for Stage 3 qualification."""

from __future__ import annotations

import os

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import CampaignLead, Company, LeadScoreSnapshot, QualificationRun
from app.providers.email_test import TestEmailProvider
from app.schemas.campaign import CampaignCreate
from app.schemas.qualification import LeadReviewRequest, QualificationRunCreate
from app.schemas.research import ResearchRunCreate
from app.services.campaign_service import create_campaign
from app.services.qualification_service import (
    execute_qualification_run,
    list_campaign_leads,
    review_lead,
    start_qualification,
)
from app.services.research_service import start_research
from app.models.enums import ReviewDecision


def main() -> None:
    db = SessionLocal()
    try:
        campaign = create_campaign(
            db,
            CampaignCreate(
                name="Stage3 TestDB Smoke",
                business_type="B2B SaaS",
                region="Northern Europe",
                offer="Smoke",
            ),
        )
        research = start_research(
            db,
            ResearchRunCreate(
                query="SaaS",
                industry="B2B SaaS",
                location="Northern Europe",
                adapter="test_source",
                limit=5,
                campaign_id=campaign.id,
            ),
        )
        assert research.status.value == "COMPLETED"

        q1 = start_qualification(
            db,
            QualificationRunCreate(campaign_id=campaign.id, research_run_id=research.id),
        )
        print("q1", q1.status.value, "scored", q1.scored_count, "created", q1.created_leads_count)
        assert q1.status.value == "COMPLETED"
        assert q1.created_leads_count >= 1

        q2 = start_qualification(
            db,
            QualificationRunCreate(campaign_id=campaign.id, research_run_id=research.id),
        )
        print("q2", q2.status.value, "created", q2.created_leads_count)
        assert q2.created_leads_count == 0

        again = execute_qualification_run(db, q1.id)
        assert again.scored_count == q1.scored_count
        assert again.created_leads_count == q1.created_leads_count

        leads = list_campaign_leads(db, campaign.id, limit=50, offset=0)
        assert leads.total >= 1
        lead = leads.items[0]
        assert lead.score_reasons
        leads_before_review = leads.total

        reviewed = review_lead(
            db,
            campaign.id,
            lead.id,
            LeadReviewRequest(decision=ReviewDecision.APPROVED, note="smoke"),
        )
        assert reviewed.review_decision == "APPROVED"
        assert reviewed.qualification_score == lead.qualification_score

        companies = db.scalar(select(func.count()).select_from(Company)) or 0
        leads_n = db.scalar(select(func.count()).select_from(CampaignLead)) or 0
        runs = db.scalar(select(func.count()).select_from(QualificationRun)) or 0
        snaps = db.scalar(select(func.count()).select_from(LeadScoreSnapshot)) or 0
        print("counts companies", companies, "leads", leads_n, "qruns", runs, "snaps", snaps)
        assert leads_n == leads_before_review
        assert snaps >= 1
        assert leads_n == 1  # no duplicate CampaignLead after second qualification

        # SYSTEM_STOP_ALL blocks automatic qualification only
        os.environ["SYSTEM_STOP_ALL"] = "true"
        get_settings.cache_clear()
        blocked = start_qualification(
            db,
            QualificationRunCreate(campaign_id=campaign.id, research_run_id=research.id),
        )
        print("blocked", blocked.status.value, bool(blocked.finished_at))
        assert blocked.status.value == "BLOCKED"
        # Manual review still works under stop switch
        still = review_lead(
            db,
            campaign.id,
            lead.id,
            LeadReviewRequest(decision=ReviewDecision.PENDING),
        )
        assert still.review_decision == "PENDING"

        assert hasattr(TestEmailProvider, "send")
    finally:
        os.environ["SYSTEM_STOP_ALL"] = "false"
        get_settings.cache_clear()
        db.close()
    print("SMOKE_STAGE3_TEST_DB_OK")


if __name__ == "__main__":
    main()
