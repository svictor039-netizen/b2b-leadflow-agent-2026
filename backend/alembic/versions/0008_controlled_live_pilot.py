"""Stage 7A: controlled live pilot infrastructure.

Revision ID: 0008_controlled_live_pilot
Revises: 0007_compliance_ready
Create Date: 2026-07-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_controlled_live_pilot"
down_revision: Union[str, None] = "0007_compliance_ready"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "live_pilots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="DRAFT"),
        sa.Column("provider_name", sa.String(length=64), nullable=True),
        sa.Column("sender_identity_masked", sa.String(length=128), nullable=True),
        sa.Column("sender_domain", sa.String(length=255), nullable=True),
        sa.Column("subject_snapshot", sa.String(length=200), nullable=False),
        sa.Column("body_snapshot", sa.Text(), nullable=False),
        sa.Column("max_recipients", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("daily_limit", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("per_minute_limit", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "requires_manual_approval",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "approval_count_required",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=False, server_default="manual"),
        sa.Column("is_test_data", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "live_delivery_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("primary_message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("live_sent_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("dry_run_sent_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["primary_message_id"], ["outreach_messages.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_live_pilots_idempotency"),
    )
    op.create_index("ix_live_pilots_campaign_id", "live_pilots", ["campaign_id"])
    op.create_index("ix_live_pilots_status", "live_pilots", ["status"])
    op.create_index(
        "ix_live_pilots_campaign_status_created",
        "live_pilots",
        ["campaign_id", "status", "created_at"],
    )
    op.create_index(
        "uq_live_pilots_active_campaign",
        "live_pilots",
        ["campaign_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('DRAFT', 'VALIDATING', 'READY_FOR_APPROVAL', 'APPROVED')"
        ),
    )

    op.create_table(
        "live_pilot_recipients",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pilot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("outreach_message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_masked", sa.String(length=128), nullable=False),
        sa.Column("recipient_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("compliance_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_message_id", sa.String(length=128), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["pilot_id"], ["live_pilots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["outreach_message_id"], ["outreach_messages.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pilot_id", "outreach_message_id", name="uq_live_pilot_recipient_message"),
        sa.UniqueConstraint("pilot_id", "position", name="uq_live_pilot_recipient_position"),
    )
    op.create_index(
        "ix_live_pilot_recipients_pilot_status",
        "live_pilot_recipients",
        ["pilot_id", "status"],
    )
    op.create_index(
        "ix_live_pilot_recipients_message",
        "live_pilot_recipients",
        ["outreach_message_id"],
    )

    op.create_table(
        "live_pilot_approvals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pilot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("challenge_hash", sa.String(length=128), nullable=False),
        sa.Column("confirmation_phrase", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.String(length=64), nullable=False, server_default="manual"),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["pilot_id"], ["live_pilots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_live_pilot_approvals_pilot_id", "live_pilot_approvals", ["pilot_id"])

    op.create_table(
        "live_pilot_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pilot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("safe_detail", sa.String(length=500), nullable=True),
        sa.Column("masked_recipient", sa.String(length=128), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["pilot_id"], ["live_pilots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_live_pilot_events_idempotency"),
    )
    op.create_index("ix_live_pilot_events_pilot_id", "live_pilot_events", ["pilot_id"])
    op.create_index("ix_live_pilot_events_event_type", "live_pilot_events", ["event_type"])

    op.create_table(
        "live_pilot_allowlist_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("recipient_masked", sa.String(length=128), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "confirmed_by_owner",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("is_test_data", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", sa.String(length=64), nullable=False, server_default="manual"),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_live_pilot_allowlist_campaign",
        "live_pilot_allowlist_entries",
        ["campaign_id"],
    )
    op.create_index(
        "uq_live_pilot_allowlist_active",
        "live_pilot_allowlist_entries",
        ["campaign_id", "recipient_fingerprint"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )


def downgrade() -> None:
    op.drop_index("uq_live_pilot_allowlist_active", table_name="live_pilot_allowlist_entries")
    op.drop_index("ix_live_pilot_allowlist_campaign", table_name="live_pilot_allowlist_entries")
    op.drop_table("live_pilot_allowlist_entries")

    op.drop_index("ix_live_pilot_events_event_type", table_name="live_pilot_events")
    op.drop_index("ix_live_pilot_events_pilot_id", table_name="live_pilot_events")
    op.drop_table("live_pilot_events")

    op.drop_index("ix_live_pilot_approvals_pilot_id", table_name="live_pilot_approvals")
    op.drop_table("live_pilot_approvals")

    op.drop_index("ix_live_pilot_recipients_message", table_name="live_pilot_recipients")
    op.drop_index("ix_live_pilot_recipients_pilot_status", table_name="live_pilot_recipients")
    op.drop_table("live_pilot_recipients")

    op.drop_index("uq_live_pilots_active_campaign", table_name="live_pilots")
    op.drop_index("ix_live_pilots_campaign_status_created", table_name="live_pilots")
    op.drop_index("ix_live_pilots_status", table_name="live_pilots")
    op.drop_index("ix_live_pilots_campaign_id", table_name="live_pilots")
    op.drop_table("live_pilots")
