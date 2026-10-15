import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.config import settings
from app.core.rate_limit import LIMIT_DEFAULT, limiter
from app.dependencies import get_current_user, get_db, get_tmdb_client
from app.tv import schemas, services

router = APIRouter()


def _require_tv_support() -> None:
    if not settings.tv_support_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.get("/tv/search", response_model=schemas.TVSearchResult)
@limiter.limit(LIMIT_DEFAULT)
async def search_tv_shows(
    request: Request,
    query: str = Query(min_length=1),
    page: int = Query(default=1, ge=1, le=500),
    _user_id: str = Depends(get_current_user),
    tmdb_client: httpx.AsyncClient = Depends(get_tmdb_client),
) -> dict:
    _require_tv_support()
    return await services.search_tv_shows(query, page, tmdb_client)


@router.post(
    "/tracking/tv/{tmdb_id}",
    response_model=schemas.WatchedTVShowResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit(LIMIT_DEFAULT)
async def track_tv_show(
    request: Request,
    tmdb_id: int,
    body: schemas.TrackTVShowRequest,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    tmdb_client: httpx.AsyncClient = Depends(get_tmdb_client),
) -> dict:
    _require_tv_support()
    return await services.track_tv_show(
        user_id=user_id,
        tmdb_id=tmdb_id,
        rating=body.rating,
        review=body.review,
        watched_date=body.watched_date,
        source=body.source,
        db=db,
        tmdb_client=tmdb_client,
    )
