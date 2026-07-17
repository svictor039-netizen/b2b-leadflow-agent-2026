"""Stage 6: compliance suppression and readiness.

Revision ID: 0007_compliance_ready
Revises: 0006_test_campaign_execution
Create Date: 2026-07-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_compliance_ready"
down_revision: Union[str, None] = "0006_test_campaign_execution"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "suppression_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("suppression_type", sa.String(length=32), nullable=False),
        sa.Column("normalized_value", sa.String(length=320), nullable=False),
        sa.Column("display_value", sa.String(length=320), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="MANUAL"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=False, server_default="manual"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_test_data", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_suppression_entries_scope", "suppression_entries", ["scope"])
    op.create_index("ix_suppression_entries_type", "suppression_entries", ["suppression_type"])
    op.create_index("ix_suppression_entries_reason", "suppression_entries", ["reason"])
    op.create_index("ix_suppression_entries_campaign_id", "suppression_entries", ["campaign_id"])
    op.create_index("ix_suppression_entries_active", "suppression_entries", ["is_active"])
    op.create_index("ix_suppression_entries_normalized", "suppression_entries", ["normalized_value"])
    op.create_index(
        "uq_suppression_active_global",
        "suppression_entries",
        ["suppression_type", "normalized_value"],
        unique=True,
        postgresql_where=sa.text("is_active = true AND scope = 'GLOBAL'"),
    )
    op.create_index(
        "uq_suppression_active_campaign",
        "suppression_entries",
        ["campaign_id", "suppression_type", "normalized_value"],
        unique=True,
        postgresql_where=sa.text("is_active = true AND scope = 'CAMPAIGN'"),
    )

    op.create_table(
        "compliance_decision_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_lead_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("outreach_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("execution_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("matched_suppression_entry_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("check_context", sa.String(length=64), nullable=False),
        sa.Column("reason_code", sa.String(length=128), nullable=False),
        sa.Column("safe_details", sa.Text(), nullable=True),
        sa.Column("masked_recipient", sa.String(length=128), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_test_data", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["campaign_lead_id"], ["campaign_leads.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["outreach_message_id"], ["outreach_messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["execution_run_id"], ["campaign_execution_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["matched_suppression_entry_id"], ["suppression_entries.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_compliance_decision_logs_idempotency"),
    )
    op.create_index("ix_compliance_logs_campaign_id", "compliance_decision_logs", ["campaign_id"])
    op.create_index("ix_compliance_logs_message_id", "compliance_decision_logs", ["outreach_message_id"])
    op.create_index("ix_compliance_logs_lead_id", "compliance_decision_logs", ["campaign_lead_id"])
    op.create_index("ix_compliance_logs_checked_at", "compliance_decision_logs", ["checked_at"])
    op.create_index("ix_compliance_logs_decision", "compliance_decision_logs", ["decision"])


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_compliance_logs_decision")
    op.execute("DROP INDEX IF EXISTS ix_compliance_logs_checked_at")
    op.execute("DROP INDEX IF EXISTS ix_compliance_logs_lead_id")
    op.execute("DROP INDEX IF EXISTS ix_compliance_logs_message_id")
    op.execute("DROP INDEX IF EXISTS ix_compliance_logs_campaign_id")
    op.drop_table("compliance_decision_logs")

    op.execute("DROP INDEX IF EXISTS uq_suppression_active_campaign")
    op.execute("DROP INDEX IF EXISTS uq_suppression_active_global")
    op.execute("DROP INDEX IF EXISTS ix_suppression_entries_normalized")
    op.execute("DROP INDEX IF EXISTS ix_suppression_entries_active")
    op.execute("DROP INDEX IF EXISTS ix_suppression_entries_campaign_id")
    op.execute("DROP INDEX IF EXISTS ix_suppression_entries_reason")
    op.execute("DROP INDEX IF EXISTS ix_suppression_entries_type")
    op.execute("DROP INDEX IF EXISTS ix_suppression_entries_scope")
    op.drop_table("suppression_entries")
