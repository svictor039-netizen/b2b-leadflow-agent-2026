from fastapi import APIRouter

from app.api import (
    campaigns,
    companies,
    compliance,
    execution,
    health,
    live_pilots,
    metrics,
    outreach,
    qualification,
    research,
)

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(metrics.router)
api_router.include_router(campaigns.router)
api_router.include_router(companies.router)
api_router.include_router(research.router)
api_router.include_router(qualification.router)
api_router.include_router(outreach.router)
api_router.include_router(execution.router)
api_router.include_router(compliance.router)
api_router.include_router(live_pilots.router)
