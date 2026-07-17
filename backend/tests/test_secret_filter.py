from app.logging.setup import redact_secrets


def test_redacts_database_url() -> None:
    text = "Connection failed: postgresql://user:secret@host:5432/db"
    result = redact_secrets(text)
    assert "secret" not in result
    assert "postgresql://" in result
    assert "***REDACTED***" in result


def test_redacts_redis_url() -> None:
    text = "REDIS_URL=redis://:password@redis:6379/0"
    result = redact_secrets(text)
    assert "password" not in result
    assert "***REDACTED***" in result


def test_redacts_api_key() -> None:
    text = "api_key=sk-live-abc123xyz"
    result = redact_secrets(text)
    assert "sk-live" not in result
    assert "***REDACTED***" in result
