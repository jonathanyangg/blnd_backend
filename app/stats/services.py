"""blnd+ stats. Aggregates run in SQL over one user's watches.

No cache: a cached year would be wrong as soon as they log a film, and each
query is one index scan of that user's rows.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.models import Profile
from app.auth.services import assert_are_friends

HIGH_RATING = 4.0
DISAGREEMENT_GAP = 1.5
RATING_SPAN = 4.5  # ratings run from 0.5 to 5.0
LIST_LIMIT = 5
RATING_WEIGHT = 0.7

_YEAR_SQL = """
WITH watches AS (
    SELECT
        w.rating,
        w.liked,
        w.tmdb_id,
        COALESCE(w.watched_date, (w.created_at AT TIME ZONE 'UTC')::date) AS seen_on,
        m.title,
        m.poster_path,
        m.year AS movie_year,
        m.runtime,
        m.director,
        m.genres
    FROM watched_movies w
    JOIN movies m ON m.tmdb_id = w.tmdb_id
    WHERE w.user_id = CAST(:user_id AS uuid)
      AND COALESCE(w.watched_date, (w.created_at AT TIME ZONE 'UTC')::date)
          >= make_date(:year, 1, 1)
      AND COALESCE(w.watched_date, (w.created_at AT TIME ZONE 'UTC')::date)
          < (make_date(:year, 1, 1) + interval '1 year')::date
),
counts AS (
    SELECT
        COUNT(*)::int AS watched,
        COUNT(rating)::int AS rated,
        COUNT(*) FILTER (WHERE liked)::int AS liked,
        COALESCE(SUM(runtime), 0)::int AS minutes
    FROM watches
),
monthly AS (
    SELECT COALESCE(jsonb_object_agg(month, jsonb_build_object(
        'count', count, 'minutes', minutes
    )), '{}'::jsonb) AS items
    FROM (
        SELECT EXTRACT(MONTH FROM seen_on)::int AS month,
               COUNT(*)::int AS count,
               COALESCE(SUM(runtime), 0)::int AS minutes
        FROM watches
        GROUP BY 1
    ) s
),
top_rated AS (
    SELECT COALESCE(jsonb_agg(
        jsonb_build_object(
            'tmdb_id', tmdb_id,
            'title', title,
            'poster_path', poster_path,
            'year', movie_year,
            'rating', rating
        )
        ORDER BY rating DESC, seen_on DESC, tmdb_id
    ), '[]'::jsonb) AS items
    FROM (
        SELECT tmdb_id, title, poster_path, movie_year, rating, seen_on
        FROM watches
        WHERE rating IS NOT NULL
        ORDER BY rating DESC, seen_on DESC, tmdb_id
        LIMIT 10
    ) s
),
top_genres AS (
    SELECT COALESCE(jsonb_agg(
        jsonb_build_object('name', name, 'count', count)
        ORDER BY count DESC, name
    ), '[]'::jsonb) AS items
    FROM (
        SELECT g->>'name' AS name, COUNT(*)::int AS count
        FROM watches
        CROSS JOIN LATERAL jsonb_array_elements(COALESCE(genres, '[]'::jsonb)) g
        WHERE COALESCE(g->>'name', '') <> ''
        GROUP BY 1
        ORDER BY count DESC, name
        LIMIT 5
    ) s
),
top_directors AS (
    SELECT COALESCE(jsonb_agg(
        jsonb_build_object('name', name, 'count', count)
        ORDER BY count DESC, name
    ), '[]'::jsonb) AS items
    FROM (
        SELECT director AS name, COUNT(*)::int AS count
        FROM watches
        WHERE director IS NOT NULL AND btrim(director) <> ''
        GROUP BY 1
        ORDER BY count DESC, name
        LIMIT 5
    ) s
)
SELECT
    counts.watched,
    counts.rated,
    counts.liked,
    counts.minutes,
    monthly.items AS monthly,
    top_rated.items AS top_rated,
    top_genres.items AS top_genres,
    top_directors.items AS top_directors
