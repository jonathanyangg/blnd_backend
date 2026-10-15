from datetime import date

import httpx
from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from sqlalchemy import or_

from app.auth.models import Profile
from app.friends.models import Friendship, UserBlock
from app.groups.models import GroupMember
from app.movies.models import Movie
from app.movies.services import get_movie_details
from app.tracking.models import (
    ActivityFeedItem,
    WatchedMovie,
    WatchedWith,
    WatchlistMovie,
)
from app.tracking.schemas import UpdateTrackingRequest


async def track_movie(
    user_id: str,
    tmdb_id: int,
    rating: float | None,
    review: str | None,
    watched_date: date | None,
    db: Session,
    tmdb_client: httpx.AsyncClient,
    source: str = "manual",
    watched_with: list | None = None,
) -> dict:
    """Track a movie — upserts if already tracked.

    When watched_with is not None, replace the tagged companions. Omitted
    leaves any existing tags in place. Tags must be accepted friends or
    Blend members, and not the owner.
    """
    companion_ids = (
        None
        if watched_with is None
        else _validate_companion_ids(user_id, watched_with, db)
    )
    # Ensure movie is cached (FK constraint)
    await get_movie_details(tmdb_id, db, tmdb_client)

    existing = (
        db.query(WatchedMovie)
        .filter(WatchedMovie.user_id == user_id, WatchedMovie.tmdb_id == tmdb_id)
        .first()
    )

    if existing:
        if rating is not None:
            existing.rating = rating
        if review is not None:
            existing.review = review
        if watched_date is not None:
            existing.watched_date = watched_date
        entry = existing
    else:
        entry = WatchedMovie(
            user_id=user_id,
            tmdb_id=tmdb_id,
            rating=rating,
            review=review,
            watched_date=watched_date,
            source=source,
        )
        db.add(entry)
    db.flush()
    if companion_ids is not None:
        _replace_companions(entry.id, user_id, companion_ids, db)

    # Remove from user's personal watchlist if present
    profile = db.query(Profile).filter(Profile.id == user_id).first()
    if profile and profile.watchlist_id:
        db.query(WatchlistMovie).filter(
            WatchlistMovie.watchlist_id == profile.watchlist_id,
            WatchlistMovie.tmdb_id == tmdb_id,
        ).delete()

    db.commit()
    db.refresh(entry)

    movie = db.query(Movie).filter(Movie.tmdb_id == tmdb_id).first()
    companions = _companions_for([entry.id], db).get(entry.id, [])
    return _to_response(entry, movie, companions)


def get_watch_history(
    user_id: str,
    limit: int,
    offset: int,
    db: Session,
    q: str | None = None,
    sort: str | None = None,
) -> dict:
    """Get paginated watch history for a user, with optional title filter + sort."""
    base = (
        db.query(WatchedMovie, Movie)
        .join(Movie, WatchedMovie.tmdb_id == Movie.tmdb_id)
        .filter(WatchedMovie.user_id == user_id)
    )
    if q:
        base = base.filter(Movie.title.ilike(f"%{q}%"))

    total = base.with_entities(func.count(WatchedMovie.id)).scalar() or 0

    rows = base.order_by(*_watched_order_by(sort)).offset(offset).limit(limit).all()

    companions = _companions_for([entry.id for entry, _movie in rows], db)
    results = [
        _to_response(entry, movie, companions.get(entry.id, []))
        for entry, movie in rows
    ]
    return {"results": results, "total": total}


