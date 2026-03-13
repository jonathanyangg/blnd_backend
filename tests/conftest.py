import os
from collections.abc import Generator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

os.environ["BLND_DISABLE_RATE_LIMITS"] = "true"

# Stable UUIDs for tests
CALLER_ID = "11111111-1111-1111-1111-111111111111"
TARGET_ID = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def mock_db() -> MagicMock:
    return MagicMock(spec=Session)


@pytest.fixture
def app_client(mock_db: MagicMock) -> Generator[TestClient, None, None]:
    from app.dependencies import get_current_user, get_db
    from main import app

    app.dependency_overrides[get_current_user] = lambda: CALLER_ID
    app.dependency_overrides[get_db] = lambda: mock_db

    client = TestClient(app)
    yield client

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)
