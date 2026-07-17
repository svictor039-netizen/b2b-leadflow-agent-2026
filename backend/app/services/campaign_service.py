from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import AppError
from app.models import (
    USER_EDITABLE_CAMPAIGN_STATUSES,
    Campaign,
    CampaignLead,
    CampaignLeadStatus,
    CampaignStatus,
    Company,
    SendingMode,
)
from app.schemas.campaign import (
    CampaignCreate,
    CampaignLeadRead,
    CampaignListItem,
    CampaignListResponse,
    CampaignRead,
    CampaignUpdate,
)


def _lead_count(db: Session, campaign_id: UUID) -> int:
    return db.scalar(
        select(func.count()).select_from(CampaignLead).where(CampaignLead.campaign_id == campaign_id)
    ) or 0


def _lead_status_counts(db: Session, campaign_id: UUID) -> dict[str, int]:
    rows = db.execute(
        select(CampaignLead.status, func.count())
        .where(CampaignLead.campaign_id == campaign_id)
        .group_by(CampaignLead.status)
    ).all()
    return {status: count for status, count in rows}


def _to_campaign_read(db: Session, campaign: Campaign) -> CampaignRead:
    lead_count = _lead_count(db, campaign.id)
    return CampaignRead(
        id=campaign.id,
        name=campaign.name,
        business_type=campaign.business_type,
        region=campaign.region,
        offer=campaign.offer,
        offer_description=campaign.offer_description,
        ideal_customer=campaign.ideal_customer,
        desired_cta=campaign.desired_cta,
        max_companies=campaign.max_companies,
        max_emails_per_lead=campaign.max_emails_per_lead,
        sending_mode=SendingMode(campaign.sending_mode),
        status=CampaignStatus(campaign.status),
        created_at=campaign.created_at,
        updated_at=campaign.updated_at,
        lead_count=lead_count,
        free_slots=max(campaign.max_companies - lead_count, 0),
        lead_status_counts=_lead_status_counts(db, campaign.id),
    )


