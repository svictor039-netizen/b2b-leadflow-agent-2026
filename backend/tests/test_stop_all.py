from app.security.stop_all import assert_outbound_allowed, is_system_stopped


def test_is_system_stopped_default(monkeypatch) -> None:
    monkeypatch.delenv("SYSTEM_STOP_ALL", raising=False)
    from app.core.config import get_settings

    get_settings.cache_clear()
    assert is_system_stopped() is False


def test_assert_outbound_allowed_when_stopped(monkeypatch) -> None:
    monkeypatch.setenv("SYSTEM_STOP_ALL", "true")
    from app.core.config import get_settings
    from app.security.stop_all import SystemStopAllError

    get_settings.cache_clear()
    try:
        assert_outbound_allowed("test operation")
        raise AssertionError("Expected SystemStopAllError")
    except SystemStopAllError as exc:
        assert "SYSTEM_STOP_ALL" in str(exc)
    finally:
        monkeypatch.delenv("SYSTEM_STOP_ALL", raising=False)
        get_settings.cache_clear()
