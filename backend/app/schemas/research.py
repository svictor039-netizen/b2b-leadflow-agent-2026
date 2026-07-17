from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import (
    MAX_QUERY_LENGTH,
    MAX_RESEARCH_LIMIT,
    ResearchItemOutcome,
    ResearchRunStatus,
)
from app.services.validation import blank_to_none


class ResearchRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=MAX_QUERY_LENGTH)
    industry: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    limit: int = Field(default=10, ge=1, le=MAX_RESEARCH_LIMIT)
    adapter: str = Field(default="test_source", max_length=64)
    campaign_id: UUID | None = None
    async_mode: bool = False

    @field_validator("query", "industry", "location", "adapter", mode="before")
    @classmethod
    def strip_strings(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("query")
    @classmethod
    def query_not_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("query must not be empty")
        return value.strip()

    @field_validator("industry", "location", mode="after")
    @classmethod
    def empty_to_none(cls, value: str | None) -> str | None:
        return blank_to_none(value)


class ResearchItemResult(BaseModel):
    outcome: ResearchItemOutcome
    company_id: UUID | None = None
    company_name: str | None = None
    domain: str | None = None
    source_record_id: str | None = None
    source_url: str | None = None
    reason: str | None = None
    is_test_data: bool = True


class ResearchRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    campaign_id: UUID | None
    status: ResearchRunStatus
    adapter: str
    query: str
    industry: str | None
    location: str | None
    limit: int
    found_count: int
    created_count: int
    matched_count: int
    updated_count: int
    skipped_count: int
    conflict_count: int
    celery_task_id: str | None
    error_message: str | None
    result_items: list[ResearchItemResult] = Field(default_factory=list)
    is_test_data: bool
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime
