"""Smoke against leadflow_test for Stage 7A controlled live pilot."""

from __future__ import annotations

import os
from unittest.mock import patch

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import Campaign, LivePilot, LivePilotEvent, OutreachMessage
from app.models.enums import ReviewDecision
from app.providers.email_test import TestEmailProvider
from app.schemas.campaign import CampaignCreate
from app.schemas.live_pilot import LivePilotCreate, LivePilotDryRunRequest, LivePilotRecipientCreate
from app.schemas.outreach import (
    DraftCreateRequest,
    OutreachSequenceCreate,
    OutreachTemplateCreate,
    SequenceStepCreate,
)
from app.schemas.qualification import LeadReviewRequest, QualificationRunCreate
from app.schemas.research import ResearchRunCreate
from app.services import live_pilot_service
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
                name="Stage7A TestDB Smoke",
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
        from app.models import CampaignLead

        leads = list(
            db.scalars(select(CampaignLead).where(CampaignLead.campaign_id == campaign.id))
        )
        assert leads
        review_lead(
            db,
            campaign.id,
            leads[0].id,
            LeadReviewRequest(decision=ReviewDecision.APPROVED),
        )
        from app.services import outreach_service

        tmpl = outreach_service.create_template(
            db,
            campaign.id,
            OutreachTemplateCreate(
                name="Smoke",
                subject_template="Hi {{company_name}}",
                body_template="Body",
                is_test_data=True,
            ),
        )
        seq = outreach_service.create_sequence(
            db,
            campaign.id,
            OutreachSequenceCreate(
                name="Seq",
                is_test_data=True,
                steps=[SequenceStepCreate(template_id=tmpl.id, step_number=1)],
            ),
        )
        outreach_service.create_drafts(
            db,
            campaign.id,
            DraftCreateRequest(sequence_id=seq.id, lead_ids=[leads[0].id]),
        )
        msg = db.scalars(
            select(OutreachMessage).where(OutreachMessage.campaign_id == campaign.id)
        ).first()
        assert msg is not None
        outreach_service.approve_message(db, campaign.id, msg.id)

        pilot = live_pilot_service.create_live_pilot(
            db,
            LivePilotCreate(
                campaign_id=campaign.id,
                message_id=msg.id,
                idempotency_key="smoke-stage7a-pilot",
            ),
        )
        live_pilot_service.add_recipient(
            db,
            pilot.id,
            LivePilotRecipientCreate(
                outreach_message_id=msg.id,
                idempotency_key="smoke-stage7a-recipient",
            ),
        )
        validation = live_pilot_service.validate_pilot(db, pilot.id)
        assert validation.test_ready is True
        assert validation.live_ready is False
        assert validation.overall_status in {
            "TEST_VALIDATED",
            "READY_FOR_PROVIDER_SELECTION",
        }

        challenge = live_pilot_service.approve_pilot(db, pilot.id)
        assert challenge.confirmation_token
        live_pilot_service.approve_pilot(
            db, pilot.id, confirmation_token=challenge.confirmation_token
        )

        provider = TestEmailProvider()
        with patch(
            "app.services.live_pilot_service.get_dry_run_provider",
            return_value=provider,
        ):
            with patch.object(provider, "send", wraps=provider.send) as mock_send:
                dry = live_pilot_service.dry_run_pilot(
                    db,
                    pilot.id,
                    idempotency_key="smoke-stage7a-dry-run",
                )
                assert dry.provider == "test_email"
                assert mock_send.call_count == 1

        refreshed = db.get(LivePilot, pilot.id)
        assert refreshed is not None
        assert refreshed.live_sent_count == 0

        events = db.scalars(
            select(LivePilotEvent).where(LivePilotEvent.pilot_id == pilot.id)
        ).all()
        assert events
        blob = " ".join(e.safe_detail or "" for e in events)
        assert "api_key" not in blob.lower()

        pilot_count = db.scalar(select(func.count()).select_from(LivePilot)) or 0
        print(f"Stage 7A smoke OK — pilots={pilot_count} live_sent=0 beat={celery_app.conf.beat_schedule}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
