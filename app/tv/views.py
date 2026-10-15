import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.affiliate.services import load_where_to_watch
from app.config import settings
from app.core.rate_limit import LIMIT_DEFAULT, limiter
from app.dependencies import get_current_user, get_db, get_tmdb_client
from app.streaming.schemas import StreamingAvailabilityResponse
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


@router.get("/tv/{tmdb_id}/streaming", response_model=StreamingAvailabilityResponse)
@limiter.limit(LIMIT_DEFAULT)
async def get_tv_streaming(
    request: Request,
    tmdb_id: int,
    country: str = Query(
        default="us",
        min_length=2,
        max_length=2,
        description="ISO 3166-1 alpha-2 country code",
    ),
    _user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    tmdb_client: httpx.AsyncClient = Depends(get_tmdb_client),
) -> dict:
    """Same streaming shape as movies. options stays empty; watch data is TMDB."""
    _require_tv_support()
    country = country.lower()
    where = await load_where_to_watch(
        "tv", tmdb_id, country, db, tmdb_client, str(request.base_url)
    )
    return {
        "tmdb_id": tmdb_id,
        "country": country,
        "options": [],
        "where_to_watch": where,
    }


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
