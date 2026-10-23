"""Hidden and test accounts stay out of social surfaces.

is_discoverable defaults true and is_test defaults false, so existing users
stay discoverable. A user can turn discovery off. Only an admin can set is_test.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.models import Profile
from app.groups.models import GroupMember
from app.import_data.models import MovieEmbedding
from app.notifications.models import NotificationInboxItem
from app.tracking.models import ActivityFeedItem
from tests.conftest import TEST_USER_ID, TEST_USER_ID_2
from tests.factories import (
    _ensure_auth_user,
    make_friendship,
    make_group,
    make_movie,
    make_profile,
    make_watched,
)

HIDDEN_ID = "33333333-3333-3333-3333-333333333333"
VISIBLE_ID = "44444444-4444-4444-4444-444444444444"
BRIDGE_ID = "55555555-5555-5555-5555-555555555555"

HIDE = [
    pytest.param({"is_discoverable": False}, id="undiscoverable"),
    pytest.param({"is_test": True}, id="test"),
]


def test_visibility_columns_default_true_and_false(db: Session) -> None:
    profile = make_profile(db, username="plain")
    assert profile.is_discoverable is True
    assert profile.is_test is False


def test_db_default_when_insert_omits_flags(db: Session) -> None:
    """ALTER TABLE defaults are what existing rows received."""
    uid = uuid.uuid4()
    _ensure_auth_user(db, uid)
    db.execute(
        text("INSERT INTO profiles (id, username) VALUES (:id, :username)"),
        {"id": str(uid), "username": "rawdefault"},
    )
    db.commit()
    row = db.execute(
        text("SELECT is_discoverable, is_test FROM profiles WHERE id = :id"),
        {"id": str(uid)},
    ).one()
    assert row.is_discoverable is True
    assert row.is_test is False


def test_me_returns_is_discoverable_and_patch_sets_it(
    client: TestClient, db: Session
) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="me")
    first = client.get("/auth/me")
    assert first.status_code == 200
    assert first.json()["is_discoverable"] is True

    updated = client.patch("/auth/profile", json={"is_discoverable": False})
    assert updated.status_code == 200
    assert updated.json()["is_discoverable"] is False

    again = client.get("/auth/me")
    assert again.status_code == 200
    assert again.json()["is_discoverable"] is False


def test_user_cannot_set_is_test(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="me")
    resp = client.patch(
        "/auth/profile", json={"is_discoverable": False, "is_test": True}
    )
    assert resp.status_code == 422
    db.expire_all()
    profile = db.query(Profile).filter(Profile.id == TEST_USER_ID).one()
    assert profile.is_test is False
    assert profile.is_discoverable is True


def test_admin_sets_is_test(client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.dependencies.settings.admin_user_id", TEST_USER_ID)
    make_profile(db, user_id=TEST_USER_ID, username="admin")
    make_profile(db, user_id=TEST_USER_ID_2, username="tester")

    resp = client.post(f"/admin/users/{TEST_USER_ID_2}/test", params={"is_test": True})
    assert resp.status_code == 200
    assert resp.json() == {"user_id": TEST_USER_ID_2, "is_test": True}

    db.expire_all()
    profile = db.query(Profile).filter(Profile.id == TEST_USER_ID_2).one()
    assert profile.is_test is True

    cleared = client.post(
        f"/admin/users/{TEST_USER_ID_2}/test", params={"is_test": False}
    )
    assert cleared.status_code == 200
    assert cleared.json()["is_test"] is False


def test_non_admin_cannot_set_is_test(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.dependencies.settings.admin_user_id",
        "99999999-9999-9999-9999-999999999999",
    )
    make_profile(db, user_id=TEST_USER_ID, username="user")
    make_profile(db, user_id=TEST_USER_ID_2, username="tester")
    resp = client.post(f"/admin/users/{TEST_USER_ID_2}/test", params={"is_test": True})
    assert resp.status_code == 403
    db.expire_all()
    profile = db.query(Profile).filter(Profile.id == TEST_USER_ID_2).one()
    assert profile.is_test is False


@pytest.mark.parametrize("hide", HIDE)
def test_search_excludes_hidden(client: TestClient, db: Session, hide: dict) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="seeker")
    make_profile(db, user_id=HIDDEN_ID, username="findhidden", **hide)
    make_profile(db, user_id=VISIBLE_ID, username="findvisible")

    resp = client.get("/auth/users/search", params={"q": "find"})
    assert resp.status_code == 200
    assert [row["username"] for row in resp.json()["results"]] == ["findvisible"]


@pytest.mark.parametrize("hide", HIDE)
def test_by_username_404_for_others_ok_for_self(
    client: TestClient, db: Session, hide: dict
) -> None:
    from app.dependencies import get_current_user
    from main import app

    make_profile(db, user_id=TEST_USER_ID, username="secret", **hide)
    make_profile(db, user_id=TEST_USER_ID_2, username="other")
    make_profile(db, user_id=VISIBLE_ID, username="public")

    app.dependency_overrides[get_current_user] = lambda: TEST_USER_ID_2
    hidden = client.get("/auth/users/by-username/secret")
    assert hidden.status_code == 404

    visible = client.get("/auth/users/by-username/public")
    assert visible.status_code == 200

    app.dependency_overrides[get_current_user] = lambda: TEST_USER_ID
    own = client.get("/auth/users/by-username/secret")
    assert own.status_code == 200
    assert own.json()["username"] == "secret"


@pytest.mark.parametrize("hide", HIDE)
def test_profile_by_id_404_for_others(client: TestClient, db: Session, hide: dict) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="caller")
    make_profile(db, user_id=TEST_USER_ID_2, username="secret", **hide)

    resp = client.get(f"/auth/users/{TEST_USER_ID_2}/profile")
    assert resp.status_code == 404


@pytest.mark.parametrize("hide", HIDE)
def test_public_watched_and_friends_404_when_hidden(
    client: TestClient, db: Session, hide: dict
) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="caller")
    make_profile(db, user_id=TEST_USER_ID_2, username="secret", **hide)
    make_friendship(db, TEST_USER_ID, TEST_USER_ID_2, status="accepted")

    assert client.get(f"/auth/users/{TEST_USER_ID_2}/watched").status_code == 404
    assert client.get(f"/auth/users/{TEST_USER_ID_2}/friends").status_code == 404
    assert client.get(f"/auth/users/{TEST_USER_ID_2}/taste").status_code == 404


@pytest.mark.parametrize("hide", HIDE)
def test_public_friends_omits_hidden_friend(
    client: TestClient, db: Session, hide: dict
) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="caller")
    make_profile(db, user_id=TEST_USER_ID_2, username="host")
    make_profile(db, user_id=HIDDEN_ID, username="ghost", **hide)
    make_profile(db, user_id=VISIBLE_ID, username="shown")
    make_friendship(db, TEST_USER_ID, TEST_USER_ID_2, status="accepted")
    make_friendship(db, TEST_USER_ID_2, HIDDEN_ID, status="accepted")
    make_friendship(db, TEST_USER_ID_2, VISIBLE_ID, status="accepted")

    resp = client.get(f"/auth/users/{TEST_USER_ID_2}/friends")
    assert resp.status_code == 200
    assert {row["id"] for row in resp.json()["friends"]} == {TEST_USER_ID, VISIBLE_ID}


@pytest.mark.parametrize("hide", HIDE)
def test_contact_suggestions_exclude_hidden(
    client: TestClient, db: Session, hide: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "contact_hash_key", "test-contact-key")
    from app.core.phone import hash_phone

    make_profile(db, user_id=TEST_USER_ID, username="seeker")
    make_profile(
        db,
        user_id=HIDDEN_ID,
        username="phonehidden",
        phone_number=hash_phone("+15551110001"),
        **hide,
    )
    make_profile(
        db,
        user_id=VISIBLE_ID,
        username="phonevisible",
        phone_number=hash_phone("+15551110002"),
    )
    uploaded = client.post(
        "/friends/contacts",
        json={"phone_numbers": ["+15551110001", "+15551110002"]},
    )
    assert uploaded.status_code == 204

    resp = client.get("/friends/suggestions")
    assert resp.status_code == 200
    assert [row["username"] for row in resp.json()["contacts"]] == ["phonevisible"]


@pytest.mark.parametrize("hide", HIDE)
def test_mutual_suggestions_exclude_hidden(
    client: TestClient, db: Session, hide: dict
) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="seeker")
    make_profile(db, user_id=BRIDGE_ID, username="bridge")
    make_profile(db, user_id=HIDDEN_ID, username="ghost", **hide)
    make_profile(db, user_id=VISIBLE_ID, username="shown")
    make_friendship(db, TEST_USER_ID, BRIDGE_ID, status="accepted")
    make_friendship(db, BRIDGE_ID, HIDDEN_ID, status="accepted")
    make_friendship(db, BRIDGE_ID, VISIBLE_ID, status="accepted")

    resp = client.get("/friends/suggestions")
    assert resp.status_code == 200
    assert [row["username"] for row in resp.json()["mutuals"]] == ["shown"]


@pytest.mark.parametrize("hide", HIDE)
def test_mutual_friends_listing_excludes_hidden(
    client: TestClient, db: Session, hide: dict
) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="caller")
    make_profile(db, user_id=TEST_USER_ID_2, username="other")
    make_profile(db, user_id=HIDDEN_ID, username="ghost", **hide)
    make_profile(db, user_id=VISIBLE_ID, username="shown")
    make_friendship(db, TEST_USER_ID, TEST_USER_ID_2, status="accepted")
    for owner in (TEST_USER_ID, TEST_USER_ID_2):
        make_friendship(db, owner, HIDDEN_ID, status="accepted")
        make_friendship(db, owner, VISIBLE_ID, status="accepted")

    resp = client.get(f"/friends/{TEST_USER_ID_2}/mutuals")
    assert resp.status_code == 200
    body = resp.json()
    assert [row["username"] for row in body["mutuals"]] == ["shown"]
    assert body["count"] == 1


@pytest.mark.parametrize("hide", HIDE)
def test_watched_by_excludes_hidden(client: TestClient, db: Session, hide: dict) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="caller")
    make_profile(db, user_id=HIDDEN_ID, username="ghost", **hide)
    make_profile(db, user_id=VISIBLE_ID, username="shown")
    make_friendship(db, TEST_USER_ID, HIDDEN_ID, status="accepted")
    make_friendship(db, TEST_USER_ID, VISIBLE_ID, status="accepted")
    make_movie(db, tmdb_id=550, title="Fight Club")
    make_watched(db, user_id=HIDDEN_ID, tmdb_id=550, rating=5.0)
    make_watched(db, user_id=VISIBLE_ID, tmdb_id=550, rating=4.0)

    resp = client.get("/tracking/550/friends")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert [row["username"] for row in body["results"]] == ["shown"]


@pytest.mark.parametrize("hide", HIDE)
def test_friend_feed_excludes_hidden(db: Session, hide: dict) -> None:
    from app.tracking.services import get_friend_feed

    make_profile(db, user_id=TEST_USER_ID, username="caller")
    make_profile(db, user_id=HIDDEN_ID, username="ghost", **hide)
    make_profile(db, user_id=VISIBLE_ID, username="shown")
    make_friendship(db, TEST_USER_ID, HIDDEN_ID, status="accepted")
    make_friendship(db, TEST_USER_ID, VISIBLE_ID, status="accepted")
    make_movie(db, tmdb_id=550, title="Fight Club")
    db.add(ActivityFeedItem(user_id=HIDDEN_ID, action="watched", tmdb_id=550))
    db.add(ActivityFeedItem(user_id=VISIBLE_ID, action="watched", tmdb_id=550))
    db.commit()

    feed = get_friend_feed(TEST_USER_ID, db)
    assert [row["username"] for row in feed["results"]] == ["shown"]


@pytest.mark.parametrize("hide", HIDE)
def test_digest_skips_hidden_activity(db: Session, hide: dict) -> None:
    from datetime import datetime, timedelta, timezone

    from app.notifications.services import _build_digest_body

    make_profile(db, user_id=TEST_USER_ID, username="caller")
    make_profile(db, user_id=HIDDEN_ID, username="ghost", **hide)
    make_profile(db, user_id=VISIBLE_ID, username="shown")
    make_friendship(db, TEST_USER_ID, HIDDEN_ID, status="accepted")
    make_friendship(db, TEST_USER_ID, VISIBLE_ID, status="accepted")
    make_movie(db, tmdb_id=550, title="Fight Club")
    db.add(ActivityFeedItem(user_id=HIDDEN_ID, action="watched", tmdb_id=550))
    db.add(ActivityFeedItem(user_id=VISIBLE_ID, action="watched", tmdb_id=550))
    db.commit()

    since = datetime.now(timezone.utc) - timedelta(days=1)
    body = _build_digest_body(TEST_USER_ID, since, db)
    assert body is not None
    assert "shown" in body
    assert "ghost" not in body


@pytest.mark.parametrize("hide", HIDE)
def test_friend_activity_fanout_skips_hidden_actor(db: Session, hide: dict) -> None:
    from app.notifications.services import fire_notification_to_friends

    actor = make_profile(db, user_id=TEST_USER_ID, username="ghost", **hide)
    make_profile(db, user_id=TEST_USER_ID_2, username="friend")
    make_friendship(db, TEST_USER_ID, TEST_USER_ID_2, status="accepted")
    make_movie(db, tmdb_id=550, title="Fight Club")

    fire_notification_to_friends(TEST_USER_ID, "rated", 550, db, rating=4.0)
    assert db.query(NotificationInboxItem).count() == 0

    actor.is_discoverable = True
    actor.is_test = False
    db.commit()
    fire_notification_to_friends(TEST_USER_ID, "rated", 550, db, rating=4.0)
    rows = db.query(NotificationInboxItem).all()
    assert len(rows) == 1
    assert str(rows[0].from_user_id) == TEST_USER_ID
    assert str(rows[0].user_id) == TEST_USER_ID_2


@pytest.mark.parametrize("hide", HIDE)
def test_fire_notification_does_not_schedule_hidden_actor(
    db: Session, hide: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.notifications.services import fire_notification

    make_profile(db, user_id=TEST_USER_ID, username="ghost", **hide)
    make_profile(db, user_id=VISIBLE_ID, username="shown")
    scheduled: list[object] = []

    def _capture(coro: object) -> None:
        scheduled.append(coro)
        close = getattr(coro, "close", None)
        if close:
            close()

    monkeypatch.setattr("app.notifications.services.asyncio.ensure_future", _capture)
    fire_notification(
        to=TEST_USER_ID_2,
        from_user=TEST_USER_ID,
        notification_type="friend_requests",
        title="Friend Request",
        body="ghost sent you a friend request",
        apns_client=None,
        db=db,
    )
    assert scheduled == []

    fire_notification(
        to=TEST_USER_ID_2,
        from_user=VISIBLE_ID,
        notification_type="friend_requests",
        title="Friend Request",
        body="shown sent you a friend request",
        apns_client=None,
        db=db,
    )
    assert len(scheduled) == 1


@pytest.mark.parametrize("hide", HIDE)
def test_inbox_hides_hidden_actor(client: TestClient, db: Session, hide: dict) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="reader")
    make_profile(db, user_id=HIDDEN_ID, username="ghost", **hide)
    make_profile(db, user_id=VISIBLE_ID, username="shown")
    make_friendship(db, TEST_USER_ID, VISIBLE_ID, status="accepted")
    db.add(
        NotificationInboxItem(
            user_id=TEST_USER_ID,
            type="friend_activity",
            from_user_id=HIDDEN_ID,
            title="Friend Activity",
            body="ghost watched a movie",
            data={},
        )
    )
    db.add(
        NotificationInboxItem(
            user_id=TEST_USER_ID,
            type="friend_activity",
            from_user_id=VISIBLE_ID,
            title="Friend Activity",
            body="shown watched a movie",
            data={},
        )
    )
    db.add(
        NotificationInboxItem(
            user_id=TEST_USER_ID,
            type="weekly_digest",
            from_user_id=None,
            title="This week",
            body="A quiet week",
            data={},
        )
    )
    db.commit()

    resp = client.get("/notifications/inbox")
    assert resp.status_code == 200
    body = resp.json()
    assert body["unread_count"] == 2
    assert {row["from_username"] for row in body["results"]} == {"shown", None}


@pytest.mark.parametrize("hide", HIDE)
def test_blend_recommendations_ignore_hidden_taste(
    db: Session, hide: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.groups.services import get_group_recommendations

    caller = make_profile(db, user_id=TEST_USER_ID, username="caller")
    hidden = make_profile(db, user_id=HIDDEN_ID, username="ghost", **hide)
    caller.taste_embedding = [1.0] + [0.0] * 1535
    hidden.taste_embedding = [0.0, 1.0] + [0.0] * 1534
    hidden.negative_embedding = [1.0] * 1536
    db.commit()

    group, _ = make_group(db, name="Blend", created_by=TEST_USER_ID)
    db.add(GroupMember(group_id=group.id, user_id=HIDDEN_ID))
    db.commit()

    captured: dict = {}

    def _pipeline(ctx: object, _db: Session, limit: int, offset: int) -> list[dict]:
        captured["pos"] = list(ctx.positive_embedding)  # type: ignore[attr-defined]
        captured["neg"] = ctx.negative_embedding  # type: ignore[attr-defined]
        return []

    monkeypatch.setattr("app.groups.services.run_recommendation_pipeline", _pipeline)
    result = get_group_recommendations(group.id, TEST_USER_ID, db, limit=5)
    assert result == {"results": []}
    assert captured["pos"][0] == pytest.approx(1.0)
    assert captured["pos"][1] == pytest.approx(0.0)
    assert captured["neg"] is None


def test_blend_match_score_uses_visible_member(db: Session) -> None:
    from app.groups.services import compute_group_match_scores

    make_profile(db, user_id=TEST_USER_ID, username="caller")
    make_profile(db, user_id=VISIBLE_ID, username="shown")
    group, _ = make_group(db, name="Blend", created_by=TEST_USER_ID)
    db.add(GroupMember(group_id=group.id, user_id=VISIBLE_ID))
    db.commit()
    make_movie(db, tmdb_id=550, title="Fight Club")
    make_watched(db, user_id=VISIBLE_ID, tmdb_id=550, rating=5.0)
    db.add(MovieEmbedding(tmdb_id=550, embedding=[1.0] * 1536))
    db.commit()

    scores = compute_group_match_scores(group.id, [550], db)
    assert 550 in scores


@pytest.mark.parametrize("hide", HIDE)
def test_blend_match_score_ignores_hidden_member(
    db: Session, hide: dict
) -> None:
    from app.groups.services import compute_group_match_scores

    make_profile(db, user_id=TEST_USER_ID, username="caller")
    make_profile(db, user_id=HIDDEN_ID, username="ghost", **hide)
    group, _ = make_group(db, name="Blend", created_by=TEST_USER_ID)
    db.add(GroupMember(group_id=group.id, user_id=HIDDEN_ID))
    db.commit()
    make_movie(db, tmdb_id=680, title="Pulp Fiction")
    make_watched(db, user_id=HIDDEN_ID, tmdb_id=680, rating=5.0)
    db.add(MovieEmbedding(tmdb_id=680, embedding=[1.0] * 1536))
    db.commit()

    assert compute_group_match_scores(group.id, [680], db) == {}


@pytest.mark.parametrize("hide", HIDE)
def test_match_404_for_hidden_friend(
    client: TestClient, db: Session, hide: dict
) -> None:
    from datetime import datetime, timedelta, timezone

    future = datetime.now(timezone.utc) + timedelta(days=30)
    make_profile(
        db,
        user_id=TEST_USER_ID,
        username="me",
        subscription_tier="premium",
        subscription_source="apple",
        subscription_expires_at=future,
    )
    make_profile(db, user_id=TEST_USER_ID_2, username="them", **hide)
    make_friendship(db, TEST_USER_ID, TEST_USER_ID_2, status="accepted")
    make_movie(db, tmdb_id=880501, title="Secret Overlap")
    make_watched(db, TEST_USER_ID, 880501, rating=5)
    make_watched(db, TEST_USER_ID_2, 880501, rating=5)

    resp = client.get(f"/stats/match/{TEST_USER_ID_2}")
    assert resp.status_code == 404
    assert "Secret Overlap" not in resp.text
    assert "them" not in resp.text


@pytest.mark.parametrize("hide", HIDE)
def test_pick_tonight_ignores_hidden_member_watches(
    client: TestClient, db: Session, hide: dict
) -> None:
    from app.groups.models import GroupMember
    from tests.test_premium import _blend_with_taste

    group_id, winner, _second = _blend_with_taste(db, second_member=False)
    make_profile(db, user_id=HIDDEN_ID, username="ghost", **hide)
    db.add(GroupMember(group_id=group_id, user_id=HIDDEN_ID))
    db.commit()
    make_watched(db, HIDDEN_ID, winner, rating=5)

    resp = client.get(f"/groups/{group_id}/pick-tonight")
    assert resp.status_code == 200
    assert resp.json()["pick"]["tmdb_id"] == winner


@pytest.mark.parametrize("hide", HIDE)
def test_hidden_veto_is_not_named(client: TestClient, db: Session, hide: dict) -> None:
    from app.groups.models import GroupMember
    from app.groups.picks import veto_tonight
    from tests.test_premium import _blend_with_taste

    group_id, winner, second = _blend_with_taste(db, second_member=False)
    make_profile(db, user_id=HIDDEN_ID, username="ghost", **hide)
    db.add(GroupMember(group_id=group_id, user_id=HIDDEN_ID))
    db.commit()

    body = veto_tonight(group_id, HIDDEN_ID, winner, "nope", db)
    assert body["pick"]["tmdb_id"] == second
    assert body["vetoes"] == []

    listed = client.get(f"/groups/{group_id}/pick-tonight")
    assert listed.status_code == 200
    assert listed.json()["pick"]["tmdb_id"] == second
    assert listed.json()["vetoes"] == []
