import logging

from app.security.stop_all import assert_outbound_allowed, is_system_stopped
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.tasks.ping")
def ping() -> dict:
    """Safe test task — no email scheduling or outbound actions."""
    logger.info("Celery ping task executed")
    return {"status": "pong", "task": "ping"}


@celery_app.task(name="app.workers.tasks.simulated_send")
def simulated_send(recipient: str, subject: str) -> dict:
    """Placeholder for future send pipeline — blocked when SYSTEM_STOP_ALL=true."""
    assert_outbound_allowed("simulated email send")
    logger.info("Simulated send task accepted", extra={"recipient": recipient, "subject": subject})
    return {
        "status": "simulated",
        "recipient": recipient,
        "subject": subject,
        "sent": False,
    }


@celery_app.task(
    name="app.workers.tasks.run_research_task",
    bind=True,
    # Avoid unbounded retries that could re-enter after partial work.
    max_retries=0,
)
def run_research_task(self, run_id: str) -> dict:
    """Execute an existing research run by id. Redelivery is idempotent via terminal status check."""
    from uuid import UUID

    from app.core.database import SessionLocal
    from app.core.exceptions import AppError
    from app.services.research_service import execute_research_run

    if is_system_stopped():
        # Still open a session to mark BLOCKED via execute_research_run.
        pass

    db = SessionLocal()
    try:
        result = execute_research_run(db, UUID(run_id))
        return {
            "run_id": str(result.id),
            "status": result.status.value,
            "found_count": result.found_count,
            "created_count": result.created_count,
        }
    except AppError as exc:
        logger.warning("Research task app error: %s", exc.message)
        return {"run_id": run_id, "status": "FAILED", "error": exc.code}
    finally:
        db.close()
