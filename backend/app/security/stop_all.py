from app.core.config import get_settings


class SystemStopAllError(Exception):
    """Raised when SYSTEM_STOP_ALL blocks an outbound operation."""


def is_system_stopped() -> bool:
    # Re-read env each check so kill switch flips are visible without process restart.
    get_settings.cache_clear()
    return get_settings().system_stop_all


def assert_outbound_allowed(operation: str = "outbound operation") -> None:
    if is_system_stopped():
        raise SystemStopAllError(
            f"SYSTEM_STOP_ALL is enabled; {operation} is blocked."
        )
