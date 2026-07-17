from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import DataSourceType
from app.models.mixins import CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.research_run import ResearchRun


class DataSource(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "data_sources"

    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    source_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=DataSourceType.MANUAL.value,
    )
    base_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    source_records: Mapped[list[CompanySourceRecord]] = relationship(
        "CompanySourceRecord",
        back_populates="data_source",
    )


class CompanySourceRecord(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    __tablename__ = "company_source_records"
    __table_args__ = (
        UniqueConstraint(
            "data_source_id",
            "external_id",
            name="uq_company_source_records_source_external",
        ),
    )

    company_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    data_source_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("data_sources.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    research_run_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("research_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    query_text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_test_data: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    company: Mapped[Company] = relationship("Company", back_populates="source_records")
    data_source: Mapped[DataSource] = relationship("DataSource", back_populates="source_records")
    research_run: Mapped[ResearchRun | None] = relationship("ResearchRun")
