import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, get_tmdb_client
from app.groups import schemas, services
from app.groups.models import Group
from app.tracking import schemas as tracking_schemas
from app.tracking import services as watchlist_services

router = APIRouter()


@router.post("/", response_model=schemas.GroupDetailResponse)
async def create_group(
    body: schemas.CreateGroupRequest,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.create_group(user_id, body.name, db)


@router.get("/", response_model=schemas.GroupListResponse)
async def list_groups(
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.list_groups(user_id, db)


@router.get("/{group_id}", response_model=schemas.GroupDetailResponse)
async def get_group(
    group_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.get_group(group_id, user_id, db)


@router.patch("/{group_id}", response_model=schemas.GroupDetailResponse)
async def update_group(
    group_id: int,
    body: schemas.UpdateGroupRequest,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    return services.update_group(group_id, user_id, updates, db)


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    services.delete_group(group_id, user_id, db)


@router.post("/{group_id}/members", response_model=schemas.GroupDetailResponse)
async def add_member(
    group_id: int,
    body: schemas.AddMemberRequest,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.add_member(group_id, user_id, body.username, db)


@router.post(
    "/{group_id}/members/{target_user_id}/kick",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def kick_member(
    group_id: int,
    target_user_id: str,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    services.kick_member(group_id, user_id, target_user_id, db)


@router.post("/{group_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave_group(
    group_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    services.leave_group(group_id, user_id, db)


@router.get(
    "/{group_id}/recommendations",
    response_model=schemas.GroupRecommendationsResponse,
)
async def get_group_recommendations(
    group_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
):
    return services.get_group_recommendations(group_id, user_id, db, limit, offset)


# --- Group Watchlist Endpoints ---


@router.get("/{group_id}/watchlist", response_model=tracking_schemas.WatchlistResponse)
async def get_group_watchlist(
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
    return watchlist_services.get_watchlist(group.watchlist_id, db, limit, offset)


@router.post(
    "/{group_id}/watchlist",
    response_model=tracking_schemas.WatchlistMovieResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_to_group_watchlist(
    group_id: int,
    body: tracking_schemas.AddToWatchlistRequest,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    tmdb_client: httpx.AsyncClient = Depends(get_tmdb_client),
):
    services._verify_membership(group_id, user_id, db)
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group or not group.watchlist_id:
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    return await watchlist_services.add_to_watchlist(
        group.watchlist_id, body.tmdb_id, user_id, db, tmdb_client
    )


@router.delete(
    "/{group_id}/watchlist/{tmdb_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_from_group_watchlist(
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
