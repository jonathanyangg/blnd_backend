"""Swipe signals are taste, not watchlist saves and not hides."""

import numpy as np
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.import_data.models import MovieEmbedding
from app.recommendations.models import HiddenMovie, MovieInteraction
from app.recommendations.services import (
    INTERESTED_WEIGHT,
    NOT_FOR_ME_WEIGHT,
    WATCHLIST_WEIGHT,
    compute_taste_embeddings,
    get_hidden_movie_ids,
)
from app.recommendations.views import _build_user_context
from app.tracking.models import WatchlistMovie
from tests.conftest import TEST_USER_ID
from tests.factories import make_movie, make_profile, make_watched, make_watchlist


def _basis(index: int) -> list[float]:
    vector = [0.0] * 1536
    vector[index] = 1.0
    return vector


def _embed(db: Session, tmdb_id: int, index: int) -> None:
    db.add(MovieEmbedding(tmdb_id=tmdb_id, embedding=_basis(index)))
    db.commit()


def test_interested_does_not_watchlist_and_not_for_me_does_not_hide(
    client_with_tmdb: TestClient, db: Session
) -> None:
    watchlist = make_watchlist(db)
    make_profile(db, user_id=TEST_USER_ID, username="swiper", watchlist_id=watchlist.id)
    make_movie(db, tmdb_id=550)

    before = (
        db.query(WatchlistMovie)
        .filter(WatchlistMovie.watchlist_id == watchlist.id)
        .count()
    )
    interested = client_with_tmdb.post("/recommendations/550/interested")
    assert interested.status_code == 200
    body = interested.json()
    assert body["tmdb_id"] == 550
    assert body["title"] == "Fight Club"
    assert "interested_at" in body
    again = client_with_tmdb.post("/recommendations/550/interested")
    assert again.status_code == 200
    assert again.json()["interested_at"] == body["interested_at"]
    assert (
        db.query(MovieInteraction)
        .filter(MovieInteraction.user_id == TEST_USER_ID)
        .count()
        == 1
    )
    assert (
        db.query(WatchlistMovie)
        .filter(WatchlistMovie.watchlist_id == watchlist.id)
        .count()
        == before
    )
    assert (
        db.query(HiddenMovie).filter(HiddenMovie.user_id == TEST_USER_ID).count() == 0
    )

    replaced = client_with_tmdb.post("/recommendations/550/not-for-me")
    assert replaced.status_code == 200
    assert "not_for_me_at" in replaced.json()
    assert (
        db.query(MovieInteraction)
        .filter(
            MovieInteraction.user_id == TEST_USER_ID,
            MovieInteraction.interaction_type == "not_for_me",
        )
        .count()
        == 1
    )
    assert (
        db.query(HiddenMovie).filter(HiddenMovie.user_id == TEST_USER_ID).count() == 0
    )
    assert (
        db.query(WatchlistMovie)
        .filter(WatchlistMovie.watchlist_id == watchlist.id)
        .count()
        == before
    )


def test_undo_schedules_another_taste_action(
    client_with_tmdb: TestClient, db: Session
) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="swiper")
    make_movie(db, tmdb_id=550)
    assert client_with_tmdb.post("/recommendations/550/interested").status_code == 200
    assert client_with_tmdb.delete("/recommendations/550/interested").status_code == 204
    from app.auth.models import Profile

    profile = db.query(Profile).filter(Profile.id == TEST_USER_ID).one()
    # One count for the swipe, one for the undo. Otherwise the taste vector
    # keeps the movie until some later, unrelated action.
    assert profile.actions_since_rebuild == 2


def test_hide_does_not_write_a_swipe(client_with_tmdb: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="swiper")
    make_movie(db, tmdb_id=550)

    hidden = client_with_tmdb.post("/recommendations/550/hide")
    assert hidden.status_code == 200
    assert (
        db.query(HiddenMovie).filter(HiddenMovie.user_id == TEST_USER_ID).count() == 1
    )
    assert (
        db.query(MovieInteraction)
        .filter(MovieInteraction.user_id == TEST_USER_ID)
        .count()
        == 0
    )


