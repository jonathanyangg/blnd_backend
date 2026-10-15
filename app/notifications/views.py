"""Notification domain endpoints: device token CRUD, notification preferences, digest."""

import asyncio

from aioapns import APNs
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
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
    return schemas.PreferencesResponse(**services.read_preferences(user_id, db))


@router.patch("/preferences", response_model=schemas.PreferencesResponse)
@limiter.limit(LIMIT_DEFAULT)
async def update_preferences(
    request: Request,
    body: schemas.UpdatePreferencesRequest,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.PreferencesResponse:
    pref = services.update_preferences(user_id, body.model_dump(exclude_none=True), db)
    return schemas.PreferencesResponse(**services.serialize_preferences(pref))


@router.get("/inbox", response_model=schemas.InboxResponse)
@limiter.limit(LIMIT_DEFAULT)
async def get_inbox(
    request: Request,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    cursor: str | None = None,
) -> dict:
    return services.get_inbox(user_id, db, limit, offset, cursor)


@router.post("/inbox/read", response_model=schemas.InboxReadResponse)
@limiter.limit(LIMIT_DEFAULT)
async def mark_inbox_read(
    request: Request,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.InboxReadResponse:
    services.mark_inbox_read(user_id, db)
    return schemas.InboxReadResponse(
        message="Inbox marked as read", unread_count=services.unread_count(user_id, db)
    )


@router.post("/inbox/{item_id}/read", response_model=schemas.InboxReadResponse)
@limiter.limit(LIMIT_DEFAULT)
async def mark_one_read(
    request: Request,
    item_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.InboxReadResponse:
    remaining = services.mark_one_read(user_id, item_id, db)
    return schemas.InboxReadResponse(
        message="Notification marked as read", unread_count=remaining
    )


@router.post("/inbox/{item_id}/accept", response_model=schemas.InboxItemResponse)
@limiter.limit(LIMIT_DEFAULT)
async def accept_notification(
    request: Request,
    item_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return services.accept_notification(user_id, item_id, db)


@router.post("/inbox/{item_id}/decline", response_model=schemas.InboxItemResponse)
@limiter.limit(LIMIT_DEFAULT)
async def decline_notification(
    request: Request,
    item_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return services.decline_notification(user_id, item_id, db)


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
