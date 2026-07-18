"""Prometheus metrics — safe aggregates only, no PII or secrets."""

from __future__ import annotations

import time
from typing import Callable

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from sqlalchemy import func, select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.database import SessionLocal
from app.models.enums import LivePilotEventType, LivePilotStatus
from app.models.live_pilot import LivePilot, LivePilotEvent

HTTP_REQUESTS_TOTAL = Counter(
    "leadflow_http_requests_total",
    "Total HTTP requests",
    ["method", "path_group", "status_class"],
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "leadflow_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path_group"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
HTTP_ERRORS_TOTAL = Counter(
    "leadflow_http_errors_total",
    "Total HTTP 5xx responses",
    ["method", "path_group"],
)
READINESS_STATE = Gauge(
    "leadflow_readiness_state",
    "1 when readiness checks pass, 0 otherwise",
)
WORKER_OPERATIONAL = Gauge(
    "leadflow_worker_operational",
    "1 when at least one Celery worker responds to ping, 0 otherwise",
)
SCHEDULER_OPERATIONAL = Gauge(
    "leadflow_scheduler_operational",
    "1 when Celery beat schedule is empty (safe default), 0 otherwise",
)
LIVE_PILOT_ATTEMPTS = Gauge(
    "leadflow_live_pilot_attempts_total",
    "Count of live pilot dry-run attempts (aggregate)",
)
BLOCKED_LIVE_PILOT_ATTEMPTS = Gauge(
    "leadflow_blocked_live_pilot_attempts_total",
    "Count of blocked live pilot events (aggregate)",
)
SUCCESSFUL_LIVE_SENDS = Gauge(
    "leadflow_successful_live_sends_total",
    "Aggregate live_sent_count across pilots",
)

_METRICS_PATHS = frozenset({"/api/metrics", "/metrics"})


def _path_group(path: str) -> str:
    if path.startswith("/api/live-pilots/"):
        return "/api/live-pilots/{id}"
    if path.startswith("/api/campaigns/"):
        parts = path.strip("/").split("/")
        if len(parts) >= 3:
            return f"/api/campaigns/{{id}}/{parts[2]}"
        return "/api/campaigns/{id}"
    return path


def _status_class(status_code: int) -> str:
    return f"{status_code // 100}xx"


def refresh_operational_gauges(readiness_ok: bool) -> None:
    READINESS_STATE.set(1 if readiness_ok else 0)

    try:
        from app.workers.celery_app import celery_app

        inspect = celery_app.control.inspect(timeout=0.5)
        ping = inspect.ping() if inspect else None
        WORKER_OPERATIONAL.set(1 if ping else 0)
        SCHEDULER_OPERATIONAL.set(1 if celery_app.conf.beat_schedule == {} else 0)
    except Exception:
        WORKER_OPERATIONAL.set(0)
        SCHEDULER_OPERATIONAL.set(1)

    try:
        db = SessionLocal()
        try:
            dry_runs = db.scalar(
                select(func.count())
                .select_from(LivePilotEvent)
                .where(LivePilotEvent.event_type == LivePilotEventType.DRY_RUN_START.value)
            ) or 0
            blocked = db.scalar(
                select(func.count())
                .select_from(LivePilot)
                .where(LivePilot.status == LivePilotStatus.BLOCKED.value)
            ) or 0
            live_sent = db.scalar(select(func.coalesce(func.sum(LivePilot.live_sent_count), 0))) or 0
            LIVE_PILOT_ATTEMPTS.set(dry_runs)
            BLOCKED_LIVE_PILOT_ATTEMPTS.set(blocked)
            SUCCESSFUL_LIVE_SENDS.set(live_sent)
        finally:
            db.close()
    except Exception:
        pass


def metrics_payload(readiness_ok: bool) -> tuple[bytes, str]:
    refresh_operational_gauges(readiness_ok)
    return generate_latest(), CONTENT_TYPE_LATEST


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in _METRICS_PATHS:
            return await call_next(request)

        method = request.method
        group = _path_group(request.url.path)
        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration = time.perf_counter() - start
            status_class = _status_class(status_code)
            HTTP_REQUESTS_TOTAL.labels(method=method, path_group=group, status_class=status_class).inc()
            HTTP_REQUEST_DURATION_SECONDS.labels(method=method, path_group=group).observe(duration)
            if status_code >= 500:
                HTTP_ERRORS_TOTAL.labels(method=method, path_group=group).inc()
