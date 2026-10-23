"""Item-item collaborative filtering over the watched_movies rating matrix.

Supplies the similarity term used by ranking: instead of asking "how close is
this movie's embedding to the user's taste embedding", CF asks "how did people
who rated the movies this user rated also rate this candidate".

Similarity between two movies is an adjusted-cosine over mean-centered ratings
of the users who rated both, shrunk toward 0 when few users co-rated them.
A candidate's score is the neighbourhood-weighted rating prediction, mapped to
0-1. Candidates without enough co-rating support are left out of the result so
the caller can fall back to embedding cosine similarity.
"""

import numpy as np
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.tracking.models import WatchedMovie

MIN_PROFILE_RATINGS = 5  # below this, the target profile has too little signal
MIN_CO_RATERS = 3  # a candidate needs this many co-raters on some rated movie
SHRINKAGE = 10.0  # co-rater count at which a similarity keeps half its value
MAX_RATING = 5.0
MAX_NEIGHBOURS = 1000


def blend_cf_similarity(cf_score: float, embedding_score: float | None) -> float:
    """Blend CF with the embedding score. Default weight keeps CF unchanged.

    A movie with no embedding has nothing to blend, so the CF score is used whole.
    """
    if embedding_score is None:
        return cf_score
    weight = min(max(settings.cf_blend_weight, 0.0), 1.0)
    return weight * cf_score + (1.0 - weight) * embedding_score


def compute_cf_scores(
    user_ids: list[str],
    candidate_tmdb_ids: list[int],
    db: Session,
) -> dict[int, float]:
    """Predict 0-1 CF scores for candidates against the given users' ratings.

    Multiple user_ids are collapsed into one profile by averaging each movie's
    ratings across the members. Blend feeds score members one by one with
    compute_member_cf_scores instead, so disagreement is not averaged away.
    Only candidates with enough co-rating support get a score.
    """
    if not user_ids or not candidate_tmdb_ids:
        return {}
    if not settings.cf_enabled:
        return {}

    profile_ratings = _profile_ratings(user_ids, db)
    if len(profile_ratings) < MIN_PROFILE_RATINGS:
        return {}

    rated_ids = sorted(profile_ratings)
    candidates = [
        t for t in dict.fromkeys(candidate_tmdb_ids) if t not in profile_ratings
    ]
    if not candidates:
        return {}

    centered, observed, item_index = _centered_rating_matrix(
        user_ids, rated_ids, candidates, db
    )
    if centered is None or observed is None:
        return {}

    rated_cols = [item_index[t] for t in rated_ids if t in item_index]
    cand_cols = [item_index[t] for t in candidates if t in item_index]
    if not rated_cols or not cand_cols:
        return {}

    rated_matrix = centered[:, rated_cols]
    cand_matrix = centered[:, cand_cols]

    similarity = _item_similarity(cand_matrix, rated_matrix)
    # Co-raters come from the observed mask. A centered 0 is a real rating
    # that landed on the user's mean, not a missing value.
    co_raters = observed[:, cand_cols].T @ observed[:, rated_cols]
    similarity *= co_raters / (co_raters + SHRINKAGE)
    np.clip(similarity, 0.0, None, out=similarity)

    profile_mean = float(np.mean(list(profile_ratings.values())))
    deviations = np.array(
        [profile_ratings[t] - profile_mean for t in rated_ids if t in item_index]
    )

    weight_sums = similarity.sum(axis=1)
    support = co_raters.max(axis=1)
    predictions = profile_mean + np.divide(
        similarity @ deviations,
        weight_sums,
        out=np.zeros_like(weight_sums),
        where=weight_sums > 0,
    )

    scored_ids = [t for t in candidates if t in item_index]
    return {
        tmdb_id: round(float(np.clip(predictions[i] / MAX_RATING, 0.0, 1.0)), 4)
        for i, tmdb_id in enumerate(scored_ids)
        if weight_sums[i] > 0 and support[i] >= MIN_CO_RATERS
    }


