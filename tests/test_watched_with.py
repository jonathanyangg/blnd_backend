"""Watched-with tags on movie logs, plus RLS for owner and companion."""

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.friends.models import UserBlock
from app.groups.models import GroupMember
from app.tracking.models import WatchedWith
from tests.conftest import TEST_USER_ID, TEST_USER_ID_2, assert_error
from tests.factories import (
    make_friendship,
    make_group,
    make_movie,
    make_profile,
    make_watched,
)

STRANGER_ID = "33333333-3333-3333-3333-333333333333"
REBUILD_PATH = "app.tracking.views.rebuild_taste_profile"


def _ids(payload: dict) -> list[str]:
    return [person["id"] for person in payload["watched_with"]]


@pytest.fixture
def people(db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="wwowner")
    make_profile(db, user_id=TEST_USER_ID_2, username="wwada", display_name="Ada")
    make_profile(db, user_id=STRANGER_ID, username="wwstranger")
    make_movie(db, tmdb_id=550)


@patch(REBUILD_PATH)
def test_track_tags_friend(
    mock_rebuild, client_with_tmdb: TestClient, db: Session, people: None
) -> None:
    make_friendship(db, TEST_USER_ID, TEST_USER_ID_2, status="accepted")
    resp = client_with_tmdb.post(
        "/tracking/",
        json={"tmdb_id": 550, "rating": 4.0, "watched_with": [TEST_USER_ID_2]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert _ids(body) == [TEST_USER_ID_2]
    assert body["watched_with"][0]["name"] == "Ada"
    assert body["watched_with"][0]["avatar"] is None

    listed = client_with_tmdb.get("/tracking/")
    assert listed.status_code == 200
    assert _ids(listed.json()["results"][0]) == [TEST_USER_ID_2]

    one = client_with_tmdb.get("/tracking/550")
    assert one.status_code == 200
    assert _ids(one.json()) == [TEST_USER_ID_2]


@patch(REBUILD_PATH)
def test_track_tags_blend_member_who_is_not_a_friend(
    mock_rebuild, client_with_tmdb: TestClient, db: Session, people: None
) -> None:
    group, _watchlist = make_group(db, created_by=TEST_USER_ID)
    db.add(GroupMember(group_id=group.id, user_id=TEST_USER_ID_2))
    db.commit()

    resp = client_with_tmdb.post(
        "/tracking/",
        json={"tmdb_id": 550, "watched_with": [TEST_USER_ID_2, TEST_USER_ID_2]},
    )
    assert resp.status_code == 200
    assert _ids(resp.json()) == [TEST_USER_ID_2]


@pytest.mark.parametrize(
    "companion_id",
    [STRANGER_ID, TEST_USER_ID, TEST_USER_ID_2],
)
@patch(REBUILD_PATH)
def test_track_rejects_people_who_are_not_friends_or_blend_members(
    mock_rebuild,
    client_with_tmdb: TestClient,
    db: Session,
    people: None,
    companion_id: str,
) -> None:
    # TEST_USER_ID_2 exists but the friendship stays pending.
    if companion_id == TEST_USER_ID_2:
        make_friendship(db, TEST_USER_ID, TEST_USER_ID_2, status="pending")

    resp = client_with_tmdb.post(
        "/tracking/", json={"tmdb_id": 550, "watched_with": [companion_id]}
    )
    assert_error(
        resp,
        status=400,
        code="BAD_REQUEST",
        message="Can only tag friends or Blend members",
    )
    assert (
        db.query(WatchedWith).filter(WatchedWith.owner_id == TEST_USER_ID).count() == 0
    )


@patch(REBUILD_PATH)
def test_track_rejects_blocked_blend_member(
    mock_rebuild, client_with_tmdb: TestClient, db: Session, people: None
) -> None:
    group, _watchlist = make_group(db, created_by=TEST_USER_ID)
    db.add(GroupMember(group_id=group.id, user_id=TEST_USER_ID_2))
    db.add(UserBlock(blocker_id=TEST_USER_ID_2, blocked_id=TEST_USER_ID))
    db.commit()

    resp = client_with_tmdb.post(
        "/tracking/", json={"tmdb_id": 550, "watched_with": [TEST_USER_ID_2]}
    )
    assert_error(
        resp,
        status=400,
        code="BAD_REQUEST",
        message="Can only tag friends or Blend members",
    )
    assert (
        db.query(WatchedWith).filter(WatchedWith.owner_id == TEST_USER_ID).count() == 0
    )


def test_update_watched_with(client: TestClient, db: Session, people: None) -> None:
    make_friendship(db, TEST_USER_ID, TEST_USER_ID_2, status="accepted")
    beau = make_profile(db, username="wwbeau", display_name="Beau")
    make_friendship(db, TEST_USER_ID, str(beau.id), status="accepted")
    make_watched(db, user_id=TEST_USER_ID, tmdb_id=550, rating=3.0)

    tagged = client.patch("/tracking/550", json={"watched_with": [TEST_USER_ID_2]})
    assert tagged.status_code == 200
    assert _ids(tagged.json()) == [TEST_USER_ID_2]

    kept = client.patch("/tracking/550", json={"rating": 4.5})
    assert kept.status_code == 200
    assert kept.json()["rating"] == 4.5
    assert _ids(kept.json()) == [TEST_USER_ID_2]

    swapped = client.patch("/tracking/550", json={"watched_with": [str(beau.id)]})
    assert swapped.status_code == 200
    assert _ids(swapped.json()) == [str(beau.id)]

    cleared = client.patch("/tracking/550", json={"watched_with": []})
    assert cleared.status_code == 200
    assert cleared.json()["watched_with"] == []


def test_put_replaces_watched_with(
    client: TestClient, db: Session, people: None
) -> None:
    make_friendship(db, TEST_USER_ID, TEST_USER_ID_2, status="accepted")
    missing = client.get("/tracking/550/watched-with")
    assert_error(
        missing, status=404, code="NOT_FOUND", message="Movie not in watch history"
    )

    make_watched(db, user_id=TEST_USER_ID, tmdb_id=550)
    put = client.put("/tracking/550/watched-with", json={"user_ids": [TEST_USER_ID_2]})
    assert put.status_code == 200
    assert put.json()["watched_with"] == [
        {"id": TEST_USER_ID_2, "name": "Ada", "avatar": None}
    ]

    got = client.get("/tracking/550/watched-with")
    assert got.status_code == 200
    assert got.json() == put.json()

    rejected = client.put(
        "/tracking/550/watched-with", json={"user_ids": [STRANGER_ID]}
    )
    assert_error(
        rejected,
        status=400,
        code="BAD_REQUEST",
        message="Can only tag friends or Blend members",
    )
    assert client.get("/tracking/550/watched-with").json()["watched_with"][0]["id"] == (
        TEST_USER_ID_2
    )

    cleared = client.put("/tracking/550/watched-with", json={"user_ids": []})
    assert cleared.status_code == 200
    assert cleared.json()["watched_with"] == []


def test_notify_watched_with_only_new_ids(
    client: TestClient, db: Session, people: None, monkeypatch
) -> None:
    import app.notifications.services as notifications

    make_friendship(db, TEST_USER_ID, TEST_USER_ID_2, status="accepted")
    beau = make_profile(db, username="wwbeau2", display_name="Beau")
    make_friendship(db, TEST_USER_ID, str(beau.id), status="accepted")
    make_watched(db, user_id=TEST_USER_ID, tmdb_id=550)
    calls: list[list[str]] = []

    def fake(
        db, *, actor_id, tagged_user_ids, tmdb_id, movie_title=None, poster_path=None
    ):
        assert actor_id == TEST_USER_ID
        assert tmdb_id == 550
        calls.append(list(tagged_user_ids))

    monkeypatch.setattr(notifications, "notify_watched_with", fake, raising=False)

    first = client.put(
        "/tracking/550/watched-with", json={"user_ids": [TEST_USER_ID_2]}
    )
    assert first.status_code == 200
    second = client.put(
        "/tracking/550/watched-with",
        json={"user_ids": [TEST_USER_ID_2, str(beau.id)]},
    )
    assert second.status_code == 200
    same = client.patch(
        "/tracking/550", json={"watched_with": [TEST_USER_ID_2, str(beau.id)]}
    )
    assert same.status_code == 200
    assert calls == [[TEST_USER_ID_2], [str(beau.id)]]


@patch(REBUILD_PATH)
def test_upsert_without_tags_keeps_existing(
    mock_rebuild, client_with_tmdb: TestClient, db: Session, people: None
) -> None:
    make_friendship(db, TEST_USER_ID, TEST_USER_ID_2, status="accepted")
    first = client_with_tmdb.post(
        "/tracking/", json={"tmdb_id": 550, "watched_with": [TEST_USER_ID_2]}
    )
    assert first.status_code == 200
    second = client_with_tmdb.post("/tracking/", json={"tmdb_id": 550, "rating": 5.0})
    assert second.status_code == 200
    assert second.json()["rating"] == 5.0
    assert _ids(second.json()) == [TEST_USER_ID_2]


def test_delete_log_removes_companions(
    client: TestClient, db: Session, people: None
) -> None:
    make_friendship(db, TEST_USER_ID, TEST_USER_ID_2, status="accepted")
    make_watched(db, user_id=TEST_USER_ID, tmdb_id=550)
    tagged = client.patch("/tracking/550", json={"watched_with": [TEST_USER_ID_2]})
    assert tagged.status_code == 200

    deleted = client.delete("/tracking/550")
    assert deleted.status_code == 204
    assert (
        db.query(WatchedWith).filter(WatchedWith.owner_id == TEST_USER_ID).count() == 0
    )


def _as_user(db: Session, user_id: str) -> None:
    claims = json.dumps({"sub": user_id, "role": "authenticated"})
    db.execute(
        text("select set_config('request.jwt.claim.sub', :sub, true)"),
        {"sub": user_id},
    )
    db.execute(
        text("select set_config('request.jwt.claims', :claims, true)"),
        {"claims": claims},
    )
    db.execute(text("set local role authenticated"))


def _as_postgres(db: Session) -> None:
    db.execute(text("reset role"))


def _visible_companions(db: Session) -> list[str]:
    rows = db.execute(text("select user_id::text from watched_with")).all()
    return sorted(row[0] for row in rows)


def test_rls_owner_and_companion_can_read(db: Session, people: None) -> None:
    entry = make_watched(db, user_id=TEST_USER_ID, tmdb_id=550)
    watch_id = entry.id
    db.add(
        WatchedWith(
            watched_movie_id=watch_id,
            owner_id=TEST_USER_ID,
            user_id=TEST_USER_ID_2,
        )
    )
    db.commit()

    _as_user(db, TEST_USER_ID)
    assert _visible_companions(db) == [TEST_USER_ID_2]
    _as_postgres(db)

    _as_user(db, TEST_USER_ID_2)
    assert _visible_companions(db) == [TEST_USER_ID_2]
    _as_postgres(db)

    _as_user(db, STRANGER_ID)
    assert _visible_companions(db) == []
    _as_postgres(db)

    _as_user(db, TEST_USER_ID)
    with pytest.raises(DBAPIError):
        with db.begin_nested():
            db.execute(
                text(
                    "insert into watched_with (watched_movie_id, owner_id, user_id) "
                    "values (:wid, :owner, :uid)"
                ),
                {"wid": watch_id, "owner": TEST_USER_ID, "uid": STRANGER_ID},
            )
    _as_postgres(db)
