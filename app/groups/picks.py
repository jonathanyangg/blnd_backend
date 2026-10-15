"""Tonight's blend pick, and the vetoes that push it to the next title.

The pick is stored per blend per UTC day so every member sees the same film.
Vetoes from other days are ignored.
shortcut: scoring scans the catalog once per new pick, add a genre index if
the catalog passes a few hundred thousand rows.
shortcut: the day boundary is UTC, switch to a blend timezone if members span regions.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import Profile
from app.auth.visibility import is_hidden_profile
from app.groups.models import BlendPick, BlendVeto, Group
from app.groups.services import _verify_membership
from app.movies.models import Movie

VETOES_PER_MEMBER_PER_DAY = 20
HIGH_RATING = 4.0

_HAS_TASTE = """
SELECT 1
FROM watched_movies w
JOIN group_members mem
  ON mem.user_id = w.user_id AND mem.group_id = :group_id
JOIN profiles p ON p.id = mem.user_id
  AND p.is_discoverable AND NOT p.is_test
JOIN movies m ON m.tmdb_id = w.tmdb_id
WHERE w.rating >= :high
  AND (
        (m.director IS NOT NULL AND btrim(m.director) <> '')
        OR EXISTS (
            SELECT 1
            FROM jsonb_array_elements(COALESCE(m.genres, '[]'::jsonb)) g
            WHERE COALESCE(g->>'name', '') <> ''
        )
      )
LIMIT 1
"""

_TASTE_PICK = """
WITH loved AS (
    SELECT m.genres, lower(btrim(m.director)) AS director
    FROM watched_movies w
    JOIN movies m ON m.tmdb_id = w.tmdb_id
    JOIN group_members mem
      ON mem.user_id = w.user_id AND mem.group_id = :group_id
    JOIN profiles p ON p.id = mem.user_id
      AND p.is_discoverable AND NOT p.is_test
    WHERE w.rating >= :high
),
genre_weights AS (
    SELECT lower(g->>'name') AS name, COUNT(*)::float AS weight
    FROM loved
    CROSS JOIN LATERAL jsonb_array_elements(COALESCE(genres, '[]'::jsonb)) g
    WHERE COALESCE(g->>'name', '') <> ''
    GROUP BY 1
),
director_weights AS (
    SELECT director AS name, COUNT(*)::float AS weight
    FROM loved
    WHERE director IS NOT NULL AND director <> ''
    GROUP BY 1
),
blocked AS (
    SELECT w.tmdb_id
    FROM watched_movies w
    JOIN group_members mem
      ON mem.user_id = w.user_id AND mem.group_id = :group_id
    JOIN profiles p ON p.id = mem.user_id
      AND p.is_discoverable AND NOT p.is_test
    UNION
    SELECT h.tmdb_id
    FROM hidden_movies h
    JOIN group_members mem
      ON mem.user_id = h.user_id AND mem.group_id = :group_id
    JOIN profiles p ON p.id = mem.user_id
      AND p.is_discoverable AND NOT p.is_test
    UNION
    SELECT v.tmdb_id
    FROM blend_vetoes v
    WHERE v.group_id = :group_id AND v.veto_date = :day
),
genre_scores AS (
    SELECT m.tmdb_id, SUM(gw.weight) AS genre_score
    FROM movies m
    CROSS JOIN LATERAL jsonb_array_elements(COALESCE(m.genres, '[]'::jsonb)) g
    JOIN genre_weights gw ON gw.name = lower(g->>'name')
    GROUP BY m.tmdb_id
)
SELECT m.tmdb_id
FROM movies m
LEFT JOIN genre_scores gs ON gs.tmdb_id = m.tmdb_id
LEFT JOIN director_weights dw ON dw.name = lower(btrim(m.director))
WHERE NOT EXISTS (SELECT 1 FROM blocked b WHERE b.tmdb_id = m.tmdb_id)
  AND (COALESCE(gs.genre_score, 0) + COALESCE(dw.weight, 0) * 2) > 0
ORDER BY (COALESCE(gs.genre_score, 0) + COALESCE(dw.weight, 0) * 2) DESC,
         m.vote_average DESC NULLS LAST,
         COALESCE(m.vote_count, 0) DESC,
         m.tmdb_id
LIMIT 1
"""

_POPULAR_PICK = """
WITH blocked AS (
    SELECT w.tmdb_id
    FROM watched_movies w
    JOIN group_members mem
      ON mem.user_id = w.user_id AND mem.group_id = :group_id
    JOIN profiles p ON p.id = mem.user_id
      AND p.is_discoverable AND NOT p.is_test
    UNION
    SELECT h.tmdb_id
    FROM hidden_movies h
    JOIN group_members mem
      ON mem.user_id = h.user_id AND mem.group_id = :group_id
    JOIN profiles p ON p.id = mem.user_id
      AND p.is_discoverable AND NOT p.is_test
    UNION
    SELECT v.tmdb_id
    FROM blend_vetoes v
    WHERE v.group_id = :group_id AND v.veto_date = :day
)
SELECT m.tmdb_id
FROM movies m
WHERE NOT EXISTS (SELECT 1 FROM blocked b WHERE b.tmdb_id = m.tmdb_id)
ORDER BY m.vote_average DESC NULLS LAST,
         COALESCE(m.vote_count, 0) DESC,
         m.tmdb_id
