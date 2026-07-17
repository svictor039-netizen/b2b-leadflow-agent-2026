"""Shared enums for Stage 1 domain models."""

from enum import StrEnum


class CampaignStatus(StrEnum):
    DRAFT = "DRAFT"
    SEARCHING = "SEARCHING"
    ENRICHING = "ENRICHING"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# Statuses editable via PATCH by the user on stage 1
USER_EDITABLE_CAMPAIGN_STATUSES = frozenset(
    {
        CampaignStatus.DRAFT,
        CampaignStatus.PAUSED,
        CampaignStatus.CANCELLED,
    }
)


class SendingMode(StrEnum):
    TEST = "TEST"
    MANUAL_APPROVAL = "MANUAL_APPROVAL"


class CompanyStatus(StrEnum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    UNKNOWN = "UNKNOWN"


class ContactType(StrEnum):
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    TELEGRAM = "TELEGRAM"
    WHATSAPP = "WHATSAPP"
    OTHER = "OTHER"


class VerificationStatus(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    INVALID = "INVALID"


class ConsentStatus(StrEnum):
    UNKNOWN = "UNKNOWN"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class CampaignLeadStatus(StrEnum):
    NEW = "NEW"
    ENRICHED = "ENRICHED"
    SCORED = "SCORED"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"
    DRAFT_READY = "DRAFT_READY"
    SCHEDULED = "SCHEDULED"
    CONTACTED = "CONTACTED"
    RESPONDED = "RESPONDED"
    INTERESTED = "INTERESTED"
    NOT_INTERESTED = "NOT_INTERESTED"
    UNSUBSCRIBED = "UNSUBSCRIBED"
    BOUNCED = "BOUNCED"
    HANDED_TO_MANAGER = "HANDED_TO_MANAGER"


class DataSourceType(StrEnum):
    MANUAL = "MANUAL"
    TEST = "TEST"
    CATALOG = "CATALOG"
    OTHER = "OTHER"


class ResearchRunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class ResearchItemOutcome(StrEnum):
    CREATED = "created"
    MATCHED_EXISTING = "matched_existing"
    UPDATED = "updated"
    SKIPPED = "skipped"
    CONFLICT = "conflict"


# Stage 2: only TestSourceAdapter is allowed
ALLOWED_RESEARCH_ADAPTERS = frozenset({"test_source"})
MAX_RESEARCH_LIMIT = 30
MAX_QUERY_LENGTH = 200
