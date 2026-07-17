from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.execution import (
    CampaignAnalyticsRead,
    ExecutionItemListResponse,
    ExecutionRunCreate,
    ExecutionRunListResponse,
    ExecutionRunRead,
)
from app.services import execution_service

router = APIRouter(prefix="/campaigns/{campaign_id}", tags=["execution"])


@router.post("/execution-runs", response_model=ExecutionRunRead, status_code=201)
def create_execution_run(
    campaign_id: UUID,
    payload: ExecutionRunCreate,
    db: Session = Depends(get_db),
) -> ExecutionRunRead:
    return execution_service.create_execution_run(db, campaign_id, payload)


@router.get("/execution-runs", response_model=ExecutionRunListResponse)
def list_execution_runs(
    campaign_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> ExecutionRunListResponse:
    return execution_service.list_execution_runs(db, campaign_id, limit=limit, offset=offset)


@router.get("/execution-runs/{run_id}", response_model=ExecutionRunRead)
def get_execution_run(
    campaign_id: UUID,
    run_id: UUID,
    db: Session = Depends(get_db),
) -> ExecutionRunRead:
    return execution_service.get_execution_run(db, campaign_id, run_id)


@router.post("/execution-runs/{run_id}/start", response_model=ExecutionRunRead)
def start_execution_run(
    campaign_id: UUID,
    run_id: UUID,
    async_mode: bool = Query(True),
    db: Session = Depends(get_db),
) -> ExecutionRunRead:
    return execution_service.start_execution_run(
        db, campaign_id, run_id, async_mode=async_mode
    )


@router.post("/execution-runs/{run_id}/pause", response_model=ExecutionRunRead)
def pause_execution_run(
    campaign_id: UUID,
    run_id: UUID,
    db: Session = Depends(get_db),
) -> ExecutionRunRead:
    return execution_service.pause_execution_run(db, campaign_id, run_id)


@router.post("/execution-runs/{run_id}/resume", response_model=ExecutionRunRead)
def resume_execution_run(
    campaign_id: UUID,
    run_id: UUID,
    async_mode: bool = Query(True),
    db: Session = Depends(get_db),
) -> ExecutionRunRead:
    return execution_service.resume_execution_run(
        db, campaign_id, run_id, async_mode=async_mode
    )


@router.post("/execution-runs/{run_id}/cancel", response_model=ExecutionRunRead)
def cancel_execution_run(
    campaign_id: UUID,
    run_id: UUID,
    db: Session = Depends(get_db),
) -> ExecutionRunRead:
    return execution_service.cancel_execution_run(db, campaign_id, run_id)


@router.get("/execution-runs/{run_id}/items", response_model=ExecutionItemListResponse)
def list_execution_items(
    campaign_id: UUID,
    run_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> ExecutionItemListResponse:
    return execution_service.list_execution_items(
        db, campaign_id, run_id, limit=limit, offset=offset
    )


@router.get("/analytics", response_model=CampaignAnalyticsRead)
def campaign_analytics(
    campaign_id: UUID,
    db: Session = Depends(get_db),
) -> CampaignAnalyticsRead:
    return execution_service.get_campaign_analytics(db, campaign_id)
