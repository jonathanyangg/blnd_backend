"""Test data factory helpers."""

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.models import Profile
from app.friends.models import Friendship
from app.groups.models import Group, GroupMember
from app.movies.models import Movie
from app.tracking.models import Watchlist, WatchedMovie, WatchlistMovie


def _ensure_auth_user(db: Session, uid: uuid.UUID) -> None:
    """Insert a dummy row into auth.users to satisfy the profiles FK."""
    db.execute(
        text(
            "INSERT INTO auth.users (id, instance_id, aud, role, email, created_at, updated_at) "
            "VALUES (:id, '00000000-0000-0000-0000-000000000000', 'authenticated', "
            "'authenticated', :email, now(), now()) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": str(uid), "email": f"{uid}@test.local"},
    )
    db.flush()


def make_profile(
    db: Session,
    user_id: str | None = None,
    username: str = "testuser",
    display_name: str | None = None,
    watchlist_id: int | None = None,
    favorite_genres: list[str] | None = None,
    phone_number: str | None = None,
    is_discoverable: bool = True,
    is_test: bool = False,
) -> Profile:
    uid = uuid.UUID(user_id) if user_id else uuid.uuid4()
    _ensure_auth_user(db, uid)
    profile = Profile(
        id=uid,
        username=username,
        display_name=display_name,
        watchlist_id=watchlist_id,
        favorite_genres=favorite_genres,
        phone_number=phone_number,
        is_discoverable=is_discoverable,
        is_test=is_test,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def make_movie(
    db: Session,
    tmdb_id: int = 550,
    title: str = "Fight Club",
    year: int | None = 1999,
    overview: str | None = "An insomniac office worker...",
    poster_path: str | None = "/poster.jpg",
    genres: list[dict] | None = None,
    vote_average: float | None = 8.4,
    director: str | None = "David Fincher",
    cast: list[dict] | None = None,
) -> Movie:
    movie = Movie(
        tmdb_id=tmdb_id,
        title=title,
        year=year,
        overview=overview,
        poster_path=poster_path,
        genres=genres or [{"id": 18, "name": "Drama"}],
        vote_average=vote_average,
        director=director,
        cast=cast or [{"name": "Brad Pitt"}],
    )
    db.add(movie)
    db.commit()
    db.refresh(movie)
    return movie


def make_watched(
    db: Session,
    user_id: str,
    tmdb_id: int = 550,
    rating: float | None = None,
    review: str | None = None,
    source: str = "manual",
) -> WatchedMovie:
    entry = WatchedMovie(
        user_id=user_id,
        tmdb_id=tmdb_id,
        rating=rating,
        review=review,
        source=source,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def make_watchlist(db: Session) -> Watchlist:
    wl = Watchlist()
    db.add(wl)
    db.commit()
    db.refresh(wl)
    return wl


def make_watchlist_movie(
    db: Session,
    watchlist_id: int,
    tmdb_id: int,
    added_by: str | None = None,
) -> WatchlistMovie:
    entry = WatchlistMovie(
        watchlist_id=watchlist_id,
        tmdb_id=tmdb_id,
        added_by=added_by,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def make_friendship(
    db: Session,
    requester_id: str,
    addressee_id: str,
    status: str = "pending",
) -> Friendship:
    f = Friendship(
        requester_id=requester_id,
        addressee_id=addressee_id,
        status=status,
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    return f


def make_group(
    db: Session,
    name: str = "Test Group",
    created_by: str = "00000000-0000-0000-0000-000000000001",
) -> tuple[Group, Watchlist]:
    """Create a group with watchlist and creator as member."""
    wl = make_watchlist(db)
    group = Group(name=name, created_by=created_by, watchlist_id=wl.id)
    db.add(group)
    db.flush()
    member = GroupMember(group_id=group.id, user_id=created_by)
    db.add(member)
    db.commit()
    db.refresh(group)
    return group, wl
