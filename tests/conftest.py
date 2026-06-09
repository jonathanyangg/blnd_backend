import os
from collections.abc import Generator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

os.environ["BLND_DISABLE_RATE_LIMITS"] = "true"

# The Supabase client is built at import time in app.dependencies; tests always
# override it via dependency_overrides, but it still needs a non-empty URL/key to
# construct. Supply placeholders so the suite runs without a real .env (e.g. CI).
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

# Tests run against the local Supabase Postgres (supabase start). Override the
# default to point elsewhere, but it must stay local — we refuse remote/prod.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
)
assert "127.0.0.1" in TEST_DATABASE_URL or "localhost" in TEST_DATABASE_URL, (
    f"Tests must use a local database; refusing {TEST_DATABASE_URL!r}"
)
# Make the app itself (engine / SessionLocal / background tasks) use the test DB.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

# Stable UUIDs for tests
CALLER_ID = "11111111-1111-1111-1111-111111111111"
TARGET_ID = "22222222-2222-2222-2222-222222222222"
TEST_USER_ID = CALLER_ID
TEST_USER_ID_2 = TARGET_ID


# --- Real-DB fixtures (integration tests) ---


@pytest.fixture(scope="session")
def _engine():
    engine = create_engine(TEST_DATABASE_URL)
    yield engine
    engine.dispose()


@pytest.fixture
def db(_engine) -> Generator[Session, None, None]:
    """A real DB session wrapped in a transaction that is rolled back after each
    test. Inner ``commit()`` calls land on a savepoint, so nothing persists."""
    connection = _engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db: Session) -> Generator[TestClient, None, None]:
    """TestClient wired to the transactional test session."""
    from app.dependencies import get_current_user, get_db
    from main import app

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: CALLER_ID

    test_client = TestClient(app)
    yield test_client

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def client_user2(db: Session) -> Generator[TestClient, None, None]:
    """TestClient authenticated as the second user (TARGET_ID)."""
    from app.dependencies import get_current_user, get_db
    from main import app

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: TARGET_ID

    test_client = TestClient(app)
    yield test_client

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)


class _FakeTMDBResponse:
    def __init__(self, tmdb_id: int) -> None:
        self._tmdb_id = tmdb_id

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return {
            "id": self._tmdb_id,
            "title": "Fight Club",
            "release_date": "1999-10-15",
            "overview": "An insomniac office worker...",
            "poster_path": "/poster.jpg",
            "genres": [],
            "runtime": 139,
            "vote_average": 8.4,
            "credits": {"cast": [], "crew": []},
            "videos": {"results": []},
        }


class _FakeTMDBClient:
    async def get(self, url: str, params: dict | None = None) -> _FakeTMDBResponse:
        tmdb_id = int(url.rstrip("/").split("/")[-1])
        return _FakeTMDBResponse(tmdb_id)


@pytest.fixture
def client_with_tmdb(db: Session) -> Generator[TestClient, None, None]:
    """TestClient with the TMDB client faked (returns Fight Club for any id), so
    movie-caching endpoints don't hit the real TMDB API."""
    from app.dependencies import get_current_user, get_db, get_tmdb_client
    from main import app

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: CALLER_ID
    app.dependency_overrides[get_tmdb_client] = lambda: _FakeTMDBClient()

    test_client = TestClient(app)
    yield test_client

    for dep in (get_db, get_current_user, get_tmdb_client):
        app.dependency_overrides.pop(dep, None)


# --- Legacy mock-style fixtures (older view-layer tests) ---


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
