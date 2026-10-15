"""Tests for the similarity term of app/movies/services.compute_match_scores."""

from sqlalchemy.orm import Session

from app.import_data.models import MovieEmbedding
from app.movies.services import compute_match_scores
from app.recommendations.ranking import W_SIMILARITY, to_match_percentage
from tests.factories import make_movie, make_profile, make_watched

RATED = [1, 2, 3, 4, 5]
CANDIDATE = 100

# Orthogonal vectors: the candidate's embedding has zero cosine similarity to
# the user's taste embedding, so any non-zero similarity must come from CF.
TASTE_VECTOR = [1.0] + [0.0] * 1535
CANDIDATE_VECTOR = [0.0, 1.0] + [0.0] * 1534


def _make_neutral_movie(db: Session, tmdb_id: int):
    """A movie with no genre/consensus/director/cast signal.

    Cast names are unique per movie so the candidate shares no cast with the
    user's rated movies.
    """
    return make_movie(
        db,
        tmdb_id=tmdb_id,
        title=f"Movie {tmdb_id}",
        genres=[],
        vote_average=None,
        director=None,
        cast=[{"name": f"Actor {tmdb_id}"}],
    )


def _setup(db: Session, with_neighbours: bool) -> str:
    for tmdb_id in [*RATED, CANDIDATE]:
        _make_neutral_movie(db, tmdb_id)
    db.add(MovieEmbedding(tmdb_id=CANDIDATE, embedding=CANDIDATE_VECTOR))

    profile = make_profile(db, username="user", favorite_genres=[])
    profile.taste_embedding = TASTE_VECTOR
    db.commit()
    user_id = str(profile.id)

    ratings = {1: 5.0, 2: 5.0, 3: 5.0, 4: 1.0, 5: 1.0}
    for tmdb_id, rating in ratings.items():
        make_watched(db, user_id=user_id, tmdb_id=tmdb_id, rating=rating)

    if with_neighbours:
        for i in range(4):
            neighbour = str(make_profile(db, username=f"neighbour{i}").id)
            for tmdb_id, rating in {**ratings, CANDIDATE: 5.0}.items():
                make_watched(db, user_id=neighbour, tmdb_id=tmdb_id, rating=rating)

    return user_id


def test_match_score_uses_cf_when_supported(db: Session) -> None:
    """Neighbours who love the candidate lift the score despite zero cosine."""
    user_id = _setup(db, with_neighbours=True)

    scores = compute_match_scores([CANDIDATE], user_id, db)

    assert scores[CANDIDATE] == to_match_percentage(round(W_SIMILARITY * 1.0, 4))


def test_match_score_falls_back_to_cosine_without_cf_support(db: Session) -> None:
    """With no co-raters the orthogonal embedding gives a zero similarity term."""
    user_id = _setup(db, with_neighbours=False)

    scores = compute_match_scores([CANDIDATE], user_id, db)

    assert scores[CANDIDATE] == to_match_percentage(0.0)
