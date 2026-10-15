"""Notification domain services: device CRUD, preference CRUD, fire_notification, digest."""

import asyncio
import base64
import json
import logging
from datetime import datetime, timedelta, timezone

from aioapns import APNs, NotificationRequest
from fastapi import HTTPException
from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

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
THREAD_COMMENT_REPLIES = "comment_replies"
THREAD_COMMENT_MENTIONS = "comment_mentions"
THREAD_COMMENT_LIKES = "comment_likes"

# Inbox `type` -> incoming preference category. Types missing here (friend and
# follow requests) always stay in the inbox. watched_with has no writer yet.
_INBOX_CATEGORY = {
    "friend_activity": "friends_ratings",
    "group_invite": "blend_activity",
    "blend_invite": "blend_activity",
    "group_watchlist": "blend_activity",
    "blend_activity": "blend_activity",
    "comment_reply": "comments_likes",
    "comment_mention": "comments_likes",
    "comment_like": "comments_likes",
    "watched_with": "watched_with_tags",
    "recommendation": "recommendations",
    "match": "recommendations",
    "weekly_digest": "recommendations",
}

# fire_notification() `notification_type` (the legacy push toggle) -> category.
_PUSH_CATEGORY = {
    "group_invites": "blend_activity",
    "comment_replies": "comments_likes",
    "comment_mentions": "comments_likes",
    "comment_like": "comments_likes",
    "friend_activity": "friends_ratings",
    "recommendations": "recommendations",
    "watched_with": "watched_with_tags",
    "match": "recommendations",
}

_IN_APP_FIELD = {
    "friends_ratings": "friends_ratings_in_app",
    "blend_activity": "blend_activity_in_app",
    "comments_likes": "comments_likes_in_app",
    "watched_with_tags": "watched_with_tags_in_app",
    "recommendations": "recommendations_in_app",
}

_PUSH_FIELD = {
    "friends_ratings": "friends_ratings_push",
    "blend_activity": "blend_activity_push",
    "comments_likes": "comments_likes_push",
    "watched_with_tags": "watched_with_tags_push",
    "recommendations": "recommendations_push",
}

# Missing preference row. friends_ratings push is the only one that defaults off.
_PUSH_DEFAULT = {
    "friends_ratings": False,
    "blend_activity": True,
    "comments_likes": True,
    "watched_with_tags": True,
    "recommendations": True,
}

_PREFERENCE_DEFAULTS = {
    "friend_requests": True,
    "group_invites": True,
    "recommendations": True,
    "friend_activity": True,
    "comment_replies": True,
    "share_ratings_activity": "friends",
    "friends_ratings_in_app": True,
    "friends_ratings_push": False,
    "blend_activity_in_app": True,
    "blend_activity_push": True,
    "comments_likes_in_app": True,
    "comments_likes_push": True,
    "watched_with_tags_in_app": True,
    "watched_with_tags_push": True,
    "recommendations_in_app": True,
    "recommendations_push": True,
}

_ACTIONABLE = {"friend_request", "follow_request"}
_CLOSED = {"accepted", "declined", "rejected"}