def _watched_order_by(sort: str | None):
    """SQL ORDER BY clause for watched movies, based on sort key."""
    if sort == "date_asc":
        return (
            WatchedMovie.watched_date.asc().nulls_first(),
            WatchedMovie.created_at.asc(),
        )
    if sort == "rating_desc":
        return (
            WatchedMovie.rating.desc().nulls_last(),
            WatchedMovie.watched_date.desc().nulls_last(),
        )
    if sort == "rating_asc":
        return (
            WatchedMovie.rating.asc().nulls_last(),
            WatchedMovie.watched_date.desc().nulls_last(),
        )
    if sort == "title_asc":
        return (Movie.title.asc(),)
    if sort == "title_desc":
        return (Movie.title.desc(),)
    if sort == "year_desc":
        return (Movie.year.desc().nulls_last(), Movie.title.asc())
    if sort == "year_asc":
        return (Movie.year.asc().nulls_last(), Movie.title.asc())
    # default: date_desc (prior behavior)
    return (
        WatchedMovie.watched_date.desc().nulls_last(),
        WatchedMovie.created_at.desc(),
    )


def get_watched_movie(user_id: str, tmdb_id: int, db: Session) -> dict | None:
    """Get a single watched movie entry."""
    row = (
        db.query(WatchedMovie, Movie)
        .join(Movie, WatchedMovie.tmdb_id == Movie.tmdb_id)
        .filter(WatchedMovie.user_id == user_id, WatchedMovie.tmdb_id == tmdb_id)
        .first()
    )
    if not row:
        return None
    companions = _companions_for([row[0].id], db).get(row[0].id, [])
    return _to_response(row[0], row[1], companions)


def update_watched_movie(
    user_id: str, tmdb_id: int, updates: UpdateTrackingRequest, db: Session
) -> dict:
    """Update rating/review/watched_date/companions on an existing entry.

    watched_with replaces the tag list when present. Null or omitted leaves it.
    """
    entry = (
        db.query(WatchedMovie)
        .filter(WatchedMovie.user_id == user_id, WatchedMovie.tmdb_id == tmdb_id)
        .first()
    )
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Movie not in watch history"
        )

    data = updates.model_dump(exclude_unset=True)
    companion_ids = None
    if "watched_with" in data and data["watched_with"] is not None:
        companion_ids = _validate_companion_ids(user_id, data["watched_with"], db)
    if "rating" in data:
        entry.rating = data["rating"]
    if "review" in data:
        entry.review = data["review"]
    if "watched_date" in data:
        entry.watched_date = data["watched_date"]
    if companion_ids is not None:
        _replace_companions(entry.id, user_id, companion_ids, db)

    db.commit()
    db.refresh(entry)

    movie = db.query(Movie).filter(Movie.tmdb_id == tmdb_id).first()
    companions = _companions_for([entry.id], db).get(entry.id, [])
    return _to_response(entry, movie, companions)


def delete_watched_movie(user_id: str, tmdb_id: int, db: Session) -> None:
    """Delete a watched movie entry."""
    entry = (
        db.query(WatchedMovie)
        .filter(WatchedMovie.user_id == user_id, WatchedMovie.tmdb_id == tmdb_id)
        .first()
    )
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Movie not in watch history"
        )
    db.delete(entry)
    db.commit()


def get_watchlist(
    watchlist_id: int,
    db: Session,
    limit: int = 20,
    offset: int = 0,
    q: str | None = None,
    sort: str | None = None,
) -> dict:
    """Get paginated watchlist movies, with optional title filter + sort."""
    base = (
        db.query(WatchlistMovie, Movie)
        .join(Movie, WatchlistMovie.tmdb_id == Movie.tmdb_id)
        .filter(WatchlistMovie.watchlist_id == watchlist_id)
    )
    if q:
        base = base.filter(Movie.title.ilike(f"%{q}%"))

    total = base.with_entities(func.count(WatchlistMovie.id)).scalar() or 0

    rows = base.order_by(*_watchlist_order_by(sort)).offset(offset).limit(limit).all()

    results = [_watchlist_to_response(entry, movie) for entry, movie in rows]

    from app.comments.services import get_comment_counts

    counts = get_comment_counts([r["tmdb_id"] for r in results], db)
    for r in results:
        r["comment_count"] = counts.get(r["tmdb_id"], 0)

    return {"results": results, "total": total}


