"""Tests for tracking domain: track, update, delete, watch history."""

from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.tracking.models import WatchlistMovie
from tests.conftest import TEST_USER_ID
from tests.factories import (
    make_movie,
    make_profile,
    make_watched,
    make_watchlist,
    make_watchlist_movie,
)

REBUILD_PATH = "app.tracking.views.rebuild_taste_profile"


# --- Track movie ---


@patch(REBUILD_PATH)
def test_track_movie(mock_rebuild, client_with_tmdb: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="user1")
    resp = client_with_tmdb.post("/tracking/", json={"tmdb_id": 550, "rating": 4.5})
    assert resp.status_code == 200
    data = resp.json()
    assert data["tmdb_id"] == 550
    assert data["title"] == "Fight Club"
    assert data["rating"] == 4.5


@patch(REBUILD_PATH)
def test_track_movie_upsert(
    mock_rebuild, client_with_tmdb: TestClient, db: Session
) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="user1")
    # First track
    client_with_tmdb.post("/tracking/", json={"tmdb_id": 550, "rating": 3.0})
    # Update via upsert
    resp = client_with_tmdb.post("/tracking/", json={"tmdb_id": 550, "rating": 4.0})
    assert resp.status_code == 200
    assert resp.json()["rating"] == 4.0


# --- Auto-remove from watchlist on track ---


def test_track_removes_from_watchlist(
    client_with_tmdb: TestClient, db: Session
) -> None:
    wl = make_watchlist(db)
    make_profile(db, user_id=TEST_USER_ID, username="user1", watchlist_id=wl.id)
    make_movie(db, tmdb_id=550)
    make_watchlist_movie(db, watchlist_id=wl.id, tmdb_id=550, added_by=TEST_USER_ID)

    # Track the movie
    resp = client_with_tmdb.post("/tracking/", json={"tmdb_id": 550})
    assert resp.status_code == 200

    # Verify removed from watchlist
    wl_entry = (
        db.query(WatchlistMovie)
        .filter(WatchlistMovie.watchlist_id == wl.id, WatchlistMovie.tmdb_id == 550)
        .first()
    )
    assert wl_entry is None


# --- Update tracked movie ---


@patch(REBUILD_PATH)
def test_update_rating(mock_rebuild, client: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="user1")
    make_movie(db, tmdb_id=550)
    make_watched(db, user_id=TEST_USER_ID, tmdb_id=550, rating=3.0)

    resp = client.patch("/tracking/550", json={"rating": 4.5})
    assert resp.status_code == 200
    assert resp.json()["rating"] == 4.5


def test_update_review(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="user1")
    make_movie(db, tmdb_id=550)
    make_watched(db, user_id=TEST_USER_ID, tmdb_id=550)

    resp = client.patch("/tracking/550", json={"review": "Great movie"})
    assert resp.status_code == 200
    assert resp.json()["review"] == "Great movie"


# --- Delete tracked movie ---


@patch(REBUILD_PATH)
def test_delete_tracked(mock_rebuild, client: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="user1")
    make_movie(db, tmdb_id=550)
    make_watched(db, user_id=TEST_USER_ID, tmdb_id=550)

    resp = client.delete("/tracking/550")
    assert resp.status_code == 204

    # Verify gone (untracked returns 200 with null body)
    resp = client.get("/tracking/550")
    assert resp.status_code == 200
    assert resp.json() is None


def test_delete_nonexistent(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="user1")
    resp = client.delete("/tracking/999")
    assert resp.status_code == 404


# --- Watch history ---


def test_watch_history_pagination(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="user1")
    for i in range(5):
        make_movie(db, tmdb_id=100 + i, title=f"Movie {i}")
        make_watched(db, user_id=TEST_USER_ID, tmdb_id=100 + i)

    resp = client.get("/tracking/", params={"limit": 2, "offset": 0})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 5
    assert len(data["results"]) == 2


def test_watch_history_empty(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="user1")
    resp = client.get("/tracking/")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


# --- Get single tracked movie ---


def test_get_watched_movie(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="user1")
    make_movie(db, tmdb_id=550)
    make_watched(db, user_id=TEST_USER_ID, tmdb_id=550, rating=4.0)

    resp = client.get("/tracking/550")
    assert resp.status_code == 200
    assert resp.json()["rating"] == 4.0


def test_get_watched_movie_not_found(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="user1")
    resp = client.get("/tracking/999")
    # Untracked movie returns 200 with a null body (response_model is nullable)
    assert resp.status_code == 200
    assert resp.json() is None
