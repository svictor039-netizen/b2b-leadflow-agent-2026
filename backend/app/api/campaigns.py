from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.enums import CampaignStatus
from app.schemas.campaign import (
    CampaignCreate,
    CampaignLeadRead,
    CampaignListResponse,
    CampaignRead,
    CampaignUpdate,
)
from app.schemas.qualification import (
    LeadReviewRequest,
    QualificationLeadListResponse,
    QualificationLeadRead,
)
from app.services import campaign_service, qualification_service

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


@router.post("", response_model=CampaignRead, status_code=status.HTTP_201_CREATED)
def create_campaign(payload: CampaignCreate, db: Session = Depends(get_db)) -> CampaignRead:
    return campaign_service.create_campaign(db, payload)


@router.get("", response_model=CampaignListResponse)
def list_campaigns(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: CampaignStatus | None = Query(None, alias="status"),
    search: str | None = Query(None, max_length=200),
    db: Session = Depends(get_db),
) -> CampaignListResponse:
    return campaign_service.list_campaigns(
        db,
        page=page,
        page_size=page_size,
        status=status_filter,
        search=search,
    )


@router.get("/{campaign_id}", response_model=CampaignRead)
def get_campaign(campaign_id: UUID, db: Session = Depends(get_db)) -> CampaignRead:
    return campaign_service.get_campaign(db, campaign_id)


@router.patch("/{campaign_id}", response_model=CampaignRead)
def update_campaign(
    campaign_id: UUID,
    payload: CampaignUpdate,
    db: Session = Depends(get_db),
) -> CampaignRead:
    return campaign_service.update_campaign(db, campaign_id, payload)


@router.get("/{campaign_id}/companies", response_model=list[CampaignLeadRead])
def list_campaign_companies(
    campaign_id: UUID,
    db: Session = Depends(get_db),
) -> list[CampaignLeadRead]:
    return campaign_service.list_campaign_companies(db, campaign_id)


@router.post(
    "/{campaign_id}/companies/{company_id}",
    response_model=CampaignLeadRead,
    status_code=status.HTTP_201_CREATED,
)
def attach_company(
    campaign_id: UUID,
    company_id: UUID,
    db: Session = Depends(get_db),
) -> CampaignLeadRead:
    return campaign_service.attach_company_to_campaign(db, campaign_id, company_id)


@router.delete(
    "/{campaign_id}/companies/{company_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def detach_company(
    campaign_id: UUID,
    company_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    campaign_service.detach_company_from_campaign(db, campaign_id, company_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{campaign_id}/leads", response_model=QualificationLeadListResponse)
def list_campaign_leads(
    campaign_id: UUID,
    qualification_status: str | None = Query(None, max_length=32),
    review_decision: str | None = Query(None, max_length=32),
    min_score: int | None = Query(None, ge=0, le=100),
    max_score: int | None = Query(None, ge=0, le=100),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> QualificationLeadListResponse:
    return qualification_service.list_campaign_leads(
        db,
        campaign_id,
        qualification_status=qualification_status,
        review_decision=review_decision,
        min_score=min_score,
        max_score=max_score,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{campaign_id}/leads/{lead_id}/review",
    response_model=QualificationLeadRead,
)
def review_campaign_lead(
    campaign_id: UUID,
    lead_id: UUID,
    payload: LeadReviewRequest,
    db: Session = Depends(get_db),
) -> QualificationLeadRead:
    return qualification_service.review_lead(db, campaign_id, lead_id, payload)
