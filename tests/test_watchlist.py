"""Tests for watchlist domain: add, remove, list."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.conftest import TEST_USER_ID
from tests.factories import (
    make_movie,
    make_profile,
    make_watchlist,
    make_watchlist_movie,
)


# --- Add to watchlist ---


def test_add_to_watchlist(client_with_tmdb: TestClient, db: Session) -> None:
    wl = make_watchlist(db)
    make_profile(db, user_id=TEST_USER_ID, username="user1", watchlist_id=wl.id)

    resp = client_with_tmdb.post("/watchlist/", json={"tmdb_id": 550})
    assert resp.status_code == 201
    data = resp.json()
    assert data["tmdb_id"] == 550
    assert data["title"] == "Fight Club"


def test_add_duplicate(client_with_tmdb: TestClient, db: Session) -> None:
    wl = make_watchlist(db)
    make_profile(db, user_id=TEST_USER_ID, username="user1", watchlist_id=wl.id)
    make_movie(db, tmdb_id=550)
    make_watchlist_movie(db, watchlist_id=wl.id, tmdb_id=550)

    resp = client_with_tmdb.post("/watchlist/", json={"tmdb_id": 550})
    assert resp.status_code == 400


# --- Remove from watchlist ---


def test_remove_from_watchlist(client: TestClient, db: Session) -> None:
    wl = make_watchlist(db)
    make_profile(db, user_id=TEST_USER_ID, username="user1", watchlist_id=wl.id)
    make_movie(db, tmdb_id=550)
    make_watchlist_movie(db, watchlist_id=wl.id, tmdb_id=550)

    resp = client.delete("/watchlist/550")
    assert resp.status_code == 204


def test_remove_nonexistent(client: TestClient, db: Session) -> None:
    wl = make_watchlist(db)
    make_profile(db, user_id=TEST_USER_ID, username="user1", watchlist_id=wl.id)

    resp = client.delete("/watchlist/999")
    assert resp.status_code == 404


# --- List watchlist ---


def test_list_watchlist(client: TestClient, db: Session) -> None:
    wl = make_watchlist(db)
    make_profile(db, user_id=TEST_USER_ID, username="user1", watchlist_id=wl.id)
    for i in range(3):
        make_movie(db, tmdb_id=100 + i, title=f"Movie {i}")
        make_watchlist_movie(db, watchlist_id=wl.id, tmdb_id=100 + i)

    resp = client.get("/watchlist/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert len(data["results"]) == 3


def test_list_watchlist_empty(client: TestClient, db: Session) -> None:
    wl = make_watchlist(db)
    make_profile(db, user_id=TEST_USER_ID, username="user1", watchlist_id=wl.id)

    resp = client.get("/watchlist/")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


def test_list_watchlist_no_profile(client: TestClient, db: Session) -> None:
    """No profile => empty watchlist, not an error."""
    resp = client.get("/watchlist/")
    assert resp.status_code == 200
    assert resp.json()["results"] == []


def test_list_watchlist_pagination(client: TestClient, db: Session) -> None:
    wl = make_watchlist(db)
    make_profile(db, user_id=TEST_USER_ID, username="user1", watchlist_id=wl.id)
    for i in range(5):
        make_movie(db, tmdb_id=200 + i, title=f"Movie {i}")
        make_watchlist_movie(db, watchlist_id=wl.id, tmdb_id=200 + i)

    resp = client.get("/watchlist/", params={"limit": 2, "offset": 0})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 5
    assert len(data["results"]) == 2
