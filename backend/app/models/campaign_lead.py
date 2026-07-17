from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import CampaignLeadStatus, ReviewDecision
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.campaign import Campaign
    from app.models.company import Company
    from app.models.lead_score_snapshot import LeadScoreSnapshot
    from app.models.research_run import ResearchRun


class CampaignLead(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "campaign_leads"
    __table_args__ = (
        UniqueConstraint("campaign_id", "company_id", name="uq_campaign_leads_campaign_company"),
        Index("ix_campaign_leads_campaign_qual_status", "campaign_id", "qualification_status"),
    )

    campaign_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=CampaignLeadStatus.NEW.value,
    )
    approved_for_research: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approved_for_email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Stage 3 qualification fields
    qualification_score: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    qualification_status: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    review_decision: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ReviewDecision.PENDING.value,
        index=True,
    )
    score_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    score_reasons: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    source_research_run_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("research_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    is_test_data: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    campaign: Mapped[Campaign] = relationship("Campaign", back_populates="leads")
    company: Mapped[Company] = relationship("Company", back_populates="campaign_leads")
    source_research_run: Mapped[ResearchRun | None] = relationship("ResearchRun")
    score_snapshots: Mapped[list[LeadScoreSnapshot]] = relationship(
        "LeadScoreSnapshot",
        back_populates="campaign_lead",
        cascade="all, delete-orphan",
    )
