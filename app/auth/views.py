from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import schemas, services
from app.dependencies import get_current_user, get_db, openai_client

router = APIRouter()


@router.post("/signup", response_model=schemas.LoginResponse)
def signup(request: schemas.SignupRequest, db: Session = Depends(get_db)):
    try:
        return services.signup(
            request.email, request.password, request.username, request.display_name, db
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/login", response_model=schemas.LoginResponse)
def login(request: schemas.LoginRequest):
    try:
        return services.login(request.email, request.password)
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


@router.get("/me", response_model=schemas.UserResponse)
def me(user_id: str = Depends(get_current_user), db: Session = Depends(get_db)):
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
def update_profile(
    body: schemas.UpdateProfileRequest,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    profile, genres_changed = services.update_profile(user_id, updates, db)
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
