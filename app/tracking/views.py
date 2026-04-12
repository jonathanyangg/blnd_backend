import asyncio

import httpx
from aioapns import APNs
from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.core.rate_limit import LIMIT_DEFAULT, limiter
from app.database import SessionLocal
from app.dependencies import (
    get_apns_client,
    get_current_user,
    get_db,
    get_tmdb_client,
    openai_client,
)
from app.notifications import services as notification_services
from app.recommendations.services import increment_action_counter, rebuild_taste_profile
from app.tracking import schemas, services
from app.tracking.models import WatchedMovie

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
    apns_client: APNs | None = Depends(get_apns_client),
):
    # Check if movie already tracked (for notification threshold)
    existing_entry = (
        db.query(WatchedMovie)
        .filter(WatchedMovie.user_id == user_id, WatchedMovie.tmdb_id == body.tmdb_id)
        .first()
    )
    was_already_tracked = existing_entry is not None
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

    # Only notify on NEW trackings with rating >= 4.0 (not upserts)
    if not was_already_tracked and body.rating is not None and body.rating >= 4.0:
        rating_val = body.rating
        tmdb_id_val = body.tmdb_id

        async def _notify_rating() -> None:
            bg_db = SessionLocal()
            try:
                await notification_services.notify_friends_of_rating(
                    user_id=user_id,
                    rating=rating_val,
                    tmdb_id=tmdb_id_val,
                    db=bg_db,
                    apns_client=apns_client,
                    previous_rating=None,  # New entry, no previous
                )
            except Exception:
                pass  # Fire-and-forget
            finally:
                bg_db.close()

        asyncio.ensure_future(_notify_rating())

    return result


@router.get("/", response_model=schemas.WatchHistoryResponse)
@limiter.limit(LIMIT_DEFAULT)
async def get_watch_history(
    request: Request,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    return services.get_watch_history(user_id, limit, offset, db)


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
    apns_client: APNs | None = Depends(get_apns_client),
):
    # Read current rating for threshold crossing detection
    current_entry = (
        db.query(WatchedMovie)
        .filter(WatchedMovie.user_id == user_id, WatchedMovie.tmdb_id == tmdb_id)
        .first()
    )
    previous_rating = current_entry.rating if current_entry else None

    result = services.update_watched_movie(user_id, tmdb_id, body, db)

    # Only trigger notification if rating was explicitly set AND >= 4.0
    new_rating = body.rating if "rating" in body.model_fields_set else None
    if new_rating is not None and new_rating >= 4.0:

        async def _notify_rating_update() -> None:
            bg_db = SessionLocal()
            try:
                await notification_services.notify_friends_of_rating(
                    user_id=user_id,
                    rating=new_rating,
                    tmdb_id=tmdb_id,
                    db=bg_db,
                    apns_client=apns_client,
                    previous_rating=previous_rating,
                )
            except Exception:
                pass  # Fire-and-forget
            finally:
                bg_db.close()

        asyncio.ensure_future(_notify_rating_update())

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
