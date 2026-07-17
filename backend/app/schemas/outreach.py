from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import (
    MAX_OUTREACH_BODY,
    MAX_OUTREACH_REJECT_NOTE,
    MAX_OUTREACH_SEQUENCE_NAME,
    MAX_OUTREACH_SUBJECT,
    MAX_OUTREACH_TEMPLATE_NAME,
)


class OutreachTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=MAX_OUTREACH_TEMPLATE_NAME)
    subject_template: str = Field(..., min_length=1, max_length=MAX_OUTREACH_SUBJECT)
    body_template: str = Field(..., min_length=1, max_length=MAX_OUTREACH_BODY)
    is_active: bool = True
    is_test_data: bool = True

    @field_validator("is_test_data")
    @classmethod
    def must_be_test(cls, v: bool) -> bool:
        if v is False:
            raise ValueError("is_test_data must be true")
        return True


class OutreachTemplateUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=MAX_OUTREACH_TEMPLATE_NAME)
    subject_template: str | None = Field(None, min_length=1, max_length=MAX_OUTREACH_SUBJECT)
    body_template: str | None = Field(None, min_length=1, max_length=MAX_OUTREACH_BODY)
    is_active: bool | None = None


class OutreachTemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    campaign_id: UUID | None
    name: str
    subject_template: str
    body_template: str
    is_active: bool
    is_test_data: bool
    created_at: datetime
    updated_at: datetime


class SequenceStepCreate(BaseModel):
    template_id: UUID
    step_number: int = Field(..., ge=1, le=3)


class SequenceStepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sequence_id: UUID
    template_id: UUID
    step_number: int
    created_at: datetime


class OutreachSequenceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=MAX_OUTREACH_SEQUENCE_NAME)
    steps: list[SequenceStepCreate] = Field(..., min_length=1, max_length=3)
    is_active: bool = True
    is_test_data: bool = True

    @field_validator("is_test_data")
    @classmethod
    def must_be_test(cls, v: bool) -> bool:
        if v is False:
            raise ValueError("is_test_data must be true")
        return True


class OutreachSequenceUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=MAX_OUTREACH_SEQUENCE_NAME)
    is_active: bool | None = None


class OutreachSequenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    campaign_id: UUID
    name: str
    is_active: bool
    is_test_data: bool
    created_at: datetime
    updated_at: datetime
    steps: list[SequenceStepRead] = []


class DraftCreateRequest(BaseModel):
    sequence_id: UUID
    lead_ids: list[UUID] = Field(..., min_length=1, max_length=50)


class DraftItemResult(BaseModel):
    lead_id: UUID
    sequence_step_id: UUID | None = None
    message_id: UUID | None = None
    outcome: str
    detail: str | None = None


class DraftCreateResponse(BaseModel):
    campaign_id: UUID
    sequence_id: UUID
    created_count: int
    matched_existing_count: int
    skipped_count: int
    conflict_count: int
    failed_count: int
    results: list[DraftItemResult]


class RejectMessageRequest(BaseModel):
    note: str | None = Field(None, max_length=MAX_OUTREACH_REJECT_NOTE)


class OutreachMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    campaign_id: UUID
    campaign_lead_id: UUID
    sequence_id: UUID
    sequence_step_id: UUID
    template_id: UUID
    recipient_email: str
    subject_rendered: str
    body_rendered: str
    status: str
    approval_decision: str
    approved_at: datetime | None = None
    approved_by: str | None = None
    rejected_at: datetime | None = None
    reject_note: str | None = None
    sent_at: datetime | None = None
    failed_at: datetime | None = None
    blocked_at: datetime | None = None
    error_message: str | None = None
    idempotency_key: str
    is_test_data: bool
    created_at: datetime
    updated_at: datetime
    company_name: str | None = None


class OutreachMessageListResponse(BaseModel):
    items: list[OutreachMessageRead]
    total: int
    limit: int
    offset: int
