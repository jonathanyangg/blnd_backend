"""Shared media_type and year filters."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import settings
from tests.conftest import TEST_USER_ID
from tests.factories import make_movie, make_profile, make_watchlist, make_watchlist_movie


def test_media_type_rejects_unknown(client: TestClient) -> None:
    response = client.get("/recommendations/now", params={"media_type": "nope"})
    assert response.status_code == 422


def test_year_min_greater_than_max_is_422(client: TestClient) -> None:
    response = client.get(
        "/recommendations/me", params={"year_min": 2010, "year_max": 1990}
    )
    assert response.status_code == 422


def test_tv_filter_is_404_when_tv_disabled(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "tv_support_enabled", False)
    response = client.get("/recommendations/now", params={"media_type": "tv"})
    assert response.status_code == 404
    assert response.json()["detail"] == "TV support is disabled"


def test_tv_filter_on_feed_is_empty_when_tv_enabled(
    client: TestClient, db: Session, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "tv_support_enabled", True)
    make_profile(db, user_id=TEST_USER_ID, username="filteruser")
    response = client.post(
        "/recommendations/me/feed",
        params={"media_type": "tv"},
        json={"limit": 10},
    )
    assert response.status_code == 200
    assert response.json()["results"] == []


def test_watchlist_media_type_and_year(
    client: TestClient, db: Session, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "tv_support_enabled", True)
    watchlist = make_watchlist(db)
    make_profile(db, user_id=TEST_USER_ID, username="filteruser", watchlist_id=watchlist.id)
    make_movie(db, tmdb_id=940001, title="Old Film", year=1975)
    make_watchlist_movie(db, watchlist.id, 940001, added_by=TEST_USER_ID)

    movie = client.get("/watchlist/", params={"media_type": "movie"})
    assert movie.status_code == 200
    assert [row["tmdb_id"] for row in movie.json()["results"]] == [940001]

    tv = client.get("/watchlist/", params={"media_type": "tv"})
    assert tv.status_code == 200
    assert tv.json()["results"] == []

    classic = client.get("/watchlist/", params={"decade": "classic"})
    assert [row["tmdb_id"] for row in classic.json()["results"]] == [940001]

    recent = client.get("/watchlist/", params={"year_min": 2000})
    assert recent.json()["results"] == []


def test_history_tv_filter_is_empty(client: TestClient, db: Session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "tv_support_enabled", True)
    make_profile(db, user_id=TEST_USER_ID, username="filteruser")
    response = client.get("/tracking/", params={"media_type": "tv"})
    assert response.status_code == 200
    assert response.json() == {"results": [], "total": 0}


def test_search_all_includes_both_types(
    client_with_tmdb: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "tv_support_enabled", True)

    async def movies(query: str, page: int, tmdb_client) -> dict:
        return {
            "results": [{"tmdb_id": 1, "title": "Dune", "year": 2021}],
            "total_results": 1,
        }

    async def shows(query: str, page: int, tmdb_client) -> dict:
        return {
            "results": [
                {"tmdb_id": 2, "title": "Dune", "year": 2021, "media_type": "tv"}
            ],
            "total_results": 1,
        }

    monkeypatch.setattr("app.movies.views.services.search_movies", movies)
    monkeypatch.setattr("app.movies.views.tv_services.search_tv_shows", shows)
    response = client_with_tmdb.get(
        "/movies/search", params={"query": "Dune", "media_type": "all"}
    )
    assert response.status_code == 200
    types = {row["media_type"] for row in response.json()["results"]}
    assert types == {"movie", "tv"}