def test_swipe_validation_and_delete(client_with_tmdb: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="swiper")
    make_movie(db, tmdb_id=550)

    client_with_tmdb.post("/recommendations/550/interested")
    deleted = client_with_tmdb.delete("/recommendations/550/interested")
    assert deleted.status_code == 204
    assert (
        db.query(MovieInteraction)
        .filter(MovieInteraction.user_id == TEST_USER_ID)
        .count()
        == 0
    )
    missing_delete = client_with_tmdb.delete("/recommendations/550/interested")
    assert missing_delete.status_code == 404

    client_with_tmdb.post("/recommendations/550/not-for-me")
    wrong_undo = client_with_tmdb.delete("/recommendations/550/interested")
    assert wrong_undo.status_code == 404
    assert (
        db.query(MovieInteraction)
        .filter(MovieInteraction.interaction_type == "not_for_me")
        .count()
        == 1
    )


def test_interested_is_excluded_like_a_watchlist_title(db: Session) -> None:
    profile = make_profile(db, user_id=TEST_USER_ID, username="swiper")
    profile.taste_embedding = _basis(0)
    make_movie(db, tmdb_id=550)
    db.add(
        MovieInteraction(
            user_id=TEST_USER_ID, tmdb_id=550, interaction_type="interested"
        )
    )
    db.commit()

    ctx = _build_user_context(TEST_USER_ID, profile, db)
    assert 550 in ctx.exclude_ids
    assert 550 not in get_hidden_movie_ids(TEST_USER_ID, db)


def test_interested_weight_and_rating_wins(db: Session) -> None:
    profile = make_profile(db, user_id=TEST_USER_ID, username="swiper")
    make_movie(db, tmdb_id=1, title="Rated")
    make_movie(db, tmdb_id=2, title="Swiped")
    make_watched(db, user_id=TEST_USER_ID, tmdb_id=1, rating=4.0)
    _embed(db, 1, 0)
    _embed(db, 2, 1)
    db.add(
        MovieInteraction(user_id=TEST_USER_ID, tmdb_id=2, interaction_type="interested")
    )
    # Same movie as the rating: the rating wins, the swipe adds nothing.
    db.add(
        MovieInteraction(user_id=TEST_USER_ID, tmdb_id=1, interaction_type="interested")
    )
    db.commit()

    positive, negative, sum_weights = compute_taste_embeddings(
        TEST_USER_ID, db, profile
    )
    assert negative is None
    assert sum_weights == 4.0 + INTERESTED_WEIGHT
    expected = (4.0 * np.array(_basis(0)) + INTERESTED_WEIGHT * np.array(_basis(1))) / (
        4.0 + INTERESTED_WEIGHT
    )
    assert positive is not None
    assert np.allclose(positive, expected)


def test_interested_and_watchlist_on_the_same_movie_count_once(db: Session) -> None:
    watchlist = make_watchlist(db)
    profile = make_profile(
        db, user_id=TEST_USER_ID, username="swiper", watchlist_id=watchlist.id
    )
    make_movie(db, tmdb_id=1, title="Rated")
    make_movie(db, tmdb_id=2, title="Saved and swiped")
    make_watched(db, user_id=TEST_USER_ID, tmdb_id=1, rating=4.0)
    from tests.factories import make_watchlist_movie

    make_watchlist_movie(db, watchlist_id=watchlist.id, tmdb_id=2)
    _embed(db, 1, 0)
    _embed(db, 2, 1)
    db.add(
        MovieInteraction(user_id=TEST_USER_ID, tmdb_id=2, interaction_type="interested")
    )
    db.commit()

    _, _, sum_weights = compute_taste_embeddings(TEST_USER_ID, db, profile)
    assert sum_weights == 4.0 + WATCHLIST_WEIGHT


