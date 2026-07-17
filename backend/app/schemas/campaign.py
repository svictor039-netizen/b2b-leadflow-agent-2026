from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import CampaignStatus, SendingMode
from app.services.validation import blank_to_none


class CampaignCreate(BaseModel):
    name: str = Field(min_length=3, max_length=200)
    business_type: str = Field(min_length=1, max_length=200)
    region: str = Field(min_length=1, max_length=200)
    offer: str = Field(min_length=1, max_length=500)
    offer_description: str | None = Field(default=None, max_length=5000)
    ideal_customer: str | None = Field(default=None, max_length=5000)
    desired_cta: str | None = Field(default=None, max_length=500)
    max_companies: int = Field(default=30, ge=1, le=30)
    max_emails_per_lead: int = Field(default=3, ge=1, le=3)
    sending_mode: SendingMode = SendingMode.MANUAL_APPROVAL

    @field_validator(
        "name",
        "business_type",
        "region",
        "offer",
        "offer_description",
        "ideal_customer",
        "desired_cta",
        mode="before",
    )
    @classmethod
    def strip_strings(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("offer_description", "ideal_customer", "desired_cta", mode="after")
    @classmethod
    def empty_to_none(cls, value: str | None) -> str | None:
        return blank_to_none(value)


class CampaignUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=3, max_length=200)
    business_type: str | None = Field(default=None, min_length=1, max_length=200)
    region: str | None = Field(default=None, min_length=1, max_length=200)
    offer: str | None = Field(default=None, min_length=1, max_length=500)
    offer_description: str | None = Field(default=None, max_length=5000)
    ideal_customer: str | None = Field(default=None, max_length=5000)
    desired_cta: str | None = Field(default=None, max_length=500)
    max_companies: int | None = Field(default=None, ge=1, le=30)
    max_emails_per_lead: int | None = Field(default=None, ge=1, le=3)
    sending_mode: SendingMode | None = None
    status: CampaignStatus | None = None

    @field_validator(
        "name",
        "business_type",
        "region",
        "offer",
        "offer_description",
        "ideal_customer",
        "desired_cta",
        mode="before",
    )
    @classmethod
    def strip_strings(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class CampaignRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    business_type: str
    region: str
    offer: str
    offer_description: str | None
    ideal_customer: str | None
    desired_cta: str | None
    max_companies: int
    max_emails_per_lead: int
    sending_mode: SendingMode
    status: CampaignStatus
    created_at: datetime
    updated_at: datetime
    lead_count: int = 0
    free_slots: int = 0
    lead_status_counts: dict[str, int] = Field(default_factory=dict)


class CampaignListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    business_type: str
    region: str
    status: CampaignStatus
    sending_mode: SendingMode
    max_companies: int
    max_emails_per_lead: int
    lead_count: int = 0
    free_slots: int = 0
    created_at: datetime
    updated_at: datetime


class CampaignListResponse(BaseModel):
    items: list[CampaignListItem]
    total: int
    page: int
    page_size: int


class CampaignLeadRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    campaign_id: UUID
    company_id: UUID
    status: str
    approved_for_research: bool
    approved_for_email: bool
    created_at: datetime
    updated_at: datetime
    company_name: str | None = None
    company_domain: str | None = None
    company_status: str | None = None
