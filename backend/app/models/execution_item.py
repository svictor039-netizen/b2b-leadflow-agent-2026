from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import ExecutionItemStatus
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.execution_run import CampaignExecutionRun
    from app.models.outreach_message import OutreachMessage


class CampaignExecutionItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "campaign_execution_items"
    __table_args__ = (
        UniqueConstraint(
            "execution_run_id",
            "outreach_message_id",
            name="uq_execution_items_run_message",
        ),
        UniqueConstraint(
            "execution_run_id",
            "position",
            name="uq_execution_items_run_position",
        ),
        Index("ix_campaign_execution_items_run_id", "execution_run_id"),
        Index("ix_campaign_execution_items_status", "status"),
        Index("ix_campaign_execution_items_message_id", "outreach_message_id"),
        Index("ix_campaign_execution_items_run_status", "execution_run_id", "status"),
    )

    execution_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("campaign_execution_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    outreach_message_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("outreach_messages.id", ondelete="RESTRICT"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ExecutionItemStatus.PENDING.value,
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_test_data: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    execution_run: Mapped[CampaignExecutionRun] = relationship(
        "CampaignExecutionRun",
        back_populates="items",
    )
    outreach_message: Mapped[OutreachMessage] = relationship("OutreachMessage")
