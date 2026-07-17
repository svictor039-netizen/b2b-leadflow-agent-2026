from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import SuppressionScope, SuppressionSource, SuppressionType
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.campaign import Campaign


class SuppressionEntry(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "suppression_entries"
    __table_args__ = (
        Index("ix_suppression_entries_scope", "scope"),
        Index("ix_suppression_entries_type", "suppression_type"),
        Index("ix_suppression_entries_reason", "reason"),
        Index("ix_suppression_entries_campaign_id", "campaign_id"),
        Index("ix_suppression_entries_active", "is_active"),
        Index("ix_suppression_entries_normalized", "normalized_value"),
        Index(
            "uq_suppression_active_global",
            "suppression_type",
            "normalized_value",
            unique=True,
            postgresql_where=text("is_active = true AND scope = 'GLOBAL'"),
        ),
        Index(
            "uq_suppression_active_campaign",
            "campaign_id",
            "suppression_type",
            "normalized_value",
            unique=True,
            postgresql_where=text("is_active = true AND scope = 'CAMPAIGN'"),
        ),
    )

    scope: Mapped[str] = mapped_column(
        String(32), nullable=False, default=SuppressionScope.GLOBAL.value
    )
    campaign_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=True,
    )
    suppression_type: Mapped[str] = mapped_column(String(32), nullable=False)
    normalized_value: Mapped[str] = mapped_column(String(320), nullable=False)
    display_value: Mapped[str] = mapped_column(String(320), nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default=SuppressionSource.MANUAL.value
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, default="manual")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_test_data: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    campaign: Mapped[Campaign | None] = relationship("Campaign")
