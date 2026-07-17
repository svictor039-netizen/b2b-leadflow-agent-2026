"""Idempotent demo seed for Stage 1 (manual only, not auto-run in production).

Usage:
    python -m app.scripts.seed_demo_data
"""

from __future__ import annotations

from sqlalchemy import select

from app.core import database as database_module
from app.core.exceptions import AppError
from app.models import (
    Campaign,
    Company,
    CompanyStatus,
    ConsentStatus,
    ContactType,
    DataSource,
    DataSourceType,
    SendingMode,
)
from app.schemas.campaign import CampaignCreate
from app.schemas.company import CompanyCreate, ContactCreate, LocationCreate
from app.services import campaign_service
from app.services.campaign_service import attach_company_to_campaign
from app.services.company_service import create_company, create_contact, create_location

DEMO_CAMPAIGN_NAME = "Demo Campaign Stage 1"
DEMO_SOURCE_NAME = "manual-demo"


def seed() -> None:
    db = database_module.SessionLocal()
    try:
        source = db.scalar(select(DataSource).where(DataSource.name == DEMO_SOURCE_NAME))
        if source is None:
            source = DataSource(
                name=DEMO_SOURCE_NAME,
                source_type=DataSourceType.TEST.value,
                base_url=None,
                enabled=True,
            )
            db.add(source)
            db.commit()

        campaign = db.scalar(select(Campaign).where(Campaign.name == DEMO_CAMPAIGN_NAME))
        if campaign is None:
            created = campaign_service.create_campaign(
                db,
                CampaignCreate(
                    name=DEMO_CAMPAIGN_NAME,
                    business_type="B2B SaaS",
                    region="Northern Europe",
                    offer="LeadFlow pilot",
                    offer_description="Demo offer for stage 1 testing.",
                    ideal_customer="SaaS companies 10-100 employees",
                    desired_cta="Book a short call",
                    max_companies=10,
                    max_emails_per_lead=2,
                    sending_mode=SendingMode.MANUAL_APPROVAL,
                ),
            )
            campaign_id = created.id
        else:
            campaign_id = campaign.id

        demo_companies = [
            {
                "name": "Nordic SaaS Labs",
                "domain": "nordicsaas.example.com",
                "website": "https://nordicsaas.example.com",
                "city": "Stockholm",
                "email": "hello@nordicsaas.example.com",
            },
            {
                "name": "Baltic Logistics Pro",
                "domain": "balticlog.example.com",
                "website": "https://balticlog.example.com",
                "city": "Riga",
                "email": "sales@balticlog.example.com",
            },
            {
                "name": "Central FinTech Group",
                "domain": "centralfin.example.com",
                "website": "https://centralfin.example.com",
                "city": "Warsaw",
                "email": "info@centralfin.example.com",
            },
        ]

        for item in demo_companies:
            existing = db.scalar(select(Company).where(Company.domain == item["domain"]))
            if existing is None:
                company = create_company(
                    db,
                    CompanyCreate(
                        name=item["name"],
                        website=item["website"],
                        domain=item["domain"],
                        description="Demo company for Stage 1.",
                        status=CompanyStatus.ACTIVE,
                    ),
                )
                create_location(
                    db,
                    company.id,
                    LocationCreate(city=item["city"], country="EU", is_primary=True),
                )
                create_contact(
                    db,
                    company.id,
                    ContactCreate(
                        contact_type=ContactType.EMAIL,
                        value=item["email"],
                        label="General",
                        source_url=item["website"],
                        consent_status=ConsentStatus.UNKNOWN,
                    ),
                )
                company_id = company.id
            else:
                company_id = existing.id

            try:
                attach_company_to_campaign(db, campaign_id, company_id)
            except AppError as exc:
                if exc.code not in {"duplicate_campaign_lead", "campaign_full"}:
                    raise

        print(f"Seed complete. Campaign id={campaign_id}")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
