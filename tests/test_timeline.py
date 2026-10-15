"""Cursor-paginated watch timelines for profiles and Blends."""

from datetime import date, datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.friends.models import UserBlock
from app.groups.models import GroupMember
from app.tv.models import TVShow, WatchedTVShow
from tests.conftest import TEST_USER_ID, TEST_USER_ID_2, assert_error
from tests.factories import (
    make_friendship,
    make_group,
    make_movie,
    make_profile,
    make_watched,
)

STRANGER_ID = "33333333-3333-3333-3333-333333333333"


def _people(db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="tlowner", display_name="Owner")
    make_profile(db, user_id=TEST_USER_ID_2, username="tlada", display_name="Ada")
    make_profile(db, user_id=STRANGER_ID, username="tlstranger")


def _watch(
    db: Session,
    user_id: str,
    tmdb_id: int,
    title: str,
    watched_date: date | None,
    created_at: datetime,
    rating: float | None = None,
) -> int:
    make_movie(db, tmdb_id=tmdb_id, title=title)
    entry = make_watched(db, user_id=user_id, tmdb_id=tmdb_id, rating=rating)
    entry.watched_date = watched_date
    entry.created_at = created_at
    db.commit()
    return entry.id


def test_profile_timeline_is_dated_and_includes_companions(
    client: TestClient, db: Session
) -> None:
    _people(db)
    _watch(
        db,
        TEST_USER_ID,
        100,
        "Older",
        date(2026, 1, 2),
        datetime(2026, 1, 2, 8, tzinfo=timezone.utc),
        rating=3.0,
    )
    newer = _watch(
        db,
        TEST_USER_ID,
        101,
        "Newer",
        date(2026, 3, 4),
        datetime(2026, 3, 4, 8, tzinfo=timezone.utc),
        rating=4.5,
    )
    db.execute(
        text(
            "insert into watched_with (watched_movie_id, owner_id, user_id) "
            "values (:log_id, :owner, :companion)"
        ),
        {"log_id": newer, "owner": TEST_USER_ID, "companion": TEST_USER_ID_2},
    )
    db.commit()

    first = client.get("/auth/users/" + TEST_USER_ID + "/timeline", params={"limit": 1})
    assert first.status_code == 200
    body = first.json()
    item = body["results"][0]
    assert item["id"] == newer
    assert item["date"] == "2026-03-04"
    assert item["created_at"].startswith("2026-03-04T08:00:00")
    assert item["rating"] == 4.5
    assert item["media"]["title"] == "Newer"
    assert item["media"]["media_type"] == "movie"
    assert item["media"]["year"] == 1999
    assert item["media"]["poster"] == "/poster.jpg"
    assert item["watched_with"] == [
        {"id": TEST_USER_ID_2, "name": "Ada", "avatar": None}
    ]
    assert item["user"]["id"] == TEST_USER_ID
    assert item["user"]["name"] == "Owner"
    assert body["next_cursor"]

    own = client.get("/tracking/timeline", params={"limit": 1})
    assert own.status_code == 200
    assert own.json()["results"][0]["id"] == newer
    assert own.json()["results"][0]["created_at"].startswith("2026-03-04T08:00:00")

    second = client.get(
        "/auth/users/" + TEST_USER_ID + "/timeline",
        params={"limit": 1, "cursor": body["next_cursor"]},
    )
    assert second.status_code == 200
    assert [row["media"]["title"] for row in second.json()["results"]] == ["Older"]
    assert second.json()["next_cursor"] is None