# Shared visibility filter for the grouped inbox and the unread count.
_VISIBLE_CTE = """
WITH visible AS (
    SELECT
        n.id,
        n.type,
        n.from_user_id,
        n.title,
        n.body,
        n.data,
        n.read,
        n.created_at,
        COALESCE(n.group_key, 'row:' || n.id::text) AS gkey
    FROM notification_inbox n
    LEFT JOIN notification_preferences mine ON mine.user_id = n.user_id
    LEFT JOIN notification_preferences actor ON actor.user_id = n.from_user_id
    WHERE n.user_id = CAST(:uid AS uuid)
      AND (
        CASE n.type
            WHEN 'friend_activity' THEN COALESCE(mine.friends_ratings_in_app, true)
            WHEN 'group_invite' THEN COALESCE(mine.blend_activity_in_app, true)
            WHEN 'blend_invite' THEN COALESCE(mine.blend_activity_in_app, true)
            WHEN 'group_watchlist' THEN COALESCE(mine.blend_activity_in_app, true)
            WHEN 'blend_activity' THEN COALESCE(mine.blend_activity_in_app, true)
            WHEN 'comment_reply' THEN COALESCE(mine.comments_likes_in_app, true)
            WHEN 'comment_mention' THEN COALESCE(mine.comments_likes_in_app, true)
            WHEN 'comment_like' THEN COALESCE(mine.comments_likes_in_app, true)
            WHEN 'watched_with' THEN COALESCE(mine.watched_with_tags_in_app, true)
            WHEN 'recommendation' THEN COALESCE(mine.recommendations_in_app, true)
            WHEN 'match' THEN COALESCE(mine.recommendations_in_app, true)
            WHEN 'weekly_digest' THEN COALESCE(mine.recommendations_in_app, true)
            ELSE true
        END
      )
      AND (
        n.type <> 'friend_activity'
        OR COALESCE(actor.share_ratings_activity, 'friends') = 'everyone'
        OR (
            COALESCE(actor.share_ratings_activity, 'friends') = 'friends'
            AND EXISTS (
                SELECT 1 FROM friendships f
                WHERE f.status = 'accepted'
                  AND (
                    (f.requester_id = n.user_id AND f.addressee_id = n.from_user_id)
                    OR (f.addressee_id = n.user_id AND f.requester_id = n.from_user_id)
                  )
            )
        )
        OR (
            COALESCE(actor.share_ratings_activity, 'friends') = 'blends'
            AND EXISTS (
                SELECT 1
                FROM group_members gm1
                JOIN group_members gm2 ON gm1.group_id = gm2.group_id
                WHERE gm1.user_id = n.user_id
                  AND gm2.user_id = n.from_user_id
                  AND gm1.user_id <> gm2.user_id
            )
        )
      )
)
"""


def _pref_row(user_id: str, db: Session) -> NotificationPreference | None:
    return (
        db.query(NotificationPreference)
        .filter(NotificationPreference.user_id == user_id)
        .first()
    )


def serialize_preferences(pref: NotificationPreference | None) -> dict:
    """Preference payload. A missing row returns lazy defaults and writes nothing."""
    if pref is None:
        return dict(_PREFERENCE_DEFAULTS)
    return {key: getattr(pref, key) for key in _PREFERENCE_DEFAULTS}


def read_preferences(user_id: str, db: Session) -> dict:
    """Return preferences without creating a row."""
    return serialize_preferences(_pref_row(user_id, db))


def in_app_enabled(user_id: str, inbox_type: str, db: Session) -> bool:
    """Whether this inbox type is shown and stored for the recipient."""
    category = _INBOX_CATEGORY.get(inbox_type)
    if category is None:
        return True
    pref = _pref_row(user_id, db)
    if pref is None:
        return True
    return bool(getattr(pref, _IN_APP_FIELD[category]))


def is_push_eligible(user_id: str, category: str, db: Session) -> bool:
    """True when `category` push is on and the user has a device token.

    Categories: friends_ratings, blend_activity, comments_likes,
    watched_with_tags, recommendations. A missing prefs row uses lazy defaults
    (friends_ratings push is off, the rest are on).
    """
    default = _PUSH_DEFAULT.get(category)
    if default is None:
        return False
    pref = _pref_row(user_id, db)
    allowed = default if pref is None else bool(getattr(pref, _PUSH_FIELD[category]))
    if not allowed:
        return False
    token = db.query(DeviceToken.id).filter(DeviceToken.user_id == user_id).first()
    return token is not None


