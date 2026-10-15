import logging

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from starlette.requests import Request
from supabase_auth.errors import AuthApiError, AuthRetryableError

from app.analytics import Event, track
from app.auth import schemas, services
from app.core.rate_limit import LIMIT_DEFAULT, limiter
from app.database import SessionLocal
from app.dependencies import get_current_user, get_db, get_tmdb_client, openai_client

logger = logging.getLogger(__name__)

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


@router.get(
    "/users/by-username/{username}", response_model=schemas.PublicProfileResponse
)
@limiter.limit(LIMIT_DEFAULT)
def get_user_profile_by_username(
    request: Request,
    username: str,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.get_public_profile_by_username(user_id, username, db)


@router.post("/signup", response_model=schemas.LoginResponse)
@limiter.limit(LIMIT_DEFAULT)
def signup(
    request: Request, body: schemas.SignupRequest, db: Session = Depends(get_db)
):
    try:
        result = services.signup(
            body.email,
            body.password,
            body.username,
            body.display_name,
            db,
            phone_number=body.phone_number,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except AuthApiError as e:
        logger.warning("Supabase signup error: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.warning("Signup failed: %s", e)
        raise HTTPException(status_code=400, detail="Signup failed")
    track(result["user_id"], Event.SIGNUP_COMPLETED)
    return result


@router.post("/login", response_model=schemas.LoginResponse)
@limiter.limit(LIMIT_DEFAULT)
def login(request: Request, body: schemas.LoginRequest):
    try:
        result = services.login(body.email, body.password)
    except httpx.HTTPStatusError as e:
        if e.response.status_code >= 500:
            raise HTTPException(
                status_code=503, detail="Auth service unavailable, try again"
            )
        raise HTTPException(status_code=401, detail="Invalid credentials")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    track(result["user_id"], Event.LOGIN_COMPLETED)
    return result


@router.post("/refresh", response_model=schemas.LoginResponse)
@limiter.limit(LIMIT_DEFAULT)
def refresh(request: Request, body: schemas.RefreshRequest):
    try:
        return services.refresh_session(body.refresh_token)
    except AuthRetryableError:
        # supabase-py turns upstream 502/503/504 into AuthRetryableError
        # rather than AuthApiError. Those are transient and must not log the
        # client out.
        raise HTTPException(
            status_code=503, detail="Auth service unavailable, try again"
        )
    except AuthApiError as e:
        # Supabase rejected the call: 4xx = bad/expired refresh token (the
        # session is truly dead), 5xx = Supabase itself is having issues
        # (transient - the client must not treat it as a logout).
        if (getattr(e, "status", None) or 400) >= 500:
            raise HTTPException(
                status_code=503, detail="Auth service unavailable, try again"
            )
        raise HTTPException(status_code=401, detail="Session refresh failed")
    except httpx.HTTPStatusError as e:
        if e.response.status_code >= 500:
            raise HTTPException(
                status_code=503, detail="Auth service unavailable, try again"
            )
        raise HTTPException(status_code=401, detail="Session refresh failed")
    except httpx.RequestError:
        # Network-level failure reaching Supabase (cold start, timeout, DNS).
        # Transient: report 503 so clients keep the session and retry.
        raise HTTPException(
            status_code=503, detail="Auth service unavailable, try again"
        )
    except Exception:
        raise HTTPException(status_code=401, detail="Session refresh failed")


@router.post("/forgot-password", response_model=schemas.MessageResponse)
@limiter.limit(LIMIT_DEFAULT)
def forgot_password(request: Request, body: schemas.ForgotPasswordRequest):
    try:
        services.forgot_password(body.email)
    except Exception:
        pass
    return {
        "message": "If an account exists with that email, a reset link has been sent"
    }


@router.post("/reset-password", response_model=schemas.MessageResponse)
@limiter.limit(LIMIT_DEFAULT)
def reset_password(
    request: Request,
    body: schemas.ResetPasswordRequest,
    user_id: str = Depends(get_current_user),
):
    try:
        services.reset_password(user_id, body.new_password)
    except Exception:
        raise HTTPException(status_code=400, detail="Password reset failed")
    return {"message": "Password updated successfully"}


@router.post("/change-password", response_model=schemas.MessageResponse)
@limiter.limit(LIMIT_DEFAULT)
def change_password(
    request: Request,
    body: schemas.ChangePasswordRequest,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    services.change_password(user_id, body.current_password, body.new_password, db)
    return {"message": "Password changed successfully"}


@router.post("/oauth", response_model=schemas.OAuthResponse)
@limiter.limit(LIMIT_DEFAULT)
async def oauth_login_view(
    request: Request, body: schemas.OAuthRequest, db: Session = Depends(get_db)
):
    try:
        return await services.oauth_login(
            body.provider, body.id_token, body.nonce, db, body.authorization_code
        )
    except AuthApiError:
        raise HTTPException(status_code=401, detail="Invalid or expired provider token")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPStatusError as e:
        if e.response.status_code >= 500:
            raise HTTPException(
                status_code=503, detail="Auth service unavailable, try again"
            )
        raise HTTPException(status_code=400, detail="OAuth login failed")
    except Exception:
        raise HTTPException(status_code=400, detail="OAuth login failed")


@router.post("/complete-onboarding", response_model=schemas.CompleteOnboardingResponse)
@limiter.limit(LIMIT_DEFAULT)
async def complete_onboarding_view(
    request: Request,
    body: schemas.CompleteOnboardingRequest,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    tmdb_client: httpx.AsyncClient = Depends(get_tmdb_client),
):
    try:
        result = await services.complete_onboarding(
            user_id,
            body.username,
            body.display_name,
            body.favorite_genres,
            [{"tmdb_id": m.tmdb_id, "rating": m.rating} for m in body.rated_movies]
            if body.rated_movies
            else None,
            db,
            tmdb_client,
            apple_refresh_token=body.apple_refresh_token,
            phone_number=body.phone_number,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=400, detail="Onboarding failed")

    # Always seed a taste profile so the user lands in the app with FYP ready.
    # Uses the rating-weighted average if they rated movies, otherwise falls
    # back to a genre-seeded embedding (or global top if no genres).
    from app.recommendations.services import rebuild_taste_profile

    try:
        rebuild_taste_profile(user_id, db, openai_client)
    except Exception:
        # Non-critical — user can still enter the app, FYP will be empty until
        # they interact. Rollback any partial profile changes so signup succeeds.
        db.rollback()

    track(user_id, Event.ONBOARDING_COMPLETED)
    return result


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
        phone_number=profile.phone_number,
        subscription_tier=profile.subscription_tier,
        subscription_expires_at=profile.subscription_expires_at,
    )


@router.get("/me/taste", response_model=schemas.GenreTasteResponse)
@limiter.limit(LIMIT_DEFAULT)
def get_taste(
    request: Request,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.get_genre_taste(user_id, db)


@router.patch("/profile", response_model=schemas.UserResponse)
@limiter.limit(LIMIT_DEFAULT)
def update_profile(
    request: Request,
    body: schemas.UpdateProfileRequest,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not body.model_fields_set:
        raise HTTPException(status_code=400, detail="No fields to update")

    try:
        profile, genres_changed = services.update_profile(user_id, body, db)
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
            except Exception:
                bg_db.rollback()
                raise
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
        phone_number=profile.phone_number,
        subscription_tier=profile.subscription_tier,
        subscription_expires_at=profile.subscription_expires_at,
    )


@router.delete("/account", status_code=204)
@limiter.limit(LIMIT_DEFAULT)
def delete_account(
    request: Request,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    track(user_id, Event.ACCOUNT_DELETED)
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
    q: str | None = Query(default=None, max_length=100),
    sort: str | None = Query(default=None),
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.get_public_watched(user_id, id, limit, offset, db, q=q, sort=sort)


@router.get("/users/{id}/friends", response_model=schemas.PublicFriendsListResponse)
@limiter.limit(LIMIT_DEFAULT)
def get_user_friends(
    request: Request,
    id: str,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.get_public_friends(user_id, id, db)


@router.get("/users/{id}/taste", response_model=schemas.GenreTasteResponse)
@limiter.limit(LIMIT_DEFAULT)
def get_user_taste(
    request: Request,
    id: str,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.get_public_taste(user_id, id, db)
