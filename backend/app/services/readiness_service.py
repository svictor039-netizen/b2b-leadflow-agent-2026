"""Shared readiness report builder for /readiness and metrics."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import get_settings
from app.core.database import check_database_connection
from app.core.migrations_check import check_migrations_current
from app.core.redis_client import check_redis_connection


@dataclass(frozen=True)
class ReadinessReport:
    ready: bool
    status: str
    checks: dict[str, str]
    runtime: dict[str, str | bool]


def build_readiness_report() -> ReadinessReport:
    settings = get_settings()
    postgres_ok = check_database_connection()
    redis_ok = check_redis_connection()
    migrations_ok, migrations_status = check_migrations_current()

    checks = {
        "postgres": "ok" if postgres_ok else "fail",
        "redis": "ok" if redis_ok else "fail",
        "migrations": migrations_status if migrations_ok else migrations_status,
    }

    ready = postgres_ok and redis_ok and migrations_ok
    runtime = {
        "environment": settings.environment,
        "system_stop_all": settings.system_stop_all,
        "live_provider_disabled": (
            not settings.live_provider_api_key.strip()
            and (
                not settings.live_provider_name.strip()
                or settings.live_provider_name == "disabled_live"
            )
        ),
    }

    return ReadinessReport(
        ready=ready,
        status="ready" if ready else "not_ready",
        checks=checks,
        runtime=runtime,
    )
