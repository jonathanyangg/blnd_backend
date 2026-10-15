import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.core.rate_limit import LIMIT_DEFAULT, limiter
from app.database import SessionLocal
from app.dependencies import (
    get_current_user,
    get_db,
    get_tmdb_client,
    openai_client,
)
from app.analytics import Event, track
from app.recommendations.services import increment_action_counter, rebuild_taste_profile
from app.tracking import schemas, services

router = APIRouter()


@router.post("/", response_model=schemas.WatchedMovieResponse)
@limiter.limit(LIMIT_DEFAULT)
async def track_movie(
    request: Request,
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
        watched_with=body.watched_with,
    )
    track(
        user_id,
        Event.MOVIE_RATED,
        {"tmdb_id": body.tmdb_id, "rating": body.rating, "source": body.source},
    )
    if increment_action_counter(user_id, db):

        def _rebuild() -> None:
            bg_db = SessionLocal()
            try:
                rebuild_taste_profile(user_id, bg_db, openai_client)
            except Exception:
                bg_db.rollback()
                raise
            finally:
                bg_db.close()

        background_tasks.add_task(_rebuild)

    # Write to friends' inboxes (ratings only)
    if body.rating is not None:
        from app.notifications.services import fire_notification_to_friends

        fire_notification_to_friends(
            user_id, "rated", body.tmdb_id, db, rating=body.rating
        )

    return result


@router.get("/", response_model=schemas.WatchHistoryResponse)
@limiter.limit(LIMIT_DEFAULT)
async def get_watch_history(
    request: Request,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    q: str | None = Query(default=None, max_length=100),
    sort: str | None = Query(default=None),
):
    return services.get_watch_history(user_id, limit, offset, db, q=q, sort=sort)


@router.get("/{tmdb_id}/friends", response_model=schemas.FriendsWhoWatchedResponse)
@limiter.limit(LIMIT_DEFAULT)
async def get_friends_who_watched(
    request: Request,
    tmdb_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return services.get_friends_who_watched(user_id, tmdb_id, db, limit, offset)


@router.get("/{tmdb_id}", response_model=schemas.WatchedMovieResponse | None)
@limiter.limit(LIMIT_DEFAULT)
async def get_watched_movie(
    request: Request,
    tmdb_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.get_watched_movie(user_id, tmdb_id, db)


@router.patch("/{tmdb_id}", response_model=schemas.WatchedMovieResponse)
@limiter.limit(LIMIT_DEFAULT)
async def update_watched_movie(
    request: Request,
    tmdb_id: int,
    body: schemas.UpdateTrackingRequest,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = services.update_watched_movie(user_id, tmdb_id, body, db)
    return result


@router.delete("/{tmdb_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(LIMIT_DEFAULT)
async def delete_watched_movie(
    request: Request,
    tmdb_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    services.delete_watched_movie(user_id, tmdb_id, db)