def _watchlist_order_by(sort: str | None):
    """SQL ORDER BY for watchlist. Rating sorts are meaningless here and ignored."""
    if sort == "date_asc":
        return (WatchlistMovie.created_at.asc(),)
    if sort == "title_asc":
        return (Movie.title.asc(),)
    if sort == "title_desc":
        return (Movie.title.desc(),)
    if sort == "year_desc":
        return (Movie.year.desc().nulls_last(), Movie.title.asc())
    if sort == "year_asc":
        return (Movie.year.asc().nulls_last(), Movie.title.asc())
    # default: date_desc (prior behavior)
    return (WatchlistMovie.created_at.desc(),)


async def add_to_watchlist(
    watchlist_id: int,
    tmdb_id: int,
    user_id: str,
    db: Session,
    tmdb_client: httpx.AsyncClient,
    source: str = "manual",
) -> dict:
    """Add a movie to a watchlist, auto-caching from TMDB."""
    await get_movie_details(tmdb_id, db, tmdb_client)

    existing = (
        db.query(WatchlistMovie)
        .filter(
            WatchlistMovie.watchlist_id == watchlist_id,
            WatchlistMovie.tmdb_id == tmdb_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Movie already in watchlist",
        )

    entry = WatchlistMovie(
        watchlist_id=watchlist_id,
        tmdb_id=tmdb_id,
        added_by=user_id,
        source=source,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)

    movie = db.query(Movie).filter(Movie.tmdb_id == tmdb_id).first()
    return _watchlist_to_response(entry, movie)


def remove_from_watchlist(watchlist_id: int, tmdb_id: int, db: Session) -> None:
    """Remove a movie from a watchlist."""
    entry = (
        db.query(WatchlistMovie)
        .filter(
            WatchlistMovie.watchlist_id == watchlist_id,
            WatchlistMovie.tmdb_id == tmdb_id,
        )
        .first()
    )
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Movie not in watchlist",
        )
    db.delete(entry)
    db.commit()


def get_watchlist_status(user_id: str, tmdb_id: int, db: Session) -> dict:
    """Check which of the user's watchlists contain a movie."""
    from app.groups.models import Group, GroupMember

    # Get personal watchlist_id
    profile = db.query(Profile).filter(Profile.id == user_id).first()
    personal_watchlist_id = profile.watchlist_id if profile else None

    # Get all group watchlist_ids for this user
    group_rows = (
        db.query(Group.id, Group.watchlist_id)
        .join(GroupMember, Group.id == GroupMember.group_id)
        .filter(GroupMember.user_id == user_id, Group.watchlist_id.isnot(None))
        .all()
    )

    # Collect all watchlist_ids to check in one query
    watchlist_id_map: dict[int, int | None] = {}  # watchlist_id -> group_id or None
    if personal_watchlist_id:
        watchlist_id_map[personal_watchlist_id] = None
    for group_id, watchlist_id in group_rows:
        if watchlist_id:
            watchlist_id_map[watchlist_id] = group_id

    if not watchlist_id_map:
        return {"personal": False, "group_ids": []}

    # Single query: which of these watchlists contain the movie?
    matching = (
        db.query(WatchlistMovie.watchlist_id)
        .filter(
            WatchlistMovie.watchlist_id.in_(list(watchlist_id_map.keys())),
            WatchlistMovie.tmdb_id == tmdb_id,
        )
        .all()
    )
    matching_ids = {row[0] for row in matching}

    personal = personal_watchlist_id in matching_ids if personal_watchlist_id else False
    group_ids = [
        watchlist_id_map[wid]
        for wid in matching_ids
        if watchlist_id_map[wid] is not None
    ]

    return {"personal": personal, "group_ids": group_ids}


