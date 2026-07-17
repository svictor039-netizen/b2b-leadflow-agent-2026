from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import OutreachApprovalDecision, OutreachMessageStatus
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.campaign import Campaign
    from app.models.campaign_lead import CampaignLead
    from app.models.outreach_sequence import OutreachSequence, OutreachSequenceStep
    from app.models.outreach_template import OutreachTemplate
    from app.models.send_attempt import SendAttempt


class OutreachMessage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "outreach_messages"
    __table_args__ = (
        UniqueConstraint(
            "campaign_lead_id",
            "sequence_step_id",
            name="uq_outreach_messages_lead_step",
        ),
        UniqueConstraint("idempotency_key", name="uq_outreach_messages_idempotency_key"),
        Index("ix_outreach_messages_campaign_id", "campaign_id"),
        Index("ix_outreach_messages_status", "status"),
        Index("ix_outreach_messages_approval_decision", "approval_decision"),
        Index("ix_outreach_messages_campaign_status", "campaign_id", "status"),
    )

    campaign_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    campaign_lead_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("campaign_leads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("outreach_sequences.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    sequence_step_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("outreach_sequence_steps.id", ondelete="RESTRICT"),
        nullable=False,
    )
    template_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("outreach_templates.id", ondelete="RESTRICT"),
        nullable=False,
    )
    recipient_email: Mapped[str] = mapped_column(String(320), nullable=False)
    subject_rendered: Mapped[str] = mapped_column(String(200), nullable=False)
    body_rendered: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=OutreachMessageStatus.DRAFT.value,
    )
    approval_decision: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=OutreachApprovalDecision.PENDING.value,
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reject_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    is_test_data: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    campaign: Mapped[Campaign] = relationship("Campaign")
    campaign_lead: Mapped[CampaignLead] = relationship("CampaignLead")
    sequence: Mapped[OutreachSequence] = relationship("OutreachSequence", back_populates="messages")
    sequence_step: Mapped[OutreachSequenceStep] = relationship(
        "OutreachSequenceStep",
        back_populates="messages",
    )
    template: Mapped[OutreachTemplate] = relationship("OutreachTemplate", back_populates="messages")
    send_attempts: Mapped[list[SendAttempt]] = relationship(
        "SendAttempt",
        back_populates="message",
        cascade="all, delete-orphan",
    )
