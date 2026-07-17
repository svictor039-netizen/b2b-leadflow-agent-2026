from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import (
    MAX_EXECUTION_BATCH_SIZE,
    MAX_EXECUTION_LIST_LIMIT,
    MAX_EXECUTION_MESSAGES,
    MIN_EXECUTION_BATCH_SIZE,
    MIN_EXECUTION_MESSAGES,
    ExecutionMode,
)


class ExecutionRunCreate(BaseModel):
    sequence_id: UUID
    message_ids: list[UUID] | None = None
    max_messages: int = Field(default=20, ge=MIN_EXECUTION_MESSAGES, le=MAX_EXECUTION_MESSAGES)
    batch_size: int = Field(default=5, ge=MIN_EXECUTION_BATCH_SIZE, le=MAX_EXECUTION_BATCH_SIZE)
    is_test_data: bool = True
    client_request_id: str | None = Field(default=None, max_length=64)

    @field_validator("is_test_data")
    @classmethod
    def must_be_test(cls, v: bool) -> bool:
        if v is False:
            raise ValueError("is_test_data must be true")
        return True

    @field_validator("message_ids")
    @classmethod
    def normalize_message_ids(cls, v: list[UUID] | None) -> list[UUID] | None:
        if v is None:
            return None
        if len(v) == 0:
            raise ValueError("message_ids must be non-empty when provided")
        seen: set[UUID] = set()
        out: list[UUID] = []
        for mid in v:
            if mid not in seen:
                seen.add(mid)
                out.append(mid)
        return out


class ExecutionItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    execution_run_id: UUID
    outreach_message_id: UUID
    position: int
    status: str
    claimed_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    is_test_data: bool
    created_at: datetime
    updated_at: datetime
    message_status: str | None = None
    company_name: str | None = None


class ExecutionItemListResponse(BaseModel):
    items: list[ExecutionItemRead]
    total: int
    limit: int
    offset: int


class ExecutionRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    campaign_id: UUID
    sequence_id: UUID
    status: str
    execution_mode: str
    max_messages: int
    batch_size: int
    started_at: datetime | None = None
    paused_at: datetime | None = None
    resumed_at: datetime | None = None
    cancelled_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    planned_count: int
    processed_count: int
    sent_count: int
    failed_count: int
    blocked_count: int
    skipped_count: int
    unknown_count: int
    idempotency_key: str
    is_test_data: bool
    created_at: datetime
    updated_at: datetime
    matched_existing: bool = False


class ExecutionRunListResponse(BaseModel):
    items: list[ExecutionRunRead]
    total: int
    limit: int
    offset: int


class CampaignAnalyticsRead(BaseModel):
    campaign_id: UUID
    is_test_data: bool = True
    approved_leads: int
    draft_messages: int
    approved_messages: int
    sent_messages: int
    failed_messages: int
    blocked_messages: int
    unknown_messages: int
    rejected_messages: int
    execution_runs_total: int
    execution_runs_completed: int
    execution_runs_failed: int
    execution_runs_blocked: int
    latest_run_status: str | None
    test_delivery_rate: float
    failure_rate: float
