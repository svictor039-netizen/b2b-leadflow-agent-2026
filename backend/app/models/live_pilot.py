"""Stage 7A controlled live pilot models."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import LivePilotRecipientStatus, LivePilotStatus
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.campaign import Campaign
    from app.models.outreach_message import OutreachMessage


class LivePilot(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "live_pilots"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_live_pilots_idempotency"),
        Index("ix_live_pilots_campaign_id", "campaign_id"),
        Index("ix_live_pilots_status", "status"),
        Index("ix_live_pilots_campaign_status_created", "campaign_id", "status", "created_at"),
        Index(
            "uq_live_pilots_active_campaign",
            "campaign_id",
            unique=True,
            postgresql_where=text(
                "status IN ('DRAFT', 'VALIDATING', 'READY_FOR_APPROVAL', 'APPROVED')"
            ),
        ),
    )

    campaign_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=LivePilotStatus.DRAFT.value,
    )
    provider_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sender_identity_masked: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sender_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    body_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    max_recipients: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    daily_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    per_minute_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    requires_manual_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    approval_count_required: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, default="manual")
    is_test_data: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    live_delivery_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    primary_message_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("outreach_messages.id", ondelete="RESTRICT"),
        nullable=False,
    )
    live_sent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dry_run_sent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    campaign: Mapped[Campaign] = relationship("Campaign")
    primary_message: Mapped[OutreachMessage] = relationship("OutreachMessage")
    recipients: Mapped[list[LivePilotRecipient]] = relationship(
        "LivePilotRecipient",
        back_populates="pilot",
        cascade="all, delete-orphan",
        order_by="LivePilotRecipient.position",
    )
    approvals: Mapped[list[LivePilotApproval]] = relationship(
        "LivePilotApproval",
        back_populates="pilot",
        cascade="all, delete-orphan",
    )
    events: Mapped[list[LivePilotEvent]] = relationship(
        "LivePilotEvent",
        back_populates="pilot",
        cascade="all, delete-orphan",
    )


class LivePilotRecipient(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "live_pilot_recipients"
    __table_args__ = (
        UniqueConstraint("pilot_id", "outreach_message_id", name="uq_live_pilot_recipient_message"),
        UniqueConstraint("pilot_id", "position", name="uq_live_pilot_recipient_position"),
        Index("ix_live_pilot_recipients_pilot_status", "pilot_id", "status"),
        Index("ix_live_pilot_recipients_message", "outreach_message_id"),
    )

    pilot_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("live_pilots.id", ondelete="CASCADE"),
        nullable=False,
    )
    outreach_message_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("outreach_messages.id", ondelete="RESTRICT"),
        nullable=False,
    )
    recipient_masked: Mapped[str] = mapped_column(String(128), nullable=False)
    recipient_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=LivePilotRecipientStatus.PENDING.value,
    )
    compliance_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)

    pilot: Mapped[LivePilot] = relationship("LivePilot", back_populates="recipients")
    outreach_message: Mapped[OutreachMessage] = relationship("OutreachMessage")


class LivePilotApproval(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "live_pilot_approvals"
    __table_args__ = (
        Index("ix_live_pilot_approvals_pilot_id", "pilot_id"),
    )

    pilot_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("live_pilots.id", ondelete="CASCADE"),
        nullable=False,
    )
    challenge_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    confirmation_phrase: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str] = mapped_column(String(64), nullable=False, default="manual")
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    pilot: Mapped[LivePilot] = relationship("LivePilot", back_populates="approvals")


class LivePilotEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "live_pilot_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_live_pilot_events_idempotency"),
        Index("ix_live_pilot_events_pilot_id", "pilot_id"),
        Index("ix_live_pilot_events_event_type", "event_type"),
    )

    pilot_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("live_pilots.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    safe_detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    masked_recipient: Mapped[str | None] = mapped_column(String(128), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)

    pilot: Mapped[LivePilot] = relationship("LivePilot", back_populates="events")


class LivePilotAllowlistEntry(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "live_pilot_allowlist_entries"
    __table_args__ = (
        Index(
            "uq_live_pilot_allowlist_active",
            "campaign_id",
            "recipient_fingerprint",
            unique=True,
            postgresql_where=text("is_active = true"),
        ),
        Index("ix_live_pilot_allowlist_campaign", "campaign_id"),
    )

    campaign_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    recipient_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    recipient_masked: Mapped[str] = mapped_column(String(128), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by_owner: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_test_data: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, default="manual")
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
