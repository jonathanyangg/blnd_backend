from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.auth import schemas, services
from app.core.rate_limit import LIMIT_DEFAULT, limiter
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
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/login", response_model=schemas.LoginResponse)
@limiter.limit(LIMIT_DEFAULT)
def login(request: Request, body: schemas.LoginRequest):
    try:
        return services.login(body.email, body.password)
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


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

        background_tasks.add_task(rebuild_taste_profile, user_id, db, openai_client)

    return schemas.UserResponse(
        id=str(profile.id),
        username=profile.username,
        display_name=profile.display_name,
        avatar_url=profile.avatar_url,
        taste_bio=profile.taste_bio,
        favorite_genres=profile.favorite_genres or [],
    )
