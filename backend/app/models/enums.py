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


class QualificationRunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class QualificationStatus(StrEnum):
    QUALIFIED = "QUALIFIED"
    REVIEW = "REVIEW"
    DISQUALIFIED = "DISQUALIFIED"


class ReviewDecision(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class QualificationItemOutcome(StrEnum):
    CREATED = "created"
    MATCHED_EXISTING = "matched_existing"
    UPDATED = "updated"
    SKIPPED = "skipped"
    CONFLICT = "conflict"


SCORING_VERSION = "stage3-v1"
MAX_REVIEW_NOTE_LENGTH = 500


# --- Stage 4: safe outreach ---

class OutreachMessageStatus(StrEnum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SENDING = "SENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class OutreachApprovalDecision(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class SendAttemptStatus(StrEnum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class DraftItemOutcome(StrEnum):
    CREATED = "created"
    MATCHED_EXISTING = "matched_existing"
    SKIPPED = "skipped"
    CONFLICT = "conflict"
    FAILED = "failed"


MAX_OUTREACH_TEMPLATE_NAME = 200
MAX_OUTREACH_SUBJECT = 200
MAX_OUTREACH_BODY = 5000
MAX_OUTREACH_SEQUENCE_NAME = 200
MAX_OUTREACH_SEQUENCE_STEPS = 3
MAX_OUTREACH_REJECT_NOTE = 500
MAX_OUTREACH_LIST_LIMIT = 100
TEST_EMAIL_DOMAIN = "example.test"
ALLOWED_OUTREACH_PROVIDER = "test_email"
OUTREACH_TEMPLATE_VARIABLES = frozenset(
    {
        "company_name",
        "company_domain",
        "company_location",
        "company_industry",
        "campaign_name",
        "lead_score",
        "qualification_status",
    }
)

# Stale PENDING outbox: delivery outcome unknown — never auto-SENT.
DELIVERY_OUTCOME_UNKNOWN = "DELIVERY_OUTCOME_UNKNOWN"
DELIVERY_OUTCOME_UNKNOWN_USER_MESSAGE = (
    "Результат тестовой отправки не подтверждён. Автоматический повтор заблокирован."
)


# --- Stage 5: test campaign orchestration ---

class ExecutionRunStatus(StrEnum):
    DRAFT = "DRAFT"
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


class ExecutionItemStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SENT = "SENT"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    SKIPPED = "SKIPPED"
    UNKNOWN = "UNKNOWN"
    CANCELLED = "CANCELLED"


class ExecutionMode(StrEnum):
    TEST_MANUAL_ONLY = "TEST_MANUAL_ONLY"


EXECUTION_TERMINAL_STATUSES = frozenset(
    {
        ExecutionRunStatus.COMPLETED.value,
        ExecutionRunStatus.FAILED.value,
        ExecutionRunStatus.BLOCKED.value,
        ExecutionRunStatus.CANCELLED.value,
    }
)
EXECUTION_ACTIVE_STATUSES = frozenset(
    {
        ExecutionRunStatus.DRAFT.value,
        ExecutionRunStatus.PENDING.value,
        ExecutionRunStatus.RUNNING.value,
        ExecutionRunStatus.PAUSED.value,
    }
)
ITEM_TERMINAL_STATUSES = frozenset(
    {
        ExecutionItemStatus.SENT.value,
        ExecutionItemStatus.FAILED.value,
        ExecutionItemStatus.BLOCKED.value,
        ExecutionItemStatus.SKIPPED.value,
        ExecutionItemStatus.UNKNOWN.value,
        ExecutionItemStatus.CANCELLED.value,
    }
)

MAX_EXECUTION_MESSAGES = 100
MIN_EXECUTION_MESSAGES = 1
MAX_EXECUTION_BATCH_SIZE = 10
MIN_EXECUTION_BATCH_SIZE = 1
MAX_EXECUTION_LIST_LIMIT = 100
PROCESSING_ITEM_STALE_AFTER_SECONDS = 30