"""Smoke against leadflow_test for Stage 5 test campaign execution."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import patch

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import (
    Campaign,
    CampaignExecutionItem,
    CampaignExecutionRun,
    CampaignLead,
    OutreachMessage,
    SendAttempt,
)
from app.models.enums import ReviewDecision
from app.providers.base import EmailSendResult
from app.providers.email_test import TestEmailProvider
from app.schemas.campaign import CampaignCreate
from app.schemas.execution import ExecutionRunCreate
from app.schemas.outreach import (
    DraftCreateRequest,
    OutreachSequenceCreate,
    OutreachTemplateCreate,
    SequenceStepCreate,
)
from app.schemas.qualification import LeadReviewRequest, QualificationRunCreate
from app.schemas.research import ResearchRunCreate
from app.services import execution_service, outreach_service
from app.services.campaign_service import create_campaign
from app.services.qualification_service import review_lead, start_qualification
from app.services.research_service import start_research
from app.workers.celery_app import celery_app


def main() -> None:
    os.environ.setdefault("SYSTEM_STOP_ALL", "false")
    get_settings.cache_clear()
    assert celery_app.conf.beat_schedule == {}

    db = SessionLocal()
    try:
        campaign = create_campaign(
            db,
            CampaignCreate(
                name="Stage5 TestDB Smoke",
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
        start_qualification(
            db,
            QualificationRunCreate(campaign_id=campaign.id, research_run_id=research.id),
        )
        leads = list(
            db.scalars(select(CampaignLead).where(CampaignLead.campaign_id == campaign.id))
        )
        assert len(leads) >= 1, f"expected leads, got {len(leads)}"
        for lead in leads:
            review_lead(
                db,
                campaign.id,
                lead.id,
                LeadReviewRequest(decision=ReviewDecision.APPROVED),
            )

        with patch.object(TestEmailProvider, "send", autospec=True) as mock_send:
            mock_send.return_value = EmailSendResult(
                success=True,
                provider="test_email",
                message_id="test-smoke-e5",
                sent_at=datetime.now(timezone.utc),
                simulated=True,
            )

            tmpl = outreach_service.create_template(
                db,
                campaign.id,
                OutreachTemplateCreate(
                    name="Smoke5 tmpl",
                    subject_template="Hi {{company_name}}",
                    body_template="Score {{lead_score}}",
                ),
            )
            seq = outreach_service.create_sequence(
                db,
                campaign.id,
                OutreachSequenceCreate(
                    name="Smoke5 seq",
                    steps=[SequenceStepCreate(template_id=tmpl.id, step_number=1)],
                ),
            )
            approved_ids = [l.id for l in leads]
            drafts = outreach_service.create_drafts(
                db,
                campaign.id,
                DraftCreateRequest(sequence_id=seq.id, lead_ids=approved_ids),
            )
            assert drafts.created_count >= 1
            msgs = list(
                db.scalars(
                    select(OutreachMessage).where(
                        OutreachMessage.campaign_id == campaign.id,
                        OutreachMessage.status == "DRAFT",
                    )
                )
            )
            for m in msgs:
                outreach_service.approve_message(db, campaign.id, m.id)

            assert mock_send.call_count == 0
            planned = len(msgs)
            assert planned >= 1

            run = execution_service.create_execution_run(
                db,
                campaign.id,
                ExecutionRunCreate(
                    sequence_id=seq.id,
                    max_messages=10,
                    batch_size=1,
                    client_request_id="smoke5-run1",
                ),
            )
            assert run.status == "PENDING"
            assert run.planned_count == planned
            assert mock_send.call_count == 0

            started = execution_service.start_execution_run(
                db, campaign.id, run.id, async_mode=False
            )
            assert started.status == "COMPLETED"
            assert started.sent_count == planned
            sent_after_start = mock_send.call_count
            assert sent_after_start == started.sent_count

            # Redelivery / second start — no extra provider calls
            again = execution_service.start_execution_run(
                db, campaign.id, run.id, async_mode=False
            )
            assert again.status == "COMPLETED"
            assert mock_send.call_count == sent_after_start

            # Second run: no eligible APPROVED left
            try:
                execution_service.create_execution_run(
                    db,
                    campaign.id,
                    ExecutionRunCreate(
                        sequence_id=seq.id,
                        max_messages=10,
                        batch_size=2,
                        client_request_id="smoke5-run2",
                    ),
                )
                raise AssertionError("expected empty_eligible_messages")
            except Exception as exc:  # noqa: BLE001
                assert getattr(exc, "code", None) == "empty_eligible_messages"

            analytics = execution_service.get_campaign_analytics(db, campaign.id)
            assert analytics.sent_messages == planned
            assert analytics.unknown_messages == 0
            assert analytics.is_test_data is True
            assert analytics.test_delivery_rate > 0

            # Fresh campaign/sequence for SYSTEM_STOP_ALL (no leftover APPROVED)
            stop_campaign = create_campaign(
                db,
                CampaignCreate(
                    name="Stage5 Stop Smoke",
                    business_type="B2B SaaS",
                    region="Northern Europe",
                    offer="Stop",
                ),
            )
            stop_research = start_research(
                db,
                ResearchRunCreate(
                    query="SaaS",
                    industry="B2B SaaS",
                    location="Northern Europe",
                    adapter="test_source",
                    limit=3,
                    campaign_id=stop_campaign.id,
                ),
            )
            start_qualification(
                db,
                QualificationRunCreate(
                    campaign_id=stop_campaign.id, research_run_id=stop_research.id
                ),
            )
            stop_lead = db.scalars(
                select(CampaignLead).where(CampaignLead.campaign_id == stop_campaign.id)
            ).first()
            assert stop_lead is not None
            review_lead(
                db,
                stop_campaign.id,
                stop_lead.id,
                LeadReviewRequest(decision=ReviewDecision.APPROVED),
            )
            stop_tmpl = outreach_service.create_template(
                db,
                stop_campaign.id,
                OutreachTemplateCreate(
                    name="Stop tmpl",
                    subject_template="Hi {{company_name}}",
                    body_template="Body",
                ),
            )
            stop_seq = outreach_service.create_sequence(
                db,
                stop_campaign.id,
                OutreachSequenceCreate(
                    name="Stop seq",
                    steps=[SequenceStepCreate(template_id=stop_tmpl.id, step_number=1)],
                ),
            )
            d2 = outreach_service.create_drafts(
                db,
                stop_campaign.id,
                DraftCreateRequest(sequence_id=stop_seq.id, lead_ids=[stop_lead.id]),
            )
            mid = next(r.message_id for r in d2.results if r.message_id)
            outreach_service.approve_message(db, stop_campaign.id, mid)
            stop_run = execution_service.create_execution_run(
                db,
                stop_campaign.id,
                ExecutionRunCreate(
                    sequence_id=stop_seq.id,
                    max_messages=5,
                    batch_size=1,
                    client_request_id="smoke5-stop",
                ),
            )
            os.environ["SYSTEM_STOP_ALL"] = "true"
            get_settings.cache_clear()
            try:
                blocked = execution_service.start_execution_run(
                    db, stop_campaign.id, stop_run.id, async_mode=False
                )
                assert blocked.status == "BLOCKED"
                assert mock_send.call_count == sent_after_start
            finally:
                os.environ["SYSTEM_STOP_ALL"] = "false"
                get_settings.cache_clear()

        recipients = db.scalars(
            select(OutreachMessage.recipient_email).where(
                OutreachMessage.campaign_id == campaign.id
            )
        ).all()
        assert all(r.endswith("@example.test") for r in recipients)

        print(
            "counts",
            {
                "campaigns": db.scalar(select(func.count()).select_from(Campaign)),
                "execution_runs": db.scalar(
                    select(func.count()).select_from(CampaignExecutionRun)
                ),
                "execution_items": db.scalar(
                    select(func.count()).select_from(CampaignExecutionItem)
                ),
                "outreach_messages": db.scalar(
                    select(func.count()).select_from(OutreachMessage)
                ),
                "send_attempts": db.scalar(select(func.count()).select_from(SendAttempt)),
            },
        )
        print("Stage5 smoke OK")
    finally:
        db.close()


if __name__ == "__main__":
    main()
