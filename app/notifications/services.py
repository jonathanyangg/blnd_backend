"""Notification domain services: device CRUD, preference CRUD, send_push, digest."""

import logging
from datetime import datetime, timedelta, timezone

from aioapns import APNs, NotificationRequest
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth.models import Profile
from app.database import SessionLocal
from app.notifications.models import DeviceToken, NotificationPreference

logger = logging.getLogger(__name__)

DIGEST_COOLDOWN_DAYS = 6


def register_device(user_id: str, token: str, platform: str, db: Session) -> None:
    """Register or re-register a device token for push notifications."""
    existing = (
        db.query(DeviceToken)
        .filter(DeviceToken.user_id == user_id, DeviceToken.token == token)
        .first()
    )
    if existing:
        existing.updated_at = datetime.now(timezone.utc)
        db.commit()
    else:
        device = DeviceToken(user_id=user_id, token=token, platform=platform)
        db.add(device)
        db.commit()


def unregister_device(user_id: str, token: str, db: Session) -> None:
    """Remove a device token. No error if token not found."""
    db.query(DeviceToken).filter(
        DeviceToken.user_id == user_id, DeviceToken.token == token
    ).delete()
    db.commit()


def get_or_create_preferences(user_id: str, db: Session) -> NotificationPreference:
    """Get notification preferences, creating with defaults if missing."""
    pref = (
        db.query(NotificationPreference)
        .filter(NotificationPreference.user_id == user_id)
        .first()
    )
    if pref is None:
        pref = NotificationPreference(
            user_id=user_id,
            friend_requests=True,
            group_invites=True,
            recommendations=True,
            friend_activity=True,
        )
        db.add(pref)
        db.commit()
        db.refresh(pref)
    return pref


def update_preferences(
    user_id: str, updates: dict[str, bool], db: Session
) -> NotificationPreference:
    """Partially update notification preferences."""
    pref = get_or_create_preferences(user_id, db)
    for key, value in updates.items():
        setattr(pref, key, value)
    pref.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(pref)
    return pref


async def send_push(
    user_id: str,
    notification_type: str,
    title: str,
    body: str,
    data: dict[str, str] | None,
    db: Session,
    apns_client: APNs | None,
) -> int:
    """Send a push notification to all of a user's devices.

    Returns the number of successfully sent notifications.
    Checks user preferences before dispatch.
    Cleans up stale tokens on APNs 410 (Unregistered/BadDeviceToken).
    """
    if apns_client is None:
        return 0

    # Check preferences
    pref = get_or_create_preferences(user_id, db)
    if not getattr(pref, notification_type, True):
        return 0

    # Get all device tokens
    tokens = db.query(DeviceToken).filter(DeviceToken.user_id == user_id).all()
    if not tokens:
        return 0

    sent = 0
    stale_ids: list[int] = []

    for device in tokens:
        request = NotificationRequest(
            device_token=device.token,
            message={
                "aps": {
                    "alert": {"title": title, "body": body},
                    "sound": "default",
                },
                **(data or {}),
            },
        )
        result = await apns_client.send_notification(request)
        if result.is_successful:
            sent += 1
        elif result.description in ("Unregistered", "BadDeviceToken"):
            logger.info(
                "Removing stale device token %s (reason: %s)",
                device.id,
                result.description,
            )
            stale_ids.append(device.id)

    # Bulk-delete stale tokens
    if stale_ids:
        db.query(DeviceToken).filter(DeviceToken.id.in_(stale_ids)).delete(
            synchronize_session=False
        )
        db.commit()

    return sent


async def run_weekly_digest(apns_client: APNs | None) -> None:
    """Send weekly digest push to all eligible users. Idempotent."""
    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=DIGEST_COOLDOWN_DAYS)

        eligible_user_ids = (
            db.query(Profile.id)
            .join(DeviceToken, DeviceToken.user_id == Profile.id)
            .outerjoin(
                NotificationPreference,
                NotificationPreference.user_id == Profile.id,
            )
            .filter(
                Profile.taste_embedding.isnot(None),
                or_(
                    NotificationPreference.last_digest_sent_at.is_(None),
                    NotificationPreference.last_digest_sent_at < cutoff,
                ),
                or_(
                    NotificationPreference.recommendations.is_(None),
                    NotificationPreference.recommendations == True,  # noqa: E712
                ),
            )
            .distinct()
            .all()
        )

        sent_count = 0
        for (user_id,) in eligible_user_ids:
            try:
                count = await send_push(
                    user_id=str(user_id),
                    notification_type="recommendations",
                    title="Fresh picks this week",
                    body="See what we found for you",
                    data={"type": "weekly_digest"},
                    db=db,
                    apns_client=apns_client,
                )
                if count > 0:
                    pref = get_or_create_preferences(str(user_id), db)
                    pref.last_digest_sent_at = datetime.now(timezone.utc)
                    db.commit()
                    sent_count += 1
            except Exception:
                logger.exception("Digest send failed for user %s", user_id)
                continue

        logger.info(
            "Weekly digest complete: sent to %d/%d eligible users",
            sent_count,
            len(eligible_user_ids),
        )
    except Exception:
        logger.exception("Weekly digest failed")
    finally:
        db.close()
