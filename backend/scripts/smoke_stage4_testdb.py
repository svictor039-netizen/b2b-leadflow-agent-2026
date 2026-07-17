"""Smoke against leadflow_test for Stage 4 safe outreach."""

from __future__ import annotations

import os
from unittest.mock import patch

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import (
    Campaign,
    CampaignLead,
    OutreachMessage,
    OutreachSequence,
    OutreachSequenceStep,
    OutreachTemplate,
    SendAttempt,
)
from app.providers.email_test import TestEmailProvider
from app.schemas.campaign import CampaignCreate
from app.schemas.outreach import (
    DraftCreateRequest,
    OutreachSequenceCreate,
    OutreachTemplateCreate,
    SequenceStepCreate,
)
from app.schemas.qualification import LeadReviewRequest, QualificationRunCreate
from app.schemas.research import ResearchRunCreate
from app.services.campaign_service import create_campaign
from app.services import outreach_service
from app.services.qualification_service import review_lead, start_qualification
from app.services.research_service import start_research
from app.models.enums import ReviewDecision


def main() -> None:
    os.environ.setdefault("SYSTEM_STOP_ALL", "false")
    get_settings.cache_clear()

    db = SessionLocal()
    try:
        campaign = create_campaign(
            db,
            CampaignCreate(
                name="Stage4 TestDB Smoke",
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
        q = start_qualification(
            db,
            QualificationRunCreate(campaign_id=campaign.id, research_run_id=research.id),
        )
        assert q.status.value == "COMPLETED"
        lead = db.scalars(
            select(CampaignLead).where(CampaignLead.campaign_id == campaign.id)
        ).first()
        assert lead
        review_lead(
            db,
            campaign.id,
            lead.id,
            LeadReviewRequest(decision=ReviewDecision.APPROVED),
        )

        with patch.object(TestEmailProvider, "send", autospec=True) as mock_send:
            tmpl = outreach_service.create_template(
                db,
                campaign.id,
                OutreachTemplateCreate(
                    name="Smoke tmpl",
                    subject_template="Hi {{company_name}}",
                    body_template="Score {{lead_score}}",
                ),
            )
            seq = outreach_service.create_sequence(
                db,
                campaign.id,
                OutreachSequenceCreate(
                    name="Smoke seq",
                    steps=[SequenceStepCreate(template_id=tmpl.id, step_number=1)],
                ),
            )
            drafts = outreach_service.create_drafts(
                db,
                campaign.id,
                DraftCreateRequest(sequence_id=seq.id, lead_ids=[lead.id]),
            )
            assert drafts.created_count >= 1
            assert mock_send.call_count == 0

            message_id = next(r.message_id for r in drafts.results if r.message_id)
            outreach_service.approve_message(db, campaign.id, message_id)
            assert mock_send.call_count == 0

            from datetime import datetime, timezone

            from app.providers.base import EmailSendResult

            mock_send.return_value = EmailSendResult(
                success=True,
                provider="test_email",
                message_id="test-smoke",
                sent_at=datetime.now(timezone.utc),
                simulated=True,
            )
            sent = outreach_service.send_message(db, campaign.id, message_id)
            assert sent.status == "SENT"
            assert mock_send.call_count == 1

            again = outreach_service.send_message(db, campaign.id, message_id)
            assert again.status == "SENT"
            assert mock_send.call_count == 1

            # Prepare another approved message for STOP test
            lead2 = db.scalars(
                select(CampaignLead)
                .where(
                    CampaignLead.campaign_id == campaign.id,
                    CampaignLead.id != lead.id,
                )
            ).first()
            if lead2:
                review_lead(
                    db,
                    campaign.id,
                    lead2.id,
                    LeadReviewRequest(decision=ReviewDecision.APPROVED),
                )
                tmpl2 = outreach_service.create_template(
                    db,
                    campaign.id,
                    OutreachTemplateCreate(
                        name="Smoke tmpl2",
                        subject_template="Hi {{company_name}}",
                        body_template="Body",
                    ),
                )
                seq2 = outreach_service.create_sequence(
                    db,
                    campaign.id,
                    OutreachSequenceCreate(
                        name="Smoke seq2",
                        steps=[SequenceStepCreate(template_id=tmpl2.id, step_number=1)],
                    ),
                )
                d2 = outreach_service.create_drafts(
                    db,
                    campaign.id,
                    DraftCreateRequest(sequence_id=seq2.id, lead_ids=[lead2.id]),
                )
                mid2 = next(r.message_id for r in d2.results if r.message_id)
                outreach_service.approve_message(db, campaign.id, mid2)
                os.environ["SYSTEM_STOP_ALL"] = "true"
                get_settings.cache_clear()
                try:
                    blocked = outreach_service.send_message(db, campaign.id, mid2)
                    assert blocked.status == "BLOCKED"
                    assert mock_send.call_count == 1  # unchanged
                finally:
                    os.environ["SYSTEM_STOP_ALL"] = "false"
                    get_settings.cache_clear()

        msg = db.get(OutreachMessage, message_id)
        assert msg is not None
        assert msg.recipient_email.endswith("@example.test")

        print(
            "counts",
            {
                "campaigns": db.scalar(select(func.count()).select_from(Campaign)),
                "campaign_leads": db.scalar(select(func.count()).select_from(CampaignLead)),
                "templates": db.scalar(select(func.count()).select_from(OutreachTemplate)),
                "sequences": db.scalar(select(func.count()).select_from(OutreachSequence)),
                "sequence_steps": db.scalar(select(func.count()).select_from(OutreachSequenceStep)),
                "messages": db.scalar(select(func.count()).select_from(OutreachMessage)),
                "send_attempts": db.scalar(select(func.count()).select_from(SendAttempt)),
            },
        )
        print("Stage4 smoke OK")
    finally:
        db.close()


if __name__ == "__main__":
    main()
