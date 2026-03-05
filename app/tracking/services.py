from datetime import date

import httpx
from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.movies.models import Movie
from app.movies.services import get_movie_details
from app.tracking.models import WatchedMovie, WatchlistMovie
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
) -> dict:
    """Track a movie — upserts if already tracked."""
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
        db.commit()
        db.refresh(existing)
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
        db.commit()
        db.refresh(entry)

    movie = db.query(Movie).filter(Movie.tmdb_id == tmdb_id).first()
    return _to_response(entry, movie)


def get_watch_history(user_id: str, limit: int, offset: int, db: Session) -> dict:
    """Get paginated watch history for a user."""
    total = (
        db.query(func.count(WatchedMovie.id))
        .filter(WatchedMovie.user_id == user_id)
        .scalar()
    )

    rows = (
        db.query(WatchedMovie, Movie)
        .join(Movie, WatchedMovie.tmdb_id == Movie.tmdb_id)
        .filter(WatchedMovie.user_id == user_id)
        .order_by(
            WatchedMovie.watched_date.desc().nulls_last(),
            WatchedMovie.created_at.desc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )

    results = [_to_response(entry, movie) for entry, movie in rows]
    return {"results": results, "total": total or 0}


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
    return _to_response(row[0], row[1])


def update_watched_movie(
    user_id: str, tmdb_id: int, updates: UpdateTrackingRequest, db: Session
) -> dict:
    """Update rating/review/watched_date on an existing entry."""
    entry = (
        db.query(WatchedMovie)
        .filter(WatchedMovie.user_id == user_id, WatchedMovie.tmdb_id == tmdb_id)
        .first()
    )
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Movie not in watch history"
        )

    update_data = updates.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(entry, field, value)

    db.commit()
    db.refresh(entry)

    movie = db.query(Movie).filter(Movie.tmdb_id == tmdb_id).first()
    return _to_response(entry, movie)


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
    watchlist_id: int, db: Session, limit: int = 20, offset: int = 0
) -> dict:
    """Get paginated watchlist movies."""
    total = (
        db.query(func.count(WatchlistMovie.id))
        .filter(WatchlistMovie.watchlist_id == watchlist_id)
        .scalar()
    )

    rows = (
        db.query(WatchlistMovie, Movie)
        .join(Movie, WatchlistMovie.tmdb_id == Movie.tmdb_id)
        .filter(WatchlistMovie.watchlist_id == watchlist_id)
        .order_by(WatchlistMovie.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    results = [_watchlist_to_response(entry, movie) for entry, movie in rows]
    return {"results": results, "total": total or 0}


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


def _watchlist_to_response(entry: WatchlistMovie, movie: Movie | None) -> dict:
    """Convert a WatchlistMovie + Movie pair to response dict."""
    return {
        "id": entry.id,
        "tmdb_id": entry.tmdb_id,
        "title": movie.title if movie else "Unknown",
        "poster_path": movie.poster_path if movie else None,
        "added_by": str(entry.added_by) if entry.added_by else None,
        "added_date": entry.added_date,
        "created_at": entry.created_at,
    }


def _to_response(entry: WatchedMovie, movie: Movie | None) -> dict:
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
    }
