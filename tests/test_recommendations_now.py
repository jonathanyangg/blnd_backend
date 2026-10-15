"""GET /recommendations/now — one pick, a reason, and a popular fallback."""

from fastapi.testclient import TestClient
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.import_data.models import MovieEmbedding
from app.movies.models import Movie
from tests.conftest import TEST_USER_ID
from tests.factories import make_movie, make_profile, make_watched

SCI_FI = [{"id": 878, "name": "Science Fiction"}]
COMEDY = [{"id": 35, "name": "Comedy"}]


def _vec(index: int, *extra: tuple[int, float]) -> list[float]:
    values = [0.0] * 1536
    values[index] = 1.0
    for position, weight in extra:
        values[position] = weight
    return values


def _force_exact_match(db: Session) -> None:
    """Seq-scan cosine search so a tiny local table still returns nearest neighbors."""
    db.execute(text("SET LOCAL enable_indexscan = off"))
    db.execute(text("SET LOCAL enable_bitmapscan = off"))


def _with_embedding(db: Session, movie: Movie, embedding: list[float]) -> Movie:
    movie.runtime = 120
    movie.vote_count = movie.vote_count or 500
    db.add(MovieEmbedding(tmdb_id=movie.tmdb_id, embedding=embedding))
    db.commit()
    db.refresh(movie)
    return movie


def _outrank(db: Session, movie: Movie) -> Movie:
    current = db.query(func.max(Movie.vote_count)).scalar() or 0
    movie.runtime = 120
    movie.vote_count = int(current) + 1000
    if (movie.vote_average or 0) < 6:
        movie.vote_average = 8.0
    db.commit()
    db.refresh(movie)
    return movie


def test_now_requires_auth(db: Session) -> None:
    from app.dependencies import get_current_user, get_db
    from main import app

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides.pop(get_current_user, None)
    try:
        response = TestClient(app).get("/recommendations/now")
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert response.status_code == 401


def test_now_returns_one_unwatched_pick_with_reason(
    client: TestClient, db: Session
) -> None:
    _force_exact_match(db)
    profile = make_profile(
        db,
        user_id=TEST_USER_ID,
        username="nowuser",
        favorite_genres=["Science Fiction"],
    )
    profile.taste_embedding = _vec(10)
    db.commit()

    watched = make_movie(
        db,
        tmdb_id=910001,
        title="Inception",
        director="Christopher Nolan",
        genres=SCI_FI,
        vote_average=8.8,
    )
    _with_embedding(db, watched, _vec(10))
    make_watched(db, TEST_USER_ID, tmdb_id=watched.tmdb_id, rating=5.0)

    dune = make_movie(
        db,
        tmdb_id=910002,
        title="Dune",
        director="Denis Villeneuve",
        genres=SCI_FI,
        vote_average=8.0,
    )
    _with_embedding(db, dune, _vec(10, (11, 0.2)))
    arrival = make_movie(
        db,
        tmdb_id=910003,
        title="Arrival",
        director="Denis Villeneuve",
        genres=SCI_FI,
        vote_average=7.6,
    )
    _with_embedding(db, arrival, _vec(10, (12, 1.2)))

    response = client.get("/recommendations/now")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"movie", "reason"}
    assert body["movie"]["tmdb_id"] == dune.tmdb_id
    assert body["movie"]["title"] == "Dune"
    assert body["reason"] == "Because you rated Inception highly"


def test_now_exclude_rerolls(client: TestClient, db: Session) -> None:
    _force_exact_match(db)
    profile = make_profile(db, user_id=TEST_USER_ID, username="nowuser")
    profile.taste_embedding = _vec(10)
    db.commit()

    first = make_movie(db, tmdb_id=910002, title="Dune", genres=SCI_FI, vote_average=8.0)
    _with_embedding(db, first, _vec(10, (11, 0.2)))
    second = make_movie(
        db, tmdb_id=910003, title="Arrival", genres=SCI_FI, vote_average=7.6
    )
    _with_embedding(db, second, _vec(10, (12, 1.2)))

    response = client.get("/recommendations/now", params={"exclude": str(first.tmdb_id)})
    assert response.status_code == 200
    body = response.json()
    assert body["movie"]["tmdb_id"] == second.tmdb_id
    assert body["reason"]


def test_now_fallback_without_history(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="nowcold")
    popular = make_movie(
        db, tmdb_id=910010, title="The Godfather", vote_average=9.2, genres=[{"id": 18, "name": "Drama"}]
    )
    _outrank(db, popular)

    response = client.get("/recommendations/now")
    assert response.status_code == 200
    body = response.json()
    assert body["movie"]["tmdb_id"] == popular.tmdb_id
    assert body["reason"] == "Popular right now"


def test_now_genre_filter_uses_fallback(client: TestClient, db: Session) -> None:
    profile = make_profile(db, user_id=TEST_USER_ID, username="nowuser")
    profile.taste_embedding = _vec(10)
    db.commit()
    comedy = make_movie(
        db, tmdb_id=910020, title="Superbad", genres=COMEDY, vote_average=7.6
    )
    _outrank(db, comedy)

    response = client.get("/recommendations/now", params={"genre": "Comedy"})
    assert response.status_code == 200
    body = response.json()
    assert body["movie"]["tmdb_id"] == comedy.tmdb_id
    assert body["reason"] == "Popular with people who like Comedy"
