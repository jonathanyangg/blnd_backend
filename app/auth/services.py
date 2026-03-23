import logging

import httpx
from fastapi import HTTPException, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.auth.models import Profile
from app.dependencies import supabase
from app.friends.models import Friendship
from app.groups.models import GroupMember
from app.movies.models import Movie
from app.movies.services import get_movie_details
from app.tracking.models import WatchedMovie, Watchlist

logger = logging.getLogger(__name__)


TASTE_GENRES = [
    "Action",
    "Comedy",
    "Drama",
    "Horror",
    "Sci-Fi",
    "Romance",
    "Thriller",
    "Animation",
]

GENRE_ALIASES: dict[str, set[str]] = {
    "Sci-Fi": {"science fiction"},
}


def _normalize_genre(raw_name: str) -> str | None:
    normalized = raw_name.strip().lower()
    for label in TASTE_GENRES:
        if normalized == label.lower():
            return label
        if normalized in GENRE_ALIASES.get(label, set()):
            return label
    return None


def get_genre_taste(user_id: str, db: Session) -> dict:
    """Compute per-genre taste scores for a user from their watch history."""
    rows = (
        db.query(Movie.genres, WatchedMovie.rating)
        .join(WatchedMovie, WatchedMovie.tmdb_id == Movie.tmdb_id)
        .filter(WatchedMovie.user_id == user_id)
        .all()
    )

    watch_count: dict[str, int] = {g: 0 for g in TASTE_GENRES}
    rating_sum: dict[str, float] = {g: 0.0 for g in TASTE_GENRES}
    rating_count: dict[str, int] = {g: 0 for g in TASTE_GENRES}
    total_rated = sum(1 for _, r in rows if r is not None)

    for genres, rating in rows:
        for genre_obj in genres or []:
            raw_name = (genre_obj.get("name") or "").strip()
            label = _normalize_genre(raw_name)
            if label:
                watch_count[label] += 1
                if rating is not None:
                    rating_sum[label] += rating
                    rating_count[label] += 1

    max_count = max(watch_count.values()) if any(watch_count.values()) else 1

    result = []
    for genre in TASTE_GENRES:
        freq = watch_count[genre] / max_count

        if rating_count[genre] > 0:
            avg_r: float | None = rating_sum[genre] / rating_count[genre]
            norm_rating = (avg_r - 0.5) / 4.5
        elif watch_count[genre] > 0:
            avg_r = None
            norm_rating = 0.5
        else:
            avg_r = None
            norm_rating = 0.0

        score = round(0.60 * freq + 0.40 * norm_rating, 4)
        result.append(
            {
                "name": genre,
                "score": score,
                "watch_count": watch_count[genre],
                "avg_rating": round(avg_r, 2) if avg_r is not None else None,
            }
        )

    return {"genres": result, "total_rated": total_rated}


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


async def oauth_login(
    provider: str,
    id_token: str,
    nonce: str | None,
    db: Session,
    authorization_code: str | None = None,
) -> dict:
    """Exchange an OAuth provider token for BLND session tokens via Supabase."""
    credentials: dict[str, str] = {"provider": provider, "token": id_token}
    if nonce is not None:
        credentials["nonce"] = nonce

    # Let AuthApiError propagate -- view layer catches it and returns 401
    auth_response = supabase.auth.sign_in_with_id_token(credentials)  # type: ignore[arg-type]

    if not auth_response.user or not auth_response.session:
        raise ValueError("OAuth login failed: missing user or session")

    user_id = str(auth_response.user.id)

    # Check if profile exists to determine new vs returning user
    profile = db.query(Profile).filter(Profile.id == user_id).first()
    is_new_user = profile is None

    # Exchange Apple authorization code for refresh_token
    apple_refresh_token = None
    if authorization_code and provider == "apple":
        try:
            from app.core.apple import exchange_apple_auth_code

            apple_refresh_token = await exchange_apple_auth_code(authorization_code)
            if profile:  # returning user -- store immediately
                profile.apple_refresh_token = apple_refresh_token
                db.commit()
        except Exception:
            logger.warning("Apple auth code exchange failed, continuing login")

    return {
        "access_token": auth_response.session.access_token,
        "refresh_token": auth_response.session.refresh_token,
        "user_id": user_id,
        "is_new_user": is_new_user,
        "apple_refresh_token": apple_refresh_token,
    }


async def complete_onboarding(
    user_id: str,
    username: str,
    display_name: str | None,
    favorite_genres: list[str] | None,
    rated_movies: list[dict] | None,
    db: Session,
    tmdb_client: httpx.AsyncClient,
    apple_refresh_token: str | None = None,
) -> dict:
    """Create Profile + Watchlist + WatchedMovie rows atomically for a new OAuth user."""
    # Guard: profile already exists (double-submit protection)
    existing = db.query(Profile).filter(Profile.id == user_id).first()
    if existing:
        raise ValueError("Profile already exists")

    # Check username uniqueness (same pattern as signup)
    conflict = db.query(Profile).filter(Profile.username == username).first()
    if conflict:
        raise ValueError("Username is already taken")

    # Create watchlist (FK dependency for profile)
    watchlist = Watchlist()
    db.add(watchlist)
    db.flush()

    # Create profile
    profile = Profile(
        id=user_id,
        username=username,
        display_name=display_name,
        favorite_genres=favorite_genres,
        watchlist_id=watchlist.id,
        apple_refresh_token=apple_refresh_token,
    )
    db.add(profile)

    # Cache and track rated movies
    if rated_movies:
        for movie in rated_movies:
            await get_movie_details(movie["tmdb_id"], db, tmdb_client)
            watched = WatchedMovie(
                user_id=user_id,
                tmdb_id=movie["tmdb_id"],
                rating=movie["rating"],
                source="onboarding",
            )
            db.add(watched)

    db.commit()
    db.refresh(profile)

    return {"user_id": str(profile.id), "username": profile.username}
