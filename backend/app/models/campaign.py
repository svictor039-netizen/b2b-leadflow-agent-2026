from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import CampaignStatus, SendingMode
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.campaign_lead import CampaignLead


class Campaign(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "campaigns"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    business_type: Mapped[str] = mapped_column(String(200), nullable=False)
    region: Mapped[str] = mapped_column(String(200), nullable=False)
    offer: Mapped[str] = mapped_column(String(500), nullable=False)
    offer_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    ideal_customer: Mapped[str | None] = mapped_column(Text, nullable=True)
    desired_cta: Mapped[str | None] = mapped_column(String(500), nullable=True)
    max_companies: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    max_emails_per_lead: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    sending_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=SendingMode.MANUAL_APPROVAL.value,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=CampaignStatus.DRAFT.value,
    )

    leads: Mapped[list[CampaignLead]] = relationship(
        "CampaignLead",
        back_populates="campaign",
        cascade="all, delete-orphan",
    )
