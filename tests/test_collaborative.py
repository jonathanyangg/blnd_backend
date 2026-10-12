"""Tests for app/recommendations/collaborative.py — item-item CF scoring."""

import numpy as np
import pytest
from sqlalchemy.orm import Session

from app.config import settings
from app.recommendations import collaborative
from app.recommendations.collaborative import (
    MIN_CO_RATERS,
    MIN_PROFILE_RATINGS,
    _item_similarity,
    compute_cf_scores,
)
from tests.factories import make_movie, make_profile, make_watched

# The target user loves 1-3 and dislikes 4-5.
LIKED = [1, 2, 3]
DISLIKED = [4, 5]
LIKED_CANDIDATE = 100
DISLIKED_CANDIDATE = 101


def _make_movies(db: Session, tmdb_ids: list[int]) -> None:
    """watched_movies.tmdb_id is a FK, so every rated id needs a movie row."""
    for tmdb_id in tmdb_ids:
        make_movie(db, tmdb_id=tmdb_id, title=f"Movie {tmdb_id}")


def _make_user(db: Session, username: str) -> str:
    return str(make_profile(db, username=username).id)


def _rate(db: Session, user_id: str, ratings: dict[int, float]) -> None:
    for tmdb_id, rating in ratings.items():
        make_watched(db, user_id=user_id, tmdb_id=tmdb_id, rating=rating)


def _target_ratings() -> dict[int, float]:
    return {**{t: 5.0 for t in LIKED}, **{t: 1.0 for t in DISLIKED}}


def _make_neighbours(db: Session, count: int) -> None:
    """Raters who agree with the target user and rate both candidates."""
    for i in range(count):
        neighbour = _make_user(db, f"neighbour{i}")
        _rate(
            db,
            neighbour,
            {**_target_ratings(), LIKED_CANDIDATE: 5.0, DISLIKED_CANDIDATE: 1.0},
        )


CANDIDATES = [LIKED_CANDIDATE, DISLIKED_CANDIDATE]


# --- compute_cf_scores ---


def test_no_users_or_candidates(db: Session) -> None:
    _make_movies(db, LIKED + DISLIKED + CANDIDATES)
    user_id = _make_user(db, "user")
    assert compute_cf_scores([], CANDIDATES, db) == {}
    assert compute_cf_scores([user_id], [], db) == {}


def test_cold_start_too_few_ratings(db: Session) -> None:
    """A user below MIN_PROFILE_RATINGS gets no CF scores (caller falls back)."""
    _make_movies(db, LIKED + DISLIKED + CANDIDATES)
    user_id = _make_user(db, "user")
    _rate(db, user_id, {t: 5.0 for t in range(1, MIN_PROFILE_RATINGS)})
    _make_neighbours(db, MIN_CO_RATERS + 1)

    assert compute_cf_scores([user_id], CANDIDATES, db) == {}


def test_no_neighbours(db: Session) -> None:
    """Ratings but nobody else rated the same movies — no signal."""
    _make_movies(db, LIKED + DISLIKED + CANDIDATES)
    user_id = _make_user(db, "user")
    _rate(db, user_id, _target_ratings())

    assert compute_cf_scores([user_id], CANDIDATES, db) == {}


def test_insufficient_co_raters(db: Session) -> None:
    """Below MIN_CO_RATERS overlapping raters, candidates stay unscored."""
    _make_movies(db, LIKED + DISLIKED + CANDIDATES)
    user_id = _make_user(db, "user")
    _rate(db, user_id, _target_ratings())
    _make_neighbours(db, MIN_CO_RATERS - 1)

    assert compute_cf_scores([user_id], CANDIDATES, db) == {}


def test_predicts_from_neighbour_ratings(db: Session) -> None:
    """Neighbours who share the user's taste drive the prediction.

    They rate LIKED_CANDIDATE like the movies the user loves and
    DISLIKED_CANDIDATE like the ones the user dislikes, so the predicted
    ratings are 5/5 and 1/5 of the scale.
    """
    _make_movies(db, LIKED + DISLIKED + CANDIDATES)
    user_id = _make_user(db, "user")
    _rate(db, user_id, _target_ratings())
    _make_neighbours(db, MIN_CO_RATERS + 1)

    scores = compute_cf_scores([user_id], CANDIDATES, db)

    assert set(scores) == set(CANDIDATES)
    assert scores[LIKED_CANDIDATE] == 1.0
    assert scores[DISLIKED_CANDIDATE] == 0.2


