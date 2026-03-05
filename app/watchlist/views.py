import httpx
from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.auth.models import Profile
from app.dependencies import get_current_user, get_db, get_tmdb_client
from app.tracking import schemas, services

router = APIRouter()


@router.get("/", response_model=schemas.WatchlistResponse)
async def get_watchlist(
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    profile = db.query(Profile).filter(Profile.id == user_id).first()
    if not profile or not profile.watchlist_id:
        return {"results": [], "total": 0}
    return services.get_watchlist(profile.watchlist_id, db, limit, offset)


@router.post(
    "/",
    response_model=schemas.WatchlistMovieResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_to_watchlist(
    body: schemas.AddToWatchlistRequest,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    tmdb_client: httpx.AsyncClient = Depends(get_tmdb_client),
):
    profile = db.query(Profile).filter(Profile.id == user_id).first()
    if not profile or not profile.watchlist_id:
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    return await services.add_to_watchlist(
        profile.watchlist_id, body.tmdb_id, user_id, db, tmdb_client, body.source
    )


@router.delete("/{tmdb_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_from_watchlist(
    tmdb_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = db.query(Profile).filter(Profile.id == user_id).first()
    if not profile or not profile.watchlist_id:
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    services.remove_from_watchlist(profile.watchlist_id, tmdb_id, db)
