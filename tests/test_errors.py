"""Error envelope, request ids, and no-leak guarantees."""

import logging
import uuid
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from limits import parse
from postgrest.exceptions import APIError
from slowapi.errors import RateLimitExceeded
from slowapi.wrappers import Limit
from supabase_auth.errors import AuthApiError, AuthRetryableError

from app.config import settings
from app.core.errors import normalize_request_id
from app.dependencies import get_current_user, get_db
from main import app
from tests.conftest import CALLER_ID, assert_error

_SQL = "SELECT password FROM users"
_TRACE = 'Traceback (most recent call last):\n  File "app/auth/services.py", line 12, in refresh'
_SECRET = "postgresql://postgres:super-secret-db-password@127.0.0.1:54322/postgres"


@pytest.fixture
def error_client():
    app.dependency_overrides[get_current_user] = lambda: CALLER_ID
    app.dependency_overrides[get_db] = lambda: MagicMock()
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)


def _install(exc: Exception) -> None:
    def _raise() -> str:
        raise exc

    app.dependency_overrides[get_current_user] = _raise


def _http_error(status: int, body: str) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://api.themoviedb.org/3/movie/1")
    response = httpx.Response(status, request=request, text=body)
    return httpx.HTTPStatusError("upstream failed", request=request, response=response)


def _assert_hidden(response: Any, *needles: str) -> None:
    for needle in needles:
        assert needle not in response.text


def test_request_id_is_generated_and_echoed(error_client: TestClient) -> None:
    response = error_client.get("/health")
    assert response.status_code == 200
    request_id = response.headers["x-request-id"]
    uuid.UUID(request_id)


def test_request_id_is_propagated(error_client: TestClient) -> None:
    response = error_client.get("/health", headers={"X-Request-ID": "req_ok.1"})
    assert response.headers["x-request-id"] == "req_ok.1"


def test_invalid_request_id_is_replaced(error_client: TestClient) -> None:
    response = error_client.get("/health", headers={"X-Request-ID": "not a valid id"})
    echoed = response.headers["x-request-id"]
    assert echoed != "not a valid id"
    uuid.UUID(echoed)
    assert "\n" not in normalize_request_id("bad\r\nX-Injected: yes")
    assert normalize_request_id("../etc/passwd") != "../etc/passwd"


def test_http_exception_shape(error_client: TestClient) -> None:
    _install(HTTPException(status_code=400, detail="Already liked"))
    response = error_client.get("/auth/me", headers={"X-Request-ID": "http-400"})
    assert_error(response, status=400, code="BAD_REQUEST", message="Already liked")


def test_bad_token_stays_401(error_client: TestClient) -> None:
    _install(HTTPException(status_code=401, detail="Invalid or expired token"))
    response = error_client.get("/auth/me", headers={"X-Request-ID": "bad-token"})
    assert_error(
        response,
        status=401,
        code="UNAUTHORIZED",
        message="Invalid or expired token",
    )


def test_missing_token_stays_401(error_client: TestClient) -> None:
    app.dependency_overrides.pop(get_current_user, None)
    response = error_client.get("/auth/me")
    assert_error(response, status=401, code="UNAUTHORIZED", message="Not authenticated")
    assert response.headers["www-authenticate"] == "Bearer"


def test_upstream_outage_message_stays_503(error_client: TestClient) -> None:
    _install(
        HTTPException(status_code=503, detail="Auth service unavailable, try again")
    )
    response = error_client.get("/auth/me")
    assert_error(
        response,
        status=503,
        code="SERVICE_UNAVAILABLE",
        message="Auth service unavailable, try again",
    )


def test_dict_detail_becomes_stable_code(error_client: TestClient) -> None:
    _install(
        HTTPException(
            status_code=402,
            detail={
                "code": "free_group_cap",
                "cap": 4,
                "premium_cap": 12,
                "message": (
                    "Free groups are limited to 4 members. "
                    "Upgrade to blnd+ for groups up to 12."
                ),
            },
        )
    )
    response = error_client.get("/auth/me")
    assert_error(
        response,
        status=402,
        code="FREE_GROUP_CAP",
        message=(
            "Free groups are limited to 4 members. "
            "Upgrade to blnd+ for groups up to 12."
        ),
    )
    assert "premium_cap" not in response.text


def test_unknown_route_is_not_found(error_client: TestClient) -> None:
    response = error_client.get("/does-not-exist")
    assert_error(response, status=404, code="NOT_FOUND", message="Not Found")


def test_validation_error_is_per_field_and_hides_input(
    error_client: TestClient,
) -> None:
    secret = "supersecretleak"
    response = error_client.post(
        "/auth/signup",
        json={"email": "a@b.com", "password": secret, "username": "ab"},
    )
    body = assert_error(response, status=422, code="VALIDATION_ERROR")
    assert "body.password" in body["detail"]
    assert "body.username" in body["detail"]
    assert secret not in response.text
    assert "input" not in body


def test_http_exception_with_sql_is_redacted(
    error_client: TestClient, caplog: pytest.LogCaptureFixture, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "database_url", _SECRET)
    _install(HTTPException(status_code=400, detail=f"failed {_SQL} {_SECRET}"))
    with caplog.at_level(logging.INFO):
        response = error_client.get("/auth/me", headers={"X-Request-ID": "redact-1"})
    assert_error(response, status=400, code="BAD_REQUEST", message="Bad request")
    _assert_hidden(response, _SQL, "super-secret-db-password", "postgresql://")
    assert "redact-1" in caplog.text
    assert _SQL in caplog.text


