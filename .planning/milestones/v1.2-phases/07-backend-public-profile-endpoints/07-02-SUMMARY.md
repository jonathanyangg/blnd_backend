---
phase: 07-backend-public-profile-endpoints
plan: "02"
subsystem: backend
tags: [api, auth, public-profile, pagination, friends]
dependency_graph:
  requires: ["07-01"]
  provides: ["GET /auth/users/{id}/watched", "GET /auth/users/{id}/friends"]
  affects: ["blnd_ios phase 8 FriendProfileView"]
tech_stack:
  added: []
  patterns: ["assert_are_friends() gate", "SQLAlchemy JOIN query for watched", "N+1-safe friends listing"]
key_files:
  created: []
  modified:
    - blnd_backend/app/auth/services.py
    - blnd_backend/app/auth/views.py
    - blnd_backend/tests/test_auth_public_profile.py
decisions:
  - "Followed existing get_watch_history() JOIN pattern from tracking/services.py for get_public_watched()"
  - "get_public_friends() resolves friend_id per-row and queries Profile individually — same pattern as friends/services.py"
metrics:
  duration: "6 minutes"
  completed_date: "2026-03-12"
  tasks_completed: 2
  files_modified: 3
---

# Phase 7 Plan 02: Public Profile Watched & Friends Endpoints Summary

**One-liner:** Paginated watched movies and friends list endpoints behind assert_are_friends() gate using SQLAlchemy JOIN and scalar count patterns.

## What Was Built

Two new REST endpoints completing Phase 7's public profile API surface:

- `GET /auth/users/{id}/watched?limit=20&offset=0` — returns `{results: [{tmdb_id, title, poster_path, rating}], total: int}`. Paginated with limit 1–100 (default 20), offset >= 0. JOINs WatchedMovie + Movie tables.
- `GET /auth/users/{id}/friends` — returns `{friends: [{id, username, display_name, avatar_url}]}`. Resolves friend IDs from both sides of the Friendship row.

Both endpoints:
- Require JWT auth (via existing `get_current_user` dependency)
- Gate access with `assert_are_friends()` — return HTTP 403 with `"Not friends with this user"` for non-friends
- Are rate-limited at `LIMIT_DEFAULT` (60/min)

## Service Functions Added

`get_public_watched(caller_id, target_id, limit, offset, db)` — appended to `app/auth/services.py`. Uses `func.count()` scalar for total, then JOIN query with `.offset().limit()` for the page.

`get_public_friends(caller_id, target_id, db)` — appended after `get_public_watched()`. Queries accepted Friendship rows for target_id (either side), resolves each friend's Profile individually.

`Movie` model imported into `app/auth/services.py` (was missing, needed for the JOIN).

## Test Coverage

9 tests total in `tests/test_auth_public_profile.py` (all passing):
- `test_get_public_profile_success` (Plan 01)
- `test_public_profile_403_not_friends` (Plan 01)
- `test_public_profile_404_user_not_found` (Plan 01)
- `test_get_public_watched_success` — 200 with 2 results, total=3
- `test_get_public_watched_403` — 403 for non-friend
- `test_get_public_watched_pagination` — limit/offset params accepted
- `test_get_public_friends_success` — 200 with 2 friends, all 4 fields present
- `test_get_public_friends_403` — 403 for non-friend
- `test_get_public_friends_empty` — `{"friends": []}` for target with no friends

## Verification

- `pytest tests/test_auth_public_profile.py`: 9 passed, 0 failed, 0 skipped
- `pytest tests/`: 9 passed (full suite)
- `pre-commit run --all-files`: ruff, ruff-format, codespell, pyright all passed
- Route order confirmed: `/users/search` precedes all `/users/{id}/*` routes in views.py

## Commits

- `ff36bee`: feat(07-02): add watched movies and friends list public profile endpoints

## Deviations from Plan

**1. [Rule 2 - Missing Import] Added Movie import to auth/services.py**
- Found during: Task 1 implementation
- Issue: `Movie` model was not imported in `app/auth/services.py` but required for the `get_public_watched()` JOIN query
- Fix: Added `from app.movies.models import Movie` to imports
- Files modified: `blnd_backend/app/auth/services.py`
- Commit: ff36bee

**Note on test file git tracking:** `tests/` directory is in `.gitignore` for the blnd_backend repo. Test file changes are not tracked in the backend git repo — this matches the existing pattern from Plan 01.

## Self-Check: PASSED

- `blnd_backend/app/auth/services.py` — modified, committed in ff36bee
- `blnd_backend/app/auth/views.py` — modified, committed in ff36bee
- `ff36bee` — confirmed in `git log --oneline -1`
- All 9 tests passing
- pre-commit clean
