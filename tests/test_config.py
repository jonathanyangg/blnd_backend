"""Startup checks for required environment variables."""

import logging

import pytest
from fastapi.testclient import TestClient

from app.config import settings, validate_required_settings


def _clear_two_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "supabase_key", "")
    monkeypatch.setattr(settings, "revenuecat_webhook_secret", "")
    monkeypatch.setattr(
        settings, "supabase_url", "https://super-secret-project.supabase.co"
    )
    monkeypatch.setattr(settings, "supabase_service_key", "service-secret-value")
    monkeypatch.setattr(
        settings,
        "database_url",
        "postgresql://user:super-secret-db-password@127.0.0.1/postgres",
    )


def test_missing_env_logs_names_not_values(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_two_required(monkeypatch)
    monkeypatch.delenv("STRICT_ENV_VALIDATION", raising=False)
    monkeypatch.setattr(settings, "strict_env_validation", "")

    with caplog.at_level(logging.ERROR):
        validate_required_settings()

    assert "SUPABASE_KEY" in caplog.text
    assert "REVENUECAT_WEBHOOK_SECRET" in caplog.text
    assert "super-secret-project" not in caplog.text
    assert "service-secret-value" not in caplog.text
    assert "super-secret-db-password" not in caplog.text


def test_strict_env_validation_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_two_required(monkeypatch)
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "true")

    with pytest.raises(RuntimeError, match="SUPABASE_KEY") as exc_info:
        validate_required_settings()

    message = str(exc_info.value)
    assert "REVENUECAT_WEBHOOK_SECRET" in message
    assert "super-secret-project" not in message
    assert "service-secret-value" not in message
    assert "super-secret-db-password" not in message


def test_strict_env_validation_off_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_two_required(monkeypatch)
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    validate_required_settings()


def test_lifespan_fails_fast_when_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_two_required(monkeypatch)
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "true")
    from main import app

    with pytest.raises(RuntimeError, match="SUPABASE_KEY"):
        with TestClient(app):
            pass
