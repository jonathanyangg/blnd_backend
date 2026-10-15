"""Liveness and database readiness probes."""

import signal
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import OperationalError

from app.database import ping_database


def test_health_is_liveness_only(app_client: TestClient) -> None:
    response = app_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_deep_ok(client: TestClient) -> None:
    response = client.get("/health/deep")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok"}


def test_health_deep_reports_error_class_only(
    app_client: TestClient, monkeypatch
) -> None:
    secret = "postgresql://user:super-secret-db-password@db.internal/postgres"

    def boom() -> None:
        raise OperationalError(secret, {}, Exception(secret))

    monkeypatch.setattr("main.ping_database", boom)

    response = app_client.get("/health/deep")
    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "db": "error",
        "error": "OperationalError",
    }
    assert "super-secret-db-password" not in response.text
    assert secret not in response.text


def test_ping_database_connect_timeout(monkeypatch) -> None:
    """A blackholed database must fail in a few seconds, not hang the worker."""

    def _alarm(_signum, _frame) -> None:
        raise TimeoutError("database probe hung")

    monkeypatch.setattr(
        "app.database.engine",
        type(
            "Engine",
            (),
            {"url": make_url("postgresql://postgres:postgres@192.0.2.1:5432/postgres")},
        )(),
    )
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(5)
    started = time.monotonic()
    try:
        with pytest.raises(OperationalError):
            ping_database()
    finally:
        signal.alarm(0)
    assert time.monotonic() - started < 5
