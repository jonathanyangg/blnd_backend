"""Integration tests for the public profile / watched / friends endpoints.

These run against the real test DB (see conftest) and seed data via factories.
The authenticated caller is CALLER_ID (the ``client`` fixture); TARGET_ID is the
user being viewed.
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.conftest import CALLER_ID, TARGET_ID
from tests.factories import make_friendship, make_movie, make_profile, make_watched

FRIEND_A = "33333333-3333-3333-3333-333333333333"


# --- Public profile (viewable by anyone, not friendship-gated) ---


def test_get_public_profile_success(client: TestClient, db: Session) -> None:
    """Returns 200 with public stat fields and no private fields."""
    make_profile(db, user_id=CALLER_ID, username="caller")
    make_profile(db, user_id=TARGET_ID, username="friend", display_name="Friend User")
    make_friendship(db, CALLER_ID, TARGET_ID, status="accepted")
    make_movie(db, tmdb_id=550, title="Fight Club")
    make_watched(db, user_id=TARGET_ID, tmdb_id=550, rating=4.5)

    response = client.get(f"/auth/users/{TARGET_ID}/profile")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == TARGET_ID
    assert data["username"] == "friend"
    assert data["display_name"] == "Friend User"
    assert data["avatar_url"] is None
    assert data["watched_count"] == 1
    assert data["friends_count"] == 1
    assert data["blends_count"] == 0
    assert data["friendship_status"] == "accepted"
    # Private fields must not leak
    assert "taste_bio" not in data
    assert "favorite_genres" not in data


def test_public_profile_is_public_without_friendship(
    client: TestClient, db: Session
) -> None:
    """A non-friend can still view a public profile; friendship_status is null."""
    make_profile(db, user_id=CALLER_ID, username="caller")
    make_profile(db, user_id=TARGET_ID, username="stranger")

    response = client.get(f"/auth/users/{TARGET_ID}/profile")

    assert response.status_code == 200
    assert response.json()["friendship_status"] is None


def test_public_profile_404_user_not_found(client: TestClient, db: Session) -> None:
    """Returns 404 when the target profile doesn't exist."""
    make_profile(db, user_id=CALLER_ID, username="caller")

    response = client.get(f"/auth/users/{TARGET_ID}/profile")

    assert response.status_code == 404


# --- Watched movies (requires friendship) ---


def test_get_public_watched_success(client: TestClient, db: Session) -> None:
    """Returns 200 with paginated watched movies for an accepted friend."""
    make_profile(db, user_id=CALLER_ID, username="caller")
    make_profile(db, user_id=TARGET_ID, username="friend")
    make_friendship(db, CALLER_ID, TARGET_ID, status="accepted")
    make_movie(db, tmdb_id=550, title="Fight Club")
    make_movie(db, tmdb_id=680, title="Pulp Fiction")
    make_watched(db, user_id=TARGET_ID, tmdb_id=550, rating=4.5)
    make_watched(db, user_id=TARGET_ID, tmdb_id=680, rating=3.0)

    response = client.get(f"/auth/users/{TARGET_ID}/watched?limit=20&offset=0")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert len(data["results"]) == 2
    for item in data["results"]:
        assert "tmdb_id" in item
        assert "title" in item
        assert "poster_path" in item
        assert "rating" in item


def test_get_public_watched_403_not_friends(client: TestClient, db: Session) -> None:
    """Returns 403 when caller is not an accepted friend of the target."""
    make_profile(db, user_id=CALLER_ID, username="caller")
    make_profile(db, user_id=TARGET_ID, username="stranger")

    response = client.get(f"/auth/users/{TARGET_ID}/watched")

    assert response.status_code == 403
    assert response.json()["detail"] == "Not friends with this user"


def test_get_public_watched_pagination(client: TestClient, db: Session) -> None:
    """limit/offset params are honored."""
    make_profile(db, user_id=CALLER_ID, username="caller")
    make_profile(db, user_id=TARGET_ID, username="friend")
    make_friendship(db, CALLER_ID, TARGET_ID, status="accepted")
    for tmdb_id in (550, 680, 13):
        make_movie(db, tmdb_id=tmdb_id, title=f"Movie {tmdb_id}")
        make_watched(db, user_id=TARGET_ID, tmdb_id=tmdb_id, rating=4.0)

    response = client.get(f"/auth/users/{TARGET_ID}/watched?limit=2&offset=0")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert len(data["results"]) == 2


# --- Friends list (requires friendship) ---


def test_get_public_friends_success(client: TestClient, db: Session) -> None:
    """Returns the target's accepted friends (including the caller)."""
    make_profile(db, user_id=CALLER_ID, username="caller")
    make_profile(db, user_id=TARGET_ID, username="friend")
    make_profile(db, user_id=FRIEND_A, username="friend_a", display_name="Friend A")
    make_friendship(db, CALLER_ID, TARGET_ID, status="accepted")
    make_friendship(db, TARGET_ID, FRIEND_A, status="accepted")

    response = client.get(f"/auth/users/{TARGET_ID}/friends")

    assert response.status_code == 200
    data = response.json()
    friend_ids = {f["id"] for f in data["friends"]}
    assert {CALLER_ID, FRIEND_A} == friend_ids
    for f in data["friends"]:
        assert "id" in f
        assert "username" in f
        assert "display_name" in f
        assert "avatar_url" in f


def test_get_public_friends_403_not_friends(client: TestClient, db: Session) -> None:
    """Returns 403 when caller is not an accepted friend of the target."""
    make_profile(db, user_id=CALLER_ID, username="caller")
    make_profile(db, user_id=TARGET_ID, username="stranger")

    response = client.get(f"/auth/users/{TARGET_ID}/friends")

    assert response.status_code == 403
    assert response.json()["detail"] == "Not friends with this user"


def test_get_public_friends_only_caller(client: TestClient, db: Session) -> None:
    """When the target's only friend is the caller, the list is just the caller."""
    make_profile(db, user_id=CALLER_ID, username="caller")
    make_profile(db, user_id=TARGET_ID, username="friend")
    make_friendship(db, CALLER_ID, TARGET_ID, status="accepted")

    response = client.get(f"/auth/users/{TARGET_ID}/friends")

    assert response.status_code == 200
    data = response.json()
    assert [f["id"] for f in data["friends"]] == [CALLER_ID]
