"""Dated watch timelines for a profile and for a Blend."""

import base64
import binascii
from datetime import date, datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from app.auth.models import Profile
from app.auth.services import assert_are_friends
from app.config import settings
from app.friends.models import Friendship, UserBlock
from app.groups.models import Group, GroupMember

def get_profile_timeline(
    caller_id: str,
    target_id: str,
    cursor: str | None,
    limit: int,
    db: Session,
) -> dict:
    """Watch history for one profile, newest diary date first.

    The caller can read their own timeline. Anyone else must be an accepted
    friend. A block in either direction hides the profile.
    """
    _assert_profile_visible(caller_id, target_id, db)
    return _page([target_id], cursor, limit, caller_id, db)


def get_blend_timeline(
    caller_id: str,
    group_id: int,
    cursor: str | None,
    limit: int,
    db: Session,
) -> dict:
    """Watch history of Blend members the caller is allowed to see.

    Membership is required. Each member's logs are included only when the
    caller is that member or an accepted friend, and neither has blocked the
    other. That matches the friends-only watch history on profiles.
    """
    group = db.query(Group.id).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Group not found"
        )
    member = (
        db.query(GroupMember.user_id)
        .filter(GroupMember.group_id == group_id, GroupMember.user_id == caller_id)
        .first()
    )
    if not member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this group"
        )

    member_ids = [
        str(row[0])
        for row in db.query(GroupMember.user_id)
        .filter(GroupMember.group_id == group_id)
        .all()
    ]
    blocked = _blocked_ids(caller_id, db)
    friends = _friend_ids(caller_id, db)
    visible = [
        user_id
        for user_id in member_ids
        if user_id not in blocked and (user_id == caller_id or user_id in friends)
    ]
    return _page(visible, cursor, limit, caller_id, db)


