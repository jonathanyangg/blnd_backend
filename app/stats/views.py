from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.core.rate_limit import LIMIT_DEFAULT, limiter
from app.dependencies import get_db, require_premium
from app.stats import schemas, services

router = APIRouter()


@router.get("/year/{year}", response_model=schemas.YearInReviewResponse)
@limiter.limit(LIMIT_DEFAULT)
def get_year_in_review(
    request: Request,
    year: int = Path(ge=1970, le=2100),
    user_id: str = Depends(require_premium),
    db: Session = Depends(get_db),
):
    return services.year_in_review(user_id, year, db)


@router.get("/genres", response_model=schemas.GenreBreakdownResponse)
@limiter.limit(LIMIT_DEFAULT)
def get_genre_breakdown(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    user_id: str = Depends(require_premium),
    db: Session = Depends(get_db),
):
    return services.genre_breakdown(user_id, db, limit)


@router.get("/directors", response_model=schemas.DirectorBreakdownResponse)
@limiter.limit(LIMIT_DEFAULT)
def get_director_breakdown(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    user_id: str = Depends(require_premium),
    db: Session = Depends(get_db),
):
    return services.director_breakdown(user_id, db, limit)


@router.get("/match/{other_id}", response_model=schemas.MatchResponse)
@limiter.limit(LIMIT_DEFAULT)
def get_match(
    request: Request,
    other_id: UUID,
    user_id: str = Depends(require_premium),
    db: Session = Depends(get_db),
):
    return services.match_with(user_id, str(other_id), db)
