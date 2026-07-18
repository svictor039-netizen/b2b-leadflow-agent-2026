import logging

from celery import Celery

from app.core.config import get_settings
from app.core.production_validation import (
    format_production_validation_error,
    validate_production_settings,
)

settings = get_settings()

if settings.is_production:
    _celery_validation_errors = validate_production_settings(settings)
    if _celery_validation_errors:
        raise RuntimeError(format_production_validation_error(_celery_validation_errors))

celery_app = Celery(
    "leadflow",
    broker=settings.broker_url,
    backend=settings.result_backend,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_hijack_root_logger=False,
    beat_schedule={},
)

logger = logging.getLogger(__name__)
