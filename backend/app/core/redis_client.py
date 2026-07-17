import redis

from app.core.config import get_settings

_settings = get_settings()
_redis_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(
            _settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
    return _redis_client


def check_redis_connection() -> bool:
    try:
        return get_redis().ping()
    except Exception:
        return False