def create_campaign(db: Session, data: CampaignCreate) -> CampaignRead:
    campaign = Campaign(
        name=data.name,
        business_type=data.business_type,
        region=data.region,
        offer=data.offer,
        offer_description=data.offer_description,
        ideal_customer=data.ideal_customer,
        desired_cta=data.desired_cta,
        max_companies=data.max_companies,
        max_emails_per_lead=data.max_emails_per_lead,
        sending_mode=data.sending_mode.value,
        status=CampaignStatus.DRAFT.value,
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return _to_campaign_read(db, campaign)


def list_campaigns(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    status: CampaignStatus | None = None,
    search: str | None = None,
) -> CampaignListResponse:
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)

    query = select(Campaign)
    count_query = select(func.count()).select_from(Campaign)

    if status is not None:
        query = query.where(Campaign.status == status.value)
        count_query = count_query.where(Campaign.status == status.value)

    if search:
        pattern = f"%{search.strip()}%"
        filt = or_(
            Campaign.name.ilike(pattern),
            Campaign.business_type.ilike(pattern),
            Campaign.region.ilike(pattern),
        )
        query = query.where(filt)
        count_query = count_query.where(filt)

    total = db.scalar(count_query) or 0
    campaigns = db.scalars(
        query.order_by(Campaign.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    items: list[CampaignListItem] = []
    for campaign in campaigns:
        lead_count = _lead_count(db, campaign.id)
        items.append(
            CampaignListItem(
                id=campaign.id,
                name=campaign.name,
                business_type=campaign.business_type,
                region=campaign.region,
                status=CampaignStatus(campaign.status),
                sending_mode=SendingMode(campaign.sending_mode),
                max_companies=campaign.max_companies,
                max_emails_per_lead=campaign.max_emails_per_lead,
                lead_count=lead_count,
                free_slots=max(campaign.max_companies - lead_count, 0),
                created_at=campaign.created_at,
                updated_at=campaign.updated_at,
            )
        )

    return CampaignListResponse(items=items, total=total, page=page, page_size=page_size)


def get_campaign(db: Session, campaign_id: UUID) -> CampaignRead:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise AppError("Campaign not found.", status_code=404, code="not_found")
    return _to_campaign_read(db, campaign)


def update_campaign(db: Session, campaign_id: UUID, data: CampaignUpdate) -> CampaignRead:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise AppError("Campaign not found.", status_code=404, code="not_found")

    payload = data.model_dump(exclude_unset=True)

    if "status" in payload:
        new_status = CampaignStatus(payload["status"])
        if new_status not in USER_EDITABLE_CAMPAIGN_STATUSES:
            raise AppError(
                f"Status '{new_status.value}' cannot be set manually on stage 1.",
                status_code=400,
                code="forbidden_status",
            )
        payload["status"] = new_status.value

    if "sending_mode" in payload:
        # Only TEST / MANUAL_APPROVAL allowed by enum; never auto-send.
        payload["sending_mode"] = SendingMode(payload["sending_mode"]).value

    if "max_companies" in payload:
        lead_count = _lead_count(db, campaign.id)
        if payload["max_companies"] < lead_count:
            raise AppError(
                f"max_companies cannot be less than current lead count ({lead_count}).",
                status_code=400,
                code="max_companies_too_low",
            )

    for field in ("offer_description", "ideal_customer", "desired_cta"):
        if field in payload and isinstance(payload[field], str) and not payload[field].strip():
            payload[field] = None

    for key, value in payload.items():
        setattr(campaign, key, value)

    db.commit()
    db.refresh(campaign)
    return _to_campaign_read(db, campaign)


def list_campaign_companies(db: Session, campaign_id: UUID) -> list[CampaignLeadRead]:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise AppError("Campaign not found.", status_code=404, code="not_found")

    leads = db.scalars(
        select(CampaignLead)
        .options(selectinload(CampaignLead.company))
        .where(CampaignLead.campaign_id == campaign_id)
        .order_by(CampaignLead.created_at.desc())
    ).all()

    result: list[CampaignLeadRead] = []
    for lead in leads:
        result.append(
            CampaignLeadRead(
                id=lead.id,
                campaign_id=lead.campaign_id,
                company_id=lead.company_id,
                status=lead.status,
                approved_for_research=lead.approved_for_research,
                approved_for_email=lead.approved_for_email,
                created_at=lead.created_at,
                updated_at=lead.updated_at,
                company_name=lead.company.name if lead.company else None,
                company_domain=lead.company.domain if lead.company else None,
                company_status=lead.company.status if lead.company else None,
            )
        )
    return result


def attach_company_to_campaign(
    db: Session,
    campaign_id: UUID,
    company_id: UUID,
) -> CampaignLeadRead:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise AppError("Campaign not found.", status_code=404, code="not_found")

    company = db.get(Company, company_id)
    if company is None:
        raise AppError("Company not found.", status_code=404, code="not_found")

    existing = db.scalar(
        select(CampaignLead).where(
            CampaignLead.campaign_id == campaign_id,
            CampaignLead.company_id == company_id,
        )
    )
    if existing is not None:
        raise AppError(
            "Company is already attached to this campaign.",
            status_code=409,
            code="duplicate_campaign_lead",
        )

    lead_count = _lead_count(db, campaign_id)
    if lead_count >= campaign.max_companies:
        raise AppError(
            f"Campaign already has the maximum of {campaign.max_companies} companies.",
            status_code=400,
            code="campaign_full",
        )

    lead = CampaignLead(
        campaign_id=campaign_id,
        company_id=company_id,
        status=CampaignLeadStatus.NEW.value,
        approved_for_research=False,
        approved_for_email=False,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    return CampaignLeadRead(
        id=lead.id,
        campaign_id=lead.campaign_id,
        company_id=lead.company_id,
        status=lead.status,
        approved_for_research=lead.approved_for_research,
        approved_for_email=lead.approved_for_email,
        created_at=lead.created_at,
        updated_at=lead.updated_at,
        company_name=company.name,
        company_domain=company.domain,
        company_status=company.status,
    )


def detach_company_from_campaign(
    db: Session,
    campaign_id: UUID,
    company_id: UUID,
) -> None:
    lead = db.scalar(
        select(CampaignLead).where(
            CampaignLead.campaign_id == campaign_id,
            CampaignLead.company_id == company_id,
        )
    )
    if lead is None:
        raise AppError("Campaign lead link not found.", status_code=404, code="not_found")

    db.delete(lead)
    db.commit()
