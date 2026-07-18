"""Alembic migration head verification for readiness checks."""

from __future__ import annotations

import os

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from app.core.database import engine

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _alembic_config() -> Config:
    cfg = Config(os.path.join(BACKEND_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_ROOT, "alembic"))
    return cfg


def check_migrations_current() -> tuple[bool, str]:
    """Return (is_current, safe_status_message without credentials)."""
    try:
        cfg = _alembic_config()
        script = ScriptDirectory.from_config(cfg)
        head = script.get_current_head()

        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            current = context.get_current_revision()

        if current is None:
            return False, "not_applied"

        if current == head:
            return True, "ok"

        return False, "behind_head"
    except Exception:
        return False, "check_failed"
