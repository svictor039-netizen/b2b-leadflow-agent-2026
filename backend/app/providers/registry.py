"""Adapter registry — Stage 2 allows only TestSourceAdapter."""

from __future__ import annotations

from app.core.exceptions import AppError
from app.models.enums import ALLOWED_RESEARCH_ADAPTERS
from app.providers.base import SourceAdapter
from app.providers.source_test import TestSourceAdapter

_REGISTRY: dict[str, type[SourceAdapter]] = {
    "test_source": TestSourceAdapter,
}


def get_source_adapter(name: str) -> SourceAdapter:
    key = (name or "").strip().lower()
    if key not in ALLOWED_RESEARCH_ADAPTERS:
        raise AppError(
            f"Adapter '{name}' is not allowed on Stage 2. Only TestSourceAdapter (test_source) is permitted.",
            status_code=400,
            code="adapter_not_allowed",
        )
    cls = _REGISTRY.get(key)
    if cls is None:
        raise AppError(
            f"Unknown adapter '{name}'.",
            status_code=400,
            code="unknown_adapter",
        )
    return cls()
