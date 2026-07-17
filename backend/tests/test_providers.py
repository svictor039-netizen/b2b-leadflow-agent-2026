import os

import pytest

from app.providers.base import EmailMessage
from app.providers.email_test import TestEmailProvider
from app.providers.source_test import TestSourceAdapter
from app.security.stop_all import SystemStopAllError


def test_test_email_provider_simulates_send() -> None:
    os.environ["SYSTEM_STOP_ALL"] = "false"
    from app.core.config import get_settings

    get_settings.cache_clear()

    provider = TestEmailProvider()
    result = provider.send(
        EmailMessage(
            to_address="test@example.com",
            subject="Hello",
            body="Test body",
        )
    )
    assert result.success is True
    assert result.simulated is True
    assert result.provider == "test_email"
    assert result.message_id.startswith("test-")


def test_test_source_adapter_returns_demo_companies() -> None:
    adapter = TestSourceAdapter()
    companies = adapter.search("SaaS", "Europe", limit=10)
    assert len(companies) > 0
    assert len(companies) <= 30
    assert all(c.name for c in companies)
    assert all(c.contact_email for c in companies)


def test_test_source_adapter_respects_limit() -> None:
    adapter = TestSourceAdapter()
    companies = adapter.search("anything", "anywhere", limit=2)
    assert len(companies) <= 2


def test_system_stop_all_blocks_email() -> None:
    os.environ["SYSTEM_STOP_ALL"] = "true"
    from app.core.config import get_settings

    get_settings.cache_clear()

    provider = TestEmailProvider()
    with pytest.raises(SystemStopAllError):
        provider.send(
            EmailMessage(
                to_address="blocked@example.com",
                subject="Blocked",
                body="Should not send",
            )
        )

    os.environ["SYSTEM_STOP_ALL"] = "false"
    get_settings.cache_clear()


def test_system_stop_all_blocks_celery_task() -> None:
    os.environ["SYSTEM_STOP_ALL"] = "true"
    from app.core.config import get_settings

    get_settings.cache_clear()

    from app.workers.tasks import simulated_send

    with pytest.raises(SystemStopAllError):
        simulated_send("test@example.com", "Subject")

    os.environ["SYSTEM_STOP_ALL"] = "false"
    get_settings.cache_clear()
