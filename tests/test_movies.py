"""Tests for movie schema: vote_average scaling."""

from app.movies.schemas import MovieResponse


def test_vote_average_scaling() -> None:
    """Raw 8.0 from TMDB -> 4.0 in response (divide by 2)."""
    resp = MovieResponse(tmdb_id=1, title="Test", vote_average=8.0)
    assert resp.vote_average == 4.0


def test_vote_average_ten() -> None:
    resp = MovieResponse(tmdb_id=1, title="Test", vote_average=10.0)
    assert resp.vote_average == 5.0


def test_vote_average_zero() -> None:
    resp = MovieResponse(tmdb_id=1, title="Test", vote_average=0.0)
    assert resp.vote_average == 0.0


def test_vote_average_none() -> None:
    resp = MovieResponse(tmdb_id=1, title="Test", vote_average=None)
    assert resp.vote_average is None


def test_vote_average_odd() -> None:
    """Raw 7.0 -> 3.5."""
    resp = MovieResponse(tmdb_id=1, title="Test", vote_average=7.0)
    assert resp.vote_average == 3.5
