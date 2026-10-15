"""Notification center on the existing inbox and preferences endpoints."""

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.comments.models import MovieComment
from app.comments.services import like_comment
from app.groups.models import GroupMember
from app.notifications.models import (
    DeviceToken,
    NotificationInboxItem,
    NotificationPreference,
)
from app.auth.models import Profile
from app.notifications.services import (
    fire_notification_to_friends,
    get_inbox,
    is_push_eligible,
    notify_watched_with,
)
from tests.conftest import CALLER_ID, TARGET_ID
from tests.factories import make_friendship, make_group, make_movie, make_profile

THIRD_ID = "33333333-3333-3333-3333-333333333333"
FOURTH_ID = "44444444-4444-4444-4444-444444444444"
FIFTH_ID = "55555555-5555-5555-5555-555555555555"
WHEN = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def _note(
    db: Session,
    user_id: str,
    *,
    type: str,
    body: str,
    created_at: datetime,
    from_user: str | None = None,
    group_key: str | None = None,
    data: dict | None = None,
    title: str = "Notice",
    read: bool = False,
) -> NotificationInboxItem:
    item = NotificationInboxItem(
        user_id=user_id,
        type=type,
        from_user_id=from_user,
        title=title,
        body=body,
        data=data or {"type": type},
        read=read,
        group_key=group_key,
        created_at=created_at,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def _prefs(db: Session, user_id: str, **fields: object) -> None:
    row = (
        db.query(NotificationPreference)
        .filter(NotificationPreference.user_id == user_id)
        .first()
    )
    if row is None:
        row = NotificationPreference(user_id=user_id)
        db.add(row)
    for key, value in fields.items():
        setattr(row, key, value)
    db.commit()


def test_groups_likes_and_marks_the_group_read(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=CALLER_ID, username="casey", display_name="Casey")
    actors = [
        (FIFTH_ID, "nriley", "Riley", WHEN),
        (FOURTH_ID, "njordan", "Jordan", WHEN + timedelta(minutes=1)),
        (THIRD_ID, "nsam", "Sam", WHEN + timedelta(minutes=2)),
        (TARGET_ID, "nalex", "Alex", WHEN + timedelta(minutes=3)),
    ]
    for uid, username, display, _stamp in actors:
        make_profile(db, user_id=uid, username=username, display_name=display)
    alex = db.query(Profile).filter(Profile.id == TARGET_ID).one()
    alex.avatar_url = "https://cdn.example/alex.jpg"
    db.commit()
    make_movie(db)
    like_data = {"type": "comment_like", "comment_id": "9", "tmdb_id": "550"}
    for uid, _username, display, stamp in actors:
        _note(
            db,
            CALLER_ID,
            type="comment_like",
            from_user=uid,
            body=f"{display} liked your review",
            created_at=stamp,
            group_key="like:comment:9",
            data=like_data,
        )
    _note(
        db,
        CALLER_ID,
        type="comment_like",
        from_user=THIRD_ID,
        body="Sam liked your review",
        created_at=WHEN + timedelta(minutes=4),
        group_key="like:comment:8",
    )
    _note(
        db,
        CALLER_ID,
        type="comment_like",
        from_user=TARGET_ID,
        body="Alex liked your review",
        created_at=WHEN + timedelta(minutes=5),
        group_key="like:comment:8",
    )

    body = client.get("/notifications/inbox").json()
    four = [item for item in body["results"] if item["group_key"] == "like:comment:9"]
    pair = [item for item in body["results"] if item["group_key"] == "like:comment:8"]
    assert len(four) == 4
    assert len(pair) == 2
    assert all(item["type"] == "like" and item["actor_count"] == 1 for item in four)
    assert all(item["target"] == {"type": "comment", "id": "9"} for item in four)
    assert all(
        item["poster_url"] == "https://image.tmdb.org/t/p/w185/poster.jpg"
        and item["data"]["poster_path"] == "/poster.jpg"
        and item["data"]["poster_url"] == item["poster_url"]
        for item in four
    )
    alex_row = next(item for item in four if item["from_username"] == "nalex")
    assert alex_row["avatar_url"] == "https://cdn.example/alex.jpg"
    assert alex_row["from_avatar_url"] == alex_row["avatar_url"]
    assert alex_row["body"] == "Alex liked your review"
    assert body["unread_count"] == 6

    marked = client.post(f"/notifications/inbox/{alex_row['id']}/read")
    assert marked.status_code == 200
    assert marked.json()["unread_count"] == 2
    again = client.get("/notifications/inbox").json()
    assert all(
        item["read"] is True
        for item in again["results"]
        if item["group_key"] == "like:comment:9"
    )
    assert all(
        item["read"] is False
        for item in again["results"]
        if item["group_key"] == "like:comment:8"
    )


def test_pagination_is_newest_first(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=CALLER_ID, username="casey")
    oldest = _note(db, CALLER_ID, type="match", body="old", created_at=WHEN)
    middle = _note(
        db, CALLER_ID, type="match", body="mid", created_at=WHEN + timedelta(minutes=1)
    )
    newest = _note(
        db, CALLER_ID, type="recommendation", body="new", created_at=WHEN + timedelta(hours=1)
    )

    page = client.get("/notifications/inbox", params={"limit": 2}).json()
    assert [item["id"] for item in page["results"]] == [newest.id, middle.id]
    assert page["results"][0]["created_at"] > page["results"][1]["created_at"]
    assert page["next_cursor"]

    page2 = client.get(
        "/notifications/inbox", params={"limit": 2, "cursor": page["next_cursor"]}
    ).json()
    assert [item["id"] for item in page2["results"]] == [oldest.id]
    assert page2["next_cursor"] is None

    offset = client.get("/notifications/inbox", params={"limit": 1, "offset": 1}).json()
    assert offset["results"][0]["id"] == middle.id

    bad = client.get("/notifications/inbox", params={"cursor": "nope"})
    assert bad.status_code == 400


def test_read_state(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=CALLER_ID, username="casey")
    first = _note(db, CALLER_ID, type="match", body="one", created_at=WHEN)
    _note(db, CALLER_ID, type="match", body="two", created_at=WHEN + timedelta(minutes=1))
    listed = client.get("/notifications/inbox").json()
    assert listed["unread_count"] == 2

    one = client.post(f"/notifications/inbox/{first.id}/read")
    assert one.status_code == 200
    assert one.json()["unread_count"] == 1
    after = client.get("/notifications/inbox").json()
    assert next(item for item in after["results"] if item["id"] == first.id)["read"] is True

    all_read = client.post("/notifications/inbox/read")
    assert all_read.status_code == 200
    assert all_read.json()["message"] == "Inbox marked as read"
    assert all_read.json()["unread_count"] == 0
    assert client.get("/notifications/inbox").json()["unread_count"] == 0


def test_inbox_hides_other_users(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=CALLER_ID, username="casey")
    make_profile(db, user_id=TARGET_ID, username="alex")
    _note(db, TARGET_ID, type="match", body="secret", created_at=WHEN)
    assert client.get("/notifications/inbox").json()["results"] == []


def test_rating_audience_at_query_time(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=CALLER_ID, username="casey")
    make_profile(db, user_id=TARGET_ID, username="alex", display_name="Alex")
    _note(
        db,
        CALLER_ID,
        type="friend_activity",
        from_user=TARGET_ID,
        body="alex rated Fight Club",
        created_at=WHEN,
        data={"type": "friend_activity", "tmdb_id": "550", "movie_title": "Fight Club"},
    )

    def visible() -> bool:
        rows = client.get("/notifications/inbox").json()["results"]
        return any(item["type"] == "friend_activity" for item in rows)

    # Default audience is friends, and these two are not friends.
    assert visible() is False

    _prefs(db, TARGET_ID, share_ratings_activity="everyone")
    assert visible() is True

    _prefs(db, TARGET_ID, share_ratings_activity="off")
    assert visible() is False

    _prefs(db, TARGET_ID, share_ratings_activity="friends")
    assert visible() is False
    make_friendship(db, TARGET_ID, CALLER_ID, status="accepted")
    assert visible() is True


def test_rating_fanout_respects_audience(db: Session) -> None:
    make_profile(db, user_id=CALLER_ID, username="casey")
    make_profile(db, user_id=TARGET_ID, username="alex")
    make_profile(db, user_id=THIRD_ID, username="sam")
    make_movie(db)
    make_friendship(db, TARGET_ID, CALLER_ID, status="accepted")
    group, _watchlist = make_group(db, name="Blend", created_by=TARGET_ID)
    db.add(GroupMember(group_id=group.id, user_id=THIRD_ID))
    db.commit()

    def bodies(user_id: str) -> list[str]:
        return [item["body"] for item in get_inbox(user_id, db)["results"]]

    fire_notification_to_friends(TARGET_ID, "rated", 550, db, rating=4.5)
    assert bodies(CALLER_ID)
    assert bodies(THIRD_ID) == []

    db.query(NotificationInboxItem).delete(synchronize_session=False)
    db.commit()
    _prefs(db, TARGET_ID, share_ratings_activity="off")
    fire_notification_to_friends(TARGET_ID, "rated", 550, db, rating=4.0)
    assert bodies(CALLER_ID) == []

    db.query(NotificationInboxItem).delete(synchronize_session=False)
    db.commit()
    _prefs(db, TARGET_ID, share_ratings_activity="everyone")
    fire_notification_to_friends(TARGET_ID, "rated", 550, db, rating=5)
    assert bodies(CALLER_ID)
    assert bodies(THIRD_ID)

    db.query(NotificationInboxItem).delete(synchronize_session=False)
    db.commit()
    _prefs(db, CALLER_ID, friends_ratings_in_app=False)
    _prefs(db, TARGET_ID, share_ratings_activity="friends")
    fire_notification_to_friends(TARGET_ID, "rated", 550, db, rating=2)
    assert bodies(CALLER_ID) == []


def test_like_fanout_and_in_app_toggle(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=CALLER_ID, username="casey", display_name="Casey")
    make_profile(db, user_id=TARGET_ID, username="alex", display_name="Alex")
    comment = MovieComment(tmdb_id=550, user_id=CALLER_ID, body="sharp")
    db.add(comment)
    db.commit()
    db.refresh(comment)

    like_comment(TARGET_ID, comment.id, db)
    listed = client.get("/notifications/inbox").json()["results"]
    assert listed[0]["type"] == "like"
    assert listed[0]["body"] == "Alex liked your review"
    assert listed[0]["actor_count"] == 1

    _prefs(db, CALLER_ID, comments_likes_in_app=False)
    comment2 = MovieComment(tmdb_id=550, user_id=CALLER_ID, body="again")
    db.add(comment2)
    db.commit()
    db.refresh(comment2)
    like_comment(TARGET_ID, comment2.id, db)
    stored = (
        db.query(NotificationInboxItem)
        .filter(
            NotificationInboxItem.user_id == CALLER_ID,
            NotificationInboxItem.type == "like",
        )
        .count()
    )
    assert stored == 1
    types = [item["type"] for item in client.get("/notifications/inbox").json()["results"]]
    assert "like" not in types


def test_accept_and_decline_friend_request(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=CALLER_ID, username="casey")
    make_profile(db, user_id=TARGET_ID, username="alex")
    pending = make_friendship(db, TARGET_ID, CALLER_ID, status="pending")
    other = make_profile(db, user_id=THIRD_ID, username="sam")
    to_decline = make_friendship(db, other.id, CALLER_ID, status="pending")

    accept_note = _note(
        db,
        CALLER_ID,
        type="friend_request",
        from_user=TARGET_ID,
        body="alex sent you a friend request",
        created_at=WHEN,
        data={"type": "friend_request", "friendship_id": str(pending.id), "user_id": TARGET_ID},
    )
    decline_note = _note(
        db,
        CALLER_ID,
        type="friend_request",
        from_user=str(other.id),
        body="sam sent you a friend request",
        created_at=WHEN + timedelta(minutes=1),
        data={
            "type": "friend_request",
            "friendship_id": str(to_decline.id),
            "user_id": str(other.id),
        },
    )
    listed = client.get("/notifications/inbox").json()["results"]
    assert all(
        item["actions"] == ["accept", "decline"]
        for item in listed
        if item["type"] == "friend_request"
    )

    accepted = client.post(f"/notifications/inbox/{accept_note.id}/accept")
    assert accepted.status_code == 200
    assert accepted.json()["actions"] == []
    assert accepted.json()["data"]["status"] == "accepted"
    assert accepted.json()["read"] is True
    db.refresh(pending)
    assert pending.status == "accepted"

    declined_resp = client.post(f"/notifications/inbox/{decline_note.id}/decline")
    assert declined_resp.status_code == 200
    assert declined_resp.json()["data"]["status"] == "declined"
    db.refresh(to_decline)
    assert to_decline.status == "rejected"

    again = client.post(f"/notifications/inbox/{accept_note.id}/accept")
    assert again.status_code == 400
    err = again.json()
    assert err["error"]["code"] == "BAD_REQUEST"
    assert err["detail"] == err["error"]["message"]
    assert err["error"]["request_id"]

    stranger = _note(
        db,
        TARGET_ID,
        type="friend_request",
        from_user=CALLER_ID,
        body="not yours",
        created_at=WHEN,
    )
    assert client.post(f"/notifications/inbox/{stranger.id}/accept").status_code == 404


def test_new_follower_is_informational(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=CALLER_ID, username="casey")
    make_profile(db, user_id=TARGET_ID, username="alex")
    note = _note(
        db,
        CALLER_ID,
        type="new_follower",
        from_user=TARGET_ID,
        body="alex started following you",
        created_at=WHEN,
        data={"type": "new_follower", "user_id": TARGET_ID},
    )
    listed = client.get("/notifications/inbox").json()["results"][0]
    assert listed["actions"] == []
    assert listed["target"] == {"type": "user", "id": TARGET_ID}
    denied = client.post(f"/notifications/inbox/{note.id}/accept")
    assert denied.status_code == 400
    assert denied.json()["error"]["code"] == "BAD_REQUEST"
    assert denied.json()["detail"] == denied.json()["error"]["message"]
    assert client.post(f"/notifications/inbox/{note.id}/decline").status_code == 400


@pytest.mark.parametrize(
    ("field", "inbox_type", "also"),
    [
        ("friend_ratings", "friend_activity", []),
        ("blend_activity", "group_invite", ["group_watchlist", "blend_activity"]),
        ("comments_likes", "like", ["comment_reply", "comment_mention"]),
        ("watched_with", "watched_with", []),
        ("recommendations", "match", ["recommendation", "weekly_digest"]),
    ],
)
def test_each_in_app_preference_hides_its_types(
    client: TestClient,
    db: Session,
    field: str,
    inbox_type: str,
    also: list[str],
) -> None:
    make_profile(db, user_id=CALLER_ID, username="casey")
    make_profile(db, user_id=TARGET_ID, username="alex")
    if inbox_type == "friend_activity":
        make_friendship(db, TARGET_ID, CALLER_ID, status="accepted")
        _prefs(db, TARGET_ID, share_ratings_activity="friends")
    types = [inbox_type, *also]
    for index, inbox_t in enumerate(types):
        _note(
            db,
            CALLER_ID,
            type=inbox_t,
            from_user=TARGET_ID,
            body=inbox_t,
            created_at=WHEN + timedelta(minutes=index),
        )

    def seen() -> set[str]:
        return {item["type"] for item in client.get("/notifications/inbox").json()["results"]}

    assert set(types) <= seen()
    client.patch("/notifications/preferences", json={"in_app": {field: False}})
    assert seen().isdisjoint(types)
    client.patch("/notifications/preferences", json={"in_app": {field: True}})
    assert set(types) <= seen()


@pytest.mark.parametrize(
    ("category", "field", "default_on"),
    [
        ("friends_ratings", "friends_ratings_push", False),
        ("blend_activity", "blend_activity_push", True),
        ("comments_likes", "comments_likes_push", True),
        ("watched_with_tags", "watched_with_tags_push", True),
        ("recommendations", "recommendations_push", True),
    ],
)
def test_each_push_preference(
    db: Session, category: str, field: str, default_on: bool
) -> None:
    make_profile(db, user_id=CALLER_ID, username="casey")
    assert is_push_eligible(CALLER_ID, category, db) is False
    db.add(DeviceToken(user_id=CALLER_ID, token=f"tok-{category}", platform="ios"))
    db.commit()
    assert is_push_eligible(CALLER_ID, category, db) is default_on
    _prefs(db, CALLER_ID, **{field: False})
    assert is_push_eligible(CALLER_ID, category, db) is False
    _prefs(db, CALLER_ID, **{field: True})
    assert is_push_eligible(CALLER_ID, category, db) is True


def test_preference_defaults_are_lazy_and_old_fields_remain(
    client: TestClient, db: Session
) -> None:
    make_profile(db, user_id=CALLER_ID, username="casey")
    first = client.get("/notifications/preferences")
    assert first.status_code == 200
    body = first.json()
    assert body["friend_requests"] is True
    assert body["group_invites"] is True
    assert body["recommendations"] is True
    assert body["friend_activity"] is True
    assert body["comment_replies"] is True
    assert body["share_ratings"] == "friends"
    assert body["in_app"] == {
        "friend_ratings": True,
        "blend_activity": True,
        "comments_likes": True,
        "watched_with": True,
        "recommendations": True,
    }
    assert body["push"]["friend_ratings"] is False
    assert body["push"]["blend_activity"] is True
    assert body["push"]["comments_likes"] is True
    assert body["push"]["watched_with"] is True
    assert body["push"]["recommendations"] is True
    assert (
        db.query(NotificationPreference)
        .filter(NotificationPreference.user_id == CALLER_ID)
        .count()
        == 0
    )

    patched = client.patch(
        "/notifications/preferences",
        json={
            "friend_requests": False,
            "share_ratings": "off",
            "push": {"friend_ratings": True},
        },
    )
    assert patched.status_code == 200
    assert patched.json()["friend_requests"] is False
    assert patched.json()["share_ratings"] == "off"
    assert patched.json()["push"]["friend_ratings"] is True
    assert patched.json()["in_app"]["watched_with"] is True
    stored = (
        db.query(NotificationPreference.share_ratings_activity)
        .filter(NotificationPreference.user_id == CALLER_ID)
        .scalar()
    )
    assert stored == "off"
    assert patched.json()["comment_replies"] is True
    assert (
        db.query(NotificationPreference)
        .filter(NotificationPreference.user_id == CALLER_ID)
        .count()
        == 1
    )
    bad = client.patch("/notifications/preferences", json={"share_ratings": "public"})
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "VALIDATION_ERROR"
    assert bad.json()["detail"] == bad.json()["error"]["message"]
    assert bad.json()["error"]["request_id"]
    blends = client.patch("/notifications/preferences", json={"share_ratings": "blends"})
    assert blends.status_code == 422


def test_watched_with_hook_emits_a_card(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=CALLER_ID, username="casey")
    actor = make_profile(db, user_id=TARGET_ID, username="alex", display_name="Alex")
    actor.avatar_url = "https://cdn.example/alex.jpg"
    db.commit()
    make_movie(db)
    notify_watched_with(
        db, actor_id=TARGET_ID, tagged_user_ids=[CALLER_ID, TARGET_ID], tmdb_id=550
    )
    db.commit()
    item = client.get("/notifications/inbox").json()["results"][0]
    assert item["type"] == "watched_with"
    assert item["body"] == "Alex watched Fight Club with you"
    assert item["avatar_url"] == "https://cdn.example/alex.jpg"
    assert item["poster_url"] == "https://image.tmdb.org/t/p/w185/poster.jpg"
    assert item["group_key"] == "watched_with:550"
    assert item["target"] == {"type": "movie", "id": "550"}
    assert item["actions"] == []

    _prefs(db, CALLER_ID, watched_with_tags_in_app=False)
    notify_watched_with(db, actor_id=TARGET_ID, tagged_user_ids=[CALLER_ID], tmdb_id=550)
    db.commit()
    stored = (
        db.query(NotificationInboxItem)
        .filter(
            NotificationInboxItem.user_id == CALLER_ID,
            NotificationInboxItem.type == "watched_with",
        )
        .count()
    )
    assert stored == 1


def test_rls_prefs_and_inbox_are_owner_only(db: Session) -> None:
    owner_id = uuid.uuid4()
    other_id = uuid.uuid4()
    make_profile(db, user_id=str(owner_id), username="rls_owner")
    make_profile(db, user_id=str(other_id), username="rls_other")
    db.add(NotificationPreference(user_id=owner_id, share_ratings_activity="off"))
    db.add(
        NotificationInboxItem(
            user_id=owner_id,
            type="match",
            title="Match",
            body="private",
            data={"type": "match"},
        )
    )
    db.commit()

    def as_user(uid: uuid.UUID) -> None:
        claims = json.dumps({"sub": str(uid), "role": "authenticated"})
        db.execute(text("reset role"))
        db.execute(
            text("select set_config('request.jwt.claim.sub', :sub, true)"),
            {"sub": str(uid)},
        )
        db.execute(
            text("select set_config('request.jwt.claims', :claims, true)"),
            {"claims": claims},
        )
        db.execute(text("set local role authenticated"))

    try:
        as_user(other_id)
        prefs = db.execute(text("select user_id::text from notification_preferences")).all()
        inbox = db.execute(text("select id from notification_inbox")).all()
        assert prefs == []
        assert inbox == []
        blocked = db.execute(
            text(
                "update notification_preferences set share_ratings_activity = 'everyone' "
                "where user_id = :uid"
            ),
            {"uid": str(owner_id)},
        )
        assert blocked.rowcount == 0

        as_user(owner_id)
        prefs = db.execute(text("select share_ratings_activity from notification_preferences")).all()
        inbox = db.execute(text("select body from notification_inbox")).all()
        assert prefs == [("off",)]
        assert inbox == [("private",)]
        updated = db.execute(
            text(
                "update notification_inbox set read = true where user_id = :uid"
            ),
            {"uid": str(owner_id)},
        )
        assert updated.rowcount == 1
    finally:
        db.execute(text("reset role"))
