from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import ComplianceDecision
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.campaign import Campaign
    from app.models.suppression_entry import SuppressionEntry


class ComplianceDecisionLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "compliance_decision_logs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_compliance_decision_logs_idempotency"),
        Index("ix_compliance_logs_campaign_id", "campaign_id"),
        Index("ix_compliance_logs_message_id", "outreach_message_id"),
        Index("ix_compliance_logs_lead_id", "campaign_lead_id"),
        Index("ix_compliance_logs_checked_at", "checked_at"),
        Index("ix_compliance_logs_decision", "decision"),
    )

    campaign_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    campaign_lead_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("campaign_leads.id", ondelete="SET NULL"),
        nullable=True,
    )
    outreach_message_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("outreach_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    execution_run_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("campaign_execution_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    decision: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ComplianceDecision.ALLOWED.value
    )
    matched_suppression_entry_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("suppression_entries.id", ondelete="SET NULL"),
        nullable=True,
    )
    check_context: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(128), nullable=False)
    safe_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    masked_recipient: Mapped[str | None] = mapped_column(String(128), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_test_data: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    campaign: Mapped[Campaign] = relationship("Campaign")
    matched_entry: Mapped[SuppressionEntry | None] = relationship("SuppressionEntry")
