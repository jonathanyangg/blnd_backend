import httpx
from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, get_tmdb_client
from app.tracking import schemas, services

router = APIRouter()


@router.post("/", response_model=schemas.WatchedMovieResponse)
async def track_movie(
    body: schemas.TrackMovieRequest,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    tmdb_client: httpx.AsyncClient = Depends(get_tmdb_client),
):
    return await services.track_movie(
        user_id=user_id,
        tmdb_id=body.tmdb_id,
        rating=body.rating,
        review=body.review,
        watched_date=body.watched_date,
        db=db,
        tmdb_client=tmdb_client,
    )


@router.get("/", response_model=schemas.WatchHistoryResponse)
async def get_watch_history(
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return services.get_watch_history(user_id, limit, offset, db)


@router.get("/{tmdb_id}", response_model=schemas.WatchedMovieResponse)
async def get_watched_movie(
    tmdb_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = services.get_watched_movie(user_id, tmdb_id, db)
    if not result:
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    return result


@router.patch("/{tmdb_id}", response_model=schemas.WatchedMovieResponse)
async def update_watched_movie(
    tmdb_id: int,
    body: schemas.UpdateTrackingRequest,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.update_watched_movie(user_id, tmdb_id, body, db)


@router.delete("/{tmdb_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watched_movie(
    tmdb_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    services.delete_watched_movie(user_id, tmdb_id, db)
