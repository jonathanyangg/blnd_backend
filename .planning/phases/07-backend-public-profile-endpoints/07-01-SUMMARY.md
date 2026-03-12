---
phase: 07-backend-public-profile-endpoints
plan: 01
subsystem: backend
tags: [fastapi, pydantic, sqlalchemy, testing, auth, friends]
dependency_graph:
  requires: []
  provides: [GET /auth/users/{id}/profile, PublicProfileResponse schema, assert_are_friends() helper, test infrastructure]
  affects: [app/auth/schemas.py, app/auth/services.py, app/auth/views.py]
tech_stack:
  added: []
  patterns: [TDD with mock SQLAlchemy session, side_effect chaining for sequential db.query() mocks]
key_files:
  created:
    - blnd_backend/tests/__init__.py
    - blnd_backend/tests/conftest.py
    - blnd_backend/tests/test_auth_public_profile.py
  modified:
    - blnd_backend/app/auth/schemas.py
    - blnd_backend/app/auth/services.py
    - blnd_backend/app/auth/views.py
decisions:
  - PublicProfileResponse deliberately excludes taste_bio and favorite_genres (privacy boundary)
  - Test fixtures use side_effect chaining to handle sequential db.query() mock calls in correct order
  - Tests directory force-added with git add -f because /tests is in blnd_backend .gitignore
  - app_client fixture typed as Generator[TestClient, None, None] to satisfy pyright
metrics:
  duration: 4 min
  completed_date: "2026-03-12"
  tasks_completed: 1
  files_changed: 6
---

# Phase 7 Plan 01: Public Profile Schemas, Friendship Gate, and Stats Endpoint Summary

**One-liner:** JWT-gated GET /auth/users/{id}/profile returning 7-field PublicProfileResponse with friendship gate (403) and mock-based test scaffold using side_effect chaining for sequential SQLAlchemy queries.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Response schemas + friendship gate + profile stats service + test scaffold | cc1efc3 | schemas.py, services.py, views.py, tests/__init__.py, conftest.py, test_auth_public_profile.py |

## What Was Built

### Schemas (blnd_backend/app/auth/schemas.py)
Five new Pydantic models appended:
- `PublicProfileResponse` — 7 public fields (id, username, display_name, avatar_url, watched_count, friends_count, blends_count). Deliberately excludes taste_bio and favorite_genres.
- `PublicWatchedMovieResponse` — tmdb_id, title, poster_path, rating
- `PublicWatchedListResponse` — results list + total count
- `PublicFriendResponse` — id, username, display_name, avatar_url
- `PublicFriendsListResponse` — friends list

### Services (blnd_backend/app/auth/services.py)
- `assert_are_friends(caller_id, target_id, db)` — queries Friendship table for accepted friendship in either direction, raises HTTP 403 "Not friends with this user" if none found
- `get_public_profile(caller_id, target_id, db)` — calls assert_are_friends(), then fetches Profile and three scalar counts (watched_count via WatchedMovie, friends_count via Friendship, blends_count via GroupMember)

### Endpoint (blnd_backend/app/auth/views.py)
- `GET /auth/users/{id}/profile` — requires JWT auth, calls services.get_public_profile(), returns PublicProfileResponse

### Test Infrastructure (blnd_backend/tests/)
- `conftest.py` — mock_db (MagicMock(spec=Session)) and app_client (TestClient with dependency overrides for get_current_user and get_db). Sets BLND_DISABLE_RATE_LIMITS=true at module level.
- `test_auth_public_profile.py` — 3 passing tests (200 success, 403 not-friends, 404 not-found) + 4 skipped Plan 02 stubs

## Verification Results

- `pytest tests/test_auth_public_profile.py -x -k "not skip" -v` — 3 passed
- `pytest tests/ -x` — 3 passed, 4 skipped
- `pre-commit run --all-files` — ruff, ruff-format, codespell, pyright all passed

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] tests/ directory was gitignored**
- **Found during:** Task 1 commit
- **Issue:** blnd_backend/.gitignore contains `/tests`, so `git add tests/` silently ignored all files
- **Fix:** Used `git add -f` to force-add test files
- **Files modified:** none (git operation only)
- **Commit:** cc1efc3

**2. [Rule 1 - Bug] app_client fixture had incorrect return type annotation**
- **Found during:** pre-commit pyright check
- **Issue:** Fixture uses `yield` but was typed as `TestClient` instead of `Generator[TestClient, None, None]`
- **Fix:** Changed return type to `Generator[TestClient, None, None]` with `from collections.abc import Generator`
- **Files modified:** blnd_backend/tests/conftest.py
- **Commit:** cc1efc3

**3. [Rule 3 - Blocking] blnd_backend/ has its own git repository**
- **Found during:** Task 1 commit from repo root
- **Issue:** The outer repo (blnd/) treats blnd_backend/ as an untracked submodule, not tracking its contents
- **Fix:** All git operations performed with `git -C /Users/adamrose/Desktop/blnd/blnd_backend` targeting the inner repo
- **Impact:** All future backend commits must target blnd_backend's own git repo

## Self-Check: PASSED

All 6 files found on disk. Commit cc1efc3 verified in blnd_backend git log.
