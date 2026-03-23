"""Tests for OAuth login and complete-onboarding flows."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError
from supabase_auth.errors import AuthApiError

from tests.conftest import CALLER_ID

# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


def test_oauth_request_schema_validation():
    """OAuthRequest rejects unknown providers, accepts 'apple', requires id_token."""
    from app.auth.schemas import OAuthRequest

    # Valid request
    req = OAuthRequest(provider="apple", id_token="some-token")
    assert req.provider == "apple"
    assert req.id_token == "some-token"
    assert req.nonce is None

    # With nonce
    req2 = OAuthRequest(provider="apple", id_token="tok", nonce="abc123")
    assert req2.nonce == "abc123"

    # Unknown provider rejected
    with pytest.raises(ValidationError):
        OAuthRequest(provider="google", id_token="tok")  # type: ignore[arg-type]

    # Missing id_token rejected
    with pytest.raises(ValidationError):
        OAuthRequest(provider="apple")  # type: ignore[call-arg]


def test_complete_onboarding_request_username_validation():
    """CompleteOnboardingRequest validates username via existing validate_username."""
    from app.auth.schemas import CompleteOnboardingRequest

    # Valid
    req = CompleteOnboardingRequest(username="validuser")
    assert req.username == "validuser"

    # Too short
    with pytest.raises(ValidationError):
        CompleteOnboardingRequest(username="ab")

    # Invalid chars
    with pytest.raises(ValidationError):
        CompleteOnboardingRequest(username="bad user!")

    # Leading underscore
    with pytest.raises(ValidationError):
        CompleteOnboardingRequest(username="_badname")


# ---------------------------------------------------------------------------
# Service-level tests: oauth_login
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("app.auth.services.supabase")
async def test_oauth_login_new_user(mock_supabase, mock_db):
    """New user (no Profile) -> is_new_user=True."""
    from app.auth.services import oauth_login

    # Mock Supabase auth response
    mock_user = MagicMock()
    mock_user.id = uuid.UUID(CALLER_ID)
    mock_session = MagicMock()
    mock_session.access_token = "access-tok"
    mock_session.refresh_token = "refresh-tok"
    mock_auth_resp = MagicMock()
    mock_auth_resp.user = mock_user
    mock_auth_resp.session = mock_session
    mock_supabase.auth.sign_in_with_id_token.return_value = mock_auth_resp

    # No profile in DB
    mock_db.query.return_value.filter.return_value.first.return_value = None

    result = await oauth_login("apple", "id-token-value", None, mock_db)

    assert result["is_new_user"] is True
    assert result["access_token"] == "access-tok"
    assert result["refresh_token"] == "refresh-tok"
    assert result["user_id"] == CALLER_ID


@pytest.mark.asyncio
@patch("app.auth.services.supabase")
async def test_oauth_login_returning_user(mock_supabase, mock_db):
    """Returning user (Profile exists) -> is_new_user=False."""
    from app.auth.services import oauth_login

    mock_user = MagicMock()
    mock_user.id = uuid.UUID(CALLER_ID)
    mock_session = MagicMock()
    mock_session.access_token = "access-tok"
    mock_session.refresh_token = "refresh-tok"
    mock_auth_resp = MagicMock()
    mock_auth_resp.user = mock_user
    mock_auth_resp.session = mock_session
    mock_supabase.auth.sign_in_with_id_token.return_value = mock_auth_resp

    # Profile exists
    mock_db.query.return_value.filter.return_value.first.return_value = MagicMock()

    result = await oauth_login("apple", "id-token-value", None, mock_db)

    assert result["is_new_user"] is False


@pytest.mark.asyncio
@patch("app.auth.services.supabase")
async def test_oauth_login_invalid_token(mock_supabase, mock_db):
    """Invalid token -> AuthApiError propagates (not caught by service)."""
    from app.auth.services import oauth_login

    mock_supabase.auth.sign_in_with_id_token.side_effect = AuthApiError(
        "invalid", 401, None
    )

    with pytest.raises(AuthApiError):
        await oauth_login("apple", "bad-token", None, mock_db)


@pytest.mark.asyncio
@patch("app.auth.services.supabase")
async def test_oauth_login_passes_nonce(mock_supabase, mock_db):
    """When nonce is provided, credentials include 'nonce'; when None, they don't."""
    from app.auth.services import oauth_login

    mock_user = MagicMock()
    mock_user.id = uuid.UUID(CALLER_ID)
    mock_session = MagicMock()
    mock_session.access_token = "at"
    mock_session.refresh_token = "rt"
    mock_auth_resp = MagicMock()
    mock_auth_resp.user = mock_user
    mock_auth_resp.session = mock_session
    mock_supabase.auth.sign_in_with_id_token.return_value = mock_auth_resp
    mock_db.query.return_value.filter.return_value.first.return_value = None

    # With nonce
    await oauth_login("apple", "tok", "my-nonce", mock_db)
    call_args = mock_supabase.auth.sign_in_with_id_token.call_args[0][0]
    assert call_args["nonce"] == "my-nonce"

    # Without nonce
    await oauth_login("apple", "tok", None, mock_db)
    call_args2 = mock_supabase.auth.sign_in_with_id_token.call_args[0][0]
    assert "nonce" not in call_args2


