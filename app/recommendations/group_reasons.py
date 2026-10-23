"""A short, honest "why" for each Blend recommendation.

The first signal that holds for every member wins:
1. a movie all of them rated highly that is among the candidate's closest
   matches in everyone's liked movies,
2. a director whose films all of them rated highly,
3. a genre all of them picked,
4. a generic line, since the ranking itself already needs every member to fit.
"""

from __future__ import annotations

import numpy as np
from sqlalchemy.orm import Session

from app.import_data.models import MovieEmbedding
from app.movies.models import Movie
from app.recommendations.group_scoring import MemberTaste
from app.tracking.models import WatchedMovie

LIKED_RATING = 4.0
CLOSEST_LIKED = 3  # the shared movie must be this close to the candidate


def attach_group_reasons(
    candidates: list[dict], members: list[MemberTaste], db: Session
) -> None:
    """Set candidate["reason"] on every candidate (mutates in place)."""
    if not candidates or len(members) < 2:
        return
    who = "both" if len(members) == 2 else "all"
    shared = _shared_liked(members, db)
    similarities = _liked_similarities(candidates, members, shared, db)

    for c in candidates:
        movie: Movie = c["movie"]
        title = _closest_shared_title(similarities.get(c["tmdb_id"], []), shared)
        if title:
            c["reason"] = f"You {who} rated {title} highly"
        elif _all_share_director(movie, members):
            c["reason"] = f"You {who} rated {movie.director} films highly"
        elif genre := _shared_genre(movie, members):
            c["reason"] = f"Matches {who} your {genre} picks"
        else:
            c["reason"] = f"Matches {who} your tastes"


def _shared_liked(members: list[MemberTaste], db: Session) -> dict[int, str]:
    """{tmdb_id: title} of movies every member rated LIKED_RATING or more."""
    rows = (
        db.query(WatchedMovie.user_id, WatchedMovie.tmdb_id, Movie.title)
        .join(Movie, Movie.tmdb_id == WatchedMovie.tmdb_id)
        .filter(
            WatchedMovie.user_id.in_([m.user_id for m in members]),
            WatchedMovie.rating >= LIKED_RATING,
        )
        .all()
    )
    likers: dict[int, set[str]] = {}
    titles: dict[int, str] = {}
    for user_id, tmdb_id, title in rows:
        likers.setdefault(tmdb_id, set()).add(str(user_id))
        titles[tmdb_id] = title
    everyone = {m.user_id for m in members}
    return {t: titles[t] for t, who in likers.items() if who >= everyone}


def _liked_similarities(
    candidates: list[dict],
    members: list[MemberTaste],
    shared: dict[int, str],
    db: Session,
) -> dict[int, list[tuple[float, int]]]:
    """Per candidate, (similarity, tmdb_id) of its closest liked movies, best first.

    "Liked" is anything any member rated LIKED_RATING or more, so a shared movie
    only counts when it is genuinely near the candidate for the group.
    """
    if not shared:
        return {}
    liked_ids = {
        row[0]
        for row in db.query(WatchedMovie.tmdb_id)
        .filter(
            WatchedMovie.user_id.in_([m.user_id for m in members]),
            WatchedMovie.rating >= LIKED_RATING,
        )
        .all()
    }
    cand_ids = [c["tmdb_id"] for c in candidates]
    rows = (
        db.query(MovieEmbedding.tmdb_id, MovieEmbedding.embedding)
        .filter(MovieEmbedding.tmdb_id.in_(liked_ids | set(cand_ids)))
        .all()
    )
    vectors = {t: np.array(list(e), dtype=np.float64) for t, e in rows}
    liked = [t for t in sorted(liked_ids) if t in vectors]
    if not liked:
        return {}
    liked_matrix = np.stack([vectors[t] for t in liked])
    liked_matrix /= np.maximum(
        np.linalg.norm(liked_matrix, axis=1, keepdims=True), 1e-12
    )

    result: dict[int, list[tuple[float, int]]] = {}
    for tmdb_id in cand_ids:
        vec = vectors.get(tmdb_id)
        if vec is None or not np.linalg.norm(vec):
            continue
        sims = liked_matrix @ (vec / np.linalg.norm(vec))
        pairs = [(float(s), t) for s, t in zip(sims, liked) if t != tmdb_id]
        pairs.sort(key=lambda p: (-p[0], p[1]))
        result[tmdb_id] = pairs[:CLOSEST_LIKED]
    return result


def _closest_shared_title(
    closest: list[tuple[float, int]], shared: dict[int, str]
) -> str | None:
    for _, tmdb_id in closest:
        if tmdb_id in shared:
            return shared[tmdb_id]
    return None


def _all_share_director(movie: Movie, members: list[MemberTaste]) -> bool:
    if not movie.director:
        return False
    return all(movie.director.lower() in m.directors for m in members)


def _shared_genre(movie: Movie, members: list[MemberTaste]) -> str | None:
    picked = [{g.lower() for g in m.genres} for m in members]
    shared = set.intersection(*picked) if picked else set()
    for g in movie.genres or []:
        name = g.get("name") if isinstance(g, dict) else None
        if name and name.lower() in shared:
            return name
    return None
