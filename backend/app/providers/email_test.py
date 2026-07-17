import uuid
from datetime import datetime, timezone

from app.providers.base import EmailMessage, EmailProvider, EmailSendResult
from app.security.stop_all import assert_outbound_allowed


class TestEmailProvider(EmailProvider):
    """Simulates email delivery without any real SMTP/IMAP interaction."""

    @property
    def name(self) -> str:
        return "test_email"

    def send(self, message: EmailMessage) -> EmailSendResult:
        assert_outbound_allowed("email send")

        message_id = f"test-{uuid.uuid4().hex[:12]}"
        return EmailSendResult(
            success=True,
            provider=self.name,
            message_id=message_id,
            sent_at=datetime.now(timezone.utc),
            simulated=True,
            detail=f"Simulated delivery to {message.to_address}",
        )
