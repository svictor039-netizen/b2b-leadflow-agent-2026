from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.enums import CompanyStatus
from app.schemas.company import (
    CompanyCreate,
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
from app.services import company_service

router = APIRouter(tags=["companies"])


@router.post("/companies", response_model=CompanyRead, status_code=status.HTTP_201_CREATED)
def create_company(payload: CompanyCreate, db: Session = Depends(get_db)) -> CompanyRead:
    return company_service.create_company(db, payload)


@router.get("/companies", response_model=CompanyListResponse)
def list_companies(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None, max_length=200),
    status_filter: CompanyStatus | None = Query(None, alias="status"),
    city: str | None = Query(None, max_length=200),
    db: Session = Depends(get_db),
) -> CompanyListResponse:
    return company_service.list_companies(
        db,
        page=page,
        page_size=page_size,
        search=search,
        status=status_filter,
        city=city,
    )


@router.get("/companies/{company_id}", response_model=CompanyRead)
def get_company(company_id: UUID, db: Session = Depends(get_db)) -> CompanyRead:
    return company_service.get_company(db, company_id)


@router.patch("/companies/{company_id}", response_model=CompanyRead)
def update_company(
    company_id: UUID,
    payload: CompanyUpdate,
    db: Session = Depends(get_db),
) -> CompanyRead:
    return company_service.update_company(db, company_id, payload)


@router.post(
    "/companies/{company_id}/locations",
    response_model=LocationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_location(
    company_id: UUID,
    payload: LocationCreate,
    db: Session = Depends(get_db),
) -> LocationRead:
    return company_service.create_location(db, company_id, payload)


@router.patch("/locations/{location_id}", response_model=LocationRead)
def update_location(
    location_id: UUID,
    payload: LocationUpdate,
    db: Session = Depends(get_db),
) -> LocationRead:
    return company_service.update_location(db, location_id, payload)


@router.delete(
    "/locations/{location_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_location(location_id: UUID, db: Session = Depends(get_db)) -> Response:
    company_service.delete_location(db, location_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/companies/{company_id}/contacts",
    response_model=ContactRead,
    status_code=status.HTTP_201_CREATED,
)
def create_contact(
    company_id: UUID,
    payload: ContactCreate,
    db: Session = Depends(get_db),
) -> ContactRead:
    return company_service.create_contact(db, company_id, payload)


@router.patch("/contacts/{contact_id}", response_model=ContactRead)
def update_contact(
    contact_id: UUID,
    payload: ContactUpdate,
    db: Session = Depends(get_db),
) -> ContactRead:
    return company_service.update_contact(db, contact_id, payload)


@router.delete(
    "/contacts/{contact_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_contact(contact_id: UUID, db: Session = Depends(get_db)) -> Response:
    company_service.delete_contact(db, contact_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
