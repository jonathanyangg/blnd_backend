from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.auth import schemas, services
from app.core.rate_limit import LIMIT_DEFAULT, limiter
from app.database import SessionLocal
from app.dependencies import get_current_user, get_db, openai_client

router = APIRouter()


@router.get("/users/search", response_model=schemas.UserSearchResponse)
@limiter.limit(LIMIT_DEFAULT)
def search_users(
    request: Request,
    q: str = Query(min_length=1, max_length=30),
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    results = services.search_users(q, user_id, db)
    return {"results": results}


@router.post("/signup", response_model=schemas.LoginResponse)
@limiter.limit(LIMIT_DEFAULT)
def signup(
    request: Request, body: schemas.SignupRequest, db: Session = Depends(get_db)
):
    try:
        return services.signup(
            body.email, body.password, body.username, body.display_name, db
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=400, detail="Signup failed")


@router.post("/login", response_model=schemas.LoginResponse)
@limiter.limit(LIMIT_DEFAULT)
def login(request: Request, body: schemas.LoginRequest):
    try:
        return services.login(body.email, body.password)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid credentials")


@router.post("/refresh", response_model=schemas.LoginResponse)
@limiter.limit(LIMIT_DEFAULT)
def refresh(request: Request, body: schemas.RefreshRequest):
    try:
        return services.refresh_session(body.refresh_token)
    except Exception:
        raise HTTPException(status_code=401, detail="Session refresh failed")


@router.get("/me", response_model=schemas.UserResponse)
@limiter.limit(LIMIT_DEFAULT)
def me(
    request: Request,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = services.get_profile(user_id, db)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return schemas.UserResponse(
        id=str(profile.id),
        username=profile.username,
        display_name=profile.display_name,
        avatar_url=profile.avatar_url,
        taste_bio=profile.taste_bio,
        favorite_genres=profile.favorite_genres or [],
    )


@router.patch("/profile", response_model=schemas.UserResponse)
@limiter.limit(LIMIT_DEFAULT)
def update_profile(
    request: Request,
    body: schemas.UpdateProfileRequest,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    try:
        profile, genres_changed = services.update_profile(user_id, updates, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    if genres_changed:
        from app.recommendations.services import rebuild_taste_profile

        def _rebuild_in_background() -> None:
            bg_db = SessionLocal()
            try:
                rebuild_taste_profile(user_id, bg_db, openai_client)
            finally:
                bg_db.close()

        background_tasks.add_task(_rebuild_in_background)

    return schemas.UserResponse(
        id=str(profile.id),
        username=profile.username,
        display_name=profile.display_name,
        avatar_url=profile.avatar_url,
        taste_bio=profile.taste_bio,
        favorite_genres=profile.favorite_genres or [],
    )


@router.delete("/account", status_code=204)
@limiter.limit(LIMIT_DEFAULT)
def delete_account(
    request: Request,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    services.delete_account(user_id, db)


@router.get("/users/{id}/profile", response_model=schemas.PublicProfileResponse)
@limiter.limit(LIMIT_DEFAULT)
def get_user_profile(
    request: Request,
    id: str,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.get_public_profile(user_id, id, db)


@router.get("/users/{id}/watched", response_model=schemas.PublicWatchedListResponse)
@limiter.limit(LIMIT_DEFAULT)
def get_user_watched(
    request: Request,
    id: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.get_public_watched(user_id, id, limit, offset, db)


@router.get("/users/{id}/friends", response_model=schemas.PublicFriendsListResponse)
@limiter.limit(LIMIT_DEFAULT)
def get_user_friends(
    request: Request,
    id: str,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.get_public_friends(user_id, id, db)
