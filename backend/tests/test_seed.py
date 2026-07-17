import os

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.models import Campaign, Company
from app.scripts.seed_demo_data import DEMO_CAMPAIGN_NAME, seed


@pytest.fixture
def seed_db_url(db_engine) -> str:
    return str(db_engine.url)


def test_seed_idempotent(db_engine) -> None:
    if os.getenv("SKIP_DB_TESTS") == "1":
        pytest.skip("SKIP_DB_TESTS=1")

    # Point SessionLocal used by seed at the test engine by temporarily patching
    from app.core import database as database_module

    original_session = database_module.SessionLocal
    database_module.SessionLocal = sessionmaker(
        bind=db_engine, autoflush=False, autocommit=False
    )
    try:
        seed()
        seed()

        session = database_module.SessionLocal()
        try:
            campaigns = session.scalars(
                select(Campaign).where(Campaign.name == DEMO_CAMPAIGN_NAME)
            ).all()
            assert len(campaigns) == 1

            companies = session.scalars(select(Company)).all()
            # At least the 3 demo domains, but not duplicated
            domains = [c.domain for c in companies if c.domain and c.domain.endswith(".example.com")]
            assert len(domains) == len(set(domains))
            assert len(domains) >= 3
        finally:
            session.close()
    finally:
        database_module.SessionLocal = original_session