def test_profile_timeline_privacy(client_user2: TestClient, db: Session) -> None:
    _people(db)
    _watch(
        db,
        TEST_USER_ID,
        100,
        "Mine",
        date(2026, 1, 1),
        datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    stranger = client_user2.get(f"/auth/users/{TEST_USER_ID}/timeline")
    assert_error(
        stranger, status=403, code="FORBIDDEN", message="Not friends with this user"
    )

    make_friendship(db, TEST_USER_ID, TEST_USER_ID_2, status="accepted")
    friend = client_user2.get(f"/auth/users/{TEST_USER_ID}/timeline")
    assert friend.status_code == 200
    assert friend.json()["results"][0]["media"]["title"] == "Mine"

    db.add(UserBlock(blocker_id=TEST_USER_ID, blocked_id=TEST_USER_ID_2))
    db.commit()
    hidden = client_user2.get(f"/auth/users/{TEST_USER_ID}/timeline")
    assert_error(hidden, status=404, code="NOT_FOUND", message="User not found")


def test_invalid_cursor(client: TestClient, db: Session) -> None:
    _people(db)
    resp = client.get(
        f"/auth/users/{TEST_USER_ID}/timeline", params={"cursor": "not-a-cursor"}
    )
    assert_error(resp, status=400, code="BAD_REQUEST", message="Invalid cursor")


def test_blend_timeline_respects_friendship_and_blocks(
    client: TestClient, db: Session
) -> None:
    _people(db)
    group, _watchlist = make_group(db, name="Friday", created_by=TEST_USER_ID)
    db.add(GroupMember(group_id=group.id, user_id=TEST_USER_ID_2))
    db.add(GroupMember(group_id=group.id, user_id=STRANGER_ID))
    db.commit()
    make_friendship(db, TEST_USER_ID, TEST_USER_ID_2, status="accepted")
    _watch(
        db,
        TEST_USER_ID,
        100,
        "Mine",
        date(2026, 1, 1),
        datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    _watch(
        db,
        TEST_USER_ID_2,
        101,
        "Ada",
        date(2026, 2, 1),
        datetime(2026, 2, 1, tzinfo=timezone.utc),
        rating=5.0,
    )
    _watch(
        db,
        STRANGER_ID,
        102,
        "Hidden",
        date(2026, 3, 1),
        datetime(2026, 3, 1, tzinfo=timezone.utc),
    )

    resp = client.get(f"/groups/{group.id}/timeline")
    assert resp.status_code == 200
    titles = [item["media"]["title"] for item in resp.json()["results"]]
    assert titles == ["Ada", "Mine"]
    assert resp.json()["results"][0]["rating"] == 5.0
    assert resp.json()["results"][0]["user"]["name"] == "Ada"
    assert isinstance(resp.json()["results"][0]["id"], int)
    assert "T" in resp.json()["results"][0]["created_at"]

    missing = client.get("/groups/999999/timeline")
    other, _wl = make_group(db, name="Closed", created_by=STRANGER_ID)
    denied = client.get(f"/groups/{other.id}/timeline")
    assert_error(missing, status=404, code="NOT_FOUND", message="Group not found")
    assert_error(
        denied, status=403, code="FORBIDDEN", message="Not a member of this group"
    )


def test_blocked_companion_is_omitted(client: TestClient, db: Session) -> None:
    _people(db)
    log_id = _watch(
        db,
        TEST_USER_ID,
        100,
        "Mine",
        date(2026, 1, 1),
        datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db.execute(
        text(
            "insert into watched_with (watched_movie_id, owner_id, user_id) "
            "values (:log_id, :owner, :companion)"
        ),
        {"log_id": log_id, "owner": TEST_USER_ID, "companion": TEST_USER_ID_2},
    )
    db.add(UserBlock(blocker_id=TEST_USER_ID_2, blocked_id=TEST_USER_ID))
    db.commit()

    resp = client.get(f"/auth/users/{TEST_USER_ID}/timeline")
    assert resp.status_code == 200
    assert resp.json()["results"][0]["watched_with"] == []


def test_tv_items_follow_the_flag(client: TestClient, db: Session, monkeypatch) -> None:
    _people(db)
    _watch(
        db,
        TEST_USER_ID,
        100,
        "Movie",
        date(2026, 1, 1),
        datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db.add(TVShow(tmdb_id=1399, title="Show"))
    db.commit()
    db.add(
        WatchedTVShow(
            user_id=TEST_USER_ID,
            tmdb_id=1399,
            rating=3.5,
            watched_date=date(2026, 4, 1),
        )
    )
    db.commit()

    off = client.get(f"/auth/users/{TEST_USER_ID}/timeline")
    assert off.status_code == 200
    assert [item["media"]["media_type"] for item in off.json()["results"]] == ["movie"]

    monkeypatch.setattr(settings, "tv_support_enabled", True)
    on = client.get(f"/auth/users/{TEST_USER_ID}/timeline")
    assert on.status_code == 200
    assert [item["media"]["title"] for item in on.json()["results"]] == [
        "Show",
        "Movie",
    ]
    assert on.json()["results"][0]["media"]["media_type"] == "tv"
    assert on.json()["results"][0]["date"] == "2026-04-01"
    assert on.json()["results"][0]["rating"] == 3.5
    assert on.json()["results"][0]["watched_with"] == []
    assert isinstance(on.json()["results"][0]["id"], int)
    assert "T" in on.json()["results"][0]["created_at"]
