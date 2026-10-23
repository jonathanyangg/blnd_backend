import httpx
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.affiliate.services import load_where_to_watch, offer_base
from app.core.rate_limit import LIMIT_DEFAULT, limiter
from app.dependencies import (
    get_current_user,
    get_db,
    get_streaming_client,
    get_tmdb_client,
)
from app.streaming import schemas, services

router = APIRouter()


@router.get(
    "/{tmdb_id}/streaming", response_model=schemas.StreamingAvailabilityResponse
)
@limiter.limit(LIMIT_DEFAULT)
async def get_streaming_availability(
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
    streaming_client: httpx.AsyncClient = Depends(get_streaming_client),
    tmdb_client: httpx.AsyncClient = Depends(get_tmdb_client),
):
    country = country.lower()
    result = await services.get_streaming_options(
        tmdb_id, country, db, streaming_client
    )
    result["where_to_watch"] = await load_where_to_watch(
        "movie", tmdb_id, country, db, tmdb_client, offer_base(request)
    )
    return result
