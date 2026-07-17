"""Stage 1: campaigns, companies, locations, contacts, sources, campaign_leads.

Revision ID: 0002_campaigns_companies
Revises: 0001_stage0_baseline
Create Date: 2026-07-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_campaigns_companies"
down_revision: Union[str, None] = "0001_stage0_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "campaigns",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("business_type", sa.String(length=200), nullable=False),
        sa.Column("region", sa.String(length=200), nullable=False),
        sa.Column("offer", sa.String(length=500), nullable=False),
        sa.Column("offer_description", sa.Text(), nullable=True),
        sa.Column("ideal_customer", sa.Text(), nullable=True),
        sa.Column("desired_cta", sa.String(length=500), nullable=True),
        sa.Column("max_companies", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("max_emails_per_lead", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("sending_mode", sa.String(length=32), nullable=False, server_default="MANUAL_APPROVAL"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="DRAFT"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_campaigns_status", "campaigns", ["status"])
    op.create_index("ix_campaigns_created_at", "campaigns", ["created_at"])

    op.create_table(
        "companies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("legal_name", sa.String(length=300), nullable=True),
        sa.Column("website", sa.String(length=500), nullable=True),
        sa.Column("domain", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="UNKNOWN"),
        sa.Column("source_confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_companies_domain", "companies", ["domain"])
    op.create_index("ix_companies_status", "companies", ["status"])
    op.create_index("ix_companies_created_at", "companies", ["created_at"])

    op.create_table(
        "data_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False, server_default="MANUAL"),
        sa.Column("base_url", sa.String(length=1000), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "company_locations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("region", sa.String(length=200), nullable=True),
        sa.Column("city", sa.String(length=200), nullable=True),
        sa.Column("address", sa.String(length=500), nullable=True),
        sa.Column("postal_code", sa.String(length=32), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_company_locations_company_id", "company_locations", ["company_id"])
    op.create_index("ix_company_locations_city", "company_locations", ["city"])

    op.create_table(
        "contacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_type", sa.String(length=32), nullable=False),
        sa.Column("value", sa.String(length=500), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column("source_url", sa.String(length=1000), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verification_status", sa.String(length=32), nullable=False, server_default="UNVERIFIED"),
        sa.Column("consent_status", sa.String(length=32), nullable=False, server_default="UNKNOWN"),
        sa.Column("consent_source", sa.String(length=500), nullable=True),
        sa.Column("do_not_contact", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_contacts_company_id", "contacts", ["company_id"])

    op.create_table(
        "company_source_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("data_source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("source_url", sa.String(length=1000), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_company_source_records_company_id", "company_source_records", ["company_id"])
    op.create_index("ix_company_source_records_data_source_id", "company_source_records", ["data_source_id"])

    op.create_table(
        "campaign_leads",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="NEW"),
        sa.Column("approved_for_research", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("approved_for_email", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("campaign_id", "company_id", name="uq_campaign_leads_campaign_company"),
    )
    op.create_index("ix_campaign_leads_campaign_id", "campaign_leads", ["campaign_id"])
    op.create_index("ix_campaign_leads_company_id", "campaign_leads", ["company_id"])


def downgrade() -> None:
    op.drop_index("ix_campaign_leads_company_id", table_name="campaign_leads")
    op.drop_index("ix_campaign_leads_campaign_id", table_name="campaign_leads")
    op.drop_table("campaign_leads")
    op.drop_index("ix_company_source_records_data_source_id", table_name="company_source_records")
    op.drop_index("ix_company_source_records_company_id", table_name="company_source_records")
    op.drop_table("company_source_records")
    op.drop_index("ix_contacts_company_id", table_name="contacts")
    op.drop_table("contacts")
    op.drop_index("ix_company_locations_city", table_name="company_locations")
    op.drop_index("ix_company_locations_company_id", table_name="company_locations")
    op.drop_table("company_locations")
    op.drop_table("data_sources")
    op.drop_index("ix_companies_created_at", table_name="companies")
    op.drop_index("ix_companies_status", table_name="companies")
    op.drop_index("ix_companies_domain", table_name="companies")
    op.drop_table("companies")
    op.drop_index("ix_campaigns_created_at", table_name="campaigns")
    op.drop_index("ix_campaigns_status", table_name="campaigns")
    op.drop_table("campaigns")
