from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.research import ResearchRunCreate, ResearchRunRead
from app.services import research_service

router = APIRouter(prefix="/research", tags=["research"])


@router.post("/runs", response_model=ResearchRunRead, status_code=201)
def create_research_run(
    payload: ResearchRunCreate,
    db: Session = Depends(get_db),
) -> ResearchRunRead:
    """Start a Stage 2 test research run (TestSourceAdapter only)."""
    return research_service.start_research(db, payload)


@router.get("/runs", response_model=list[ResearchRunRead])
def list_research_runs(
    status: str | None = Query(None, max_length=32),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[ResearchRunRead]:
    """List research runs (used by Stage 3 qualification UI)."""
    return research_service.list_research_runs(db, status=status, limit=limit)


@router.get("/runs/{run_id}", response_model=ResearchRunRead)
def get_research_run(run_id: UUID, db: Session = Depends(get_db)) -> ResearchRunRead:
    return research_service.get_research_run(db, run_id)
