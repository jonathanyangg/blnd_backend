from fastapi import HTTPException, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.auth.models import Profile
from app.dependencies import supabase
from app.friends.models import Friendship
from app.groups.models import GroupMember
from app.movies.models import Movie
from app.tracking.models import WatchedMovie, Watchlist


def signup(
    email: str, password: str, username: str, display_name: str | None, db: Session
) -> dict:
    """Create user via Supabase Auth and insert profile via SQLAlchemy."""
    existing = db.query(Profile).filter(Profile.username == username).first()
    if existing:
        raise ValueError("Username is already taken")

    auth_response = supabase.auth.sign_up({"email": email, "password": password})
    if not auth_response.user or not auth_response.session:
        raise ValueError("Signup failed")

    user_id = auth_response.user.id

    watchlist = Watchlist()
    db.add(watchlist)
    db.flush()

    profile = Profile(
        id=user_id,
        username=username,
        display_name=display_name,
        watchlist_id=watchlist.id,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)

    return {
        "access_token": auth_response.session.access_token,
        "refresh_token": auth_response.session.refresh_token,
        "user_id": str(user_id),
    }


def login(email: str, password: str) -> dict:
    """Login via Supabase Auth."""
    auth_response = supabase.auth.sign_in_with_password(
        {"email": email, "password": password}
    )
    if not auth_response.user or not auth_response.session:
        raise ValueError("Login failed")

    return {
        "access_token": auth_response.session.access_token,
        "refresh_token": auth_response.session.refresh_token,
        "user_id": str(auth_response.user.id),
    }


def refresh_session(refresh_token: str) -> dict:
    """Refresh session via Supabase Auth."""
    auth_response = supabase.auth.refresh_session(refresh_token)
    if not auth_response.user or not auth_response.session:
        raise ValueError("Refresh failed")

    return {
        "access_token": auth_response.session.access_token,
        "refresh_token": auth_response.session.refresh_token,
        "user_id": str(auth_response.user.id),
    }


def get_profile(user_id: str, db: Session) -> Profile | None:
    return db.query(Profile).filter(Profile.id == user_id).first()


def search_users(query: str, user_id: str, db: Session, limit: int = 10) -> list[dict]:
    """Search users by username prefix (ILIKE), excluding the current user."""
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    profiles = (
        db.query(Profile)
        .filter(Profile.username.ilike(f"{escaped}%"), Profile.id != user_id)
        .limit(limit)
        .all()
    )
    return [
        {
            "id": str(p.id),
            "username": p.username,
            "display_name": p.display_name,
            "avatar_url": p.avatar_url,
        }
        for p in profiles
    ]


def update_profile(
    user_id: str, updates: dict, db: Session
) -> tuple[Profile | None, bool]:
    """Update profile fields. Returns (profile, genres_changed)."""
    profile = db.query(Profile).filter(Profile.id == user_id).first()
    if not profile:
        return None, False

    genres_changed = False

    if "username" in updates:
        new_username = updates["username"]
        if new_username != profile.username:
            conflict = (
                db.query(Profile)
                .filter(Profile.username == new_username, Profile.id != profile.id)
                .first()
            )
            if conflict:
                raise ValueError("Username is already taken")
            profile.username = new_username
    if "display_name" in updates:
        profile.display_name = updates["display_name"]
    if "avatar_url" in updates:
        profile.avatar_url = updates["avatar_url"]
    if "favorite_genres" in updates:
        old_genres = profile.favorite_genres or []
        new_genres = updates["favorite_genres"]
        if set(old_genres) != set(new_genres):
            genres_changed = True
        profile.favorite_genres = new_genres

    db.commit()
    db.refresh(profile)
    return profile, genres_changed


def assert_are_friends(caller_id: str, target_id: str, db: Session) -> None:
    """Raise 403 if caller and target are not accepted friends."""
    friendship = (
        db.query(Friendship)
        .filter(
            Friendship.status == "accepted",
            or_(
                (Friendship.requester_id == caller_id)
                & (Friendship.addressee_id == target_id),
                (Friendship.requester_id == target_id)
                & (Friendship.addressee_id == caller_id),
            ),
        )
        .first()
    )
    if not friendship:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not friends with this user",
        )


def get_public_profile(caller_id: str, target_id: str, db: Session) -> dict:
    """Get public profile stats for another user. Requires friendship."""
    assert_are_friends(caller_id, target_id, db)

    profile = db.query(Profile).filter(Profile.id == target_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="User not found")

    watched_count = (
        db.query(func.count(WatchedMovie.id))
        .filter(WatchedMovie.user_id == target_id)
        .scalar()
        or 0
    )

    friends_count = (
        db.query(func.count(Friendship.id))
        .filter(
            Friendship.status == "accepted",
            or_(
                Friendship.requester_id == target_id,
                Friendship.addressee_id == target_id,
            ),
        )
        .scalar()
        or 0
    )

    blends_count = (
        db.query(func.count(GroupMember.group_id))
        .filter(GroupMember.user_id == target_id)
        .scalar()
        or 0
    )

    return {
        "id": str(profile.id),
        "username": profile.username,
        "display_name": profile.display_name,
        "avatar_url": profile.avatar_url,
        "watched_count": watched_count,
        "friends_count": friends_count,
        "blends_count": blends_count,
    }


def get_public_watched(
    caller_id: str, target_id: str, limit: int, offset: int, db: Session
) -> dict:
    """Get paginated watched movies for another user. Requires friendship."""
    assert_are_friends(caller_id, target_id, db)

    total = (
        db.query(func.count(WatchedMovie.id))
        .filter(WatchedMovie.user_id == target_id)
        .scalar()
        or 0
    )

    rows = (
        db.query(WatchedMovie, Movie)
        .join(Movie, WatchedMovie.tmdb_id == Movie.tmdb_id)
        .filter(WatchedMovie.user_id == target_id)
        .order_by(
            WatchedMovie.watched_date.desc().nulls_last(),
            WatchedMovie.created_at.desc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )

    results = [
        {
            "tmdb_id": entry.tmdb_id,
            "title": movie.title,
            "poster_path": movie.poster_path,
            "rating": entry.rating,
        }
        for entry, movie in rows
    ]
    return {"results": results, "total": total}


def get_public_friends(caller_id: str, target_id: str, db: Session) -> dict:
    """Get friends list for another user. Requires friendship."""
    assert_are_friends(caller_id, target_id, db)

    friendships = (
        db.query(Friendship)
        .filter(
            Friendship.status == "accepted",
            or_(
                Friendship.requester_id == target_id,
                Friendship.addressee_id == target_id,
            ),
        )
        .all()
    )

    friends = []
    for f in friendships:
        friend_id = (
            f.addressee_id if str(f.requester_id) == target_id else f.requester_id
        )
        profile = db.query(Profile).filter(Profile.id == friend_id).first()
        if profile:
            friends.append(
                {
                    "id": str(profile.id),
                    "username": profile.username,
                    "display_name": profile.display_name,
                    "avatar_url": profile.avatar_url,
                }
            )

    return {"friends": friends}
