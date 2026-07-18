"""Disabled live email provider — never sends, no network, no secrets."""

from datetime import datetime, timezone

from app.providers.base import EmailMessage, EmailProvider, EmailSendResult

LIVE_PROVIDER_NOT_CONFIGURED = "LIVE_PROVIDER_NOT_CONFIGURED"


class DisabledLiveEmailProvider(EmailProvider):
    """Placeholder until owner selects and configures a real provider in Stage 7B."""

    @property
    def name(self) -> str:
        return "disabled_live"

    @property
    def supports_live_delivery(self) -> bool:
        return False

    @property
    def supports_idempotency(self) -> bool:
        return True

    @property
    def supports_delivery_events(self) -> bool:
        return False

    def validate_configuration(self) -> tuple[bool, str]:
        return False, LIVE_PROVIDER_NOT_CONFIGURED

    def check_readiness(self) -> tuple[bool, str]:
        return False, LIVE_PROVIDER_NOT_CONFIGURED

    def send(self, message: EmailMessage) -> EmailSendResult:
        _ = message
        return EmailSendResult(
            success=False,
            provider=self.name,
            message_id="",
            sent_at=datetime.now(timezone.utc),
            simulated=False,
            detail=LIVE_PROVIDER_NOT_CONFIGURED,
        )