def test_unhandled_exception_hides_sql_trace_and_secret(
    error_client: TestClient, caplog: pytest.LogCaptureFixture, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "database_url", _SECRET)
    _install(RuntimeError(f"{_SQL}; {_TRACE}; {_SECRET}"))
    with caplog.at_level(logging.ERROR):
        response = error_client.get("/auth/me", headers={"X-Request-ID": "err-leak-1"})
    assert_error(
        response, status=500, code="INTERNAL_ERROR", message="Internal server error"
    )
    _assert_hidden(
        response,
        _SQL,
        "Traceback",
        "app/auth/services.py",
        "super-secret-db-password",
        "RuntimeError",
    )
    assert response.headers["x-request-id"] == "err-leak-1"
    assert "err-leak-1" in caplog.text
    assert _SQL in caplog.text
    assert "super-secret-db-password" in caplog.text


def test_uncaught_auth_api_error_is_401(error_client: TestClient) -> None:
    _install(AuthApiError(f"Invalid Refresh Token {_SQL}", 401, None))
    response = error_client.get("/auth/me", headers={"X-Request-ID": "auth-401"})
    assert_error(
        response,
        status=401,
        code="UNAUTHORIZED",
        message="Invalid or expired token",
    )
    _assert_hidden(response, _SQL, "Invalid Refresh Token")


def test_uncaught_auth_5xx_is_503(error_client: TestClient) -> None:
    _install(AuthApiError(f"Internal Server Error {_SQL}", 500, None))
    response = error_client.get("/auth/me")
    assert_error(
        response,
        status=503,
        code="SERVICE_UNAVAILABLE",
        message="Auth service unavailable, try again",
    )
    _assert_hidden(response, _SQL, "Internal Server Error")


def test_uncaught_auth_retryable_is_503(error_client: TestClient) -> None:
    _install(AuthRetryableError(f"Service Unavailable {_SQL}", 503))
    response = error_client.get("/auth/me")
    assert_error(
        response,
        status=503,
        code="SERVICE_UNAVAILABLE",
        message="Auth service unavailable, try again",
    )
    _assert_hidden(response, _SQL)


def test_uncaught_tmdb_5xx_is_503(error_client: TestClient) -> None:
    _install(_http_error(500, '{"status_message": "SELECT secret FROM tmdb"}'))
    response = error_client.get("/auth/me")
    assert_error(
        response,
        status=503,
        code="SERVICE_UNAVAILABLE",
        message="Upstream service unavailable, try again",
    )
    _assert_hidden(response, "SELECT secret", "status_message")


def test_uncaught_tmdb_401_is_not_a_user_logout(error_client: TestClient) -> None:
    _install(_http_error(401, '{"status_message": "Invalid API key"}'))
    response = error_client.get("/auth/me")
    assert_error(
        response, status=502, code="BAD_GATEWAY", message="Upstream request failed"
    )
    assert "Invalid API key" not in response.text


def test_uncaught_tmdb_404_stays_404(error_client: TestClient) -> None:
    _install(_http_error(404, '{"status_message": "movie missing"}'))
    response = error_client.get("/auth/me")
    assert_error(response, status=404, code="NOT_FOUND", message="Not found")
    assert "movie missing" not in response.text


def test_uncaught_connect_error_is_503(error_client: TestClient) -> None:
    _install(httpx.ConnectError(f"connection refused {_SECRET}"))
    response = error_client.get("/auth/me")
    assert_error(
        response,
        status=503,
        code="SERVICE_UNAVAILABLE",
        message="Upstream service unavailable, try again",
    )
    _assert_hidden(response, "connection refused", "super-secret-db-password")


def test_supabase_query_error_hides_sql(error_client: TestClient) -> None:
    _install(
        APIError(
            {
                "message": 'relation "profiles" does not exist',
                "code": "42P01",
                "hint": _SQL,
                "details": _SECRET,
            }
        )
    )
    response = error_client.get("/auth/me")
    assert_error(
        response, status=502, code="BAD_GATEWAY", message="Upstream request failed"
    )
    _assert_hidden(response, _SQL, "profiles", "super-secret-db-password", "42P01")


def test_supabase_connection_error_is_503(error_client: TestClient) -> None:
    _install(
        APIError(
            {
                "message": "Could not connect to the database",
                "code": "PGRST000",
                "details": _SQL,
            }
        )
    )
    response = error_client.get("/auth/me")
    assert_error(
        response,
        status=503,
        code="SERVICE_UNAVAILABLE",
        message="Upstream service unavailable, try again",
    )
    _assert_hidden(response, _SQL, "Could not connect", "PGRST000")


def test_rate_limit_shape(error_client: TestClient) -> None:
    limit = Limit(
        parse("1/minute"),
        lambda: "test",
        None,
        False,
        None,
        f"secret limiter {_SQL}",
        None,
        1,
        False,
    )
    _install(RateLimitExceeded(limit))
    response = error_client.get("/auth/me", headers={"X-Request-ID": "rate-1"})
    assert_error(response, status=429, code="RATE_LIMITED", message="Too many requests")
    _assert_hidden(response, _SQL, "1 per 1 minute")