LIMIT 1
"""


def get_or_create_pick(group_id: int, user_id: str, db: Session) -> dict:
    """Return today's pick, creating it when the blend doesn't have one yet."""
    _require_member(group_id, user_id, db)
    day = _today()
    tmdb_id = _ensure_pick(group_id, day, db)
    return _payload(group_id, day, tmdb_id, db)


def veto_tonight(
    group_id: int, user_id: str, tmdb_id: int, reason: str, db: Session
) -> dict:
    """Store a veto for today and re-pick, skipping every vetoed title."""
    _require_member(group_id, user_id, db)
    movie = db.query(Movie.tmdb_id).filter(Movie.tmdb_id == tmdb_id).first()
    if movie is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Movie not found")

    day = _today()
    already = (
        db.query(BlendVeto)
        .filter(
            BlendVeto.group_id == group_id,
            BlendVeto.veto_date == day,
            BlendVeto.user_id == user_id,
            BlendVeto.tmdb_id == tmdb_id,
        )
        .first()
    )
    if already is None:
        used = (
            db.query(BlendVeto)
            .filter(
                BlendVeto.group_id == group_id,
                BlendVeto.veto_date == day,
                BlendVeto.user_id == user_id,
            )
            .count()
        )
        if used >= VETOES_PER_MEMBER_PER_DAY:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Veto limit reached for today",
            )

    db.execute(
        insert(BlendVeto)
        .values(
            group_id=group_id,
            veto_date=day,
            user_id=user_id,
            tmdb_id=tmdb_id,
            reason=reason,
        )
        .on_conflict_do_update(
            index_elements=["group_id", "veto_date", "user_id", "tmdb_id"],
            set_={"reason": reason},
        )
    )
    db.flush()
    picked = _ensure_pick(group_id, day, db)
    return _payload(group_id, day, picked, db)


def _require_member(group_id: int, user_id: str, db: Session) -> None:
    group = db.query(Group.id).filter(Group.id == group_id).first()
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Group not found"
        )
    _verify_membership(group_id, user_id, db)


def _ensure_pick(group_id: int, day, db: Session) -> int | None:
    vetoed = {
        row[0]
        for row in db.query(BlendVeto.tmdb_id)
        .filter(BlendVeto.group_id == group_id, BlendVeto.veto_date == day)
        .all()
    }
    current = (
        db.query(BlendPick)
        .filter(BlendPick.group_id == group_id, BlendPick.pick_date == day)
        .first()
    )
    if current is not None and current.tmdb_id not in vetoed:
        return current.tmdb_id

    chosen = _choose(group_id, day, db)
    if chosen is None:
        if current is not None:
            db.delete(current)
            db.commit()
        return None
    if current is not None:
        current.tmdb_id = chosen
        db.commit()
        return chosen

    nested = db.begin_nested()
    try:
        db.add(BlendPick(group_id=group_id, pick_date=day, tmdb_id=chosen))
        db.flush()
    except IntegrityError:
        nested.rollback()
        winner = (
            db.query(BlendPick)
            .filter(BlendPick.group_id == group_id, BlendPick.pick_date == day)
            .first()
        )
        if winner is None:
            raise
        if winner.tmdb_id in vetoed:
            winner.tmdb_id = chosen
        db.commit()
        return winner.tmdb_id
    db.commit()
    return chosen


def _choose(group_id: int, day, db: Session) -> int | None:
    params = {"group_id": group_id, "day": day, "high": HIGH_RATING}
    has_taste = db.execute(text(_HAS_TASTE), params).first()
    if has_taste is not None:
        row = db.execute(text(_TASTE_PICK), params).first()
        if row is not None:
            return int(row.tmdb_id)
    row = db.execute(text(_POPULAR_PICK), params).first()
    if row is None:
        return None
    return int(row.tmdb_id)


def _payload(group_id: int, day, tmdb_id: int | None, db: Session) -> dict:
    pick = None
    if tmdb_id is not None:
        movie = db.query(Movie).filter(Movie.tmdb_id == tmdb_id).first()
        if movie is not None:
            pick = {
                "tmdb_id": movie.tmdb_id,
                "title": movie.title,
                "year": movie.year,
                "poster_path": movie.poster_path,
                "overview": movie.overview,
                "genres": movie.genres or [],
                "director": movie.director,
                "runtime": movie.runtime,
                "vote_average": movie.vote_average,
            }
    rows = (
        db.query(BlendVeto, Movie.title)
        .join(Movie, Movie.tmdb_id == BlendVeto.tmdb_id)
        .filter(BlendVeto.group_id == group_id, BlendVeto.veto_date == day)
        .order_by(BlendVeto.created_at.asc(), BlendVeto.tmdb_id.asc())
        .all()
    )
    user_ids = {veto.user_id for veto, _title in rows}
    names = {}
    if user_ids:
        names = {
            profile.id: profile.username
            for profile in db.query(Profile).filter(Profile.id.in_(user_ids)).all()
            if not is_hidden_profile(profile)
        }
    return {
        "date": day,
        "pick": pick,
        "vetoes": [
            {
                "tmdb_id": veto.tmdb_id,
                "title": title,
                "user_id": str(veto.user_id),
                "username": names[veto.user_id],
                "reason": veto.reason,
            }
            for veto, title in rows
            if veto.user_id in names
        ],
    }


def _today():
    return datetime.now(timezone.utc).date()
