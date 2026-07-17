"""Stage 2: research_runs + provenance fields on company_source_records.

Revision ID: 0003_research_runs
Revises: 0002_campaigns_companies
Create Date: 2026-07-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_research_runs"
down_revision: Union[str, None] = "0002_campaigns_companies"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "research_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("adapter", sa.String(length=64), nullable=False),
        sa.Column("query", sa.String(length=200), nullable=False),
        sa.Column("industry", sa.String(length=200), nullable=True),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column("limit", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("found_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("matched_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conflict_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("result_items", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_test_data", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_research_runs_campaign_id", "research_runs", ["campaign_id"])
    op.create_index("ix_research_runs_status", "research_runs", ["status"])

    op.add_column(
        "company_source_records",
        sa.Column("research_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "company_source_records",
        sa.Column("query_text", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "company_source_records",
        sa.Column("is_test_data", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.create_foreign_key(
        "fk_company_source_records_research_run_id",
        "company_source_records",
        "research_runs",
        ["research_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_company_source_records_research_run_id",
        "company_source_records",
        ["research_run_id"],
    )
    op.create_unique_constraint(
        "uq_company_source_records_source_external",
        "company_source_records",
        ["data_source_id", "external_id"],
    )
    # Application-level dedup by domain; partial unique helps when domain present.
    op.create_index(
        "uq_companies_domain_not_null",
        "companies",
        ["domain"],
        unique=True,
        postgresql_where=sa.text("domain IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_companies_domain_not_null", table_name="companies")
    op.drop_constraint(
        "uq_company_source_records_source_external",
        "company_source_records",
        type_="unique",
    )
    op.drop_index("ix_company_source_records_research_run_id", table_name="company_source_records")
    op.drop_constraint(
        "fk_company_source_records_research_run_id",
        "company_source_records",
        type_="foreignkey",
    )
    op.drop_column("company_source_records", "is_test_data")
    op.drop_column("company_source_records", "query_text")
    op.drop_column("company_source_records", "research_run_id")
    op.drop_index("ix_research_runs_status", table_name="research_runs")
    op.drop_index("ix_research_runs_campaign_id", table_name="research_runs")
    op.drop_table("research_runs")