# ---------------------------------------------------------------------------
# Service-level tests: complete_onboarding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("app.auth.services.get_movie_details", new_callable=AsyncMock)
async def test_complete_onboarding_creates_profile(mock_get_details, mock_db):
    """Creates Watchlist, Profile, WatchedMovie rows atomically."""
    from app.auth.services import complete_onboarding

    # No existing profile
    mock_db.query.return_value.filter.return_value.first.return_value = None

    # Make flush assign an id to the watchlist
    def fake_flush():
        # Find the added watchlist and set its id
        for call in mock_db.add.call_args_list:
            obj = call[0][0]
            if hasattr(obj, "id") and obj.id is None:
                obj.id = 42

    mock_db.flush.side_effect = fake_flush

    # Make refresh a no-op
    mock_db.refresh.side_effect = lambda obj: None

    mock_tmdb = AsyncMock()

    result = await complete_onboarding(
        user_id=CALLER_ID,
        username="testuser",
        display_name="Test User",
        favorite_genres=["Action", "Comedy"],
        rated_movies=[{"tmdb_id": 550, "rating": 4.5}],
        db=mock_db,
        tmdb_client=mock_tmdb,
    )

    assert result["user_id"] == CALLER_ID
    assert result["username"] == "testuser"

    # Verify get_movie_details was called for the rated movie
    mock_get_details.assert_awaited_once_with(550, mock_db, mock_tmdb)

    # Verify db.commit was called
    mock_db.commit.assert_called_once()

    # Verify at least 3 objects were added (Watchlist, Profile, WatchedMovie)
    assert mock_db.add.call_count >= 3


@pytest.mark.asyncio
async def test_complete_onboarding_duplicate_profile(mock_db):
    """Existing profile -> ValueError('Profile already exists')."""
    from app.auth.services import complete_onboarding

    mock_db.query.return_value.filter.return_value.first.return_value = MagicMock()

    mock_tmdb = AsyncMock()

    with pytest.raises(ValueError, match="Profile already exists"):
        await complete_onboarding(
            user_id=CALLER_ID,
            username="testuser",
            display_name=None,
            favorite_genres=None,
            rated_movies=None,
            db=mock_db,
            tmdb_client=mock_tmdb,
        )


@pytest.mark.asyncio
async def test_complete_onboarding_duplicate_username(mock_db):
    """Username conflict -> ValueError('Username is already taken')."""
    from app.auth.services import complete_onboarding

    # First query (by user_id) returns None (no profile for this user)
    # Second query (by username) returns existing profile (conflict)
    mock_db.query.return_value.filter.return_value.first.side_effect = [
        None,
        MagicMock(),
    ]

    mock_tmdb = AsyncMock()

    with pytest.raises(ValueError, match="Username is already taken"):
        await complete_onboarding(
            user_id=CALLER_ID,
            username="takenname",
            display_name=None,
            favorite_genres=None,
            rated_movies=None,
            db=mock_db,
            tmdb_client=mock_tmdb,
        )


