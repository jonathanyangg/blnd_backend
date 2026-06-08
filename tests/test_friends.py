"""Tests for friends domain: request/accept/reject/list/remove."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.conftest import TEST_USER_ID, TEST_USER_ID_2
from tests.factories import make_friendship, make_profile


# --- Send friend request ---


def test_send_request_success(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="user1")
    make_profile(db, user_id=TEST_USER_ID_2, username="user2")
    resp = client.post("/friends/request", json={"addressee_username": "user2"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"


def test_send_request_self(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="user1")
    resp = client.post("/friends/request", json={"addressee_username": "user1"})
    assert resp.status_code == 400


def test_send_request_duplicate_pending(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="user1")
    make_profile(db, user_id=TEST_USER_ID_2, username="user2")
    make_friendship(db, TEST_USER_ID, TEST_USER_ID_2, status="pending")
    resp = client.post("/friends/request", json={"addressee_username": "user2"})
    assert resp.status_code == 400


def test_send_request_user_not_found(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="user1")
    resp = client.post("/friends/request", json={"addressee_username": "ghost"})
    assert resp.status_code == 404


# --- Accept friend request ---


def test_accept_right_user(client_user2: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="user1")
    make_profile(db, user_id=TEST_USER_ID_2, username="user2")
    f = make_friendship(db, TEST_USER_ID, TEST_USER_ID_2, status="pending")
    resp = client_user2.post(f"/friends/{f.id}/accept")
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"


def test_accept_wrong_user(client: TestClient, db: Session) -> None:
    """Requester (user1) cannot accept their own request."""
    make_profile(db, user_id=TEST_USER_ID, username="user1")
    make_profile(db, user_id=TEST_USER_ID_2, username="user2")
    f = make_friendship(db, TEST_USER_ID, TEST_USER_ID_2, status="pending")
    resp = client.post(f"/friends/{f.id}/accept")
    assert resp.status_code == 403


# --- Reject friend request ---


def test_reject_right_user(client_user2: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="user1")
    make_profile(db, user_id=TEST_USER_ID_2, username="user2")
    f = make_friendship(db, TEST_USER_ID, TEST_USER_ID_2, status="pending")
    resp = client_user2.post(f"/friends/{f.id}/reject")
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"


def test_reject_wrong_user(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="user1")
    make_profile(db, user_id=TEST_USER_ID_2, username="user2")
    f = make_friendship(db, TEST_USER_ID, TEST_USER_ID_2, status="pending")
    resp = client.post(f"/friends/{f.id}/reject")
    assert resp.status_code == 403


# --- Re-request after rejection ---


def test_re_request_after_rejection(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="user1")
    make_profile(db, user_id=TEST_USER_ID_2, username="user2")
    make_friendship(db, TEST_USER_ID, TEST_USER_ID_2, status="rejected")
    resp = client.post("/friends/request", json={"addressee_username": "user2"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"


# --- List friends ---


def test_list_friends(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="user1")
    make_profile(db, user_id=TEST_USER_ID_2, username="user2")
    make_friendship(db, TEST_USER_ID, TEST_USER_ID_2, status="accepted")
    resp = client.get("/friends/")
    assert resp.status_code == 200
    friends = resp.json()["friends"]
    assert len(friends) == 1
    assert friends[0]["username"] == "user2"


def test_list_friends_both_directions(client: TestClient, db: Session) -> None:
    """Friend shows up whether user is requester or addressee."""
    make_profile(db, user_id=TEST_USER_ID, username="user1")
    make_profile(db, user_id=TEST_USER_ID_2, username="user2")
    # user2 requested, user1 is addressee
    make_friendship(db, TEST_USER_ID_2, TEST_USER_ID, status="accepted")
    resp = client.get("/friends/")
    assert resp.status_code == 200
    assert len(resp.json()["friends"]) == 1


# --- Remove friend ---


def test_remove_friend(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="user1")
    make_profile(db, user_id=TEST_USER_ID_2, username="user2")
    f = make_friendship(db, TEST_USER_ID, TEST_USER_ID_2, status="accepted")
    resp = client.delete(f"/friends/{f.id}")
    assert resp.status_code == 204

    # Verify friendship is gone
    resp = client.get("/friends/")
    assert resp.json()["friends"] == []


# --- Pending requests ---


def test_pending_requests(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="user1")
    make_profile(db, user_id=TEST_USER_ID_2, username="user2")
    make_friendship(db, TEST_USER_ID, TEST_USER_ID_2, status="pending")
    resp = client.get("/friends/requests")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["outgoing"]) == 1
    assert len(data["incoming"]) == 0
