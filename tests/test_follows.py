"""Follows: one-way, independent of mutual friendships."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.dependencies import get_current_user
from app.friends.models import Follow, Friendship
from main import app
from tests.conftest import CALLER_ID, TARGET_ID
from tests.factories import make_follow, make_profile

USER_A = "33333333-3333-3333-3333-333333333333"
USER_B = "44444444-4444-4444-4444-444444444444"
USER_C = "55555555-5555-5555-5555-555555555555"


def _as(user_id: str) -> None:
    app.dependency_overrides[get_current_user] = lambda: user_id


def test_follow_and_unfollow_are_idempotent(
    client: TestClient, db: Session, monkeypatch
) -> None:
    make_profile(db, user_id=CALLER_ID, username="caller")
    make_profile(db, user_id=TARGET_ID, username="target")
    calls: list[dict] = []
    monkeypatch.setattr(
        "app.friends.views.fire_notification", lambda **kwargs: calls.append(kwargs)
    )

    first = client.post(f"/auth/users/{TARGET_ID}/follow")
    second = client.post(f"/auth/users/{TARGET_ID}/follow")

    assert first.status_code == 200
    assert first.json() == {"following": True}
    assert second.status_code == 200
    mine = db.query(Follow).filter(Follow.follower_id == CALLER_ID)
    assert mine.count() == 1
    assert (
        db.query(Friendship)
        .filter(
            Friendship.requester_id.in_([CALLER_ID, TARGET_ID]),
            Friendship.addressee_id.in_([CALLER_ID, TARGET_ID]),
        )
        .count()
        == 0
    )
    assert len(calls) == 1
    assert calls[0]["to"] == TARGET_ID
    assert calls[0]["notification_type"] == "new_followers"
    assert calls[0]["data"]["type"] == "new_follower"
    assert calls[0]["data"]["user_id"] == CALLER_ID

    assert client.delete(f"/auth/users/{TARGET_ID}/follow").status_code == 204
    assert client.delete(f"/auth/users/{TARGET_ID}/follow").status_code == 204
    assert mine.count() == 0


def test_self_follow_rejected(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=CALLER_ID, username="caller")
    resp = client.post(f"/auth/users/{CALLER_ID}/follow")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Cannot follow yourself"
    # UUID letter case is still the same account. The check constraint would
    # reject the row; the API should 400 before that.
    resp = client.post(f"/auth/users/{CALLER_ID.upper()}/follow")
    assert resp.status_code == 400
    assert db.query(Follow).filter(Follow.follower_id == CALLER_ID).count() == 0


def test_follow_missing_user(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=CALLER_ID, username="caller")
    resp = client.post(f"/auth/users/{TARGET_ID}/follow")
    assert resp.status_code == 404


def test_counts_on_profile_and_me(client: TestClient, db: Session, monkeypatch) -> None:
    monkeypatch.setattr("app.friends.views.fire_notification", lambda **kwargs: None)
    make_profile(db, user_id=CALLER_ID, username="caller")
    make_profile(db, user_id=TARGET_ID, username="target")

    assert client.post(f"/auth/users/{TARGET_ID}/follow").status_code == 200

    profile = client.get(f"/auth/users/{TARGET_ID}/profile").json()
    assert profile["followers_count"] == 1
    assert profile["following_count"] == 0
    me = client.get("/auth/me").json()
    assert me["followers_count"] == 0
    assert me["following_count"] == 1

    assert client.delete(f"/auth/users/{TARGET_ID}/follow").status_code == 204
    profile = client.get(f"/auth/users/{TARGET_ID}/profile").json()
    assert profile["followers_count"] == 0
    assert client.get("/auth/me").json()["following_count"] == 0


def test_followers_and_following_pagination_and_flags(
    client: TestClient, db: Session
) -> None:
    make_profile(db, user_id=CALLER_ID, username="viewer")
    make_profile(db, user_id=TARGET_ID, username="target")
    make_profile(db, user_id=USER_A, username="user_a")
    make_profile(db, user_id=USER_B, username="user_b")
    make_profile(db, user_id=USER_C, username="user_c")
    # Insert order is id order. Newest page is C, B then A.
    make_follow(db, USER_A, TARGET_ID)
    make_follow(db, USER_B, TARGET_ID)
    make_follow(db, USER_C, TARGET_ID)
    make_follow(db, USER_A, CALLER_ID)  # A follows the viewer
    make_follow(db, CALLER_ID, USER_B)  # viewer follows B

    first = client.get(f"/auth/users/{TARGET_ID}/followers?limit=2")
    assert first.status_code == 200
    page = first.json()
    assert [row["username"] for row in page["results"]] == ["user_c", "user_b"]
    assert page["next_cursor"]
    by_name = {row["username"]: row for row in page["results"]}
    assert by_name["user_c"]["is_following_me"] is False
    assert by_name["user_c"]["am_following"] is False
    assert by_name["user_b"]["is_following_me"] is False
    assert by_name["user_b"]["am_following"] is True

    second = client.get(
        f"/auth/users/{TARGET_ID}/followers?limit=2&cursor={page['next_cursor']}"
    )
    assert second.status_code == 200
    rest = second.json()
    assert [row["username"] for row in rest["results"]] == ["user_a"]
    assert rest["next_cursor"] is None
    assert rest["results"][0]["is_following_me"] is True
    assert rest["results"][0]["am_following"] is False

    ids = [row["id"] for row in page["results"] + rest["results"]]
    assert len(ids) == len(set(ids)) == 3

    # No friendship required: lists are public. Profiles have no private flag.
    assert db.query(Friendship).count() == 0

    bad = client.get(f"/auth/users/{TARGET_ID}/followers?cursor=nope")
    assert bad.status_code == 400


def test_following_list(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=CALLER_ID, username="viewer")
    make_profile(db, user_id=TARGET_ID, username="target")
    make_profile(db, user_id=USER_A, username="user_a")
    make_follow(db, TARGET_ID, CALLER_ID)
    make_follow(db, TARGET_ID, USER_A)
    make_follow(db, USER_A, CALLER_ID)

    resp = client.get(f"/auth/users/{TARGET_ID}/following")
    assert resp.status_code == 200
    rows = {row["username"]: row for row in resp.json()["results"]}
    assert list(rows) == ["user_a", "viewer"]
    # user_a follows the viewer; the viewer does not follow user_a back.
    assert rows["user_a"]["is_following_me"] is True
    assert rows["user_a"]["am_following"] is False
    # The viewer's own row is "target follows me", not a self-follow.
    assert rows["viewer"]["is_following_me"] is False
    assert rows["viewer"]["am_following"] is False


def test_blocks_hide_follows(client: TestClient, db: Session, monkeypatch) -> None:
    monkeypatch.setattr("app.friends.views.fire_notification", lambda **kwargs: None)
    make_profile(db, user_id=CALLER_ID, username="caller")
    make_profile(db, user_id=TARGET_ID, username="target")
    make_profile(db, user_id=USER_A, username="user_a")
    assert client.post(f"/auth/users/{TARGET_ID}/follow").status_code == 200
    make_follow(db, USER_A, TARGET_ID)

    # Blocking a person who follows the target hides them from the viewer's
    # list. The follow itself stays; the block is not with the profile owner.
    assert client.post(f"/friends/blocks/{USER_A}").status_code == 204
    hidden_person = client.get(f"/auth/users/{TARGET_ID}/followers")
    assert hidden_person.status_code == 200
    assert [row["id"] for row in hidden_person.json()["results"]] == [CALLER_ID]
    assert (
        db.query(Follow)
        .filter(Follow.follower_id == USER_A, Follow.followee_id == TARGET_ID)
        .count()
        == 1
    )
    assert client.delete(f"/friends/blocks/{USER_A}").status_code == 204

    assert client.post(f"/friends/blocks/{TARGET_ID}").status_code == 204
    assert db.query(Follow).filter(Follow.follower_id == CALLER_ID).count() == 0
    assert client.post(f"/auth/users/{TARGET_ID}/follow").status_code == 404

    # Owner blocked the viewer: their lists are hidden. user_a still follows them.
    _as(TARGET_ID)
    assert client.post(f"/friends/blocks/{CALLER_ID}").status_code == 204
    _as(CALLER_ID)
    hidden = client.get(f"/auth/users/{TARGET_ID}/followers")
    assert hidden.status_code == 404

    # A third party still sees the remaining follower. The blocked caller is omitted.
    _as(USER_A)
    listed = client.get(f"/auth/users/{TARGET_ID}/followers")
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()["results"]] == [USER_A]


def test_remove_follower_is_owner_only_and_idempotent(
    client: TestClient, db: Session
) -> None:
    make_profile(db, user_id=CALLER_ID, username="caller")
    make_profile(db, user_id=TARGET_ID, username="target")
    make_follow(db, TARGET_ID, CALLER_ID)

    _as(TARGET_ID)
    denied = client.delete(f"/auth/users/{CALLER_ID}/followers/{TARGET_ID}")
    assert denied.status_code == 403
    rows = db.query(Follow).filter(Follow.followee_id == CALLER_ID)
    assert rows.count() == 1

    _as(CALLER_ID)
    assert (
        client.delete(f"/auth/users/{CALLER_ID}/followers/{TARGET_ID}").status_code
        == 204
    )
    assert (
        client.delete(f"/auth/users/{CALLER_ID}/followers/{TARGET_ID}").status_code
        == 204
    )
    assert rows.count() == 0
    assert client.get("/auth/me").json()["followers_count"] == 0