FROM counts, monthly, top_rated, top_genres, top_directors
"""

_BREAKDOWN_GENRES = """
SELECT g->>'name' AS name,
       COUNT(*)::int AS count,
       ROUND(AVG(w.rating)::numeric, 2) AS avg_rating,
       COALESCE(SUM(m.runtime), 0)::int AS minutes
FROM watched_movies w
JOIN movies m ON m.tmdb_id = w.tmdb_id
CROSS JOIN LATERAL jsonb_array_elements(COALESCE(m.genres, '[]'::jsonb)) g
WHERE w.user_id = CAST(:user_id AS uuid)
  AND COALESCE(g->>'name', '') <> ''
GROUP BY 1
ORDER BY count DESC, name
LIMIT :limit
"""

_BREAKDOWN_DIRECTORS = """
SELECT m.director AS name,
       COUNT(*)::int AS count,
       ROUND(AVG(w.rating)::numeric, 2) AS avg_rating,
       COALESCE(SUM(m.runtime), 0)::int AS minutes
FROM watched_movies w
JOIN movies m ON m.tmdb_id = w.tmdb_id
WHERE w.user_id = CAST(:user_id AS uuid)
  AND m.director IS NOT NULL
  AND btrim(m.director) <> ''
GROUP BY 1
ORDER BY count DESC, name
LIMIT :limit
"""

_PAIR_SQL = """
SELECT w.user_id::text AS user_id,
       w.tmdb_id,
       w.rating,
       m.title,
       m.poster_path,
       m.genres
