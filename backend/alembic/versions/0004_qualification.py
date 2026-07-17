"""Stage 3: qualification_runs, lead_score_snapshots, CampaignLead scoring fields.

Revision ID: 0004_qualification
Revises: 0003_research_runs
Create Date: 2026-07-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_qualification"
down_revision: Union[str, None] = "0003_research_runs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "qualification_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("research_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("scoring_version", sa.String(length=64), nullable=False, server_default="stage3-v1"),
        sa.Column("found_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_leads_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("matched_leads_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scored_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("qualified_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("review_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("disqualified_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conflict_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("is_test_data", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["research_run_id"], ["research_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_qualification_runs_campaign_id", "qualification_runs", ["campaign_id"])
    op.create_index("ix_qualification_runs_research_run_id", "qualification_runs", ["research_run_id"])
    op.create_index("ix_qualification_runs_status", "qualification_runs", ["status"])

    op.add_column("campaign_leads", sa.Column("qualification_score", sa.Integer(), nullable=True))
    op.add_column("campaign_leads", sa.Column("qualification_status", sa.String(length=32), nullable=True))
    op.add_column(
        "campaign_leads",
        sa.Column("review_decision", sa.String(length=32), nullable=False, server_default="PENDING"),
    )
    op.add_column("campaign_leads", sa.Column("score_version", sa.String(length=64), nullable=True))
    op.add_column("campaign_leads", sa.Column("scored_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "campaign_leads",
        sa.Column("score_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "campaign_leads",
        sa.Column("source_research_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "campaign_leads",
        sa.Column("is_test_data", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column("campaign_leads", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("campaign_leads", sa.Column("review_note", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_campaign_leads_source_research_run_id",
        "campaign_leads",
        "research_runs",
        ["source_research_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_campaign_leads_qualification_score", "campaign_leads", ["qualification_score"])
    op.create_index("ix_campaign_leads_qualification_status", "campaign_leads", ["qualification_status"])
    op.create_index("ix_campaign_leads_review_decision", "campaign_leads", ["review_decision"])
    op.create_index(
        "ix_campaign_leads_source_research_run_id",
        "campaign_leads",
        ["source_research_run_id"],
    )
    op.create_index(
        "ix_campaign_leads_campaign_qual_status",
        "campaign_leads",
        ["campaign_id", "qualification_status"],
    )

    op.create_table(
        "lead_score_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("qualification_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_lead_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("scoring_version", sa.String(length=64), nullable=False),
        sa.Column("qualification_status", sa.String(length=32), nullable=False),
        sa.Column("reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("input_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_test_data", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["qualification_run_id"],
            ["qualification_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_lead_id"],
            ["campaign_leads.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "qualification_run_id",
            "campaign_lead_id",
            name="uq_lead_score_snapshots_run_lead",
        ),
    )
    op.create_index(
        "ix_lead_score_snapshots_qualification_run_id",
        "lead_score_snapshots",
        ["qualification_run_id"],
    )
    op.create_index(
        "ix_lead_score_snapshots_campaign_lead_id",
        "lead_score_snapshots",
        ["campaign_lead_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_lead_score_snapshots_campaign_lead_id", table_name="lead_score_snapshots")
    op.drop_index("ix_lead_score_snapshots_qualification_run_id", table_name="lead_score_snapshots")
    op.drop_table("lead_score_snapshots")

    op.drop_index("ix_campaign_leads_campaign_qual_status", table_name="campaign_leads")
    op.drop_index("ix_campaign_leads_source_research_run_id", table_name="campaign_leads")
    op.drop_index("ix_campaign_leads_review_decision", table_name="campaign_leads")
    op.drop_index("ix_campaign_leads_qualification_status", table_name="campaign_leads")
    op.drop_index("ix_campaign_leads_qualification_score", table_name="campaign_leads")
    op.drop_constraint("fk_campaign_leads_source_research_run_id", "campaign_leads", type_="foreignkey")
    op.drop_column("campaign_leads", "review_note")
    op.drop_column("campaign_leads", "reviewed_at")
    op.drop_column("campaign_leads", "is_test_data")
    op.drop_column("campaign_leads", "source_research_run_id")
    op.drop_column("campaign_leads", "score_reasons")
    op.drop_column("campaign_leads", "scored_at")
    op.drop_column("campaign_leads", "score_version")
    op.drop_column("campaign_leads", "review_decision")
    op.drop_column("campaign_leads", "qualification_status")
    op.drop_column("campaign_leads", "qualification_score")

    op.drop_index("ix_qualification_runs_status", table_name="qualification_runs")
    op.drop_index("ix_qualification_runs_research_run_id", table_name="qualification_runs")
    op.drop_index("ix_qualification_runs_campaign_id", table_name="qualification_runs")
    op.drop_table("qualification_runs")
