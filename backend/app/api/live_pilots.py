from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.live_pilot import (
    LivePilotApprovalResponse,
    LivePilotApproveRequest,
    LivePilotCreate,
    LivePilotDryRunRequest,
    LivePilotDryRunResponse,
    LivePilotListResponse,
    LivePilotRead,
    LivePilotReadinessResponse,
    LivePilotRecipientCreate,
    LivePilotRecipientListResponse,
    LivePilotRecipientRead,
    LivePilotValidationResponse,
)
from app.services import live_pilot_service

router = APIRouter(tags=["live-pilots"])


@router.post("/live-pilots", response_model=LivePilotRead, status_code=201)
def create_live_pilot(
    payload: LivePilotCreate,
    db: Session = Depends(get_db),
) -> LivePilotRead:
    return live_pilot_service.create_live_pilot(db, payload)


@router.get("/live-pilots", response_model=LivePilotListResponse)
def list_live_pilots(
    campaign_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> LivePilotListResponse:
    return live_pilot_service.list_live_pilots(
        db, campaign_id=campaign_id, limit=limit, offset=offset
    )


@router.get("/live-pilots/{pilot_id}", response_model=LivePilotRead)
def get_live_pilot(pilot_id: UUID, db: Session = Depends(get_db)) -> LivePilotRead:
    return live_pilot_service.get_live_pilot(db, pilot_id)


@router.post("/live-pilots/{pilot_id}/validate", response_model=LivePilotValidationResponse)
def validate_live_pilot(
    pilot_id: UUID,
    db: Session = Depends(get_db),
) -> LivePilotValidationResponse:
    return live_pilot_service.validate_pilot(db, pilot_id)


@router.post("/live-pilots/{pilot_id}/approve", response_model=LivePilotApprovalResponse)
def approve_live_pilot(
    pilot_id: UUID,
    payload: LivePilotApproveRequest | None = None,
    db: Session = Depends(get_db),
) -> LivePilotApprovalResponse:
    token = payload.confirmation_token if payload else None
    return live_pilot_service.approve_pilot(db, pilot_id, confirmation_token=token)


@router.post("/live-pilots/{pilot_id}/cancel", response_model=LivePilotRead)
def cancel_live_pilot(pilot_id: UUID, db: Session = Depends(get_db)) -> LivePilotRead:
    return live_pilot_service.cancel_pilot(db, pilot_id)


@router.post("/live-pilots/{pilot_id}/dry-run", response_model=LivePilotDryRunResponse)
def dry_run_live_pilot(
    pilot_id: UUID,
    payload: LivePilotDryRunRequest,
    db: Session = Depends(get_db),
) -> LivePilotDryRunResponse:
    return live_pilot_service.dry_run_pilot(
        db, pilot_id, idempotency_key=payload.idempotency_key
    )


@router.get("/live-pilots/{pilot_id}/readiness", response_model=LivePilotReadinessResponse)
def live_pilot_readiness(
    pilot_id: UUID,
    db: Session = Depends(get_db),
) -> LivePilotReadinessResponse:
    return live_pilot_service.get_readiness(db, pilot_id)


@router.get("/live-pilots/{pilot_id}/recipients", response_model=LivePilotRecipientListResponse)
def list_live_pilot_recipients(
    pilot_id: UUID,
    db: Session = Depends(get_db),
) -> LivePilotRecipientListResponse:
    return live_pilot_service.list_recipients(db, pilot_id)


@router.post(
    "/live-pilots/{pilot_id}/recipients",
    response_model=LivePilotRecipientRead,
    status_code=201,
)
def add_live_pilot_recipient(
    pilot_id: UUID,
    payload: LivePilotRecipientCreate,
    db: Session = Depends(get_db),
) -> LivePilotRecipientRead:
    return live_pilot_service.add_recipient(db, pilot_id, payload)
