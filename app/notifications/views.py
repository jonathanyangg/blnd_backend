"""Notification domain endpoints: device token CRUD, notification preferences, digest."""

import asyncio

from aioapns import APNs
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session
from starlette.requests import Request
from starlette.responses import Response

from app.config import settings
from app.core.rate_limit import LIMIT_DEFAULT, LIMIT_HEAVY, limiter
from app.dependencies import get_apns_client, get_current_user, get_db
from app.notifications import schemas, services

router = APIRouter()


@router.post("/device", response_model=schemas.MessageResponse)
@limiter.limit(LIMIT_DEFAULT)
async def register_device(
    request: Request,
    body: schemas.RegisterDeviceRequest,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.MessageResponse:
    services.register_device(user_id, body.token, body.platform, db)
    return schemas.MessageResponse(message="Device registered")


@router.delete("/device", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(LIMIT_DEFAULT)
async def unregister_device(
    request: Request,
    body: schemas.RegisterDeviceRequest,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    services.unregister_device(user_id, body.token, db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/preferences", response_model=schemas.PreferencesResponse)
@limiter.limit(LIMIT_DEFAULT)
async def get_preferences(
    request: Request,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.PreferencesResponse:
    pref = services.get_or_create_preferences(user_id, db)
    return schemas.PreferencesResponse(
        friend_requests=pref.friend_requests,
        group_invites=pref.group_invites,
        recommendations=pref.recommendations,
        friend_activity=pref.friend_activity,
    )


@router.patch("/preferences", response_model=schemas.PreferencesResponse)
@limiter.limit(LIMIT_DEFAULT)
async def update_preferences(
    request: Request,
    body: schemas.UpdatePreferencesRequest,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.PreferencesResponse:
    pref = services.update_preferences(user_id, body.model_dump(exclude_none=True), db)
    return schemas.PreferencesResponse(
        friend_requests=pref.friend_requests,
        group_invites=pref.group_invites,
        recommendations=pref.recommendations,
        friend_activity=pref.friend_activity,
    )


@router.post("/badge/reset", response_model=schemas.MessageResponse)
@limiter.limit(LIMIT_DEFAULT)
async def reset_badge(
    request: Request,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.MessageResponse:
    services.reset_badge(user_id, db)
    return schemas.MessageResponse(message="Badge reset")


@router.post(
    "/send-weekly-digest",
    response_model=schemas.DigestStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit(LIMIT_HEAVY)
async def send_weekly_digest(
    request: Request,
    x_digest_key: str = Header(..., alias="X-Digest-Key"),
    apns_client: APNs | None = Depends(get_apns_client),
) -> schemas.DigestStatusResponse:
    """Trigger weekly digest push notifications (API key auth, for cron use)."""
    if not settings.digest_api_key or x_digest_key != settings.digest_api_key:
        raise HTTPException(status_code=403, detail="Invalid digest key")

    asyncio.ensure_future(services.run_weekly_digest(apns_client))
    return schemas.DigestStatusResponse(status="started")
