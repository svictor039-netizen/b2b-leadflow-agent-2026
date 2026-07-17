"""Pytest fixtures — SAVEPOINT isolation against PostgreSQL test DB."""

from __future__ import annotations

import os
from collections.abc import Generator
from urllib.parse import urlparse, urlunparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

os.environ.setdefault("SYSTEM_STOP_ALL", "false")

from app.core.config import get_settings
from app.core.database import Base, get_db
from app.main import create_app

get_settings.cache_clear()


def _default_test_database_url() -> str:
    if os.getenv("TEST_DATABASE_URL"):
        return os.environ["TEST_DATABASE_URL"]
    base = os.getenv("DATABASE_URL") or get_settings().database_url
    parsed = urlparse(base)
    return urlunparse(parsed._replace(path="/leadflow_test"))


def _admin_database_url(test_url: str) -> str:
    parsed = urlparse(test_url)
    return urlunparse(parsed._replace(path="/postgres"))


def _ensure_test_database(url: str) -> str:
    if "leadflow_test" not in urlparse(url).path:
        return url

    admin_url = _admin_database_url(url)
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = 'leadflow_test'")
            ).scalar()
            if not exists:
                conn.execute(text("CREATE DATABASE leadflow_test"))
    finally:
        engine.dispose()
    return url


@pytest.fixture(scope="session")
def db_engine():
    if os.getenv("SKIP_DB_TESTS") == "1":
        pytest.skip("SKIP_DB_TESTS=1")

    url = _ensure_test_database(_default_test_database_url())
    engine = create_engine(url, poolclass=NullPool)

    import app.models  # noqa: F401

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def db_session(db_engine) -> Generator[Session, None, None]:
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, autoflush=False, autocommit=False)
    session.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(sess: Session, trans) -> None:  # type: ignore[no-untyped-def]
        if trans.nested and not trans._parent.nested:  # noqa: SLF001
            sess.begin_nested()

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def client_no_db() -> TestClient:
    return TestClient(create_app())