def _friend_ids(user_id: str, db: Session) -> list[str]:
    rows = (
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
    return [
        str(row.addressee_id) if str(row.requester_id) == user_id else str(row.requester_id)
        for row in rows
    ]


def _blend_mate_ids(user_id: str, db: Session) -> list[str]:
    from app.groups.models import GroupMember

    my_groups = db.query(GroupMember.group_id).filter(GroupMember.user_id == user_id)
    rows = (
        db.query(GroupMember.user_id)
        .filter(GroupMember.group_id.in_(my_groups), GroupMember.user_id != user_id)
        .distinct()
        .all()
    )
    return [str(row[0]) for row in rows]


def rating_recipient_ids(user_id: str, db: Session) -> list[str]:
    """Who should receive this user's rating activity right now.

    shortcut: audience "everyone" fans out to friends and blend-mates, not every
    profile. A rating must not write one inbox row per user on the free tier.
    Query time still shows a row to its recipient when the audience is everyone.
    """
    pref = _pref_row(user_id, db)
    audience = pref.share_ratings_activity if pref else "friends"
    if audience == "off":
        return []
    friends = _friend_ids(user_id, db)
    if audience == "friends":
        return friends
    mates = _blend_mate_ids(user_id, db)
    if audience == "blends":
        return mates
    # shortcut: "everyone" stops at friends and blend-mates, not every profile.
    seen: list[str] = []
    for uid in friends + mates:
        if uid not in seen:
            seen.append(uid)
    return seen


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
    group_key: str | None = None,
    skip_inbox: bool = False,
) -> None:
    """Fire-and-forget push + inbox write. One-liner from any view.

    Handles its own DB session and error isolation.
    """

    async def _dispatch() -> None:
        bg_db = SessionLocal()
        try:
            await _send_push(
                user_id=to,
                notification_type=notification_type,
                title=title,
                body=body,
                data=data,
                db=bg_db,
                apns_client=apns_client,
                thread_id=thread,
                from_user_id=from_user,
                group_key=group_key,
                skip_inbox=skip_inbox,
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


async def _send_push(
    user_id: str,
    notification_type: str,
    title: str,
    body: str,
    data: dict[str, str] | None,
    db: Session,
    apns_client: APNs | None,
    thread_id: str | None = None,
    from_user_id: str | None = None,
    group_key: str | None = None,
    skip_inbox: bool = False,
) -> int:
    """Send a push notification to all of a user's devices.

    Writes notification_inbox unless the in-app toggle is off or skip_inbox is set.
    Returns the number of successfully sent notifications.
    Push requires the legacy toggle and the category push toggle.
    Cleans up stale tokens on APNs 410 (Unregistered/BadDeviceToken).
    """
    inbox_type = data.get("type", notification_type) if data else notification_type
    if not skip_inbox and in_app_enabled(user_id, inbox_type, db):
        db.add(
            NotificationInboxItem(
                user_id=user_id,
                type=inbox_type,
                from_user_id=from_user_id,
                title=title,
                body=body,
                data=data or {},
                group_key=group_key,
            )
        )
        db.commit()

    if apns_client is None:
        return 0

    # Legacy push toggles (friend_requests, group_invites, ...) still gate send.
    pref = get_or_create_preferences(user_id, db)
    if not getattr(pref, notification_type, True):
        return 0

    category = _PUSH_CATEGORY.get(notification_type)
    if category is not None and not is_push_eligible(user_id, category, db):
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


def fire_notification_to_friends(
    user_id: str, action: str, tmdb_id: int, db: Session, rating: float | None = None
) -> None:
    """Write a rating/watch event into recipients' inboxes (no push).

    Recipients follow share_ratings_activity. In-app friends_ratings can drop one.
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

    recipient_ids = rating_recipient_ids(user_id, db)
    if not recipient_ids:
        return

    prefs = {
        str(row.user_id): row
        for row in db.query(NotificationPreference)
        .filter(NotificationPreference.user_id.in_(recipient_ids))
        .all()
    }
    group_key = f"rating:{tmdb_id}" if action == "rated" else None
    for fid in recipient_ids:
        pref = prefs.get(fid)
        if pref is not None and not pref.friends_ratings_in_app:
            continue
        db.add(
            NotificationInboxItem(
                user_id=fid,
                type="friend_activity",
                from_user_id=user_id,
                title="Friend Activity",
                body=body_text,
                data={
                    "type": "friend_activity",
                    "tmdb_id": str(tmdb_id),
                    "movie_title": movie_title,
                },
                group_key=group_key,
            )
        )
    db.commit()


def _decode_cursor(cursor: str) -> tuple[datetime, int]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        stamp, raw_id = raw.rsplit("|", 1)
        return datetime.fromisoformat(stamp), int(raw_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid cursor")


def _encode_cursor(created_at: datetime, item_id: int) -> str:
    raw = f"{created_at.isoformat()}|{item_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _as_dict(value: object) -> dict:
    if not value:
        return {}
    if isinstance(value, str):
        loaded = json.loads(value)
        return loaded if isinstance(loaded, dict) else {}
    if isinstance(value, dict):
        return value
    return dict(value)  # type: ignore[arg-type]


def _actor_id_list(value: object) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        inner = value.strip("{}")
        return [part.strip() for part in inner.split(",") if part.strip()]
    return [str(item) for item in value if item]  # type: ignore[union-attr]


def _display_name(profile: Profile | None) -> str:
    if profile is None:
        return "Someone"
    return profile.display_name or profile.username or "Someone"


def _grouped_body(inbox_type: str, count: int, names: list[str], data: dict, fallback: str) -> str:
    """Collapse a group into one line. A single actor keeps the stored body."""
    if count < 2 or not names:
        return fallback
    if inbox_type == "comment_like":
        phrase = "liked your review"
    elif inbox_type == "friend_activity":
        phrase = f"rated {data.get('movie_title') or 'a movie'}"
    else:
        return fallback
    if count == 2 and len(names) >= 2:
        return f"{names[0]} and {names[1]} {phrase}"
    return f"{names[0]} and {count - 1} others {phrase}"


def _actions_for(inbox_type: str, data: dict) -> list[str]:
    if inbox_type not in _ACTIONABLE:
        return []
    if data.get("status") in _CLOSED:
        return []
    return ["accept", "decline"]


def _visible_params(user_id: str, cursor_at: datetime | None, cursor_id: int | None) -> dict:
    return {"uid": user_id, "cursor_at": cursor_at, "cursor_id": cursor_id}


def unread_count(user_id: str, db: Session) -> int:
    """Unread inbox rows that pass in-app and rating-audience filters."""
    row = db.execute(
        text(_VISIBLE_CTE + "SELECT COUNT(*)::int AS n FROM visible WHERE read = false"),
        {"uid": user_id},
    ).one()
    return int(row.n)


def get_inbox(
    user_id: str,
    db: Session,
    limit: int = 30,
    offset: int = 0,
    cursor: str | None = None,
) -> dict:
    """Grouped inbox, newest first.

    Rows that share group_key become one item. `offset` still pages that grouped
    list for the shipped app. `cursor` is the keyset used by the new center.
    A row with no group_key stays its own item, so existing rows page as before.
    """
    cursor_at: datetime | None = None
    cursor_id: int | None = None
    if cursor:
        cursor_at, cursor_id = _decode_cursor(cursor)
        offset = 0

    rows = (
        db.execute(
            text(
                _VISIBLE_CTE
                + """
                , grouped AS (
                    SELECT
                        gkey,
                        (ARRAY_AGG(id ORDER BY created_at DESC, id DESC))[1] AS id,
                        (ARRAY_AGG(type ORDER BY created_at DESC, id DESC))[1] AS type,
                        (ARRAY_AGG(title ORDER BY created_at DESC, id DESC))[1] AS title,
                        (ARRAY_AGG(body ORDER BY created_at DESC, id DESC))[1] AS body,
                        (ARRAY_AGG(data ORDER BY created_at DESC, id DESC))[1] AS data,
                        (ARRAY_AGG(created_at ORDER BY created_at DESC, id DESC))[1] AS created_at,
                        BOOL_AND(read) AS read,
                        COUNT(*)::int AS actor_count,
                        (ARRAY_AGG(from_user_id ORDER BY created_at DESC, id DESC))[1:8] AS actor_ids
                    FROM visible
                    GROUP BY gkey
                )
                SELECT * FROM grouped
                WHERE (
                    CAST(:cursor_at AS timestamptz) IS NULL
                    OR (created_at, id) < (
                        CAST(:cursor_at AS timestamptz),
                        CAST(:cursor_id AS bigint)
                    )
                )
                ORDER BY created_at DESC, id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {
                **_visible_params(user_id, cursor_at, cursor_id),
                "limit": limit + 1,
                "offset": offset,
            },
        )
        .mappings()
        .all()
    )
    has_more = len(rows) > limit
    page = rows[:limit]

    all_ids: list[str] = []
    parsed_ids: list[list[str]] = []
    for row in page:
        ids = _actor_id_list(row["actor_ids"])
        parsed_ids.append(ids)
        all_ids.extend(ids)
    profiles = {}
    if all_ids:
        profiles = {
            str(profile.id): profile
            for profile in db.query(Profile).filter(Profile.id.in_(all_ids)).all()
        }

    results = []
    for row, actor_ids in zip(page, parsed_ids, strict=True):
        data = _as_dict(row["data"])
        actors = []
        names = []
        for actor_id in actor_ids:
            profile = profiles.get(actor_id)
            names.append(_display_name(profile))
            actors.append(
                {
                    "id": actor_id,
                    "username": profile.username if profile else None,
                    "display_name": profile.display_name if profile else None,
                    "avatar_url": profile.avatar_url if profile else None,
                }
            )
        lead = profiles.get(actor_ids[0]) if actor_ids else None
        created_at = row["created_at"]
        results.append(
            {
                "id": int(row["id"]),
                "type": row["type"],
                "from_username": lead.username if lead else None,
                "from_avatar_url": lead.avatar_url if lead else None,
                "title": row["title"],
                "body": _grouped_body(
                    row["type"], int(row["actor_count"]), names, data, row["body"]
                ),
                "data": data,
                "read": bool(row["read"]),
                "created_at": created_at.isoformat()
                if isinstance(created_at, datetime)
                else str(created_at),
                "actors": actors,
                "actor_count": int(row["actor_count"]),
                "actions": _actions_for(row["type"], data),
            }
        )

    next_cursor = None
    if has_more and page:
        last = page[-1]
        stamp = last["created_at"]
        if not isinstance(stamp, datetime):
            stamp = datetime.fromisoformat(str(stamp))
        next_cursor = _encode_cursor(stamp, int(last["id"]))

    return {
        "results": results,
        "unread_count": unread_count(user_id, db),
        "next_cursor": next_cursor,
    }


