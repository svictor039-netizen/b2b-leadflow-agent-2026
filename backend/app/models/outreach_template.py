from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.campaign import Campaign
    from app.models.outreach_sequence import OutreachSequenceStep
    from app.models.outreach_message import OutreachMessage


class OutreachTemplate(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "outreach_templates"
    __table_args__ = (Index("ix_outreach_templates_campaign_id", "campaign_id"),)

    campaign_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    subject_template: Mapped[str] = mapped_column(String(200), nullable=False)
    body_template: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_test_data: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    campaign: Mapped[Campaign | None] = relationship("Campaign")
    sequence_steps: Mapped[list[OutreachSequenceStep]] = relationship(
        "OutreachSequenceStep",
        back_populates="template",
    )
    messages: Mapped[list[OutreachMessage]] = relationship(
        "OutreachMessage",
        back_populates="template",
    )
