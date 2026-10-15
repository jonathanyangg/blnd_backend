"""Tests for auth: username validation + profile endpoints."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.auth.schemas import SignupRequest, UpdateProfileRequest
from tests.conftest import TEST_USER_ID, TEST_USER_ID_2, assert_error
from tests.factories import make_profile


# --- Username validation (schema-level) ---


def test_valid_username_simple() -> None:
    req = SignupRequest(email="a@b.com", password="Pass1234", username="john")
    assert req.username == "john"


def test_valid_username_with_period() -> None:
    req = SignupRequest(email="a@b.com", password="Pass1234", username="john.doe")
    assert req.username == "john.doe"


def test_valid_username_with_underscore() -> None:
    req = SignupRequest(email="a@b.com", password="Pass1234", username="john_doe")
    assert req.username == "john_doe"


def test_valid_username_alphanumeric() -> None:
    req = SignupRequest(email="a@b.com", password="Pass1234", username="j0hn123")
    assert req.username == "j0hn123"


def test_username_case_normalization() -> None:
    req = SignupRequest(email="a@b.com", password="Pass1234", username="JohnDoe")
    assert req.username == "johndoe"


def test_username_too_short() -> None:
    with pytest.raises(ValidationError):
        SignupRequest(email="a@b.com", password="Pass1234", username="ab")


def test_username_too_long() -> None:
    with pytest.raises(ValidationError):
        SignupRequest(email="a@b.com", password="Pass1234", username="a" * 31)


def test_username_empty() -> None:
    with pytest.raises(ValidationError):
        SignupRequest(email="a@b.com", password="Pass1234", username="")


def test_username_with_space() -> None:
    with pytest.raises(ValidationError):
        SignupRequest(email="a@b.com", password="Pass1234", username="john doe")


def test_username_with_at() -> None:
    with pytest.raises(ValidationError):
        SignupRequest(email="a@b.com", password="Pass1234", username="john@doe")


def test_username_with_hash() -> None:
    with pytest.raises(ValidationError):
        SignupRequest(email="a@b.com", password="Pass1234", username="john#doe")


def test_username_leading_period() -> None:
    with pytest.raises(ValidationError):
        SignupRequest(email="a@b.com", password="Pass1234", username=".john")


def test_username_trailing_period() -> None:
    with pytest.raises(ValidationError):
        SignupRequest(email="a@b.com", password="Pass1234", username="john.")


def test_username_leading_underscore() -> None:
    with pytest.raises(ValidationError):
        SignupRequest(email="a@b.com", password="Pass1234", username="_john")


def test_username_trailing_underscore() -> None:
    with pytest.raises(ValidationError):
        SignupRequest(email="a@b.com", password="Pass1234", username="john_")


def test_username_consecutive_periods() -> None:
    with pytest.raises(ValidationError):
        SignupRequest(email="a@b.com", password="Pass1234", username="john..doe")


def test_username_consecutive_underscores() -> None:
    with pytest.raises(ValidationError):
        SignupRequest(email="a@b.com", password="Pass1234", username="john__doe")


# --- UpdateProfileRequest username validation ---


def test_update_profile_valid_username() -> None:
    req = UpdateProfileRequest(username="newname")
    assert req.username == "newname"


def test_update_profile_none_username() -> None:
    req = UpdateProfileRequest(display_name="New Name")
    assert req.username is None


def test_update_profile_invalid_username() -> None:
    with pytest.raises(ValidationError):
        UpdateProfileRequest(username=".bad")


# --- GET /auth/me ---


def test_get_me(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="testuser")
    resp = client.get("/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "testuser"
    assert data["id"] == TEST_USER_ID


def test_get_me_is_premium_follows_the_profile_row(
    client: TestClient, db: Session
) -> None:
    profile = make_profile(db, user_id=TEST_USER_ID, username="testuser")
    free = client.get("/auth/me")
    assert free.status_code == 200
    assert free.json()["is_premium"] is False

    profile.subscription_tier = "premium"
    profile.subscription_source = "admin"
    profile.subscription_expires_at = None
    db.commit()
    premium = client.get("/auth/me")
    assert premium.status_code == 200
    assert premium.json()["is_premium"] is True


def test_get_me_not_found(client: TestClient) -> None:
    resp = client.get("/auth/me")
    assert resp.status_code == 404


# --- PATCH /auth/profile ---


def test_update_profile_display_name(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="testuser")
    resp = client.patch("/auth/profile", json={"display_name": "New Name"})
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "New Name"


def test_update_profile_username_conflict(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="user1")
    make_profile(db, user_id=TEST_USER_ID_2, username="taken")
    resp = client.patch("/auth/profile", json={"username": "taken"})
    assert_error(resp, status=400, code="BAD_REQUEST", contains="already taken")


def test_update_profile_empty_body(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="testuser")
    resp = client.patch("/auth/profile", json={})
    assert resp.status_code == 400


# --- GET /auth/users/search ---


def test_user_search(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="alice")
    make_profile(db, user_id=TEST_USER_ID_2, username="alice_bob")
    resp = client.get("/auth/users/search", params={"q": "alice"})
    assert resp.status_code == 200
    results = resp.json()["results"]
    # Should not include current user (TEST_USER_ID = alice)
    assert len(results) == 1
    assert results[0]["username"] == "alice_bob"


def test_user_search_no_results(client: TestClient, db: Session) -> None:
    make_profile(db, user_id=TEST_USER_ID, username="alice")
    resp = client.get("/auth/users/search", params={"q": "zzz"})
    assert resp.status_code == 200
    assert resp.json()["results"] == []


# --- POST /auth/refresh error mapping ---


def test_refresh_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.auth.services.refresh_session",
        lambda refresh_token: {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "user_id": TEST_USER_ID,
        },
    )
    resp = client.post("/auth/refresh", json={"refresh_token": "old-refresh"})
    assert resp.status_code == 200
    assert resp.json()["access_token"] == "new-access"


def test_refresh_invalid_token_returns_401(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from supabase_auth.errors import AuthApiError

    def _raise(refresh_token: str) -> None:
        raise AuthApiError("Invalid Refresh Token", 400, None)

    monkeypatch.setattr("app.auth.services.refresh_session", _raise)
    resp = client.post("/auth/refresh", json={"refresh_token": "bad"})
    assert_error(resp, status=401, code="UNAUTHORIZED", message="Session refresh failed")
    assert "Invalid Refresh Token" not in resp.text


def test_refresh_generic_error_returns_401(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise(refresh_token: str) -> None:
        raise ValueError("Refresh failed")

    monkeypatch.setattr("app.auth.services.refresh_session", _raise)
    resp = client.post("/auth/refresh", json={"refresh_token": "bad"})
    assert_error(resp, status=401, code="UNAUTHORIZED", message="Session refresh failed")
    assert "Refresh failed" not in resp.text


def test_refresh_supabase_5xx_returns_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from supabase_auth.errors import AuthApiError

    def _raise(refresh_token: str) -> None:
        raise AuthApiError("Internal Server Error", 500, None)

    monkeypatch.setattr("app.auth.services.refresh_session", _raise)
    resp = client.post("/auth/refresh", json={"refresh_token": "any"})
    assert_error(
        resp, status=503, code="SERVICE_UNAVAILABLE", contains="unavailable"
    )
    assert "Internal Server Error" not in resp.text


def test_refresh_retryable_upstream_returns_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from supabase_auth.errors import AuthRetryableError

    def _raise(refresh_token: str) -> None:
        raise AuthRetryableError("Service Unavailable", 503)

    monkeypatch.setattr("app.auth.services.refresh_session", _raise)
    resp = client.post("/auth/refresh", json={"refresh_token": "any"})
    assert_error(
        resp,
        status=503,
        code="SERVICE_UNAVAILABLE",
        message="Auth service unavailable, try again",
    )


def test_refresh_network_error_returns_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx

    def _raise(refresh_token: str) -> None:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("app.auth.services.refresh_session", _raise)
    resp = client.post("/auth/refresh", json={"refresh_token": "any"})
    assert_error(
        resp, status=503, code="SERVICE_UNAVAILABLE", contains="unavailable"
    )
    assert "connection refused" not in resp.text
