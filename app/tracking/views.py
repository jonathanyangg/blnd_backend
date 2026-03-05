import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.auth.models import Profile
from app.dependencies import get_current_user, get_db, get_tmdb_client, openai_client
from app.tracking import schemas, services

router = APIRouter()


def _trigger_taste_rebuild(
    background_tasks: BackgroundTasks, user_id: str, db: Session
) -> None:
    from app.recommendations.services import rebuild_taste_profile

    background_tasks.add_task(rebuild_taste_profile, user_id, db, openai_client)


@router.post("/", response_model=schemas.WatchedMovieResponse)
async def track_movie(
    body: schemas.TrackMovieRequest,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    tmdb_client: httpx.AsyncClient = Depends(get_tmdb_client),
):
    result = await services.track_movie(
        user_id=user_id,
        tmdb_id=body.tmdb_id,
        rating=body.rating,
        review=body.review,
        watched_date=body.watched_date,
        db=db,
        tmdb_client=tmdb_client,
        source=body.source,
    )
    if body.rating is not None:
        _trigger_taste_rebuild(background_tasks, user_id, db)
    return result


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
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = services.update_watched_movie(user_id, tmdb_id, body, db)
    if body.rating is not None:
        _trigger_taste_rebuild(background_tasks, user_id, db)
    return result


@router.delete("/{tmdb_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watched_movie(
    tmdb_id: int,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    services.delete_watched_movie(user_id, tmdb_id, db)
    _trigger_taste_rebuild(background_tasks, user_id, db)


# --- Watchlist Endpoints ---


@router.get("/watchlist", response_model=schemas.WatchlistResponse)
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
    "/watchlist",
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


@router.delete("/watchlist/{tmdb_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_from_watchlist(
    tmdb_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = db.query(Profile).filter(Profile.id == user_id).first()
    if not profile or not profile.watchlist_id:
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    services.remove_from_watchlist(profile.watchlist_id, tmdb_id, db)
