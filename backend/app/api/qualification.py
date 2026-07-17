from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.qualification import QualificationRunCreate, QualificationRunRead
from app.services import qualification_service

router = APIRouter(prefix="/qualification", tags=["qualification"])


@router.post("/runs", response_model=QualificationRunRead, status_code=201)
def create_qualification_run(
    payload: QualificationRunCreate,
    db: Session = Depends(get_db),
) -> QualificationRunRead:
    """Start Stage 3 qualification (deterministic scoring, no email)."""
    return qualification_service.start_qualification(db, payload)


@router.get("/runs/{run_id}", response_model=QualificationRunRead)
def get_qualification_run(run_id: UUID, db: Session = Depends(get_db)) -> QualificationRunRead:
    return qualification_service.get_qualification_run(db, run_id)
