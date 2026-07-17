from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.outreach import (
    DraftCreateRequest,
    DraftCreateResponse,
    OutreachMessageListResponse,
    OutreachMessageRead,
    OutreachSequenceCreate,
    OutreachSequenceRead,
    OutreachSequenceUpdate,
    OutreachTemplateCreate,
    OutreachTemplateRead,
    OutreachTemplateUpdate,
    RejectMessageRequest,
)
from app.services import outreach_service

router = APIRouter(prefix="/campaigns/{campaign_id}/outreach", tags=["outreach"])


@router.post("/templates", response_model=OutreachTemplateRead, status_code=201)
def create_template(
    campaign_id: UUID,
    payload: OutreachTemplateCreate,
    db: Session = Depends(get_db),
) -> OutreachTemplateRead:
    return outreach_service.create_template(db, campaign_id, payload)


@router.get("/templates", response_model=list[OutreachTemplateRead])
def list_templates(campaign_id: UUID, db: Session = Depends(get_db)) -> list[OutreachTemplateRead]:
    return outreach_service.list_templates(db, campaign_id)


@router.patch("/templates/{template_id}", response_model=OutreachTemplateRead)
def update_template(
    campaign_id: UUID,
    template_id: UUID,
    payload: OutreachTemplateUpdate,
    db: Session = Depends(get_db),
) -> OutreachTemplateRead:
    return outreach_service.update_template(db, campaign_id, template_id, payload)


@router.post("/sequences", response_model=OutreachSequenceRead, status_code=201)
def create_sequence(
    campaign_id: UUID,
    payload: OutreachSequenceCreate,
    db: Session = Depends(get_db),
) -> OutreachSequenceRead:
    return outreach_service.create_sequence(db, campaign_id, payload)


@router.get("/sequences", response_model=list[OutreachSequenceRead])
def list_sequences(campaign_id: UUID, db: Session = Depends(get_db)) -> list[OutreachSequenceRead]:
    return outreach_service.list_sequences(db, campaign_id)


@router.patch("/sequences/{sequence_id}", response_model=OutreachSequenceRead)
def update_sequence(
    campaign_id: UUID,
    sequence_id: UUID,
    payload: OutreachSequenceUpdate,
    db: Session = Depends(get_db),
) -> OutreachSequenceRead:
    return outreach_service.update_sequence(db, campaign_id, sequence_id, payload)


@router.post("/drafts", response_model=DraftCreateResponse, status_code=201)
def create_drafts(
    campaign_id: UUID,
    payload: DraftCreateRequest,
    db: Session = Depends(get_db),
) -> DraftCreateResponse:
    return outreach_service.create_drafts(db, campaign_id, payload)


@router.get("/messages", response_model=OutreachMessageListResponse)
def list_messages(
    campaign_id: UUID,
    status: str | None = Query(None, max_length=32),
    approval_decision: str | None = Query(None, max_length=32),
    sequence_id: UUID | None = None,
    lead_id: UUID | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> OutreachMessageListResponse:
    return outreach_service.list_messages(
        db,
        campaign_id,
        status=status,
        approval_decision=approval_decision,
        sequence_id=sequence_id,
        lead_id=lead_id,
        limit=limit,
        offset=offset,
    )


@router.get("/messages/{message_id}", response_model=OutreachMessageRead)
def get_message(
    campaign_id: UUID,
    message_id: UUID,
    db: Session = Depends(get_db),
) -> OutreachMessageRead:
    return outreach_service.get_message(db, campaign_id, message_id)


@router.post("/messages/{message_id}/approve", response_model=OutreachMessageRead)
def approve_message(
    campaign_id: UUID,
    message_id: UUID,
    db: Session = Depends(get_db),
) -> OutreachMessageRead:
    return outreach_service.approve_message(db, campaign_id, message_id)


@router.post("/messages/{message_id}/reject", response_model=OutreachMessageRead)
def reject_message(
    campaign_id: UUID,
    message_id: UUID,
    payload: RejectMessageRequest | None = None,
    db: Session = Depends(get_db),
) -> OutreachMessageRead:
    return outreach_service.reject_message(db, campaign_id, message_id, payload)


@router.post("/messages/{message_id}/reset", response_model=OutreachMessageRead)
def reset_message(
    campaign_id: UUID,
    message_id: UUID,
    db: Session = Depends(get_db),
) -> OutreachMessageRead:
    return outreach_service.reset_message_to_draft(db, campaign_id, message_id)


@router.post("/messages/{message_id}/send", response_model=OutreachMessageRead)
def send_message(
    campaign_id: UUID,
    message_id: UUID,
    db: Session = Depends(get_db),
) -> OutreachMessageRead:
    msg = outreach_service.send_message(db, campaign_id, message_id)
    return outreach_service.get_message(db, campaign_id, msg.id)
