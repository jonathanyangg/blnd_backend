"""Notification domain services: device CRUD, preference CRUD, send_push, digest, event helpers."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aioapns import APNs, NotificationRequest
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.auth.models import Profile
from app.database import SessionLocal
from app.friends.models import Friendship
from app.movies.models import Movie
from app.notifications.models import (
    DeviceToken,
    NotificationInboxItem,
    NotificationPreference,
)
from app.tracking.models import ActivityFeedItem

logger = logging.getLogger(__name__)

DIGEST_COOLDOWN_DAYS = 6

# Thread-id constants for APNs notification grouping
THREAD_FRIEND_REQUESTS = "friend_requests"
THREAD_GROUP_INVITES = "group_invites"
THREAD_FRIEND_ACTIVITY = "friend_activity"
THREAD_GROUP_ACTIVITY = "group_activity"


def fire_notification(
    *,
    to: str,
    from_user: str | None = None,
    notification_type: str,
    title: str,
    body: str,
    data: dict[str, str] | None = None,
    thread: str | None = None,
    apns_client: APNs | None,
) -> None:
    """Fire-and-forget push + inbox write. One-liner from any view.

    Handles its own DB session and error isolation.
    """

    async def _dispatch() -> None:
        bg_db = SessionLocal()
        try:
            await send_push(
                user_id=to,
                notification_type=notification_type,
                title=title,
                body=body,
                data=data,
                db=bg_db,
                apns_client=apns_client,
                thread_id=thread,
                from_user_id=from_user,
            )
        except Exception:
            logger.exception("fire_notification failed for user %s", to)
        finally:
            bg_db.close()

    asyncio.ensure_future(_dispatch())


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
    from_user_id: str | None = None,
) -> int:
    """Send a push notification to all of a user's devices.

    Also writes to notification_inbox for persistent history.
    Returns the number of successfully sent notifications.
    Checks user preferences before dispatch.
    Cleans up stale tokens on APNs 410 (Unregistered/BadDeviceToken).
    """
    # Always write to inbox (even if push is skipped/fails)
    inbox_item = NotificationInboxItem(
        user_id=user_id,
        type=data.get("type", notification_type) if data else notification_type,
        from_user_id=from_user_id,
        title=title,
        body=body,
        data=data or {},
    )
    db.add(inbox_item)
    db.commit()

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

    # Increment badge count
    pref.badge_count = (pref.badge_count or 0) + 1
    db.commit()

    # Build aps dict
    aps: dict[str, object] = {
        "alert": {"title": title, "body": body},
        "sound": "default",
        "badge": pref.badge_count,
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


def write_activity_to_inbox(
    user_id: str, action: str, tmdb_id: int, db: Session, rating: float | None = None
) -> None:
    """Write a friend activity event to all friends' inboxes (no push, just inbox).

    Used for watches and low ratings that don't warrant a push notification
    but should still appear in the unified feed.
    """
    profile = db.query(Profile).filter(Profile.id == user_id).first()
    if not profile:
        return
    movie = db.query(Movie).filter(Movie.tmdb_id == tmdb_id).first()
    movie_title = movie.title if movie else "a movie"

    if action == "rated" and rating:
        formatted = f"{rating:.1f}".rstrip("0").rstrip(".")
        body_text = f"{profile.username} rated {movie_title} ★ {formatted}"
    elif action == "watched":
        body_text = f"{profile.username} watched {movie_title}"
    elif action == "watchlisted":
        body_text = f"{profile.username} added {movie_title} to watchlist"
    else:
        body_text = f"{profile.username} {action} {movie_title}"

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
    friend_ids = [
        str(f.addressee_id) if str(f.requester_id) == user_id else str(f.requester_id)
        for f in friendships
    ]

    for fid in friend_ids:
        db.add(
            NotificationInboxItem(
                user_id=fid,
                type="friend_activity",
                from_user_id=user_id,
                title="Friend Activity",
                body=body_text,
                data={"type": "friend_activity", "tmdb_id": str(tmdb_id)},
            )
        )
    db.commit()


async def notify_friends_of_rating(
    user_id: str,
    rating: float,
    tmdb_id: int,
    db: Session,
    apns_client: APNs | None,
    previous_rating: float | None = None,
) -> None:
    """Fan out friend activity notifications when a user rates a movie >= 4.0.

    Uses batched DB queries for preferences + device tokens to avoid N+1.

    Skips entirely when:
    - rating < 4.0
    - previous_rating was already >= 4.0 (no re-notification on updates)
    """
    if rating < 4.0 or apns_client is None:
        return

    if previous_rating is not None and previous_rating >= 4.0:
        return

    # Get sender's username + movie title
    profile = db.query(Profile).filter(Profile.id == user_id).first()
    if profile is None:
        return
    movie = db.query(Movie).filter(Movie.tmdb_id == tmdb_id).first()
    if movie is None:
        return

    # Get all friend IDs in one query
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
    friend_ids = [
        str(f.addressee_id) if str(f.requester_id) == user_id else str(f.requester_id)
        for f in friendships
    ]
    if not friend_ids:
        return

    # Batch-fetch preferences for all friends
    prefs = (
        db.query(NotificationPreference)
        .filter(NotificationPreference.user_id.in_(friend_ids))
        .all()
    )
    pref_map = {str(p.user_id): p for p in prefs}

    # Batch-fetch device tokens for all friends
    all_tokens = db.query(DeviceToken).filter(DeviceToken.user_id.in_(friend_ids)).all()
    tokens_by_user: dict[str, list[DeviceToken]] = {}
    for t in all_tokens:
        tokens_by_user.setdefault(str(t.user_id), []).append(t)

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    stale_ids: list[int] = []

    for fid in friend_ids:
        # Check preference
        pref = pref_map.get(fid)
        if pref and not pref.friend_activity:
            continue

        # Check 24-hour cap
        if (
            pref
            and pref.last_friend_activity_push_at
            and pref.last_friend_activity_push_at > cutoff
        ):
            continue

        tokens = tokens_by_user.get(fid, [])
        if not tokens:
            continue

        # Increment badge + write to inbox
        if pref is None:
            pref = get_or_create_preferences(fid, db)
        pref.badge_count = (pref.badge_count or 0) + 1

        body_text = f"{profile.username} loved {movie.title}"
        db.add(
            NotificationInboxItem(
                user_id=fid,
                type="friend_activity",
                from_user_id=user_id,
                title="Friend Activity",
                body=body_text,
                data={"type": "friend_activity", "tmdb_id": str(tmdb_id)},
            )
        )

        aps: dict[str, object] = {
            "alert": {
                "title": "Friend Activity",
                "body": body_text,
            },
            "sound": "default",
            "badge": pref.badge_count,
            "thread-id": THREAD_FRIEND_ACTIVITY,
        }

        sent = False
        for device in tokens:
            try:
                request = NotificationRequest(
                    device_token=device.token,
                    message={
                        "aps": aps,
                        "type": "friend_activity",
                        "tmdb_id": str(tmdb_id),
                    },
                )
                result = await apns_client.send_notification(request)
                if result.is_successful:
                    sent = True
                elif result.description in ("Unregistered", "BadDeviceToken"):
                    stale_ids.append(device.id)
            except Exception:
                logger.exception(
                    "Failed to send friend activity push to device %s", device.id
                )

        if sent:
            pref.last_friend_activity_push_at = datetime.now(timezone.utc)

    # Bulk cleanup + commit
    if stale_ids:
        db.query(DeviceToken).filter(DeviceToken.id.in_(stale_ids)).delete(
            synchronize_session=False
        )
    db.commit()


def get_inbox(user_id: str, db: Session, limit: int = 30, offset: int = 0) -> dict:
    """Get notification inbox with sender profile info."""
    rows = (
        db.query(NotificationInboxItem, Profile)
        .outerjoin(Profile, NotificationInboxItem.from_user_id == Profile.id)
        .filter(NotificationInboxItem.user_id == user_id)
        .order_by(NotificationInboxItem.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    unread_count = (
        db.query(func.count(NotificationInboxItem.id))
        .filter(
            NotificationInboxItem.user_id == user_id,
            NotificationInboxItem.read == False,  # noqa: E712
        )
        .scalar()
        or 0
    )

    results = [
        {
            "id": item.id,
            "type": item.type,
            "from_username": profile.username if profile else None,
            "from_avatar_url": profile.avatar_url if profile else None,
            "title": item.title,
            "body": item.body,
            "data": item.data or {},
            "read": item.read,
            "created_at": item.created_at.isoformat(),
        }
        for item, profile in rows
    ]
    return {"results": results, "unread_count": unread_count}


def mark_inbox_read(user_id: str, db: Session) -> None:
    """Mark all inbox items as read."""
    db.query(NotificationInboxItem).filter(
        NotificationInboxItem.user_id == user_id,
        NotificationInboxItem.read == False,  # noqa: E712
    ).update({"read": True}, synchronize_session=False)
    db.commit()


def _build_digest_body(user_id: str, since: datetime, db: Session) -> str | None:
    """Build a personalized digest message from friend activity this week."""
    # Get friend IDs
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
    friend_ids = [
        str(f.addressee_id) if str(f.requester_id) == user_id else str(f.requester_id)
        for f in friendships
    ]
    if not friend_ids:
        return None

    # Count activity from friends this week
    activity_count = (
        db.query(func.count(ActivityFeedItem.id))
        .filter(
            ActivityFeedItem.user_id.in_(friend_ids),
            ActivityFeedItem.created_at >= since,
        )
        .scalar()
        or 0
    )
    if activity_count == 0:
        return None

    # Get distinct friends who were active
    active_friends = (
        db.query(Profile.username)
        .join(ActivityFeedItem, ActivityFeedItem.user_id == Profile.id)
        .filter(
            ActivityFeedItem.user_id.in_(friend_ids),
            ActivityFeedItem.created_at >= since,
        )
        .distinct()
        .limit(3)
        .all()
    )
    names = [row[0] for row in active_friends]

    if len(names) == 1:
        return f"{names[0]} watched {activity_count} movie{'s' if activity_count != 1 else ''} this week"
    elif len(names) == 2:
        return f"{names[0]} and {names[1]} were active this week"
    else:
        others = len(names) - 2
        return f"{names[0]}, {names[1]} and {others} other{'s' if others > 1 else ''} were active this week"


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
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)

        for (user_id,) in eligible_user_ids:
            try:
                uid = str(user_id)
                body = _build_digest_body(uid, week_ago, db)
                if not body:
                    continue

                count = await send_push(
                    user_id=uid,
                    notification_type="recommendations",
                    title="This week on blnd",
                    body=body,
                    data={"type": "weekly_digest"},
                    db=db,
                    apns_client=apns_client,
                )
                if count > 0:
                    pref = get_or_create_preferences(uid, db)
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


def reset_badge(user_id: str, db: Session) -> None:
    """Reset badge count to 0 (called when user opens the app)."""
    pref = get_or_create_preferences(user_id, db)
    pref.badge_count = 0
    db.commit()
