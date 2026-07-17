from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin, utc_now

if TYPE_CHECKING:
    from app.models.campaign import Campaign
    from app.models.outreach_message import OutreachMessage
    from app.models.outreach_template import OutreachTemplate


class OutreachSequence(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "outreach_sequences"
    __table_args__ = (Index("ix_outreach_sequences_campaign_id", "campaign_id"),)

    campaign_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_test_data: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    campaign: Mapped[Campaign] = relationship("Campaign")
    steps: Mapped[list[OutreachSequenceStep]] = relationship(
        "OutreachSequenceStep",
        back_populates="sequence",
        cascade="all, delete-orphan",
        order_by="OutreachSequenceStep.step_number",
    )
    messages: Mapped[list[OutreachMessage]] = relationship(
        "OutreachMessage",
        back_populates="sequence",
    )


class OutreachSequenceStep(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "outreach_sequence_steps"
    __table_args__ = (
        UniqueConstraint("sequence_id", "step_number", name="uq_outreach_sequence_step_number"),
        Index("ix_outreach_sequence_steps_sequence_id", "sequence_id"),
        Index("ix_outreach_sequence_steps_template_id", "template_id"),
    )

    sequence_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("outreach_sequences.id", ondelete="CASCADE"),
        nullable=False,
    )
    template_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("outreach_templates.id", ondelete="RESTRICT"),
        nullable=False,
    )
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=utc_now,
    )

    sequence: Mapped[OutreachSequence] = relationship("OutreachSequence", back_populates="steps")
    template: Mapped[OutreachTemplate] = relationship("OutreachTemplate", back_populates="sequence_steps")
    messages: Mapped[list[OutreachMessage]] = relationship(
        "OutreachMessage",
        back_populates="sequence_step",
    )
