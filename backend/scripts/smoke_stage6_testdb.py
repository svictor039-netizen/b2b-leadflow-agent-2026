"""Smoke against leadflow_test for Stage 6 compliance readiness."""

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
    CampaignLead,
    ComplianceDecisionLog,
    OutreachMessage,
    SendAttempt,
    SuppressionEntry,
)
from app.models.enums import ReviewDecision
from app.providers.base import EmailSendResult
from app.providers.email_test import TestEmailProvider
from app.schemas.campaign import CampaignCreate
from app.schemas.compliance import SuppressionCreate, TestComplianceEventCreate
from app.schemas.execution import ExecutionRunCreate
from app.schemas.outreach import (
    DraftCreateRequest,
    OutreachSequenceCreate,
    OutreachTemplateCreate,
    SequenceStepCreate,
)
from app.schemas.qualification import LeadReviewRequest, QualificationRunCreate
from app.schemas.research import ResearchRunCreate
from app.services import compliance_service, execution_service, outreach_service
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
                name="Stage6 Smoke",
                business_type="B2B SaaS",
                region="Northern Europe",
                offer="Smoke",
            ),
        )
        research = start_research(
            db,
            ResearchRunCreate(
                query="SaaS",
                industry="SaaS",
                location="Europe",
                adapter="test_source",
                limit=5,
                campaign_id=campaign.id,
            ),
        )
        start_qualification(
            db,
            QualificationRunCreate(campaign_id=campaign.id, research_run_id=research.id),
        )
        leads = list(
            db.scalars(
                select(CampaignLead).where(CampaignLead.campaign_id == campaign.id)
            ).all()
        )
        assert len(leads) >= 2, f"need 2 leads for smoke, got {len(leads)}"
        for ld in leads[:2]:
            review_lead(
                db,
                campaign.id,
                ld.id,
                LeadReviewRequest(decision=ReviewDecision.APPROVED),
            )

        tmpl = outreach_service.create_template(
            db,
            campaign.id,
            OutreachTemplateCreate(
                name="S6",
                subject_template="Hi {{company_name}}",
                body_template="Body",
            ),
        )
        seq = outreach_service.create_sequence(
            db,
            campaign.id,
            OutreachSequenceCreate(
                name="S6seq",
                steps=[
                    SequenceStepCreate(template_id=tmpl.id, step_number=1),
                    SequenceStepCreate(template_id=tmpl.id, step_number=2),
                ],
            ),
        )
        drafts = outreach_service.create_drafts(
            db,
            campaign.id,
            DraftCreateRequest(
                sequence_id=seq.id, lead_ids=[leads[0].id, leads[1].id]
            ),
        )
        mids = [r.message_id for r in drafts.results if r.message_id]
        assert len(mids) >= 4
        for mid in mids:
            outreach_service.approve_message(db, campaign.id, mid)

        by_lead_step: dict[tuple, OutreachMessage] = {}
        for mid in mids:
            msg = db.get(OutreachMessage, mid)
            assert msg
            db.refresh(msg)
            step_no = msg.sequence_step.step_number
            by_lead_step[(msg.campaign_lead_id, step_no)] = msg

        msg_l0_s1 = by_lead_step[(leads[0].id, 1)]
        msg_l1_s1 = by_lead_step[(leads[1].id, 1)]
        msg_l0_s2 = by_lead_step[(leads[0].id, 2)]
        msg_l1_s2 = by_lead_step[(leads[1].id, 2)]
        assert msg_l0_s1.recipient_email != msg_l1_s1.recipient_email

        with patch.object(TestEmailProvider, "send", autospec=True) as mock_send:
            mock_send.return_value = EmailSendResult(
                success=True,
                provider="test_email",
                message_id="s6",
                sent_at=datetime.now(timezone.utc),
                simulated=True,
            )

            compliance_service.create_suppression(
                db,
                SuppressionCreate(
                    scope="CAMPAIGN",
                    campaign_id=campaign.id,
                    suppression_type="EMAIL",
                    value=msg_l0_s1.recipient_email,
                    reason="UNSUBSCRIBE",
                    is_test_data=True,
                ),
            )
            assert (
                compliance_service.check_message_api(
                    db, campaign.id, msg_l0_s1.id
                ).allowed
                is False
            )
            assert (
                compliance_service.check_message_api(
                    db, campaign.id, msg_l1_s1.id
                ).allowed
                is True
            )

            # Stage 4: blocked → provider 0
            blocked = outreach_service.send_message(db, campaign.id, msg_l0_s1.id)
            assert blocked.status == "BLOCKED"
            assert mock_send.call_count == 0

            # Stage 4: allowed → provider 1
            sent = outreach_service.send_message(db, campaign.id, msg_l1_s1.id)
            assert sent.status == "SENT"
            assert mock_send.call_count == 1

            # Stage 5: step2 messages — same recipients → one BLOCKED item, one SENT
            run = execution_service.create_execution_run(
                db,
                campaign.id,
                ExecutionRunCreate(
                    sequence_id=seq.id,
                    message_ids=[msg_l0_s2.id, msg_l1_s2.id],
                    max_messages=10,
                    batch_size=5,
                    is_test_data=True,
                ),
            )
            started = execution_service.start_execution_run(
                db, campaign.id, run.id, async_mode=False
            )
            assert started.blocked_count >= 1
            assert started.sent_count >= 1
            assert mock_send.call_count == 1 + started.sent_count

            before = mock_send.call_count
            compliance_service.create_test_event(
                db,
                campaign.id,
                TestComplianceEventCreate(
                    message_id=msg_l1_s1.id,
                    event_type="UNSUBSCRIBE",
                    is_test_data=True,
                ),
            )
            again = outreach_service.send_message(db, campaign.id, msg_l1_s1.id)
            assert again.status == "SENT"
            assert mock_send.call_count == before
            provider_after_event = mock_send.call_count

        report = compliance_service.build_provider_readiness_report()
        assert report.test_mode_ready is True
        assert report.live_mode_ready is False
        assert report.overall_status == "TEST_READY"
        assert "sk_live" not in str(report.model_dump())

        print(
            "counts",
            {
                "campaigns": db.scalar(select(func.count()).select_from(Campaign)),
                "suppression_entries": db.scalar(
                    select(func.count()).select_from(SuppressionEntry)
                ),
                "compliance_decision_logs": db.scalar(
                    select(func.count()).select_from(ComplianceDecisionLog)
                ),
                "outreach_messages": db.scalar(
                    select(func.count()).select_from(OutreachMessage)
                ),
                "execution_items": db.scalar(
                    select(func.count()).select_from(CampaignExecutionItem)
                ),
                "send_attempts": db.scalar(select(func.count()).select_from(SendAttempt)),
                "provider_calls": provider_after_event,
            },
        )
        print(
            "readiness",
            report.overall_status,
            "live_ready",
            report.live_mode_ready,
            "beat",
            celery_app.conf.beat_schedule,
        )
        print("Stage6 smoke OK")
    finally:
        db.close()


if __name__ == "__main__":
    main()
