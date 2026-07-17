from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import (
    MAX_REVIEW_NOTE_LENGTH,
    QualificationRunStatus,
    QualificationStatus,
    ReviewDecision,
    SCORING_VERSION,
)
from app.services.validation import blank_to_none


class QualificationRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_id: UUID
    research_run_id: UUID
    async_mode: bool = False


class QualificationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    campaign_id: UUID
    research_run_id: UUID
    status: QualificationRunStatus
    scoring_version: str = SCORING_VERSION
    found_count: int
    created_leads_count: int
    matched_leads_count: int
    scored_count: int
    qualified_count: int
    review_count: int
    disqualified_count: int
    conflict_count: int
    skipped_count: int
    celery_task_id: str | None = None
    error_message: str | None = None
    is_test_data: bool
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ScoreReasonRead(BaseModel):
    code: str
    points: int
    detail: str = ""


class QualificationLeadRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    campaign_id: UUID
    company_id: UUID
    company_name: str | None = None
    company_domain: str | None = None
    qualification_score: int | None = None
    qualification_status: str | None = None
    review_decision: str
    score_version: str | None = None
    scored_at: datetime | None = None
    score_reasons: list[ScoreReasonRead | dict] = Field(default_factory=list)
    source_research_run_id: UUID | None = None
    is_test_data: bool = True
    reviewed_at: datetime | None = None
    review_note: str | None = None
    status: str
    approved_for_email: bool = False
    created_at: datetime
    updated_at: datetime


class QualificationLeadListResponse(BaseModel):
    items: list[QualificationLeadRead]
    total: int
    limit: int
    offset: int


class LeadReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: ReviewDecision
    note: str | None = Field(default=None, max_length=MAX_REVIEW_NOTE_LENGTH)

    @field_validator("note", mode="before")
    @classmethod
    def strip_note(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("note", mode="after")
    @classmethod
    def empty_note(cls, value: str | None) -> str | None:
        return blank_to_none(value)