# ---------------------------------------------------------------------------
# Endpoint-level tests
# ---------------------------------------------------------------------------


@patch("app.auth.services.oauth_login", new_callable=AsyncMock)
def test_oauth_endpoint_returns_tokens(mock_oauth_login, app_client):
    """POST /auth/oauth with valid service response -> 200 with tokens."""
    mock_oauth_login.return_value = {
        "access_token": "at",
        "refresh_token": "rt",
        "user_id": CALLER_ID,
        "is_new_user": True,
        "apple_refresh_token": None,
    }

    resp = app_client.post(
        "/auth/oauth",
        json={"provider": "apple", "id_token": "valid-token"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["access_token"] == "at"
    assert data["refresh_token"] == "rt"
    assert data["user_id"] == CALLER_ID
    assert data["is_new_user"] is True


@patch("app.auth.services.oauth_login", new_callable=AsyncMock)
def test_oauth_endpoint_invalid_token_401(mock_oauth_login, app_client):
    """POST /auth/oauth with AuthApiError from service -> 401."""
    mock_oauth_login.side_effect = AuthApiError("invalid", 401, None)

    resp = app_client.post(
        "/auth/oauth",
        json={"provider": "apple", "id_token": "bad-token"},
    )
    assert resp.status_code == 401
    assert "Invalid or expired provider token" in resp.json()["detail"]


@patch("app.auth.services.complete_onboarding", new_callable=AsyncMock)
def test_complete_onboarding_endpoint_creates_profile(mock_onboarding, app_client):
    """POST /auth/complete-onboarding with mocked service -> 200."""
    from app.dependencies import get_tmdb_client
    from main import app

    app.dependency_overrides[get_tmdb_client] = lambda: MagicMock()

    mock_onboarding.return_value = {
        "user_id": CALLER_ID,
        "username": "newuser",
    }

    resp = app_client.post(
        "/auth/complete-onboarding",
        json={"username": "newuser", "display_name": "New User"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == CALLER_ID
    assert data["username"] == "newuser"

    app.dependency_overrides.pop(get_tmdb_client, None)


@patch("app.auth.services.complete_onboarding", new_callable=AsyncMock)
def test_complete_onboarding_endpoint_duplicate_400(mock_onboarding, app_client):
    """POST /auth/complete-onboarding with ValueError from service -> 400."""
    from app.dependencies import get_tmdb_client
    from main import app

    app.dependency_overrides[get_tmdb_client] = lambda: MagicMock()

    mock_onboarding.side_effect = ValueError("Profile already exists")

    resp = app_client.post(
        "/auth/complete-onboarding",
        json={"username": "existinguser"},
    )
    assert resp.status_code == 400
    assert "Profile already exists" in resp.json()["detail"]

    app.dependency_overrides.pop(get_tmdb_client, None)


@patch("app.auth.views.BackgroundTasks.add_task")
@patch("app.auth.services.complete_onboarding", new_callable=AsyncMock)
def test_complete_onboarding_endpoint_triggers_taste_rebuild(
    mock_onboarding, mock_add_task, app_client
):
    """Onboarding with rated_movies triggers background taste rebuild."""
    from app.dependencies import get_tmdb_client
    from main import app

    app.dependency_overrides[get_tmdb_client] = lambda: MagicMock()

    mock_onboarding.return_value = {
        "user_id": CALLER_ID,
        "username": "newuser",
    }

    resp = app_client.post(
        "/auth/complete-onboarding",
        json={
            "username": "newuser",
            "rated_movies": [{"tmdb_id": 550, "rating": 4.5}],
        },
    )
    assert resp.status_code == 200

    # Background task should have been called for taste rebuild
    mock_add_task.assert_called_once()

    app.dependency_overrides.pop(get_tmdb_client, None)
