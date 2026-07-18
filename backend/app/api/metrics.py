from fastapi import APIRouter, Response

from app.core.migrations_check import check_migrations_current
from app.core.redis_client import check_redis_connection
from app.observability.metrics import metrics_payload
from app.services.readiness_service import build_readiness_report

router = APIRouter(tags=["system"])


@router.get("/metrics")
def prometheus_metrics() -> Response:
    report = build_readiness_report()
    payload, content_type = metrics_payload(report.ready)
    return Response(content=payload, media_type=content_type)
