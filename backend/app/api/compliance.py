from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.compliance import (
    ComplianceCheckRequest,
    ComplianceCheckResponse,
    ProviderReadinessReport,
    SuppressionCreate,
    SuppressionListResponse,
    SuppressionPatch,
    SuppressionRead,
    TestComplianceEventCreate,
    TestComplianceEventResponse,
)
from app.services import compliance_service

router = APIRouter(tags=["compliance"])


@router.post("/compliance/suppressions", response_model=SuppressionRead, status_code=201)
def create_suppression(payload: SuppressionCreate, db: Session = Depends(get_db)) -> SuppressionRead:
    return compliance_service.create_suppression(db, payload)


@router.get("/compliance/suppressions", response_model=SuppressionListResponse)
def list_suppressions(
    scope: str | None = None,
    suppression_type: str | None = None,
    reason: str | None = None,
    is_active: bool | None = None,
    campaign_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> SuppressionListResponse:
    return compliance_service.list_suppressions(
        db,
        scope=scope,
        suppression_type=suppression_type,
        reason=reason,
        is_active=is_active,
        campaign_id=campaign_id,
        limit=limit,
        offset=offset,
    )


@router.get("/compliance/suppressions/{entry_id}", response_model=SuppressionRead)
def get_suppression(entry_id: UUID, db: Session = Depends(get_db)) -> SuppressionRead:
    return compliance_service.get_suppression(db, entry_id)


@router.patch("/compliance/suppressions/{entry_id}", response_model=SuppressionRead)
def patch_suppression(
    entry_id: UUID, payload: SuppressionPatch, db: Session = Depends(get_db)
) -> SuppressionRead:
    return compliance_service.patch_suppression(db, entry_id, payload)


@router.post("/compliance/suppressions/{entry_id}/deactivate", response_model=SuppressionRead)
def deactivate_suppression(entry_id: UUID, db: Session = Depends(get_db)) -> SuppressionRead:
    return compliance_service.deactivate_suppression(db, entry_id)


@router.post("/compliance/suppressions/{entry_id}/reactivate", response_model=SuppressionRead)
def reactivate_suppression(entry_id: UUID, db: Session = Depends(get_db)) -> SuppressionRead:
    return compliance_service.reactivate_suppression(db, entry_id)


@router.post(
    "/campaigns/{campaign_id}/compliance/check",
    response_model=ComplianceCheckResponse,
)
def check_compliance(
    campaign_id: UUID,
    payload: ComplianceCheckRequest,
    db: Session = Depends(get_db),
) -> ComplianceCheckResponse:
    return compliance_service.check_message_api(db, campaign_id, payload.message_id)


@router.post(
    "/campaigns/{campaign_id}/compliance/test-events",
    response_model=TestComplianceEventResponse,
    status_code=201,
)
def create_test_event(
    campaign_id: UUID,
    payload: TestComplianceEventCreate,
    db: Session = Depends(get_db),
) -> TestComplianceEventResponse:
    return compliance_service.create_test_event(db, campaign_id, payload)


@router.get("/compliance/provider-readiness", response_model=ProviderReadinessReport)
def provider_readiness() -> ProviderReadinessReport:
    return compliance_service.build_provider_readiness_report()


@router.post("/compliance/provider-readiness/validate", response_model=ProviderReadinessReport)
def validate_provider_readiness() -> ProviderReadinessReport:
    return compliance_service.build_provider_readiness_report()
