import hmac
import logging

from fastapi import APIRouter, Body, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.dependencies import get_db, require_admin
from app.subscriptions import services
from app.subscriptions.schemas import (
    RevenueCatWebhookPayload,
    SubscriptionStatusResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/webhooks/revenuecat", status_code=status.HTTP_204_NO_CONTENT)
async def revenuecat_webhook(
    payload: RevenueCatWebhookPayload = Body(...),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> None:
    """Receive entitlement events from RevenueCat and update profiles.

    The shared secret is set in RevenueCat's dashboard and sent back as the
    Authorization header on every event. hmac.compare_digest guards against
    timing-based secret discovery.
    """
    expected = settings.revenuecat_webhook_secret
    if not expected:
        logger.error("revenuecat_webhook_secret not configured; rejecting webhook")
        raise HTTPException(status_code=503, detail="Webhook not configured")
    provided = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    services.apply_webhook_event(payload.event, db)


@router.post(
    "/admin/subscriptions/{user_id}/grant",
    response_model=SubscriptionStatusResponse,
)
async def admin_grant_subscription(
    user_id: str,
    days: int = 365,
    _admin: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SubscriptionStatusResponse:
    """Grant premium for `days` days. Admin-only; used for comps and beta."""
    try:
        profile = services.admin_grant(user_id, days, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return SubscriptionStatusResponse(
        tier=profile.subscription_tier,
        expires_at=profile.subscription_expires_at.isoformat()
        if profile.subscription_expires_at
        else None,
        source=profile.subscription_source,
    )
