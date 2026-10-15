"""Shared media_type and year filters."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import settings
from tests.conftest import TEST_USER_ID
from tests.factories import (
    make_group,
    make_movie,
    make_profile,
    make_watched,
    make_watchlist,
    make_watchlist_movie,
)


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
    make_profile(
        db, user_id=TEST_USER_ID, username="filteruser", watchlist_id=watchlist.id
    )
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


def test_history_tv_filter_is_empty(
    client: TestClient, db: Session, monkeypatch
) -> None:
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


def test_search_without_media_type_stays_movies(
    client_with_tmdb: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "tv_support_enabled", True)

    async def movies(query: str, page: int, tmdb_client) -> dict:
        return {
            "results": [{"tmdb_id": 1, "title": "Dune", "year": 2021}],
            "total_results": 1,
        }

    async def shows(query: str, page: int, tmdb_client) -> dict:
        raise AssertionError("TV search must not run when media_type is omitted")

    monkeypatch.setattr("app.movies.views.services.search_movies", movies)
    monkeypatch.setattr("app.movies.views.tv_services.search_tv_shows", shows)
    response = client_with_tmdb.get("/movies/search", params={"query": "Dune"})
    assert response.status_code == 200
    assert [row["tmdb_id"] for row in response.json()["results"]] == [1]
    assert response.json()["results"][0]["media_type"] == "movie"


def test_tv_search_honors_year_and_movie_filter(
    client_with_tmdb: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "tv_support_enabled", True)

    async def shows(query: str, page: int, tmdb_client) -> dict:
        return {
            "results": [
                {"tmdb_id": 1, "title": "Old", "year": 1995, "media_type": "tv"},
                {"tmdb_id": 2, "title": "New", "year": 2022, "media_type": "tv"},
            ],
            "total_results": 2,
        }

    monkeypatch.setattr("app.tv.views.services.search_tv_shows", shows)
    classics = client_with_tmdb.get(
        "/tv/search", params={"query": "show", "year_max": 1989}
    )
    assert classics.status_code == 200
    assert classics.json()["results"] == []

    recent = client_with_tmdb.get(
        "/tv/search", params={"query": "show", "year_min": 2020, "year_max": 2029}
    )
    assert [row["tmdb_id"] for row in recent.json()["results"]] == [2]

    movies = client_with_tmdb.get(
        "/tv/search", params={"query": "show", "media_type": "movie"}
    )
    assert movies.status_code == 200
    assert movies.json() == {"results": [], "total_results": 0}


def test_semantic_discover_tv_is_empty_and_year_filters(
    client: TestClient, db: Session, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "tv_support_enabled", True)
    make_profile(db, user_id=TEST_USER_ID, username="filteruser")
    monkeypatch.setattr("app.recommendations.views.is_premium", lambda profile: True)

    def discover(**kwargs):
        return {
            "query": kwargs["query"],
            "results": [
                {"tmdb_id": 1, "title": "Heat", "year": 1995, "match_score": 0.8},
                {"tmdb_id": 2, "title": "Dune", "year": 2021, "match_score": 0.7},
            ],
        }

    monkeypatch.setattr(
        "app.recommendations.semantic_search.run_semantic_discover", discover
    )
    tv = client.post(
        "/recommendations/semantic-discover",
        params={"media_type": "tv"},
        json={"query": "quiet crime", "limit": 10},
    )
    assert tv.status_code == 200
    assert tv.json()["results"] == []

    nineties = client.post(
        "/recommendations/semantic-discover",
        params={"year_min": 1990, "year_max": 1999},
        json={"query": "quiet crime", "limit": 10},
    )
    assert nineties.status_code == 200
    rows = nineties.json()["results"]
    assert [row["tmdb_id"] for row in rows] == [1]
    assert rows[0]["media_type"] == "movie"
    assert rows[0]["year"] == 1995


def test_watched_and_watchlist_items_include_year_and_media_type(
    client: TestClient, db: Session
) -> None:
    watchlist = make_watchlist(db)
    make_profile(
        db, user_id=TEST_USER_ID, username="filteruser", watchlist_id=watchlist.id
    )
    make_movie(db, tmdb_id=940010, title="Heat", year=1995)
    make_watched(db, user_id=TEST_USER_ID, tmdb_id=940010)
    make_watchlist_movie(db, watchlist.id, 940010, added_by=TEST_USER_ID)

    history = client.get("/tracking/")
    assert history.status_code == 200
    row = history.json()["results"][0]
    assert row["year"] == 1995
    assert row["media_type"] == "movie"

    saved = client.get("/watchlist/")
    assert saved.status_code == 200
    item = saved.json()["results"][0]
    assert item["year"] == 1995
    assert item["media_type"] == "movie"


def test_group_watchlist_items_include_media_type(
    client: TestClient, db: Session
) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="filteruser")
    group, watchlist = make_group(db, created_by=TEST_USER_ID)
    make_movie(db, tmdb_id=940011, title="Alien", year=1979)
    make_watchlist_movie(db, watchlist.id, 940011, added_by=TEST_USER_ID)
    response = client.get(f"/groups/{group.id}/watchlist")
    assert response.status_code == 200
    row = response.json()["results"][0]
    assert row["tmdb_id"] == 940011
    assert row["year"] == 1979
    assert row["media_type"] == "movie"
