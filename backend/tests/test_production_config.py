"""Stage 8 production configuration validation tests."""

from __future__ import annotations

import pytest

from app.core.config import Settings, get_settings
from app.core.production_validation import (
    format_production_validation_error,
    validate_production_settings,
)
from app.main import create_app


def _prod_settings(**overrides: object) -> Settings:
    base = {
        "environment": "production",
        "debug": False,
        "database_url": "postgresql://produser:verylongproductionpass@postgres:5432/leadflow_prod",
        "redis_url": "redis://redis:6379/0",
        "frontend_origin": "https://app.customer.example.org",
        "system_stop_all": True,
        "real_email_provider_enabled": False,
        "live_outreach_enabled": False,
        "provider_api_key": "",
        "live_provider_name": "",
        "live_provider_api_key": "",
        "live_daily_limit": 0,
        "allow_insecure_local_production_smoke": False,
    }
    base.update(overrides)
    return Settings.model_construct(**base)


def test_valid_production_settings_pass() -> None:
    assert validate_production_settings(_prod_settings()) == []


def test_production_rejects_debug() -> None:
    errors = validate_production_settings(_prod_settings(debug=True))
    assert any("DEBUG" in err for err in errors)


def test_production_rejects_dev_database_defaults() -> None:
    errors = validate_production_settings(
        _prod_settings(database_url="postgresql://leadflow:leadflow_dev_password@postgres:5432/leadflow")
    )
    assert any("DATABASE_URL" in err for err in errors)


def test_production_rejects_localhost_cors() -> None:
    errors = validate_production_settings(_prod_settings(frontend_origin="http://localhost:8080"))
    assert any("FRONTEND_ORIGIN" in err for err in errors)


def test_production_rejects_live_provider_credentials() -> None:
    errors = validate_production_settings(
        _prod_settings(live_provider_api_key="sk-live-secret-key-value")
    )
    assert any("LIVE_PROVIDER_API_KEY" in err for err in errors)


def test_production_rejects_enabled_real_provider_flags() -> None:
    errors = validate_production_settings(_prod_settings(real_email_provider_enabled=True))
    assert any("REAL_EMAIL_PROVIDER_ENABLED" in err for err in errors)


def test_local_smoke_mode_allows_insecure_origin() -> None:
    settings = _prod_settings(
        allow_insecure_local_production_smoke=True,
        frontend_origin="http://127.0.0.1:8080",
        database_url="postgresql://leadflow:leadflow_dev_password@postgres:5432/leadflow",
    )
    assert validate_production_settings(settings) == []


def test_create_app_fails_on_invalid_production_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://leadflow:leadflow_dev_password@postgres:5432/leadflow")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("FRONTEND_ORIGIN", "http://localhost:8080")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError) as exc:
        create_app()
    assert "Production configuration validation failed" in str(exc.value)
    get_settings.cache_clear()


def test_format_production_validation_error_lists_issues() -> None:
    message = format_production_validation_error(["first issue", "second issue"])
    assert "first issue" in message
    assert "second issue" in message
