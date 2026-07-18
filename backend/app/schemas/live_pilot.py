"""Stage 7A live pilot API schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LivePilotCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_id: UUID
    message_id: UUID
    idempotency_key: str = Field(min_length=8, max_length=255)
    max_recipients: int | None = Field(default=1, ge=1, le=5)
    provider_name: str | None = None
    live_delivery_enabled: bool = False
    is_test_data: bool = True

    @field_validator("live_delivery_enabled")
    @classmethod
    def reject_live_enabled(cls, v: bool) -> bool:
        if v:
            raise ValueError("live_delivery_enabled must be false on Stage 7A")
        return v


class LivePilotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    campaign_id: UUID
    status: str
    provider_name: str | None
    sender_identity_masked: str | None
    sender_domain: str | None
    subject_snapshot: str
    body_snapshot: str
    max_recipients: int
    daily_limit: int
    per_minute_limit: int
    requires_manual_approval: bool
    approval_count_required: int
    approved_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    created_by: str
    is_test_data: bool
    live_delivery_enabled: bool
    primary_message_id: UUID
    live_sent_count: int
    dry_run_sent_count: int
    created_at: datetime
    updated_at: datetime


class LivePilotListResponse(BaseModel):
    items: list[LivePilotRead]
    total: int
    limit: int
    offset: int


class LivePilotRecipientCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outreach_message_id: UUID
    recipient_email: str | None = None
    idempotency_key: str = Field(min_length=8, max_length=255)


class LivePilotRecipientRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    pilot_id: UUID
    outreach_message_id: UUID
    recipient_masked: str
    recipient_fingerprint: str
    status: str
    compliance_checked_at: datetime | None
    approved_at: datetime | None
    sent_at: datetime | None
    provider_message_id: str | None
    error_code: str | None
    position: int
    created_at: datetime
    updated_at: datetime


class LivePilotRecipientListResponse(BaseModel):
    items: list[LivePilotRecipientRead]
    total: int


class LivePilotValidationCheck(BaseModel):
    name: str
    passed: bool
    detail: str


class LivePilotValidationResponse(BaseModel):
    ready: bool
    overall_status: str
    blockers: list[str]
    warnings: list[str]
    checks: list[LivePilotValidationCheck]
    generated_at: datetime
    test_ready: bool
    live_ready: bool
    is_test_data: bool = True


class LivePilotReadinessResponse(LivePilotValidationResponse):
    live_mode_ready: bool = False
    production_status: str = "LIVE_NOT_READY"


class LivePilotApproveRequest(BaseModel):
    confirmation_token: str | None = None


class LivePilotApprovalResponse(BaseModel):
    pilot_id: UUID
    status: str
    confirmation_phrase: str | None = None
    confirmation_token: str | None = None
    expires_at: datetime | None = None
    approved: bool
    message: str
    is_test_data: bool = True


class LivePilotDryRunRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=255)


class LivePilotDryRunResponse(BaseModel):
    pilot_id: UUID
    status: str
    dry_run: bool
    simulated: bool
    provider: str
    recipients_processed: int
    live_sent_count: int
    message: str
    is_test_data: bool = True
