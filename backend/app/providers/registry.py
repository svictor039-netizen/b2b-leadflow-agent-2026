"""Central provider and source adapter registry."""

from __future__ import annotations

from app.core.exceptions import AppError
from app.models.enums import (
    ALLOWED_LIVE_PILOT_PROVIDERS,
    ALLOWED_OUTREACH_PROVIDER,
    ALLOWED_RESEARCH_ADAPTERS,
)
from app.providers.base import EmailProvider, SourceAdapter
from app.providers.email_disabled_live import DisabledLiveEmailProvider
from app.providers.email_test import TestEmailProvider
from app.providers.source_test import TestSourceAdapter

_SOURCE_REGISTRY: dict[str, type[SourceAdapter]] = {
    "test_source": TestSourceAdapter,
}

_EMAIL_REGISTRY: dict[str, type[EmailProvider]] = {
    ALLOWED_OUTREACH_PROVIDER: TestEmailProvider,
    "disabled_live": DisabledLiveEmailProvider,
}

ALLOWED_PILOT_DRY_RUN_PROVIDER = ALLOWED_OUTREACH_PROVIDER


def get_source_adapter(name: str) -> SourceAdapter:
    key = (name or "").strip().lower()
    if key not in ALLOWED_RESEARCH_ADAPTERS:
        raise AppError(
            f"Adapter '{name}' is not allowed on Stage 2. Only TestSourceAdapter (test_source) is permitted.",
            status_code=400,
            code="adapter_not_allowed",
        )
    cls = _SOURCE_REGISTRY.get(key)
    if cls is None:
        raise AppError(
            f"Unknown adapter '{name}'.",
            status_code=400,
            code="unknown_adapter",
        )
    return cls()


def get_provider(name: str) -> EmailProvider:
    cls = _EMAIL_REGISTRY.get(name)
    if cls is None:
        raise AppError(
            f"Unknown provider: {name}",
            status_code=422,
            code="unknown_provider",
        )
    return cls()


def get_dry_run_provider() -> EmailProvider:
    return get_provider(ALLOWED_PILOT_DRY_RUN_PROVIDER)


def get_live_provider(name: str | None) -> EmailProvider:
    if not name or name not in ALLOWED_LIVE_PILOT_PROVIDERS:
        return DisabledLiveEmailProvider()
    return get_provider(name)


def list_registered_email_providers() -> list[str]:
    return sorted(_EMAIL_REGISTRY.keys())
