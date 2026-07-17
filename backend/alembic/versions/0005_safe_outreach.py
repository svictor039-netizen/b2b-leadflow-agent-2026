"""Stage 4: safe outreach templates, sequences, messages, send attempts.

Revision ID: 0005_safe_outreach
Revises: 0004_qualification
Create Date: 2026-07-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_safe_outreach"
down_revision: Union[str, None] = "0004_qualification"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "outreach_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("subject_template", sa.String(length=200), nullable=False),
        sa.Column("body_template", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_test_data", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outreach_templates_campaign_id", "outreach_templates", ["campaign_id"])

    op.create_table(
        "outreach_sequences",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_test_data", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outreach_sequences_campaign_id", "outreach_sequences", ["campaign_id"])

    op.create_table(
        "outreach_sequence_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("step_number >= 1 AND step_number <= 3", name="ck_outreach_step_number_range"),
        sa.ForeignKeyConstraint(["sequence_id"], ["outreach_sequences.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["template_id"], ["outreach_templates.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sequence_id", "step_number", name="uq_outreach_sequence_step_number"),
    )
    op.create_index("ix_outreach_sequence_steps_sequence_id", "outreach_sequence_steps", ["sequence_id"])
    op.create_index("ix_outreach_sequence_steps_template_id", "outreach_sequence_steps", ["template_id"])

    op.create_table(
        "outreach_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_lead_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence_step_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_email", sa.String(length=320), nullable=False),
        sa.Column("subject_rendered", sa.String(length=200), nullable=False),
        sa.Column("body_rendered", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="DRAFT"),
        sa.Column("approval_decision", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.String(length=64), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reject_note", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("is_test_data", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["campaign_lead_id"], ["campaign_leads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sequence_id"], ["outreach_sequences.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sequence_step_id"], ["outreach_sequence_steps.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["template_id"], ["outreach_templates.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("campaign_lead_id", "sequence_step_id", name="uq_outreach_messages_lead_step"),
        sa.UniqueConstraint("idempotency_key", name="uq_outreach_messages_idempotency_key"),
    )
    op.create_index("ix_outreach_messages_campaign_id", "outreach_messages", ["campaign_id"])
    op.create_index("ix_outreach_messages_campaign_lead_id", "outreach_messages", ["campaign_lead_id"])
    op.create_index("ix_outreach_messages_sequence_id", "outreach_messages", ["sequence_id"])
    op.create_index("ix_outreach_messages_status", "outreach_messages", ["status"])
    op.create_index("ix_outreach_messages_approval_decision", "outreach_messages", ["approval_decision"])
    op.create_index(
        "ix_outreach_messages_campaign_status",
        "outreach_messages",
        ["campaign_id", "status"],
    )

    op.create_table(
        "send_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_name", sa.String(length=64), nullable=False, server_default="test_email"),
        sa.Column("provider_message_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("safe_error_message", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("is_test_data", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["outreach_messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_send_attempts_idempotency_key"),
    )
    op.create_index("ix_send_attempts_message_id", "send_attempts", ["message_id"])
    op.create_index(
        "uq_send_attempts_message_success",
        "send_attempts",
        ["message_id"],
        unique=True,
        postgresql_where=sa.text("status = 'SUCCESS'"),
    )


def downgrade() -> None:
    op.drop_index("uq_send_attempts_message_success", table_name="send_attempts")
    op.drop_index("ix_send_attempts_message_id", table_name="send_attempts")
    op.drop_table("send_attempts")

    op.drop_index("ix_outreach_messages_campaign_status", table_name="outreach_messages")
    op.drop_index("ix_outreach_messages_approval_decision", table_name="outreach_messages")
    op.drop_index("ix_outreach_messages_status", table_name="outreach_messages")
    op.drop_index("ix_outreach_messages_sequence_id", table_name="outreach_messages")
    op.drop_index("ix_outreach_messages_campaign_lead_id", table_name="outreach_messages")
    op.drop_index("ix_outreach_messages_campaign_id", table_name="outreach_messages")
    op.drop_table("outreach_messages")

    op.drop_index("ix_outreach_sequence_steps_template_id", table_name="outreach_sequence_steps")
    op.drop_index("ix_outreach_sequence_steps_sequence_id", table_name="outreach_sequence_steps")
    op.drop_table("outreach_sequence_steps")

    op.drop_index("ix_outreach_sequences_campaign_id", table_name="outreach_sequences")
    op.drop_table("outreach_sequences")

    op.drop_index("ix_outreach_templates_campaign_id", table_name="outreach_templates")
    op.drop_table("outreach_templates")
