import hashlib
import uuid
from datetime import datetime, timezone

from app.providers.base import EmailMessage, EmailProvider, EmailSendResult
from app.security.stop_all import assert_outbound_allowed

# Process-local at-most-once cache for TestEmailProvider (same worker redelivery).
# Cross-process safety is enforced by SendAttempt unique idempotency_key in DB.
_SENT_BY_KEY: dict[str, EmailSendResult] = {}


def clear_test_email_idempotency_cache() -> None:
    """Test helper — clears in-process send cache."""
    _SENT_BY_KEY.clear()


class TestEmailProvider(EmailProvider):
    """Simulates email delivery without any real SMTP/IMAP interaction."""

    @property
    def name(self) -> str:
        return "test_email"

    def send(self, message: EmailMessage) -> EmailSendResult:
        assert_outbound_allowed("email send")

        key = None
        if message.metadata:
            raw = message.metadata.get("idempotency_key")
            if isinstance(raw, str) and raw.strip():
                key = raw.strip()

        if key and key in _SENT_BY_KEY:
            return _SENT_BY_KEY[key]

        if key:
            digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
            message_id = f"test-{digest}"
        else:
            message_id = f"test-{uuid.uuid4().hex[:12]}"

        result = EmailSendResult(
            success=True,
            provider=self.name,
            message_id=message_id,
            sent_at=datetime.now(timezone.utc),
            simulated=True,
            detail="Simulated delivery (test provider)",
        )
        if key:
            _SENT_BY_KEY[key] = result
        return result
