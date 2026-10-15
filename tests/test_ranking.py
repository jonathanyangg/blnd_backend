"""Tests for app/recommendations/ranking.py — pure functions, no mocking needed."""

from app.movies.models import Movie
from app.recommendations.ranking import (
    MATCH_BOOST,
    W_SIMILARITY,
    _cast_boost,
    _consensus_score,
    _director_boost,
    _genre_overlap,
    rerank_candidates,
    to_match_percentage,
)


# --- _genre_overlap ---


def test_genre_overlap_empty_user_genres() -> None:
    assert _genre_overlap([{"name": "Drama"}], []) == 0.0


def test_genre_overlap_empty_movie_genres() -> None:
    assert _genre_overlap([], ["drama"]) == 0.0


def test_genre_overlap_both_empty() -> None:
    assert _genre_overlap([], []) == 0.0


def test_genre_overlap_full() -> None:
    movie = [{"name": "Drama"}, {"name": "Thriller"}]
    user = ["drama", "thriller"]
    assert _genre_overlap(movie, user) == 1.0


def test_genre_overlap_partial() -> None:
    movie = [{"name": "Drama"}, {"name": "Comedy"}]
    user = ["drama", "thriller"]
    # intersection={"drama"}, union={"drama","comedy","thriller"} => 1/3
    result = _genre_overlap(movie, user)
    assert abs(result - 1 / 3) < 1e-9


def test_genre_overlap_no_overlap() -> None:
    movie = [{"name": "Horror"}]
    user = ["comedy"]
    assert _genre_overlap(movie, user) == 0.0


# --- _consensus_score ---


def test_consensus_none() -> None:
    assert _consensus_score(None) == 0.0


def test_consensus_zero() -> None:
    assert _consensus_score(0) == 0.0


def test_consensus_five() -> None:
    assert _consensus_score(5) == 0.5


def test_consensus_ten() -> None:
    assert _consensus_score(10) == 1.0


def test_consensus_above_ten() -> None:
    # Should clamp to 1.0
    assert _consensus_score(12) == 1.0


# --- _director_boost ---


def test_director_match() -> None:
    assert _director_boost("David Fincher", {"david fincher"}) == 1.0


def test_director_no_match() -> None:
    assert _director_boost("David Fincher", {"christopher nolan"}) == 0.0


def test_director_none() -> None:
    assert _director_boost(None, {"david fincher"}) == 0.0


def test_director_empty_set() -> None:
    assert _director_boost("David Fincher", set()) == 0.0


# --- _cast_boost ---


def test_cast_partial_overlap() -> None:
    movie_cast = [{"name": "Brad Pitt"}, {"name": "Edward Norton"}]
    top_cast = {"brad pitt", "leonardo dicaprio"}
    # 1 match / 2 movie cast = 0.5
    assert _cast_boost(movie_cast, top_cast) == 0.5


def test_cast_full_overlap() -> None:
    movie_cast = [{"name": "Brad Pitt"}]
    top_cast = {"brad pitt"}
    assert _cast_boost(movie_cast, top_cast) == 1.0


def test_cast_no_overlap() -> None:
    movie_cast = [{"name": "Brad Pitt"}]
    top_cast = {"leonardo dicaprio"}
    assert _cast_boost(movie_cast, top_cast) == 0.0


def test_cast_empty_movie() -> None:
    assert _cast_boost([], {"brad pitt"}) == 0.0


def test_cast_empty_top() -> None:
    assert _cast_boost([{"name": "Brad Pitt"}], set()) == 0.0


# --- to_match_percentage ---


def test_match_percentage_zero() -> None:
    # 0 + (1 - 0) * 0.4 = 0.4
    assert to_match_percentage(0.0) == MATCH_BOOST


def test_match_percentage_one() -> None:
    # 1 + (1 - 1) * 0.4 = 1.0
    assert to_match_percentage(1.0) == 1.0


def test_match_percentage_half() -> None:
    # 0.5 + MATCH_BOOST (0.33) = 0.83
    assert to_match_percentage(0.5) == round(0.5 + MATCH_BOOST, 4)


# --- rerank_candidates: CF vs embedding similarity ---


def _candidate(tmdb_id: int, similarity: float) -> dict:
    movie = Movie(tmdb_id=tmdb_id, title=f"Movie {tmdb_id}", genres=[], cast=[])
    return {"tmdb_id": tmdb_id, "similarity": similarity, "movie": movie}


def _scores(ranked: list[dict]) -> dict[int, float]:
    return {c["tmdb_id"]: c["score"] for c in ranked}


def test_rerank_uses_cf_score_over_embedding_similarity() -> None:
    ranked = rerank_candidates(
        [_candidate(1, 0.9), _candidate(2, 0.1)],
        user_genres=[],
        top_directors=set(),
        top_cast=set(),
        cf_scores={1: 0.1, 2: 0.9},
    )
    scores = _scores(ranked)
    assert scores[2] == round(W_SIMILARITY * 0.9, 4)
    assert scores[1] == round(W_SIMILARITY * 0.1, 4)


def test_rerank_falls_back_to_embedding_similarity_without_cf_score() -> None:
    ranked = rerank_candidates(
        [_candidate(1, 0.9), _candidate(2, 0.1)],
        user_genres=[],
        top_directors=set(),
        top_cast=set(),
        cf_scores={2: 0.4},
    )
    scores = _scores(ranked)
    assert scores[1] == round(W_SIMILARITY * 0.9, 4)
    assert scores[2] == round(W_SIMILARITY * 0.4, 4)


def test_rerank_without_cf_scores_matches_embedding_similarity() -> None:
    ranked = rerank_candidates(
        [_candidate(1, 0.9)],
        user_genres=[],
        top_directors=set(),
        top_cast=set(),
    )
    assert _scores(ranked)[1] == round(W_SIMILARITY * 0.9, 4)
