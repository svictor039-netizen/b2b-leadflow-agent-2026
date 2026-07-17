from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import (
    MAX_COMPLIANCE_REASON_LENGTH,
    ComplianceTestEventType,
    SuppressionReason,
    SuppressionScope,
    SuppressionSource,
    SuppressionType,
)


class SuppressionCreate(BaseModel):
    scope: SuppressionScope
    campaign_id: UUID | None = None
    suppression_type: SuppressionType
    value: str = Field(min_length=1, max_length=320)
    reason: SuppressionReason
    source: SuppressionSource = SuppressionSource.MANUAL
    expires_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=MAX_COMPLIANCE_REASON_LENGTH)
    is_test_data: bool = True

    @field_validator("is_test_data")
    @classmethod
    def must_be_test(cls, v: bool) -> bool:
        if v is False:
            raise ValueError("is_test_data must be true")
        return True


class SuppressionPatch(BaseModel):
    expires_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=MAX_COMPLIANCE_REASON_LENGTH)
    reason: SuppressionReason | None = None


class SuppressionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    scope: str
    campaign_id: UUID | None
    suppression_type: str
    display_value: str
    reason: str
    source: str
    is_active: bool
    expires_at: datetime | None
    created_by: str
    notes: str | None
    is_test_data: bool
    created_at: datetime
    updated_at: datetime


class SuppressionListResponse(BaseModel):
    items: list[SuppressionRead]
    total: int
    limit: int
    offset: int


class ComplianceCheckRequest(BaseModel):
    message_id: UUID


class ComplianceCheckResponse(BaseModel):
    allowed: bool
    decision: str
    reason_code: str
    suppression_type: str | None = None
    scope: str | None = None
    matched_suppression_entry_id: UUID | None = None
    safe_message: str
    checked_at: datetime
    is_test_data: bool = True


class TestComplianceEventCreate(BaseModel):
    message_id: UUID
    event_type: ComplianceTestEventType
    is_test_data: bool = True

    @field_validator("is_test_data")
    @classmethod
    def must_be_test(cls, v: bool) -> bool:
        if v is False:
            raise ValueError("is_test_data must be true")
        return True


class TestComplianceEventResponse(BaseModel):
    event_type: str
    suppression: SuppressionRead
    message_id: UUID
    is_test_data: bool = True


class ProviderReadinessCheck(BaseModel):
    name: str
    status: str
    detail: str


class ProviderReadinessReport(BaseModel):
    overall_status: str
    test_mode_ready: bool
    live_mode_ready: bool
    production_readiness_status: str
    checks: list[ProviderReadinessCheck]
    blockers: list[str]
    warnings: list[str]
    generated_at: datetime
    is_test_data: bool = True
