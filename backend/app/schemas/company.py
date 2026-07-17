from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import (
    CompanyStatus,
    ConsentStatus,
    ContactType,
    VerificationStatus,
)
from app.services.validation import blank_to_none


class LocationCreate(BaseModel):
    country: str | None = Field(default=None, max_length=100)
    region: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=200)
    address: str | None = Field(default=None, max_length=500)
    postal_code: str | None = Field(default=None, max_length=32)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    is_primary: bool = False

    @field_validator(
        "country", "region", "city", "address", "postal_code", mode="before"
    )
    @classmethod
    def strip_opt(cls, value: object) -> object:
        if isinstance(value, str):
            return blank_to_none(value)
        return value


class LocationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    country: str | None = Field(default=None, max_length=100)
    region: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=200)
    address: str | None = Field(default=None, max_length=500)
    postal_code: str | None = Field(default=None, max_length=32)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    is_primary: bool | None = None


class LocationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    country: str | None
    region: str | None
    city: str | None
    address: str | None
    postal_code: str | None
    latitude: float | None
    longitude: float | None
    is_primary: bool
    created_at: datetime
    updated_at: datetime


class ContactCreate(BaseModel):
    contact_type: ContactType
    value: str = Field(min_length=1, max_length=500)
    label: str | None = Field(default=None, max_length=200)
    source_url: str | None = Field(default=None, max_length=1000)
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    consent_status: ConsentStatus = ConsentStatus.UNKNOWN
    consent_source: str | None = Field(default=None, max_length=500)
    do_not_contact: bool = False

    @field_validator("value", "label", "source_url", "consent_source", mode="before")
    @classmethod
    def strip_opt(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped
        return value


class ContactUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contact_type: ContactType | None = None
    value: str | None = Field(default=None, min_length=1, max_length=500)
    label: str | None = Field(default=None, max_length=200)
    source_url: str | None = Field(default=None, max_length=1000)
    verification_status: VerificationStatus | None = None
    consent_status: ConsentStatus | None = None
    consent_source: str | None = Field(default=None, max_length=500)
    do_not_contact: bool | None = None


class ContactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    contact_type: ContactType
    value: str
    label: str | None
    source_url: str | None
    collected_at: datetime | None
    verified_at: datetime | None
    verification_status: VerificationStatus
    consent_status: ConsentStatus
    consent_source: str | None
    do_not_contact: bool
    created_at: datetime
    updated_at: datetime


class CompanyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    legal_name: str | None = Field(default=None, max_length=300)
    website: str | None = Field(default=None, max_length=500)
    domain: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    status: CompanyStatus = CompanyStatus.UNKNOWN
    source_confidence: float | None = Field(default=None, ge=0, le=1)

    @field_validator("name", "legal_name", "website", "domain", "description", mode="before")
    @classmethod
    def strip_strings(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class CompanyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=300)
    legal_name: str | None = Field(default=None, max_length=300)
    website: str | None = Field(default=None, max_length=500)
    domain: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    status: CompanyStatus | None = None
    source_confidence: float | None = Field(default=None, ge=0, le=1)


class CompanyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    legal_name: str | None
    website: str | None
    domain: str | None
    description: str | None
    status: CompanyStatus
    source_confidence: float | None
    created_at: datetime
    updated_at: datetime
    locations: list[LocationRead] = Field(default_factory=list)
    contacts: list[ContactRead] = Field(default_factory=list)


class CompanyListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    domain: str | None
    website: str | None
    status: CompanyStatus
    created_at: datetime
    updated_at: datetime


class CompanyListResponse(BaseModel):
    items: list[CompanyListItem]
    total: int
    page: int
    page_size: int