def _watchlist_to_response(entry: WatchlistMovie, movie: Movie | None) -> dict:
    """Convert a WatchlistMovie + Movie pair to response dict."""
    vote = movie.vote_average if movie else None
    return {
        "id": entry.id,
        "tmdb_id": entry.tmdb_id,
        "title": movie.title if movie else "Unknown",
        "year": movie.year if movie else None,
        "overview": movie.overview if movie else None,
        "poster_path": movie.poster_path if movie else None,
        "backdrop_path": movie.backdrop_path if movie else None,
        "genres": movie.genres or [] if movie else [],
        "runtime": movie.runtime if movie else None,
        "vote_average": round(vote / 2, 1) if vote else None,
        "trailer_url": movie.trailer_url if movie else None,
        "director": movie.director if movie else None,
        "cast": (movie.cast or [])[:5] if movie else [],
        "tagline": movie.tagline if movie else None,
        "added_by": str(entry.added_by) if entry.added_by else None,
        "added_date": entry.added_date,
        "created_at": entry.created_at,
    }


def get_friends_who_watched(
    user_id: str, tmdb_id: int, db: Session, limit: int = 20, offset: int = 0
) -> dict:
    """Get friends who watched a specific movie, with their ratings."""
    # Get accepted friend IDs (both directions)
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

    friend_ids = []
    for f in friendships:
        fid = f.addressee_id if str(f.requester_id) == user_id else f.requester_id
        friend_ids.append(str(fid))

    if not friend_ids:
        return {"results": [], "total": 0}

    # Count total friends who watched
    total = (
        db.query(func.count(WatchedMovie.id))
        .filter(WatchedMovie.user_id.in_(friend_ids), WatchedMovie.tmdb_id == tmdb_id)
        .scalar()
    )

    # Query watched entries joined with profile
    rows = (
        db.query(WatchedMovie, Profile)
        .join(Profile, WatchedMovie.user_id == Profile.id)
        .filter(WatchedMovie.user_id.in_(friend_ids), WatchedMovie.tmdb_id == tmdb_id)
        .order_by(WatchedMovie.rating.desc().nulls_last())
        .offset(offset)
        .limit(limit)
        .all()
    )

    results = [
        {
            "user_id": str(p.id),
            "username": p.username,
            "display_name": p.display_name,
            "avatar_url": p.avatar_url,
            "rating": w.rating,
            "review": w.review,
            "watched_date": w.watched_date,
        }
        for w, p in rows
    ]

    return {"results": results, "total": total or 0}


def _to_response(
    entry: WatchedMovie,
    movie: Movie | None,
    companions: list[dict] | None = None,
) -> dict:
    """Convert a WatchedMovie + Movie pair to response dict."""
    return {
        "id": entry.id,
        "tmdb_id": entry.tmdb_id,
        "title": movie.title if movie else "Unknown",
        "poster_path": movie.poster_path if movie else None,
        "rating": entry.rating,
        "review": entry.review,
        "watched_date": entry.watched_date,
        "liked": entry.liked,
        "created_at": entry.created_at,
        "watched_with": companions or [],
    }


def _validate_companion_ids(
    owner_id: str, companion_ids: list, db: Session
) -> list[str]:
    """Dedupe companion ids. Each must be an accepted friend or Blend member.

    The owner cannot tag themselves. A block in either direction rejects the
    tag even when the two users still share a Blend.
    """
    deduped: list[str] = []
    seen: set[str] = set()
    for raw in companion_ids:
        companion_id = str(raw)
        if companion_id in seen:
            continue
        seen.add(companion_id)
        deduped.append(companion_id)
    if not deduped:
        return []
    if owner_id in seen:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only tag friends or Blend members",
        )
    allowed = _taggable_user_ids(owner_id, db)
    if any(companion_id not in allowed for companion_id in deduped):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only tag friends or Blend members",
        )
    blocked = (
        db.query(UserBlock.id)
        .filter(
            or_(
                (UserBlock.blocker_id == owner_id)
                & (UserBlock.blocked_id.in_(deduped)),
                (UserBlock.blocked_id == owner_id)
                & (UserBlock.blocker_id.in_(deduped)),
            )
        )
        .first()
    )
    if blocked:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only tag friends or Blend members",
        )
    return deduped


