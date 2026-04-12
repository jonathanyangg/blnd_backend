import asyncio

import httpx
from aioapns import APNs
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.auth.models import Profile
from app.core.rate_limit import LIMIT_DEFAULT, limiter
from app.database import SessionLocal
from app.dependencies import get_apns_client, get_current_user, get_db, get_tmdb_client
from app.groups import schemas, services
from app.groups.models import Group, GroupMember
from app.movies.models import Movie
from app.notifications import services as notification_services
from app.notifications.services import THREAD_GROUP_ACTIVITY, THREAD_GROUP_INVITES
from app.tracking import schemas as tracking_schemas
from app.tracking import services as watchlist_services
from app.tracking.services import record_activity

router = APIRouter()


@router.post("/", response_model=schemas.GroupDetailResponse)
@limiter.limit(LIMIT_DEFAULT)
async def create_group(
    request: Request,
    body: schemas.CreateGroupRequest,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.create_group(user_id, body.name, db)


@router.get("/", response_model=schemas.GroupListResponse)
@limiter.limit(LIMIT_DEFAULT)
async def list_groups(
    request: Request,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.list_groups(user_id, db)


@router.get("/{group_id}", response_model=schemas.GroupDetailResponse)
@limiter.limit(LIMIT_DEFAULT)
async def get_group(
    request: Request,
    group_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.get_group(group_id, user_id, db)


@router.patch("/{group_id}", response_model=schemas.GroupDetailResponse)
@limiter.limit(LIMIT_DEFAULT)
async def update_group(
    request: Request,
    group_id: int,
    body: schemas.UpdateGroupRequest,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not body.model_fields_set:
        raise HTTPException(status_code=400, detail="No fields to update")
    return services.update_group(group_id, user_id, body, db)


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(LIMIT_DEFAULT)
async def delete_group(
    request: Request,
    group_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    services.delete_group(group_id, user_id, db)


@router.post("/{group_id}/members", response_model=schemas.GroupDetailResponse)
@limiter.limit(LIMIT_DEFAULT)
async def add_member(
    request: Request,
    group_id: int,
    body: schemas.AddMemberRequest,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    apns_client: APNs | None = Depends(get_apns_client),
):
    result = services.add_member(group_id, user_id, body.username, db)

    # Gather data for notification (within request scope)
    target_profile = db.query(Profile).filter(Profile.username == body.username).first()
    adder_profile = db.query(Profile).filter(Profile.id == user_id).first()
    group_name = result.get("name", "a group")

    if target_profile and adder_profile:
        target_id = str(target_profile.id)
        adder_username = adder_profile.username or "Someone"

        async def _send_group_invite_push() -> None:
            bg_db = SessionLocal()
            try:
                await notification_services.send_push(
                    user_id=target_id,
                    notification_type="group_invites",
                    title="Added to Group",
                    body=f"{adder_username} added you to {group_name}",
                    data={"type": "group_invite", "group_id": str(group_id)},
                    db=bg_db,
                    apns_client=apns_client,
                    thread_id=THREAD_GROUP_INVITES,
                )
            except Exception:
                pass  # Fire-and-forget; send_push logs its own errors
            finally:
                bg_db.close()

        asyncio.ensure_future(_send_group_invite_push())

    return result


@router.post(
    "/{group_id}/members/{target_user_id}/kick",
    status_code=status.HTTP_204_NO_CONTENT,
)
@limiter.limit(LIMIT_DEFAULT)
async def kick_member(
    request: Request,
    group_id: int,
    target_user_id: str,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    services.kick_member(group_id, user_id, target_user_id, db)


@router.post("/{group_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(LIMIT_DEFAULT)
async def leave_group(
    request: Request,
    group_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    services.leave_group(group_id, user_id, db)


@router.get(
    "/{group_id}/recommendations",
    response_model=schemas.GroupRecommendationsResponse,
)
@limiter.limit(LIMIT_DEFAULT)
async def get_group_recommendations(
    request: Request,
    group_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
):
    return services.get_group_recommendations(group_id, user_id, db, limit, offset)


@router.post(
    "/{group_id}/recommendations/feed",
    response_model=schemas.GroupRecommendationsResponse,
)
@limiter.limit(LIMIT_DEFAULT)
async def get_group_feed(
    request: Request,
    group_id: int,
    body: schemas.GroupFeedRequest,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Infinite scroll feed for group recommendations with exclude list."""
    return services.get_group_recommendations(
        group_id, user_id, db, body.limit, 0, extra_exclude=body.exclude
    )


# --- Group Watchlist Endpoints ---


@router.get("/{group_id}/watchlist", response_model=tracking_schemas.WatchlistResponse)
@limiter.limit(LIMIT_DEFAULT)
async def get_group_watchlist(
    request: Request,
    group_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    services._verify_membership(group_id, user_id, db)
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group or not group.watchlist_id:
        return {"results": [], "total": 0}
    data = watchlist_services.get_watchlist(group.watchlist_id, db, limit, offset)
    # Inject group match scores
    tmdb_ids = [r["tmdb_id"] for r in data["results"]]
    if tmdb_ids:
        scores = services.compute_group_match_scores(group_id, tmdb_ids, db)
        for r in data["results"]:
            r["match_score"] = scores.get(r["tmdb_id"])
    return data


@router.post(
    "/{group_id}/watchlist",
    response_model=tracking_schemas.WatchlistMovieResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(LIMIT_DEFAULT)
async def add_to_group_watchlist(
    request: Request,
    group_id: int,
    body: tracking_schemas.AddToWatchlistRequest,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    tmdb_client: httpx.AsyncClient = Depends(get_tmdb_client),
    apns_client: APNs | None = Depends(get_apns_client),
):
    services._verify_membership(group_id, user_id, db)
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group or not group.watchlist_id:
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    result = await watchlist_services.add_to_watchlist(
        group.watchlist_id, body.tmdb_id, user_id, db, tmdb_client, body.source
    )

    # Record activity
    record_activity(user_id, "watchlisted", body.tmdb_id, db)

    # Notify other group members
    adder_profile = db.query(Profile).filter(Profile.id == user_id).first()
    movie = db.query(Movie).filter(Movie.tmdb_id == body.tmdb_id).first()
    group_name = group.name or "a blend"
    adder_name = adder_profile.username if adder_profile else "Someone"
    movie_title = movie.title if movie else "a movie"

    member_ids = [
        str(m.user_id)
        for m in db.query(GroupMember).filter(GroupMember.group_id == group_id).all()
        if str(m.user_id) != user_id
    ]

    if member_ids:

        async def _send_watchlist_push() -> None:
            bg_db = SessionLocal()
            try:
                for mid in member_ids:
                    await notification_services.send_push(
                        user_id=mid,
                        notification_type="group_invites",
                        title=group_name,
                        body=f"{adder_name} added {movie_title} to the watchlist",
                        data={
                            "type": "group_watchlist",
                            "group_id": str(group_id),
                            "tmdb_id": str(body.tmdb_id),
                        },
                        db=bg_db,
                        apns_client=apns_client,
                        thread_id=THREAD_GROUP_ACTIVITY,
                    )
            except Exception:
                pass
            finally:
                bg_db.close()

        asyncio.ensure_future(_send_watchlist_push())

    return result


@router.delete(
    "/{group_id}/watchlist/{tmdb_id}", status_code=status.HTTP_204_NO_CONTENT
)
@limiter.limit(LIMIT_DEFAULT)
async def remove_from_group_watchlist(
    request: Request,
    group_id: int,
    tmdb_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    services._verify_membership(group_id, user_id, db)
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group or not group.watchlist_id:
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    watchlist_services.remove_from_watchlist(group.watchlist_id, tmdb_id, db)
