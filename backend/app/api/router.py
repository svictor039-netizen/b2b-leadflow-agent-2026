from fastapi import APIRouter

from app.api import campaigns, companies, health, research

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(campaigns.router)
api_router.include_router(companies.router)
api_router.include_router(research.router)
