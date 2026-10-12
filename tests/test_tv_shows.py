"""Feature-flagged, show-level TV support tests."""

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.dependencies import get_current_user, get_db, get_tmdb_client
from app.tracking.models import WatchedMovie
from tests.conftest import TEST_USER_ID


class _FakeTVResponse:
    def __init__(self, data: dict) -> None:
        self._data = data

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._data


class _FakeTVTMDBClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def get(self, url: str, params: dict | None = None) -> _FakeTVResponse:
        self.calls.append(url)
        if url == "/search/tv":
            return _FakeTVResponse(
                {
                    "page": 1,
                    "results": [
                        {
                            "id": 1399,
                            "name": "Game of Thrones",
                            "first_air_date": "2011-04-17",
                            "overview": "Nine noble families...",
                            "poster_path": "/tv-poster.jpg",
                            "vote_average": 8.4,
                            "vote_count": 100,
                        }
                    ],
                    "total_pages": 1,
                    "total_results": 1,
                }
            )
        return _FakeTVResponse(
            {
                "id": 1399,
                "name": "Game of Thrones",
                "first_air_date": "2011-04-17",
                "overview": "Nine noble families...",
                "poster_path": "/tv-poster.jpg",
                "backdrop_path": "/tv-backdrop.jpg",
                "genres": [{"id": 18, "name": "Drama"}],
                "number_of_seasons": 8,
                "episode_run_time": [57],
                "vote_average": 8.4,
                "vote_count": 100,
            }
        )


def _tv_client(db: Session) -> TestClient:
    from main import app

    fake = _FakeTVTMDBClient()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: TEST_USER_ID
    app.dependency_overrides[get_tmdb_client] = lambda: fake
    return TestClient(app)


def test_tv_support_defaults_off() -> None:
    assert settings.tv_support_enabled is False


def test_tv_search_is_disabled_by_default(
    client_with_tmdb: TestClient,
) -> None:
    response = client_with_tmdb.get("/tv/search", params={"query": "Thrones"})

    assert response.status_code == 404


def test_tv_search_uses_tmdb_tv_search(
    client_with_tmdb: TestClient,
    db: Session,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "tv_support_enabled", True)
    fake = _FakeTVTMDBClient()
    client_with_tmdb.app.dependency_overrides[get_tmdb_client] = lambda: fake

    response = client_with_tmdb.get("/tv/search", params={"query": "Thrones"})

    assert response.status_code == 200
    assert fake.calls == ["/search/tv"]
    result = response.json()
    assert result["total_results"] == 1
    assert result["results"][0]["tmdb_id"] == 1399
    assert result["results"][0]["title"] == "Game of Thrones"
    assert result["results"][0]["year"] == 2011


def test_track_tv_show_does_not_collide_with_movie_id(
    client_with_tmdb: TestClient,
    db: Session,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "tv_support_enabled", True)
    db.execute(
        text(
            "INSERT INTO movies (tmdb_id, title) VALUES (1399, 'Movie 1399') "
            "ON CONFLICT (tmdb_id) DO NOTHING"
        )
    )
    db.commit()
    response = client_with_tmdb.post(
        "/tracking/tv/1399",
        json={"rating": 4.5},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["tmdb_id"] == 1399
    assert data["title"] == "Game of Thrones"
    assert data["rating"] == 4.5
    assert (
        db.query(WatchedMovie).filter(WatchedMovie.tmdb_id == 1399).count() == 0
    )