def compute_member_cf_scores(
    user_ids: list[str],
    candidate_tmdb_ids: list[int],
    db: Session,
) -> dict[str, dict[int, float]]:
    """CF scores per member, each from that member's own ratings.

    A member without enough ratings or co-rater support gets {} (or misses some
    candidates), so the caller falls back to that member's embedding taste.
    """
    return {
        user_id: compute_cf_scores([user_id], candidate_tmdb_ids, db)
        for user_id in user_ids
    }


def _profile_ratings(user_ids: list[str], db: Session) -> dict[int, float]:
    """Ratings of the target profile, averaged per movie across its members."""
    rows = (
        db.query(WatchedMovie.tmdb_id, WatchedMovie.rating)
        .filter(
            WatchedMovie.user_id.in_(user_ids),
            WatchedMovie.rating.isnot(None),
        )
        .all()
    )
    totals: dict[int, list[float]] = {}
    for tmdb_id, rating in rows:
        totals.setdefault(tmdb_id, []).append(float(rating))
    return {tmdb_id: sum(rs) / len(rs) for tmdb_id, rs in totals.items()}


def _centered_rating_matrix(
    user_ids: list[str],
    rated_ids: list[int],
    candidate_ids: list[int],
    db: Session,
) -> tuple[np.ndarray | None, np.ndarray | None, dict[int, int]]:
    """Build the (neighbour × movie) matrix of mean-centered ratings.

    Neighbours are users — excluding the target profile — who rated at least
    one of the profile's movies. Unrated cells stay 0 so they drop out of the
    dot products that form item-item similarities. The boolean matrix says
    which cells were actually rated.
    """
    # shortcut: at most MAX_NEIGHBOURS people, the ones who share the most
    # movies with the profile. Switch to a precomputed item-item table once a
    # popular title has more raters than this.
    overlap = func.count(WatchedMovie.tmdb_id)
    neighbour_ids = (
        db.query(WatchedMovie.user_id)
        .filter(
            WatchedMovie.tmdb_id.in_(rated_ids),
            WatchedMovie.rating.isnot(None),
            WatchedMovie.user_id.notin_(user_ids),
        )
        .group_by(WatchedMovie.user_id)
        .order_by(overlap.desc(), WatchedMovie.user_id)
        .limit(MAX_NEIGHBOURS)
        .subquery()
    )
    rows = (
        db.query(WatchedMovie.user_id, WatchedMovie.tmdb_id, WatchedMovie.rating)
        .filter(
            WatchedMovie.user_id.in_(neighbour_ids.select()),
            WatchedMovie.tmdb_id.in_(rated_ids + candidate_ids),
            WatchedMovie.rating.isnot(None),
        )
        .all()
    )
    if not rows:
        return None, None, {}

    user_index: dict[str, int] = {}
    item_index: dict[int, int] = {}
    for user_id, tmdb_id, _ in rows:
        user_index.setdefault(str(user_id), len(user_index))
        item_index.setdefault(tmdb_id, len(item_index))

    matrix = np.zeros((len(user_index), len(item_index)))
    for user_id, tmdb_id, rating in rows:
        matrix[user_index[str(user_id)], item_index[tmdb_id]] = float(rating)

    observed = matrix != 0
    counts = observed.sum(axis=1, keepdims=True)
    means = np.divide(
        matrix.sum(axis=1, keepdims=True),
        counts,
        out=np.zeros_like(counts, dtype=np.float64),
        where=counts > 0,
    )
    centered = np.where(observed, matrix - means, 0.0)
    return centered, observed.astype(np.float64), item_index


def _item_similarity(columns: np.ndarray, other: np.ndarray) -> np.ndarray:
    """Cosine similarity between every column pair of two centered matrices."""
    norms = np.linalg.norm(columns, axis=0)
    other_norms = np.linalg.norm(other, axis=0)
    denom = np.outer(norms, other_norms)
    return np.divide(
        columns.T @ other,
        denom,
        out=np.zeros(denom.shape),
        where=denom > 0,
    )
