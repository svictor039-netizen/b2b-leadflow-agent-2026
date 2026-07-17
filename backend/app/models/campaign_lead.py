from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import CampaignLeadStatus
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.campaign import Campaign
    from app.models.company import Company


class CampaignLead(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "campaign_leads"
    __table_args__ = (
        UniqueConstraint("campaign_id", "company_id", name="uq_campaign_leads_campaign_company"),
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

    campaign: Mapped[Campaign] = relationship("Campaign", back_populates="leads")
    company: Mapped[Company] = relationship("Company", back_populates="campaign_leads")
