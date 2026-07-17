from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import SendAttemptStatus
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.outreach_message import OutreachMessage


class SendAttempt(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Test outbox / send history for Stage 4. No real SMTP."""

    __tablename__ = "send_attempts"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_send_attempts_idempotency_key"),
        Index("ix_send_attempts_message_id", "message_id"),
        Index(
            "uq_send_attempts_message_success",
            "message_id",
            unique=True,
            postgresql_where=text("status = 'SUCCESS'"),
        ),
    )

    message_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("outreach_messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False, default="test_email")
    provider_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=SendAttemptStatus.SUCCESS.value,
    )
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    safe_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    is_test_data: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    message: Mapped[OutreachMessage] = relationship("OutreachMessage", back_populates="send_attempts")
