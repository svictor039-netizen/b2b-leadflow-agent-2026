"""Stage 5: campaign execution runs and items.

Revision ID: 0006_test_campaign_execution
Revises: 0005_safe_outreach
Create Date: 2026-07-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_test_campaign_execution"
down_revision: Union[str, None] = "0005_safe_outreach"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "campaign_execution_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="DRAFT"),
        sa.Column("execution_mode", sa.String(length=32), nullable=False, server_default="TEST_MANUAL_ONLY"),
        sa.Column("max_messages", sa.Integer(), nullable=False),
        sa.Column("batch_size", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("planned_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocked_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unknown_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("is_test_data", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sequence_id"], ["outreach_sequences.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_campaign_execution_runs_idempotency"),
    )
    op.create_index("ix_campaign_execution_runs_campaign_id", "campaign_execution_runs", ["campaign_id"])
    op.create_index("ix_campaign_execution_runs_status", "campaign_execution_runs", ["status"])
    op.create_index("ix_campaign_execution_runs_sequence_id", "campaign_execution_runs", ["sequence_id"])
    op.create_index(
        "ix_campaign_execution_runs_campaign_status",
        "campaign_execution_runs",
        ["campaign_id", "status"],
    )
    # One active (non-terminal) run per campaign+sequence; history of terminal runs allowed.
    op.create_index(
        "uq_execution_runs_active_campaign_sequence",
        "campaign_execution_runs",
        ["campaign_id", "sequence_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('DRAFT', 'PENDING', 'RUNNING', 'PAUSED')"
        ),
    )

    op.create_table(
        "campaign_execution_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("outreach_message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("is_test_data", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["execution_run_id"], ["campaign_execution_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["outreach_message_id"], ["outreach_messages.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execution_run_id", "outreach_message_id", name="uq_execution_items_run_message"),
        sa.UniqueConstraint("execution_run_id", "position", name="uq_execution_items_run_position"),
    )
    op.create_index("ix_campaign_execution_items_run_id", "campaign_execution_items", ["execution_run_id"])
    op.create_index("ix_campaign_execution_items_status", "campaign_execution_items", ["status"])
    op.create_index("ix_campaign_execution_items_message_id", "campaign_execution_items", ["outreach_message_id"])
    op.create_index(
        "ix_campaign_execution_items_run_status",
        "campaign_execution_items",
        ["execution_run_id", "status"],
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_campaign_execution_items_run_status")
    op.execute("DROP INDEX IF EXISTS ix_campaign_execution_items_message_id")
    op.execute("DROP INDEX IF EXISTS ix_campaign_execution_items_status")
    op.execute("DROP INDEX IF EXISTS ix_campaign_execution_items_run_id")
    op.drop_table("campaign_execution_items")

    op.execute("DROP INDEX IF EXISTS uq_execution_runs_active_campaign_sequence")
    op.execute("DROP INDEX IF EXISTS ix_campaign_execution_runs_campaign_status")
    op.execute("DROP INDEX IF EXISTS ix_campaign_execution_runs_sequence_id")
    op.execute("DROP INDEX IF EXISTS ix_campaign_execution_runs_status")
    op.execute("DROP INDEX IF EXISTS ix_campaign_execution_runs_campaign_id")
    op.drop_table("campaign_execution_runs")
