"""RevenueCat webhook authentication."""

import pytest
from fastapi.testclient import TestClient

from app.config import settings


def test_webhook_rejects_empty_secret(
    app_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "revenuecat_webhook_secret", "")
    response = app_client.post(
        "/webhooks/revenuecat",
        json={
            "api_version": "1.0",
            "event": {
                "type": "TEST",
                "id": "evt_1",
                "app_user_id": "user_1",
            },
        },
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "Webhook not configured"
