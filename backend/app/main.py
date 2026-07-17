import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.middleware import RequestIdMiddleware
from app.logging.setup import RequestIdLogFilter, setup_logging

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestIdMiddleware)

    logging.getLogger().addFilter(RequestIdLogFilter())

    register_exception_handlers(app)
    app.include_router(api_router)

    @app.on_event("startup")
    async def on_startup() -> None:
        logger.info(
            "Application started",
            extra={
                "version": settings.app_version,
                "environment": settings.environment,
                "system_stop_all": settings.system_stop_all,
            },
        )

    return app


app = create_app()
