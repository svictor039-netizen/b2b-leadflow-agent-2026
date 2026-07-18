import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.middleware import RequestIdMiddleware
from app.core.production_validation import (
    format_production_validation_error,
    validate_production_settings,
)
from app.core.request_logging import RequestLoggingMiddleware
from app.logging.setup import RequestIdLogFilter, setup_logging
from app.observability.metrics import MetricsMiddleware

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)

    if settings.is_production:
        validation_errors = validate_production_settings(settings)
        if validation_errors:
            message = format_production_validation_error(validation_errors)
            logger.error(message)
            raise RuntimeError(message)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    if settings.is_production:
        cors_origins = [settings.frontend_origin]
    else:
        cors_origins = [settings.frontend_origin]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(RequestIdMiddleware)

    logging.getLogger().addFilter(RequestIdLogFilter())

    register_exception_handlers(app)
    app.include_router(api_router)

    @app.on_event("startup")
    async def on_startup() -> None:
        logger.info(
            "Application started",
            extra={
                "request_id": "-",
                "version": settings.app_version,
                "environment": settings.environment,
                "system_stop_all": settings.system_stop_all,
                "production_mode": settings.is_production,
            },
        )

    return app


app = create_app()
