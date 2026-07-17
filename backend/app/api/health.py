from fastapi import APIRouter

from app.core.config import get_settings
from app.core.database import check_database_connection
from app.core.redis_client import check_redis_connection

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": get_settings().app_name,
    }


@router.get("/readiness")
def readiness() -> dict:
    postgres_ok = check_database_connection()
    redis_ok = check_redis_connection()
    ready = postgres_ok and redis_ok
    return {
        "status": "ready" if ready else "not_ready",
        "checks": {
            "postgres": "ok" if postgres_ok else "fail",
            "redis": "ok" if redis_ok else "fail",
        },
    }


@router.get("/version")
def version() -> dict:
    settings = get_settings()
    return {
        "version": settings.app_version,
        "environment": settings.environment,
        "stage": "0",
    }