def _assert_profile_visible(caller_id: str, target_id: str, db: Session) -> None:
    profile = db.query(Profile.id).filter(Profile.id == target_id).first()
    if not profile or (
        caller_id != target_id and target_id in _blocked_ids(caller_id, db)
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    if caller_id != target_id:
        assert_are_friends(caller_id, target_id, db)


def _blocked_ids(viewer_id: str, db: Session) -> set[str]:
    rows = (
        db.query(UserBlock.blocker_id, UserBlock.blocked_id)
        .filter(
            or_(
                UserBlock.blocker_id == viewer_id,
                UserBlock.blocked_id == viewer_id,
            )
        )
        .all()
    )
    blocked = {str(blocker) for blocker, _blocked in rows}
    blocked.update(str(blocked_id) for _blocker, blocked_id in rows)
    blocked.discard(viewer_id)
    return blocked


def _friend_ids(user_id: str, db: Session) -> set[str]:
    rows = (
        db.query(Friendship.requester_id, Friendship.addressee_id)
        .filter(
            Friendship.status == "accepted",
            or_(
                Friendship.requester_id == user_id,
                Friendship.addressee_id == user_id,
            ),
        )
        .all()
    )
    friends: set[str] = set()
    for requester_id, addressee_id in rows:
        other = addressee_id if str(requester_id) == user_id else requester_id
        friends.add(str(other))
    return friends


def _page(
    user_ids: list[str],
    cursor: str | None,
    limit: int,
    viewer_id: str,
    db: Session,
) -> dict:
    if not user_ids:
        return {"results": [], "next_cursor": None}

    tv_enabled = settings.tv_support_enabled
    params: dict = {"limit": limit + 1}
    user_sql, user_params = _in_clause("u", user_ids, cast="uuid")
    params.update(user_params)
    cursor_sql = ""
    if cursor:
        sort_date, created_at, media_type, log_id = _decode_cursor(cursor, tv_enabled)
        cursor_sql = """
            WHERE sort_date < :sort_date
               OR (sort_date = :sort_date AND sort_created < :sort_created)
               OR (
                    sort_date = :sort_date
                    AND sort_created = :sort_created
                    AND media_type < :media_type
               )
               OR (
                    sort_date = :sort_date
                    AND sort_created = :sort_created
                    AND media_type = :media_type
                    AND log_id < :log_id
               )
        """
        params.update(
            {
                "sort_date": sort_date,
                "sort_created": created_at,
                "media_type": media_type,
                "log_id": log_id,
            }
        )

    tv_sql = ""
    if tv_enabled:
        tv_sql = f"""
            UNION ALL
            SELECT 'tv' AS media_type,
                   wt.id AS log_id,
                   wt.user_id::text AS user_id,
                   p.username,
                   p.display_name,
                   p.avatar_url,
                   wt.tmdb_id,
                   t.title,
                   t.poster_path,
                   wt.rating,
                   wt.watched_date,
                   wt.created_at,
                   COALESCE(
                       wt.watched_date,
                       (wt.created_at AT TIME ZONE 'UTC')::date,
                       DATE '1970-01-01'
                   ) AS sort_date,
                   COALESCE(wt.created_at, TIMESTAMPTZ '1970-01-01+00') AS sort_created
            FROM watched_tv_shows wt
            JOIN tv_shows t ON t.tmdb_id = wt.tmdb_id
            JOIN profiles p ON p.id = wt.user_id
            WHERE wt.user_id IN ({user_sql})
        """

    sql = f"""
        SELECT media_type, log_id, user_id, username, display_name, avatar_url,
               tmdb_id, title, poster_path, rating, watched_date, created_at,
               sort_date, sort_created
        FROM (
            SELECT 'movie' AS media_type,
                   wm.id AS log_id,
                   wm.user_id::text AS user_id,
                   p.username,
                   p.display_name,
                   p.avatar_url,
                   wm.tmdb_id,
                   m.title,
                   m.poster_path,
                   wm.rating,
                   wm.watched_date,
                   wm.created_at,
                   COALESCE(
                       wm.watched_date,
                       (wm.created_at AT TIME ZONE 'UTC')::date,
                       DATE '1970-01-01'
                   ) AS sort_date,
                   COALESCE(wm.created_at, TIMESTAMPTZ '1970-01-01+00') AS sort_created
            FROM watched_movies wm
            JOIN movies m ON m.tmdb_id = wm.tmdb_id
            JOIN profiles p ON p.id = wm.user_id
            WHERE wm.user_id IN ({user_sql})
            {tv_sql}
        ) logs
        {cursor_sql}
        ORDER BY sort_date DESC, sort_created DESC, media_type DESC, log_id DESC
        LIMIT :limit
    """
    rows = db.execute(text(sql), params).mappings().all()
    page = rows[:limit]
    companions = _companions_for(
        [row["log_id"] for row in page if row["media_type"] == "movie"],
        _blocked_ids(viewer_id, db),
        db,
    )
    results = []
    for row in page:
        results.append(
            {
                "media_type": row["media_type"],
                "id": row["log_id"],
                "tmdb_id": row["tmdb_id"],
                "title": row["title"],
                "poster_path": row["poster_path"],
                "rating": row["rating"],
                "watched_date": row["watched_date"],
                "created_at": row["created_at"],
                "user": {
                    "user_id": row["user_id"],
                    "username": row["username"],
                    "display_name": row["display_name"],
                    "avatar_url": row["avatar_url"],
                },
                "watched_with": companions.get(row["log_id"], [])
                if row["media_type"] == "movie"
                else [],
            }
        )
    next_cursor = None
    if len(rows) > limit and page:
        last = page[-1]
        next_cursor = _encode_cursor(
            last["sort_date"],
            last["sort_created"],
            last["media_type"],
            last["log_id"],
        )
    return {"results": results, "next_cursor": next_cursor}


def _companions_for(
    movie_log_ids: list[int], blocked: set[str], db: Session
) -> dict[int, list[dict]]:
    if not movie_log_ids:
        return {}
    id_sql, params = _in_clause("m", movie_log_ids)
    rows = (
        db.execute(
            text(
                f"""
            SELECT w.watched_movie_id AS log_id,
                   p.id::text AS user_id,
                   p.username,
                   p.display_name,
                   p.avatar_url
            FROM watched_with w
            JOIN profiles p ON p.id = w.user_id
            WHERE w.watched_movie_id IN ({id_sql})
            ORDER BY p.username
            """
            ),
            params,
        )
        .mappings()
        .all()
    )
    grouped: dict[int, list[dict]] = {}
    for row in rows:
        if row["user_id"] in blocked:
            continue
        grouped.setdefault(row["log_id"], []).append(
            {
                "user_id": row["user_id"],
                "username": row["username"],
                "display_name": row["display_name"],
                "avatar_url": row["avatar_url"],
            }
        )
    return grouped


def _in_clause(prefix: str, values: list, cast: str | None = None) -> tuple[str, dict]:
    params: dict = {}
    parts: list[str] = []
    for index, value in enumerate(values):
        key = f"{prefix}{index}"
        parts.append(f"CAST(:{key} AS {cast})" if cast else f":{key}")
        params[key] = value
    return ", ".join(parts), params


def _encode_cursor(
    sort_date: date, created_at: datetime, media_type: str, log_id: int
) -> str:
    raw = f"{sort_date.isoformat()}|{created_at.isoformat()}|{media_type}|{log_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str, tv_enabled: bool) -> tuple[date, datetime, str, int]:
    padding = "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(cursor + padding).decode()
        date_s, created_s, media_type, id_s = raw.split("|")
        sort_date = date.fromisoformat(date_s)
        created_at = datetime.fromisoformat(created_s)
        log_id = int(id_s)
    except (ValueError, binascii.Error, UnicodeDecodeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid cursor"
        ) from None
    if media_type not in ("movie", "tv") or (media_type == "tv" and not tv_enabled):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid cursor"
        )
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return sort_date, created_at, media_type, log_id