def mark_inbox_read(user_id: str, db: Session) -> None:
    """Mark all inbox items as read."""
    db.query(NotificationInboxItem).filter(
        NotificationInboxItem.user_id == user_id,
        NotificationInboxItem.read == False,  # noqa: E712
    ).update({"read": True}, synchronize_session=False)
    db.commit()


def _own_item(user_id: str, item_id: int, db: Session) -> NotificationInboxItem:
    item = (
        db.query(NotificationInboxItem)
        .filter(
            NotificationInboxItem.id == item_id,
            NotificationInboxItem.user_id == user_id,
        )
        .first()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    return item


def _mark_group_read(item: NotificationInboxItem, db: Session) -> None:
    query = db.query(NotificationInboxItem).filter(
        NotificationInboxItem.user_id == item.user_id,
        NotificationInboxItem.read == False,  # noqa: E712
    )
    if item.group_key:
        query = query.filter(NotificationInboxItem.group_key == item.group_key)
    else:
        query = query.filter(NotificationInboxItem.id == item.id)
    query.update({"read": True}, synchronize_session=False)
    item.read = True


def mark_one_read(user_id: str, item_id: int, db: Session) -> int:
    """Mark one inbox group read. Returns the remaining unread row count."""
    item = _own_item(user_id, item_id, db)
    _mark_group_read(item, db)
    db.commit()
    return unread_count(user_id, db)


def _present_item(item: NotificationInboxItem, db: Session) -> dict:
    profile = None
    if item.from_user_id is not None:
        profile = db.query(Profile).filter(Profile.id == item.from_user_id).first()
    data = dict(item.data or {})
    actor = None
    if profile is not None:
        actor = {
            "id": str(profile.id),
            "username": profile.username,
            "display_name": profile.display_name,
            "avatar_url": profile.avatar_url,
        }
    return {
        "id": item.id,
        "type": item.type,
        "from_username": profile.username if profile else None,
        "from_avatar_url": profile.avatar_url if profile else None,
        "title": item.title,
        "body": item.body,
        "data": data,
        "read": item.read,
        "created_at": item.created_at.isoformat(),
        "actors": [actor] if actor else [],
        "actor_count": 1,
        "actions": _actions_for(item.type, data),
    }


def _set_action_status(item: NotificationInboxItem, status: str) -> None:
    data = dict(item.data or {})
    data["status"] = status
    item.data = data
    flag_modified(item, "data")


def _pending_friendship_id(item: NotificationInboxItem, user_id: str, db: Session) -> int:
    raw = (item.data or {}).get("friendship_id")
    if raw:
        return int(raw)
    if item.from_user_id is None:
        raise HTTPException(status_code=400, detail="Friend request is missing a sender")
    row = (
        db.query(Friendship)
        .filter(
            Friendship.addressee_id == user_id,
            Friendship.requester_id == item.from_user_id,
            Friendship.status == "pending",
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Friend request not found")
    return row.id


def _require_actionable(item: NotificationInboxItem) -> None:
    if item.type not in _ACTIONABLE:
        raise HTTPException(
            status_code=400, detail="Notification has no accept or decline action"
        )
    status = (item.data or {}).get("status")
    if status in _CLOSED:
        raise HTTPException(status_code=400, detail=f"Notification already {status}")


def accept_notification(user_id: str, item_id: int, db: Session) -> dict:
    """Accept a friend request, or record a follow-request accept.

    Follow requests have no follows table, so accept only updates this row.
    """
    item = _own_item(user_id, item_id, db)
    _require_actionable(item)
    friendship_id = (
        _pending_friendship_id(item, user_id, db) if item.type == "friend_request" else None
    )
    _set_action_status(item, "accepted")
    _mark_group_read(item, db)
    if friendship_id is not None:
        from app.friends.services import accept_friend_request

        # Commits the friendship and this row together.
        accept_friend_request(user_id, friendship_id, db)
    else:
        db.commit()
    db.refresh(item)
    return _present_item(item, db)


def decline_notification(user_id: str, item_id: int, db: Session) -> dict:
    """Decline a friend request, or record a follow-request decline."""
    item = _own_item(user_id, item_id, db)
    _require_actionable(item)
    friendship_id = (
        _pending_friendship_id(item, user_id, db) if item.type == "friend_request" else None
    )
    _set_action_status(item, "declined")
    _mark_group_read(item, db)
    if friendship_id is not None:
        from app.friends.services import reject_friend_request

        # Commits the friendship and this row together.
        reject_friend_request(user_id, friendship_id, db)
    else:
        db.commit()
    db.refresh(item)
    return _present_item(item, db)


def record_comment_like(
    db: Session, *, comment_owner_id: str, comment_id: int, tmdb_id: int, actor_id: str
) -> None:
    """Fan a like into the comment author's inbox. Caller commits."""
    if comment_owner_id == actor_id:
        return
    if not in_app_enabled(comment_owner_id, "comment_like", db):
        return
    actor = db.query(Profile).filter(Profile.id == actor_id).first()
    name = _display_name(actor)
    db.add(
        NotificationInboxItem(
            user_id=comment_owner_id,
            type="comment_like",
            from_user_id=actor_id,
            title="New Like",
            body=f"{name} liked your review",
            data={
                "type": "comment_like",
                "comment_id": str(comment_id),
                "tmdb_id": str(tmdb_id),
            },
            group_key=f"like:comment:{comment_id}",
        )
    )


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

                count = await _send_push(
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