def test_cf_kill_switch_returns_no_scores(db: Session, monkeypatch) -> None:
    """CF_ENABLED=false makes supported candidates fall back to embeddings."""
    _make_movies(db, LIKED + DISLIKED + CANDIDATES)
    user_id = _make_user(db, "user")
    _rate(db, user_id, _target_ratings())
    _make_neighbours(db, MIN_CO_RATERS + 1)
    monkeypatch.setattr(settings, "cf_enabled", False)

    scores = compute_cf_scores([user_id], CANDIDATES, db)

    assert scores == {}


def test_neighbour_fan_out_cap(db: Session, monkeypatch) -> None:
    """Only the capped number of neighbours can contribute CF evidence."""
    _make_movies(db, LIKED + DISLIKED + CANDIDATES)
    user_id = _make_user(db, "user")
    _rate(db, user_id, _target_ratings())
    _make_neighbours(db, MIN_CO_RATERS + 1)
    monkeypatch.setattr(collaborative, "MAX_NEIGHBOURS", 1)

    scores = compute_cf_scores([user_id], CANDIDATES, db)

    assert scores == {}


def test_scores_stay_in_unit_range(db: Session) -> None:
    """Even with an extreme profile mean, scores stay within 0-1."""
    _make_movies(db, LIKED + DISLIKED + CANDIDATES)
    user_id = _make_user(db, "user")
    _rate(db, user_id, {**{t: 5.0 for t in LIKED}, **{t: 4.5 for t in DISLIKED}})
    for i in range(MIN_CO_RATERS + 1):
        neighbour = _make_user(db, f"neighbour{i}")
        _rate(
            db,
            neighbour,
            {
                **{t: 5.0 for t in LIKED},
                **{t: 0.5 for t in DISLIKED},
                LIKED_CANDIDATE: 5.0,
                DISLIKED_CANDIDATE: 0.5,
            },
        )

    scores = compute_cf_scores([user_id], CANDIDATES, db)

    assert all(0.0 <= s <= 1.0 for s in scores.values())


def test_already_rated_candidates_are_skipped(db: Session) -> None:
    _make_movies(db, LIKED + DISLIKED + CANDIDATES)
    user_id = _make_user(db, "user")
    _rate(db, user_id, {**_target_ratings(), LIKED_CANDIDATE: 4.0})
    _make_neighbours(db, MIN_CO_RATERS + 1)

    scores = compute_cf_scores([user_id], CANDIDATES, db)

    assert LIKED_CANDIDATE not in scores
    assert DISLIKED_CANDIDATE in scores


def test_group_profile_combines_members(db: Session) -> None:
    """Group members' ratings collapse into one profile, and members are not
    treated as each other's neighbours."""
    _make_movies(db, LIKED + DISLIKED + CANDIDATES)
    member_a = _make_user(db, "membera")
    member_b = _make_user(db, "memberb")
    _rate(db, member_a, {t: 5.0 for t in LIKED})
    _rate(db, member_b, {t: 1.0 for t in DISLIKED})
    _make_neighbours(db, MIN_CO_RATERS + 1)

    scores = compute_cf_scores([member_a, member_b], CANDIDATES, db)

    assert scores[LIKED_CANDIDATE] > scores[DISLIKED_CANDIDATE]


def test_group_averages_shared_movie_ratings(db: Session) -> None:
    """A movie rated by several members counts once, at the average rating."""
    _make_movies(db, LIKED + DISLIKED + CANDIDATES)
    member_a = _make_user(db, "membera")
    member_b = _make_user(db, "memberb")
    _rate(db, member_a, _target_ratings())
    _rate(db, member_b, {LIKED[0]: 1.0})
    _make_neighbours(db, MIN_CO_RATERS + 1)

    both = compute_cf_scores([member_a, member_b], CANDIDATES, db)
    solo = compute_cf_scores([member_a], CANDIDATES, db)

    # Member B's 1.0 pulls that movie's profile rating from 5.0 to 3.0, so the
    # group is predicted to like the candidate less than member A alone.
    assert both[LIKED_CANDIDATE] < solo[LIKED_CANDIDATE]


# --- _item_similarity ---


def test_item_similarity_identical_columns() -> None:
    columns = np.array([[1.0], [2.0]])
    assert _item_similarity(columns, columns)[0][0] == pytest.approx(1.0)


def test_item_similarity_opposite_columns() -> None:
    columns = np.array([[1.0], [2.0]])
    assert _item_similarity(columns, -columns)[0][0] == pytest.approx(-1.0)


def test_item_similarity_zero_column() -> None:
    """A column with no centered ratings has no similarity to anything."""
    result = _item_similarity(np.array([[0.0], [0.0]]), np.array([[1.0], [2.0]]))
    assert result[0][0] == 0.0
