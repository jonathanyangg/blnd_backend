from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from starlette import status
from starlette.requests import Request

from app.actors import schemas, services
from app.core.rate_limit import LIMIT_DEFAULT, limiter
from app.dependencies import get_current_user, get_db

router = APIRouter()


@router.post("/{person_id}/like", response_model=schemas.LikedActorResponse)
@limiter.limit(LIMIT_DEFAULT)
def like_actor(
    request: Request,
    person_id: int,
    body: schemas.LikeActorRequest,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    liked = services.like_actor(user_id, person_id, body.name, body.profile_path, db)
    return {
        "tmdb_person_id": liked.tmdb_person_id,
        "name": liked.name,
        "profile_path": liked.profile_path,
        "liked_at": liked.created_at.isoformat(),
    }


@router.delete("/{person_id}/like", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(LIMIT_DEFAULT)
def unlike_actor(
    request: Request,
    person_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    deleted = services.unlike_actor(user_id, person_id, db)
    if not deleted:
        raise HTTPException(status_code=404, detail="Actor not liked")


@router.get("/liked", response_model=schemas.LikedActorsListResponse)
@limiter.limit(LIMIT_DEFAULT)
def list_liked_actors(
    request: Request,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return services.get_liked_actors(user_id, db, limit, offset)
