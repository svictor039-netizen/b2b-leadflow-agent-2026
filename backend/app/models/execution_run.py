from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import ExecutionMode, ExecutionRunStatus
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.campaign import Campaign
    from app.models.execution_item import CampaignExecutionItem
    from app.models.outreach_sequence import OutreachSequence


class CampaignExecutionRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "campaign_execution_runs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_campaign_execution_runs_idempotency"),
        Index("ix_campaign_execution_runs_campaign_id", "campaign_id"),
        Index("ix_campaign_execution_runs_status", "status"),
        Index("ix_campaign_execution_runs_sequence_id", "sequence_id"),
        Index("ix_campaign_execution_runs_campaign_status", "campaign_id", "status"),
        Index(
            "uq_execution_runs_active_campaign_sequence",
            "campaign_id",
            "sequence_id",
            unique=True,
            postgresql_where=text(
                "status IN ('DRAFT', 'PENDING', 'RUNNING', 'PAUSED')"
            ),
        ),
    )

    campaign_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("outreach_sequences.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ExecutionRunStatus.DRAFT.value,
    )
    execution_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ExecutionMode.TEST_MANUAL_ONLY.value,
    )
    max_messages: Mapped[int] = mapped_column(Integer, nullable=False)
    batch_size: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    planned_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blocked_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unknown_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    is_test_data: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    campaign: Mapped[Campaign] = relationship("Campaign")
    sequence: Mapped[OutreachSequence] = relationship("OutreachSequence")
    items: Mapped[list[CampaignExecutionItem]] = relationship(
        "CampaignExecutionItem",
        back_populates="execution_run",
        cascade="all, delete-orphan",
        order_by="CampaignExecutionItem.position",
    )