def _taggable_user_ids(owner_id: str, db: Session) -> set[str]:
    """Accepted friends plus anyone who shares a Blend with the owner."""
    friendships = (
        db.query(Friendship.requester_id, Friendship.addressee_id)
        .filter(
            Friendship.status == "accepted",
            or_(
                Friendship.requester_id == owner_id,
                Friendship.addressee_id == owner_id,
            ),
        )
        .all()
    )
    allowed: set[str] = set()
    for requester_id, addressee_id in friendships:
        other = addressee_id if str(requester_id) == owner_id else requester_id
        allowed.add(str(other))

    blend_ids = [
        row[0]
        for row in db.query(GroupMember.group_id)
        .filter(GroupMember.user_id == owner_id)
        .all()
    ]
    if blend_ids:
        members = (
            db.query(GroupMember.user_id)
            .filter(
                GroupMember.group_id.in_(blend_ids),
                GroupMember.user_id != owner_id,
            )
            .all()
        )
        allowed.update(str(row[0]) for row in members)
    return allowed


def _replace_companions(
    watched_movie_id: int, owner_id: str, companion_ids: list[str], db: Session
) -> None:
    """Replace the companion set for one watch log. Caller commits."""
    db.query(WatchedWith).filter(
        WatchedWith.watched_movie_id == watched_movie_id
    ).delete(synchronize_session=False)
    for companion_id in companion_ids:
        db.add(
            WatchedWith(
                watched_movie_id=watched_movie_id,
                owner_id=owner_id,
                user_id=companion_id,
            )
        )


def _companions_for(entry_ids: list[int], db: Session) -> dict[int, list[dict]]:
    """Batch-load companions for watch logs, ordered by username within each log."""
    if not entry_ids:
        return {}
    rows = (
        db.query(WatchedWith, Profile)
        .join(Profile, WatchedWith.user_id == Profile.id)
        .filter(WatchedWith.watched_movie_id.in_(entry_ids))
        .order_by(Profile.username.asc())
        .all()
    )
    grouped: dict[int, list[dict]] = {}
    for link, profile in rows:
        grouped.setdefault(link.watched_movie_id, []).append(
            {
                "user_id": str(profile.id),
                "username": profile.username,
                "display_name": profile.display_name,
                "avatar_url": profile.avatar_url,
            }
        )
    return grouped


# --- Activity Feed ---


def record_activity(
    user_id: str, action: str, tmdb_id: int, db: Session, rating: float | None = None
) -> None:
    """Record an activity feed item."""
    item = ActivityFeedItem(
        user_id=user_id, action=action, tmdb_id=tmdb_id, rating=rating
    )
    db.add(item)
    db.commit()


def get_friend_feed(
    user_id: str, db: Session, limit: int = 50, offset: int = 0
) -> dict:
    """Get activity feed from friends, most recent first."""
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
        return {"results": []}

    # Query feed items from friends, joined with profile + movie
    rows = (
        db.query(ActivityFeedItem, Profile, Movie)
        .join(Profile, ActivityFeedItem.user_id == Profile.id)
        .outerjoin(Movie, ActivityFeedItem.tmdb_id == Movie.tmdb_id)
        .filter(ActivityFeedItem.user_id.in_(friend_ids))
        .order_by(ActivityFeedItem.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    results = [
        {
            "id": item.id,
            "user_id": str(profile.id),
            "username": profile.username,
            "display_name": profile.display_name,
            "avatar_url": profile.avatar_url,
            "action": item.action,
            "tmdb_id": item.tmdb_id,
            "title": movie.title if movie else None,
            "poster_path": movie.poster_path if movie else None,
            "rating": item.rating,
            "created_at": item.created_at,
        }
        for item, profile, movie in rows
    ]
    return {"results": results}
