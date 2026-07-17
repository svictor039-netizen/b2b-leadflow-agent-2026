"""LeadScoreSnapshot — explainable score history for Stage 3."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.campaign_lead import CampaignLead
    from app.models.qualification_run import QualificationRun


class LeadScoreSnapshot(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    __tablename__ = "lead_score_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "qualification_run_id",
            "campaign_lead_id",
            name="uq_lead_score_snapshots_run_lead",
        ),
    )

    qualification_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("qualification_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    campaign_lead_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("campaign_leads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    scoring_version: Mapped[str] = mapped_column(String(64), nullable=False)
    qualification_status: Mapped[str] = mapped_column(String(32), nullable=False)
    reasons: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    input_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_test_data: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    qualification_run: Mapped[QualificationRun] = relationship(
        "QualificationRun",
        back_populates="score_snapshots",
    )
    campaign_lead: Mapped[CampaignLead] = relationship(
        "CampaignLead",
        back_populates="score_snapshots",
    )
