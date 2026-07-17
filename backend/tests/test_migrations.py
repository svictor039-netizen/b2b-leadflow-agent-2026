import os
from urllib.parse import urlparse, urlunparse

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import NullPool

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _alembic_config(url: str) -> Config:
    cfg = Config(os.path.join(BACKEND_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_ROOT, "alembic"))
    # Alembic Config treats % as interpolation — escape for passwords/URLs.
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def _base_url() -> str:
    return os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL") or ""


@pytest.fixture
def migration_url() -> str:
    if os.getenv("SKIP_DB_TESTS") == "1":
        pytest.skip("SKIP_DB_TESTS=1")

    base = _base_url()
    if not base:
        pytest.skip("DATABASE_URL not set")

    parsed = urlparse(base)
    db_name = "leadflow_mig_test"
    admin_url = urlunparse(parsed._replace(path="/postgres"))
    url = urlunparse(parsed._replace(path=f"/{db_name}"))

    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"),
            {"n": db_name},
        ).scalar()
        if exists:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    engine.dispose()
    return url


def test_alembic_upgrade_head_and_tables(migration_url: str) -> None:
    cfg = _alembic_config(migration_url)
    command.upgrade(cfg, "head")

    engine = create_engine(migration_url, poolclass=NullPool)
    tables = set(inspect(engine).get_table_names())
    expected = {
        "campaigns",
        "companies",
        "company_locations",
        "contacts",
        "data_sources",
        "company_source_records",
        "campaign_leads",
        "research_runs",
        "alembic_version",
    }
    assert expected.issubset(tables)

    insp = inspect(engine)
    uniques = {
        u["name"] for u in insp.get_unique_constraints("company_source_records")
    }
    assert "uq_company_source_records_source_external" in uniques
    indexes = {i["name"]: i for i in insp.get_indexes("companies")}
    assert "uq_companies_domain_not_null" in indexes
    assert indexes["uq_companies_domain_not_null"]["unique"] is True

    # Idempotent upgrade
    command.upgrade(cfg, "head")

    # One-step downgrade then re-upgrade (Stage 1 schema preserved)
    command.downgrade(cfg, "-1")
    tables_after = set(inspect(engine).get_table_names())
    assert "research_runs" not in tables_after
    assert "campaigns" in tables_after
    assert "company_source_records" in tables_after

    command.upgrade(cfg, "head")
    assert "research_runs" in set(inspect(engine).get_table_names())
    engine.dispose()


def test_alembic_stage1_then_stage2(migration_url: str) -> None:
    """Upgrade from empty → Stage 1 → Stage 2 without data loss markers."""
    cfg = _alembic_config(migration_url)
    command.upgrade(cfg, "0002_campaigns_companies")
    engine = create_engine(migration_url, poolclass=NullPool)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO campaigns (id, name, business_type, region, offer, status, created_at, updated_at) "
                "VALUES (gen_random_uuid(), 'mig-keep', 'SaaS', 'EU', 'Demo', 'DRAFT', now(), now())"
            )
        )
    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        name = conn.execute(text("SELECT name FROM campaigns WHERE name = 'mig-keep'")).scalar()
        assert name == "mig-keep"
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert version == "0003_research_runs"
    engine.dispose()
