"""Notification domain services: device CRUD, preference CRUD, send_push, digest, event helpers."""

import logging
from datetime import datetime, timedelta, timezone

from aioapns import APNs, NotificationRequest
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth.models import Profile
from app.database import SessionLocal
from app.friends.models import Friendship
from app.movies.models import Movie
from app.notifications.models import DeviceToken, NotificationPreference

logger = logging.getLogger(__name__)

DIGEST_COOLDOWN_DAYS = 6

# Thread-id constants for APNs notification grouping
THREAD_FRIEND_REQUESTS = "friend_requests"
THREAD_GROUP_INVITES = "group_invites"
THREAD_FRIEND_ACTIVITY = "friend_activity"


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
    thread_id: str | None = None,
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

    # Build aps dict
    aps: dict[str, object] = {
        "alert": {"title": title, "body": body},
        "sound": "default",
    }
    if thread_id:
        aps["thread-id"] = thread_id

    sent = 0
    stale_ids: list[int] = []

    for device in tokens:
        request = NotificationRequest(
            device_token=device.token,
            message={
                "aps": aps,
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


async def notify_friend_activity(
    recipient_id: str,
    sender_username: str,
    movie_title: str,
    tmdb_id: int,
    db: Session,
    apns_client: APNs | None,
) -> int:
    """Send a friend activity push notification with a rolling 24-hour daily cap.

    Returns the number of successfully sent notifications (0 if capped or preference disabled).
    """
    pref = get_or_create_preferences(recipient_id, db)

    # Check 24-hour rolling cap
    if pref.last_friend_activity_push_at is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        if pref.last_friend_activity_push_at > cutoff:
            return 0

    count = await send_push(
        user_id=recipient_id,
        notification_type="friend_activity",
        title="Friend Activity",
        body=f"{sender_username} loved {movie_title}",
        data={"type": "friend_activity", "tmdb_id": str(tmdb_id)},
        db=db,
        apns_client=apns_client,
        thread_id=THREAD_FRIEND_ACTIVITY,
    )

    if count > 0:
        pref.last_friend_activity_push_at = datetime.now(timezone.utc)
        db.commit()

    return count


async def notify_friends_of_rating(
    user_id: str,
    rating: float,
    tmdb_id: int,
    db: Session,
    apns_client: APNs | None,
    previous_rating: float | None = None,
) -> None:
    """Fan out friend activity notifications when a user rates a movie >= 4.0.

    Skips entirely when:
    - rating < 4.0
    - previous_rating was already >= 4.0 (no re-notification on updates)
    """
    if rating < 4.0:
        return

    if previous_rating is not None and previous_rating >= 4.0:
        return

    # Get sender's username
    profile = db.query(Profile).filter(Profile.id == user_id).first()
    if profile is None:
        return

    # Get movie title
    movie = db.query(Movie).filter(Movie.tmdb_id == tmdb_id).first()
    if movie is None:
        return

    # Get all accepted friendships
    friendships = (
        db.query(Friendship)
        .filter(
            Friendship.status == "accepted",
            or_(
                Friendship.requester_id == user_id,
                Friendship.addressee_id == user_id,
            ),
        )
        .all()
    )

    for friendship in friendships:
        friend_id = (
            str(friendship.addressee_id)
            if str(friendship.requester_id) == user_id
            else str(friendship.requester_id)
        )
        try:
            await notify_friend_activity(
                recipient_id=friend_id,
                sender_username=profile.username,
                movie_title=movie.title,
                tmdb_id=tmdb_id,
                db=db,
                apns_client=apns_client,
            )
        except Exception:
            logger.exception(
                "Failed to send friend activity notification to %s", friend_id
            )
            continue


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
