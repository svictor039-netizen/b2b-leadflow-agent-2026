from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import AppError
from app.models import (
    Company,
    CompanyLocation,
    CompanyStatus,
    ConsentStatus,
    Contact,
    ContactType,
    VerificationStatus,
)
from app.schemas.company import (
    CompanyCreate,
    CompanyListItem,
    CompanyListResponse,
    CompanyRead,
    CompanyUpdate,
    ContactCreate,
    ContactRead,
    ContactUpdate,
    LocationCreate,
    LocationRead,
    LocationUpdate,
)
from app.services.validation import (
    blank_to_none,
    normalize_domain,
    normalize_website,
    assert_safe_url,
    validate_email_value,
)


def _company_detail(company: Company) -> CompanyRead:
    return CompanyRead.model_validate(company)


def create_company(db: Session, data: CompanyCreate) -> CompanyRead:
    website = normalize_website(data.website) if data.website else None
    domain = normalize_domain(data.domain) if data.domain else None
    if domain is None and website:
        # light extraction without aggressive rewrite
        from urllib.parse import urlparse

        host = urlparse(website).netloc.lower().removeprefix("www.")
        domain = host or None

    company = Company(
        name=data.name.strip(),
        legal_name=blank_to_none(data.legal_name),
        website=website,
        domain=domain,
        description=blank_to_none(data.description),
        status=data.status.value,
        source_confidence=data.source_confidence,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    company = db.scalars(
        select(Company)
        .options(selectinload(Company.locations), selectinload(Company.contacts))
        .where(Company.id == company.id)
    ).one()
    return _company_detail(company)


def list_companies(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    status: CompanyStatus | None = None,
    city: str | None = None,
) -> CompanyListResponse:
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)

    query = select(Company)
    count_query = select(func.count()).select_from(Company)

    if status is not None:
        query = query.where(Company.status == status.value)
        count_query = count_query.where(Company.status == status.value)

    if search:
        pattern = f"%{search.strip()}%"
        filt = or_(
            Company.name.ilike(pattern),
            Company.domain.ilike(pattern),
            Company.legal_name.ilike(pattern),
        )
        query = query.where(filt)
        count_query = count_query.where(filt)

    if city:
        city_pattern = f"%{city.strip()}%"
        city_subq = select(CompanyLocation.company_id).where(
            CompanyLocation.city.ilike(city_pattern)
        )
        query = query.where(Company.id.in_(city_subq))
        count_query = count_query.where(Company.id.in_(city_subq))

    total = db.scalar(count_query) or 0
    companies = db.scalars(
        query.order_by(Company.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    items = [CompanyListItem.model_validate(c) for c in companies]
    return CompanyListResponse(items=items, total=total, page=page, page_size=page_size)


def get_company(db: Session, company_id: UUID) -> CompanyRead:
    company = db.scalars(
        select(Company)
        .options(selectinload(Company.locations), selectinload(Company.contacts))
        .where(Company.id == company_id)
    ).first()
    if company is None:
        raise AppError("Company not found.", status_code=404, code="not_found")
    return _company_detail(company)


def update_company(db: Session, company_id: UUID, data: CompanyUpdate) -> CompanyRead:
    company = db.get(Company, company_id)
    if company is None:
        raise AppError("Company not found.", status_code=404, code="not_found")

    payload = data.model_dump(exclude_unset=True)

    if "website" in payload:
        payload["website"] = normalize_website(payload["website"]) if payload["website"] else None
    if "domain" in payload:
        payload["domain"] = normalize_domain(payload["domain"]) if payload["domain"] else None
    if "legal_name" in payload:
        payload["legal_name"] = blank_to_none(payload["legal_name"])
    if "description" in payload:
        payload["description"] = blank_to_none(payload["description"])
    if "status" in payload:
        payload["status"] = CompanyStatus(payload["status"]).value
    if "name" in payload and isinstance(payload["name"], str):
        payload["name"] = payload["name"].strip()

    for key, value in payload.items():
        setattr(company, key, value)

    db.commit()
    return get_company(db, company_id)


def create_location(db: Session, company_id: UUID, data: LocationCreate) -> LocationRead:
    company = db.get(Company, company_id)
    if company is None:
        raise AppError("Company not found.", status_code=404, code="not_found")

    location = CompanyLocation(
        company_id=company_id,
        country=blank_to_none(data.country),
        region=blank_to_none(data.region),
        city=blank_to_none(data.city),
        address=blank_to_none(data.address),
        postal_code=blank_to_none(data.postal_code),
        latitude=data.latitude,
        longitude=data.longitude,
        is_primary=data.is_primary,
    )
    db.add(location)
    db.commit()
    db.refresh(location)
    return LocationRead.model_validate(location)


def update_location(db: Session, location_id: UUID, data: LocationUpdate) -> LocationRead:
    location = db.get(CompanyLocation, location_id)
    if location is None:
        raise AppError("Location not found.", status_code=404, code="not_found")

    payload = data.model_dump(exclude_unset=True)
    for field in ("country", "region", "city", "address", "postal_code"):
        if field in payload:
            payload[field] = blank_to_none(payload[field])

    for key, value in payload.items():
        setattr(location, key, value)

    db.commit()
    db.refresh(location)
    return LocationRead.model_validate(location)


def delete_location(db: Session, location_id: UUID) -> None:
    location = db.get(CompanyLocation, location_id)
    if location is None:
        raise AppError("Location not found.", status_code=404, code="not_found")
    db.delete(location)
    db.commit()


def _prepare_contact_fields(data: ContactCreate | ContactUpdate, *, partial: bool = False) -> dict:
    if isinstance(data, ContactCreate):
        payload = data.model_dump()
    else:
        payload = data.model_dump(exclude_unset=True)

    if "value" in payload and payload["value"] is not None:
        payload["value"] = payload["value"].strip()

    contact_type = payload.get("contact_type")
    if contact_type is not None:
        contact_type = ContactType(contact_type)
        payload["contact_type"] = contact_type.value

    if "value" in payload and payload["value"] is not None:
        effective_type = contact_type
        if effective_type is None and not partial:
            effective_type = ContactType.EMAIL
        # For updates, validate email only when type is EMAIL or existing will be checked at call site
        if effective_type == ContactType.EMAIL or (
            partial and "contact_type" not in payload and False
        ):
            pass
        if effective_type == ContactType.EMAIL:
            payload["value"] = validate_email_value(payload["value"])

    if "source_url" in payload:
        payload["source_url"] = blank_to_none(payload["source_url"])
        if payload["source_url"]:
            assert_safe_url(payload["source_url"])

    if "label" in payload:
        payload["label"] = blank_to_none(payload["label"])
    if "consent_source" in payload:
        payload["consent_source"] = blank_to_none(payload["consent_source"])

    if "verification_status" in payload and payload["verification_status"] is not None:
        payload["verification_status"] = VerificationStatus(payload["verification_status"]).value
    if "consent_status" in payload and payload["consent_status"] is not None:
        payload["consent_status"] = ConsentStatus(payload["consent_status"]).value

    return payload


def create_contact(db: Session, company_id: UUID, data: ContactCreate) -> ContactRead:
    company = db.get(Company, company_id)
    if company is None:
        raise AppError("Company not found.", status_code=404, code="not_found")

    payload = _prepare_contact_fields(data)
    if data.contact_type == ContactType.EMAIL:
        payload["value"] = validate_email_value(data.value)

    contact = Contact(
        company_id=company_id,
        contact_type=payload["contact_type"],
        value=payload["value"],
        label=payload.get("label"),
        source_url=payload.get("source_url"),
        collected_at=datetime.now(timezone.utc),
        verification_status=payload.get(
            "verification_status", VerificationStatus.UNVERIFIED.value
        ),
        consent_status=payload.get("consent_status", ConsentStatus.UNKNOWN.value),
        consent_source=payload.get("consent_source"),
        do_not_contact=payload.get("do_not_contact", False),
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return ContactRead.model_validate(contact)


def update_contact(db: Session, contact_id: UUID, data: ContactUpdate) -> ContactRead:
    contact = db.get(Contact, contact_id)
    if contact is None:
        raise AppError("Contact not found.", status_code=404, code="not_found")

    payload = data.model_dump(exclude_unset=True)

    new_type = ContactType(payload["contact_type"]) if "contact_type" in payload else ContactType(
        contact.contact_type
    )
    if "contact_type" in payload:
        payload["contact_type"] = new_type.value

    if "value" in payload and payload["value"] is not None:
        payload["value"] = payload["value"].strip()
        if new_type == ContactType.EMAIL:
            payload["value"] = validate_email_value(payload["value"])

    if "source_url" in payload:
        payload["source_url"] = blank_to_none(payload["source_url"])
        if payload["source_url"]:
            assert_safe_url(payload["source_url"])

    for field in ("label", "consent_source"):
        if field in payload:
            payload[field] = blank_to_none(payload[field])

    if "verification_status" in payload and payload["verification_status"] is not None:
        payload["verification_status"] = VerificationStatus(payload["verification_status"]).value
    if "consent_status" in payload and payload["consent_status"] is not None:
        payload["consent_status"] = ConsentStatus(payload["consent_status"]).value

    for key, value in payload.items():
        setattr(contact, key, value)

    db.commit()
    db.refresh(contact)
    return ContactRead.model_validate(contact)


def delete_contact(db: Session, contact_id: UUID) -> None:
    contact = db.get(Contact, contact_id)
    if contact is None:
        raise AppError("Contact not found.", status_code=404, code="not_found")
    db.delete(contact)
    db.commit()