FROM watched_movies w
JOIN movies m ON m.tmdb_id = w.tmdb_id
WHERE w.user_id IN (CAST(:me AS uuid), CAST(:them AS uuid))
"""


def year_in_review(user_id: str, year: int, db: Session) -> dict:
    """Counts, top titles, and monthly runtime for one calendar year.

    A row counts in `year` by watched_date, or by created_at's UTC date when
    watched_date is missing. Minutes are the sum of known runtimes.
    """
    row = db.execute(text(_YEAR_SQL), {"user_id": user_id, "year": year}).one()
    by_month = _month_map(_json(row.monthly))
    return {
        "year": year,
        "counts": {
            "watched": row.watched,
            "rated": row.rated,
            "liked": row.liked,
            "minutes": row.minutes,
        },
        "top_rated": [
            {**item, "rating": float(item["rating"])} for item in _json(row.top_rated)
        ],
        "top_genres": _json(row.top_genres),
        "top_directors": _json(row.top_directors),
        "monthly": [
            {
                "month": month,
                "count": int(by_month.get(month, {}).get("count", 0)),
                "minutes": int(by_month.get(month, {}).get("minutes", 0)),
            }
            for month in range(1, 13)
        ],
    }


def genre_breakdown(user_id: str, db: Session, limit: int) -> dict:
    """All-time genre counts, average rating, and runtime for the caller."""
    rows = db.execute(text(_BREAKDOWN_GENRES), {"user_id": user_id, "limit": limit})
    return {"genres": [_breakdown_row(row) for row in rows]}


def director_breakdown(user_id: str, db: Session, limit: int) -> dict:
    """All-time director counts, average rating, and runtime for the caller."""
    rows = db.execute(
        text(_BREAKDOWN_DIRECTORS), {"user_id": user_id, "limit": limit}
    )
    return {"directors": [_breakdown_row(row) for row in rows]}


def match_with(user_id: str, other_id: str, db: Session) -> dict:
    """Match percent plus the overlap that explains it.

    Friends only. A hidden or test account, or someone who blocked the
    caller, is a 404, same as the public profile. The payload only includes
    titles both people rated.
    """
    if user_id == other_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot compare a user with themselves",
        )

    from app.auth.visibility import raise_if_hidden_from
    from app.friends.services import get_block_state

    other = db.query(Profile).filter(Profile.id == other_id).first()
    if other is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    raise_if_hidden_from(user_id, other)
    _, has_blocked_me = get_block_state(user_id, other_id, db)
    if has_blocked_me:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    assert_are_friends(user_id, other_id, db)

    mine: dict[int, dict] = {}
    theirs: dict[int, dict] = {}
    my_genres: dict[str, int] = defaultdict(int)
    their_genres: dict[str, int] = defaultdict(int)
    rows = db.execute(text(_PAIR_SQL), {"me": user_id, "them": other_id})
    for row in rows:
        bucket = mine if row.user_id == user_id else theirs
        genre_counts = my_genres if row.user_id == user_id else their_genres
        bucket[row.tmdb_id] = {
            "tmdb_id": row.tmdb_id,
            "title": row.title,
            "poster_path": row.poster_path,
            "rating": row.rating,
        }
        for name in _genre_names(row.genres):
            genre_counts[name] += 1

    shared_rated = []
    for tmdb_id, mine_row in mine.items():
        their_row = theirs.get(tmdb_id)
        if their_row is None or mine_row["rating"] is None or their_row["rating"] is None:
            continue
        shared_rated.append(
            {
                "tmdb_id": tmdb_id,
                "title": mine_row["title"],
                "poster_path": mine_row["poster_path"],
                "my_rating": float(mine_row["rating"]),
                "their_rating": float(their_row["rating"]),
            }
        )

    highs = [
        row
        for row in shared_rated
        if row["my_rating"] >= HIGH_RATING and row["their_rating"] >= HIGH_RATING
    ]
    highs.sort(key=lambda row: (-min(row["my_rating"], row["their_rating"]), row["tmdb_id"]))

    gaps = [
        row
        for row in shared_rated
        if abs(row["my_rating"] - row["their_rating"]) >= DISAGREEMENT_GAP
    ]
    gaps.sort(key=lambda row: (-abs(row["my_rating"] - row["their_rating"]), row["tmdb_id"]))

    overlap = [
        {"name": name, "my_count": my_genres[name], "their_count": their_genres[name]}
        for name in my_genres.keys() & their_genres.keys()
    ]
    overlap.sort(key=lambda row: (-min(row["my_count"], row["their_count"]), row["name"]))

    return {
        "user_id": str(other.id),
        "username": other.username,
        "display_name": other.display_name,
        "match_percent": _match_percent(shared_rated, my_genres, their_genres),
        "shared_high_ratings": highs[:LIST_LIMIT],
        "genre_overlap": overlap[:LIST_LIMIT],
        "biggest_disagreements": gaps[:LIST_LIMIT],
    }


def _match_percent(
    shared_rated: list[dict],
    my_genres: dict[str, int],
    their_genres: dict[str, int],
) -> int:
    rating_score = None
    if shared_rated:
        mae = sum(abs(row["my_rating"] - row["their_rating"]) for row in shared_rated) / len(
            shared_rated
        )
        rating_score = max(0.0, 1.0 - mae / RATING_SPAN)

    genre_score = None
    if my_genres and their_genres:
        genre_score = _cosine(my_genres, their_genres)

    if rating_score is None and genre_score is None:
        return 0
    if rating_score is None:
        score = genre_score or 0.0
    elif genre_score is None:
        score = rating_score
    else:
        score = RATING_WEIGHT * rating_score + (1 - RATING_WEIGHT) * genre_score
    return min(100, int(score * 100 + 0.5))


def _cosine(left: dict[str, int], right: dict[str, int]) -> float:
    keys = set(left) | set(right)
    dot = sum(left.get(key, 0) * right.get(key, 0) for key in keys)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _genre_names(genres: object) -> list[str]:
    parsed = _json(genres)
    if not isinstance(parsed, list):
        return []
    names = []
    for genre in parsed:
        if isinstance(genre, dict):
            name = (genre.get("name") or "").strip()
            if name:
                names.append(name)
    return names


def _breakdown_row(row) -> dict:
    avg = row.avg_rating
    return {
        "name": row.name,
        "count": row.count,
        "avg_rating": float(avg) if avg is not None else None,
        "minutes": row.minutes,
    }


def _month_map(raw: object) -> dict[int, dict]:
    if not isinstance(raw, dict):
        return {}
    return {int(key): value for key, value in raw.items()}


def _json(value: object) -> dict | list:
    if isinstance(value, str):
        return json.loads(value)
    if value is None:
        return []
    return value  # type: ignore[return-value]
