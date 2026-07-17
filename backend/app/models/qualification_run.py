"""Stage 3 QualificationRun model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import QualificationRunStatus, SCORING_VERSION
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.campaign import Campaign
    from app.models.research_run import ResearchRun
    from app.models.lead_score_snapshot import LeadScoreSnapshot


class QualificationRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "qualification_runs"

    campaign_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    research_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("research_runs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=QualificationRunStatus.PENDING.value,
        index=True,
    )
    scoring_version: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=SCORING_VERSION,
    )
    found_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_leads_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matched_leads_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scored_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    qualified_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    disqualified_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    conflict_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_test_data: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    campaign: Mapped[Campaign] = relationship("Campaign")
    research_run: Mapped[ResearchRun] = relationship("ResearchRun")
    score_snapshots: Mapped[list[LeadScoreSnapshot]] = relationship(
        "LeadScoreSnapshot",
        back_populates="qualification_run",
        cascade="all, delete-orphan",
    )
