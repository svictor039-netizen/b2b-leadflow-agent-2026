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


@pytest.fixture(scope="module")
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
        "alembic_version",
    }
    assert expected.issubset(tables)

    command.upgrade(cfg, "head")

    command.downgrade(cfg, "0001_stage0_baseline")
    tables_after = set(inspect(engine).get_table_names())
    assert "campaigns" not in tables_after

    command.upgrade(cfg, "head")
    assert "campaigns" in set(inspect(engine).get_table_names())
    engine.dispose()
