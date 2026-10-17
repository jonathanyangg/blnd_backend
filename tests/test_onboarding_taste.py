"""POST /onboarding/taste seeds ratings and returns recommendations."""

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.models import Profile
from app.import_data.models import MovieEmbedding
from app.movies.models import Movie
from app.tracking.models import WatchedMovie
from tests.conftest import TEST_USER_ID
from tests.factories import make_movie, make_profile

SCI_FI = [{"id": 878, "name": "Science Fiction"}]


def _vec(index: int) -> list[float]:
    values = [0.0] * 1536
    values[index] = 1.0
    return values


def _force_exact_match(db: Session) -> None:
    db.execute(text("SET LOCAL enable_indexscan = off"))
    db.execute(text("SET LOCAL enable_bitmapscan = off"))


def _film(db: Session, tmdb_id: int, title: str, embedding: list[float]) -> Movie:
    movie = make_movie(
        db,
        tmdb_id=tmdb_id,
        title=title,
        genres=SCI_FI,
        vote_average=8.0,
    )
    movie.runtime = 120
    movie.vote_count = 500
    db.add(MovieEmbedding(tmdb_id=tmdb_id, embedding=embedding))
    db.commit()
    return movie


def test_taste_rejects_fewer_than_five(client_with_tmdb: TestClient) -> None:
    response = client_with_tmdb.post(
        "/onboarding/taste",
        json={"picks": [{"tmdb_id": 1, "rating": 4.0}] * 4},
    )
    assert response.status_code == 422


def test_taste_rejects_duplicate_ids(client_with_tmdb: TestClient) -> None:
    response = client_with_tmdb.post(
        "/onboarding/taste",
        json={"picks": [{"tmdb_id": 1, "rating": 4.0}] * 5},
    )
    assert response.status_code == 422


def test_taste_requires_a_profile(client_with_tmdb: TestClient) -> None:
    picks = [{"tmdb_id": 930000 + index, "rating": 4.0} for index in range(5)]
    response = client_with_tmdb.post("/onboarding/taste", json={"picks": picks})
    assert response.status_code == 404


def test_taste_saves_picks_and_returns_recommendations(
    client_with_tmdb: TestClient, db: Session
) -> None:
    _force_exact_match(db)
    make_profile(db, user_id=TEST_USER_ID, username="tasteuser")
    picks = []
    for index in range(5):
        tmdb_id = 930001 + index
        _film(db, tmdb_id, f"Pick {index}", _vec(3))
        rating = None if index == 4 else 4.0 + index * 0.1
        picks.append({"tmdb_id": tmdb_id, "rating": rating})
    _film(db, 930100, "Neighbor", _vec(3))

    response = client_with_tmdb.post("/onboarding/taste", json={"picks": picks})
    assert response.status_code == 200
    body = response.json()
    assert [item["tmdb_id"] for item in body["saved"]] == [930001 + i for i in range(5)]
    assert body["saved"][4]["rating"] is None
    assert body["saved"][0]["rating"] == 4.0
    assert all(item["tmdb_id"] != 930100 for item in body["saved"])
    assert isinstance(body["results"], list)
    assert 930100 in {item["tmdb_id"] for item in body["results"]}
    assert all(item["tmdb_id"] not in {930001 + i for i in range(5)} for item in body["results"])

    stored = (
        db.query(WatchedMovie)
        .filter(WatchedMovie.user_id == TEST_USER_ID, WatchedMovie.tmdb_id == 930005)
        .one()
    )
    assert stored.rating is None
    assert stored.source == "onboarding_taste"
    profile = db.query(Profile).filter(Profile.id == TEST_USER_ID).one()
    assert profile.taste_embedding is not None
