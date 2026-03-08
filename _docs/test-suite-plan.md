# Test Suite Plan

## Context

Zero tests exist on a codebase with real business logic (friend request flows, group permissions, recommendation pipeline, Letterboxd import). One bad deploy breaks everything. Tests go first so they catch regressions from the other two features (TMDB sync, rate limiting).

---

## New Dependencies

Add to `requirements.txt`:
```
pytest==8.3.5
pytest-asyncio==0.25.3
```

---

## New Files

### `pyproject.toml` — pytest config
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

### `tests/__init__.py` — empty

### `tests/conftest.py` — core fixtures

**Test DB (SQLite in-memory):**
- `create_engine("sqlite://", poolclass=StaticPool)`
- Register SQLAlchemy type compiler: `@compiles(Vector, "sqlite")` → returns `"TEXT"` (pgvector `Vector(1536)` column won't work in SQLite otherwise)
- `Base.metadata.create_all(bind=engine)` creates all tables
- Fixture yields a session, closes on teardown
- Key imports: `app/database.py:Base`, `app/dependencies.py:get_db,get_current_user,get_tmdb_client`

**Auth override:**
```python
TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
TEST_USER_ID_2 = "00000000-0000-0000-0000-000000000002"

app.dependency_overrides[get_current_user] = lambda: TEST_USER_ID
```

**DB override:**
```python
app.dependency_overrides[get_db] = lambda: test_session
```

**TMDB mock:**
- Override `get_tmdb_client` with a mock `httpx.AsyncClient` that returns canned TMDB responses
- Configurable per-test for different movie data

**Client fixture:**
```python
from fastapi.testclient import TestClient
client = TestClient(app)
```

**Environment:**
- Set `TESTING=true` env var (used by rate limiting feature to disable limits)

### `tests/factories.py` — test data helpers

Helper functions that create and commit test records:
- `make_profile(db, user_id, username, ...)` → Profile
- `make_movie(db, tmdb_id, title, genres, ...)` → Movie
- `make_watched(db, user_id, tmdb_id, rating, ...)` → WatchedMovie
- `make_watchlist(db)` → Watchlist
- `make_friendship(db, requester_id, addressee_id, status)` → Friendship
- `make_group(db, name, created_by)` → Group + Watchlist + GroupMember

---

## Test Files (priority order)

### `tests/test_ranking.py` — pure functions, no mocking needed

Tests for `app/recommendations/ranking.py`:
- `_genre_overlap()`: empty lists, partial overlap, full overlap, Jaccard math
- `_consensus_score()`: None → 0.0, 0 → 0.0, 5 → 0.5, 10 → 1.0
- `_director_boost()`: match → 1.0, no match → 0.0, None → 0.0
- `_cast_boost()`: partial overlap fraction
- `to_match_percentage()`: verify compression formula (`score + (1 - score) * 0.4`)

### `tests/test_auth.py` — username validation + profile

Tests for `app/auth/schemas.py` (validation) and `app/auth/views.py`:
- **Valid usernames**: "john", "john.doe", "john_doe", "j0hn123"
- **Too short / too long**: "", "ab", 31-char string
- **Invalid characters**: spaces, @, #, !, etc.
- **Leading/trailing specials**: ".john", "john.", "_john", "john_"
- **Consecutive specials**: "john..doe", "john__doe", "john._doe"
- **Case normalization**: "JohnDoe" → "johndoe"
- **Signup via TestClient**: mock supabase auth, verify profile + watchlist created
- **Profile update**: username conflict returns 400

### `tests/test_friends.py` — state machine + permissions

Tests for `app/friends/services.py` and `app/friends/views.py`:
- **Send request**: success, self-request → 400, duplicate pending → 400
- **Accept**: right user only (addressee), wrong user → 403
- **Reject**: right user only, wrong user → 403
- **Re-request after rejection**: allowed
- **List friends**: shows both directions (requester + addressee)
- **Remove**: either party can remove

Requires two test users (TEST_USER_ID + TEST_USER_ID_2).

### `tests/test_groups.py` — CRUD + permissions

Tests for `app/groups/services.py` and `app/groups/views.py`:
- **Create**: auto-creates watchlist, adds creator as member
- **Update**: creator only, non-creator → 403
- **Add member**: by username, 10-member cap, already member → 400
- **Kick**: cannot kick owner → 400
- **Leave**: ownership transfers to earliest member
- **Delete**: creator only, non-creator → 403, cascades

### `tests/test_tracking.py` — tracking + watchlist integration

Tests for `app/tracking/services.py` and `app/tracking/views.py`:
- **Track movie**: auto-cache from TMDB mock, creates WatchedMovie
- **Auto-remove from watchlist**: movie in watchlist gets removed on track
- **Update rating/review**: PATCH endpoint
- **Delete tracked movie**: DELETE endpoint
- **Paginated watch history**: GET with offset/limit

### `tests/test_watchlist.py` — CRUD

Tests for `app/watchlist/services.py` and `app/watchlist/views.py`:
- **Add to watchlist**: auto-cache from TMDB mock
- **Remove from watchlist**: DELETE
- **List watchlist**: paginated GET

### `tests/test_movies.py` — vote_average scaling

Tests for `app/movies/schemas.py`:
- `MovieResponse` field_validator: raw 8.0 → 4.0 (÷2), raw 10 → 5.0, raw 0 → 0.0

---

## Verification

1. `.venv/bin/pip install pytest pytest-asyncio`
2. `.venv/bin/python -m pytest tests/ -v` — all tests pass
3. `pre-commit run --all-files` — ruff/pyright pass on test files
4. No test requires a running database, TMDB API key, or OpenAI API key
