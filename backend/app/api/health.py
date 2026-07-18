from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.services.readiness_service import build_readiness_report

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": get_settings().app_name,
    }


@router.get("/liveness")
def liveness() -> dict:
    return {
        "status": "alive",
        "service": get_settings().app_name,
    }


@router.get("/readiness")
def readiness() -> JSONResponse:
    report = build_readiness_report()
    payload = {
        "status": report.status,
        "checks": report.checks,
        "runtime": report.runtime,
    }
    status_code = 200 if report.ready else 503
    return JSONResponse(status_code=status_code, content=payload)


@router.get("/version")
def version() -> dict:
    settings = get_settings()
    return {
        "version": settings.app_version,
        "environment": settings.environment,
        "stage": "8",
    }
