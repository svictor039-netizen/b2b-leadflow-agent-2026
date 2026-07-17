from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import CompanyStatus
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.campaign_lead import CampaignLead
    from app.models.company_source_record import CompanySourceRecord
    from app.models.contact import Contact


class Company(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(300), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=CompanyStatus.UNKNOWN.value,
        index=True,
    )
    source_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    locations: Mapped[list[CompanyLocation]] = relationship(
        "CompanyLocation",
        back_populates="company",
        cascade="all, delete-orphan",
    )
    contacts: Mapped[list[Contact]] = relationship(
        "Contact",
        back_populates="company",
        cascade="all, delete-orphan",
    )
    source_records: Mapped[list[CompanySourceRecord]] = relationship(
        "CompanySourceRecord",
        back_populates="company",
        cascade="all, delete-orphan",
    )
    campaign_leads: Mapped[list[CampaignLead]] = relationship(
        "CampaignLead",
        back_populates="company",
    )


class CompanyLocation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "company_locations"

    company_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    region: Mapped[str | None] = mapped_column(String(200), nullable=True)
    city: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    company: Mapped[Company] = relationship("Company", back_populates="locations")
