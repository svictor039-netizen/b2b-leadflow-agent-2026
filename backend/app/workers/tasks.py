import logging

from app.security.stop_all import assert_outbound_allowed
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