def test_watchlist_weight_unchanged_without_swipes(db: Session) -> None:
    watchlist = make_watchlist(db)
    profile = make_profile(
        db, user_id=TEST_USER_ID, username="swiper", watchlist_id=watchlist.id
    )
    make_movie(db, tmdb_id=1, title="Rated")
    make_movie(db, tmdb_id=2, title="Saved")
    make_watched(db, user_id=TEST_USER_ID, tmdb_id=1, rating=4.0)
    from tests.factories import make_watchlist_movie

    make_watchlist_movie(db, watchlist_id=watchlist.id, tmdb_id=2)
    _embed(db, 1, 0)
    _embed(db, 2, 1)

    positive, _, sum_weights = compute_taste_embeddings(TEST_USER_ID, db, profile)
    assert sum_weights == 4.0 + WATCHLIST_WEIGHT
    expected = (4.0 * np.array(_basis(0)) + WATCHLIST_WEIGHT * np.array(_basis(1))) / (
        4.0 + WATCHLIST_WEIGHT
    )
    assert positive is not None
    assert np.allclose(positive, expected)


def test_not_for_me_is_weaker_than_hide(db: Session) -> None:
    profile = make_profile(db, user_id=TEST_USER_ID, username="swiper")
    make_movie(db, tmdb_id=1, title="Hidden")
    make_movie(db, tmdb_id=2, title="Skipped")
    _embed(db, 1, 0)
    _embed(db, 2, 1)
    db.add(HiddenMovie(user_id=TEST_USER_ID, tmdb_id=1))
    db.add(
        MovieInteraction(user_id=TEST_USER_ID, tmdb_id=2, interaction_type="not_for_me")
    )
    db.commit()

    _, negative, sum_weights = compute_taste_embeddings(TEST_USER_ID, db, profile)
    assert sum_weights is None
    assert negative is not None
    total = 1.0 + NOT_FOR_ME_WEIGHT
    expected = (np.array(_basis(0)) + NOT_FOR_ME_WEIGHT * np.array(_basis(1))) / total
    assert np.allclose(negative, expected)


def test_hide_wins_over_interested_on_the_same_movie(db: Session) -> None:
    profile = make_profile(db, user_id=TEST_USER_ID, username="swiper")
    make_movie(db, tmdb_id=1, title="Both")
    _embed(db, 1, 0)
    db.add(HiddenMovie(user_id=TEST_USER_ID, tmdb_id=1))
    db.add(
        MovieInteraction(user_id=TEST_USER_ID, tmdb_id=1, interaction_type="interested")
    )
    db.commit()

    positive, negative, sum_weights = compute_taste_embeddings(
        TEST_USER_ID, db, profile
    )
    assert positive is None
    assert sum_weights is None
    assert negative is not None
    assert np.allclose(negative, _basis(0))


def test_hide_wins_over_not_for_me_on_the_same_movie(db: Session) -> None:
    profile = make_profile(db, user_id=TEST_USER_ID, username="swiper")
    make_movie(db, tmdb_id=1, title="Both")
    _embed(db, 1, 0)
    db.add(HiddenMovie(user_id=TEST_USER_ID, tmdb_id=1))
    db.add(
        MovieInteraction(user_id=TEST_USER_ID, tmdb_id=1, interaction_type="not_for_me")
    )
    db.commit()

    _, negative, _ = compute_taste_embeddings(TEST_USER_ID, db, profile)
    assert negative is not None
    # Weight 1.0 only. A second 0.5 would have pulled the vector off the axis.
    assert np.allclose(negative, _basis(0))


def test_swipe_on_uncached_movie_caches_it_first(
    client_with_tmdb: TestClient, db: Session
) -> None:
    """A reel card can come straight from TMDB; the swipe must not 500 on the FK."""
    make_profile(db, user_id=TEST_USER_ID)
    resp = client_with_tmdb.post("/recommendations/680/not-for-me")
    assert resp.status_code == 200
    assert resp.json()["tmdb_id"] == 680
    row = (
        db.query(MovieInteraction)
        .filter(
            MovieInteraction.user_id == TEST_USER_ID, MovieInteraction.tmdb_id == 680
        )
        .one()
    )
    assert row.interaction_type == "not_for_me"
