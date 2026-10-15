"""Tests for groups domain: CRUD + permissions."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.groups.models import Group, GroupMember
from tests.conftest import TEST_USER_ID, TEST_USER_ID_2
from tests.factories import make_group, make_profile


# --- Create group ---


def test_create_group(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="user1")
    resp = client.post("/groups/", json={"name": "Movie Night"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Movie Night"
    assert data["created_by"] == TEST_USER_ID
    assert len(data["members"]) == 1
    assert data["members"][0]["username"] == "user1"


# --- Update group ---


def test_update_group_creator(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="user1")
    group, _ = make_group(db, name="Old Name", created_by=TEST_USER_ID)
    resp = client.patch(f"/groups/{group.id}", json={"name": "New Name"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"


def test_update_group_non_member(client_user2: TestClient, db: Session) -> None:
    # Any member can update a group; a non-member is rejected (403).
    make_profile(db, user_id=TEST_USER_ID, username="user1")
    make_profile(db, user_id=TEST_USER_ID_2, username="user2")
    group, _ = make_group(db, name="Group", created_by=TEST_USER_ID)
    # user2 is NOT a member of the group

    resp = client_user2.patch(f"/groups/{group.id}", json={"name": "Nope"})
    assert resp.status_code == 403


# --- Add member ---


def test_add_member(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="user1")
    make_profile(db, user_id=TEST_USER_ID_2, username="user2")
    group, _ = make_group(db, name="Group", created_by=TEST_USER_ID)

    resp = client.post(f"/groups/{group.id}/members", json={"username": "user2"})
    assert resp.status_code == 200
    members = resp.json()["members"]
    assert len(members) == 2


def _fill_members(db: Session, group_id: int, count: int, start: int) -> None:
    for i in range(count):
        uid = f"00000000-0000-4000-8000-{start + i:012d}"
        make_profile(db, user_id=uid, username=f"mem{start + i}")
        db.add(GroupMember(group_id=group_id, user_id=uid))
    db.commit()


def test_free_group_cap_detail_is_a_message_object(
    client: TestClient, db: Session
) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="owner")
    make_profile(db, user_id=TEST_USER_ID_2, username="extra")
    group, _ = make_group(db, name="Free", created_by=TEST_USER_ID)
    _fill_members(db, group.id, 3, 1)
    resp = client.post(f"/groups/{group.id}/members", json={"username": "extra"})
    assert resp.status_code == 402
    body = resp.json()
    message = (
        "Free groups are limited to 4 members. Upgrade to blnd+ for groups up to 12."
    )
    assert body["error"]["code"] == "FREE_GROUP_CAP"
    assert body["error"]["message"] == message
    assert body["detail"] == {"message": message}
    assert "Upgrade to blnd+" in body["detail"]["message"]


def test_group_full_detail_is_a_message_object(
    client: TestClient, db: Session
) -> None:
    owner = make_profile(db, user_id=TEST_USER_ID, username="owner")
    owner.subscription_tier = "premium"
    owner.subscription_source = "admin"
    db.commit()
    make_profile(db, user_id=TEST_USER_ID_2, username="extra")
    group, _ = make_group(db, name="Plus", created_by=TEST_USER_ID)
    _fill_members(db, group.id, 11, 20)
    resp = client.post(f"/groups/{group.id}/members", json={"username": "extra"})
    assert resp.status_code == 400
    body = resp.json()
    message = "Group is full (12 members max)."
    assert body["error"]["code"] == "GROUP_FULL"
    assert body["error"]["message"] == message
    assert body["detail"] == {"message": message}


def test_add_member_already_member(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="user1")
    make_profile(db, user_id=TEST_USER_ID_2, username="user2")
    group, _ = make_group(db, name="Group", created_by=TEST_USER_ID)
    db.add(GroupMember(group_id=group.id, user_id=TEST_USER_ID_2))
    db.commit()

    resp = client.post(f"/groups/{group.id}/members", json={"username": "user2"})
    assert resp.status_code == 400


# --- Kick member ---


def test_kick_member(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="user1")
    make_profile(db, user_id=TEST_USER_ID_2, username="user2")
    group, _ = make_group(db, name="Group", created_by=TEST_USER_ID)
    db.add(GroupMember(group_id=group.id, user_id=TEST_USER_ID_2))
    db.commit()

    resp = client.post(f"/groups/{group.id}/members/{TEST_USER_ID_2}/kick")
    assert resp.status_code == 204


def test_kick_owner(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="user1")
    make_profile(db, user_id=TEST_USER_ID_2, username="user2")
    group, _ = make_group(db, name="Group", created_by=TEST_USER_ID)
    db.add(GroupMember(group_id=group.id, user_id=TEST_USER_ID_2))
    db.commit()

    # user2 tries to kick owner
    resp = client.post(f"/groups/{group.id}/members/{TEST_USER_ID}/kick")
    assert resp.status_code == 400


# --- Leave group ---


def test_leave_group_transfers_ownership(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="user1")
    make_profile(db, user_id=TEST_USER_ID_2, username="user2")
    group, _ = make_group(db, name="Group", created_by=TEST_USER_ID)
    db.add(GroupMember(group_id=group.id, user_id=TEST_USER_ID_2))
    db.commit()

    resp = client.post(f"/groups/{group.id}/leave")
    assert resp.status_code == 204

    # Verify ownership transferred
    db.expire_all()
    updated_group = db.query(Group).filter(Group.id == group.id).first()
    assert updated_group is not None
    assert str(updated_group.created_by) == TEST_USER_ID_2


# --- Delete group ---


def test_delete_group_creator(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="user1")
    group, _ = make_group(db, name="Group", created_by=TEST_USER_ID)

    resp = client.delete(f"/groups/{group.id}")
    assert resp.status_code == 204

    # Verify group is gone
    assert db.query(Group).filter(Group.id == group.id).first() is None


def test_delete_group_non_creator(client_user2: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="user1")
    make_profile(db, user_id=TEST_USER_ID_2, username="user2")
    group, _ = make_group(db, name="Group", created_by=TEST_USER_ID)
    db.add(GroupMember(group_id=group.id, user_id=TEST_USER_ID_2))
    db.commit()

    resp = client_user2.delete(f"/groups/{group.id}")
    assert resp.status_code == 403


# --- List / Get ---


def test_list_groups(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="user1")
    make_group(db, name="Group A", created_by=TEST_USER_ID)
    make_group(db, name="Group B", created_by=TEST_USER_ID)

    resp = client.get("/groups/")
    assert resp.status_code == 200
    assert len(resp.json()["groups"]) == 2


def test_get_group(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="user1")
    group, _ = make_group(db, name="Group", created_by=TEST_USER_ID)

    resp = client.get(f"/groups/{group.id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Group"


def test_get_group_non_member(client_user2: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="user1")
    make_profile(db, user_id=TEST_USER_ID_2, username="user2")
    group, _ = make_group(db, name="Group", created_by=TEST_USER_ID)

    resp = client_user2.get(f"/groups/{group.id}")
    assert resp.status_code == 403
