"""Liveness and database readiness probes."""

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError


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
