---
phase: 07-backend-public-profile-endpoints
verified: 2026-03-12T00:00:00Z
status: passed
score: 7/7 must-haves verified
gaps: []
human_verification:
  - test: "Hit GET /auth/users/{id}/profile against a real Supabase DB with two friend accounts"
    expected: "Returns 200 with correct counts pulled from live watched_movies, friendships, group_members tables"
    why_human: "Tests use mock SQLAlchemy session — actual DB query correctness (joins, filters, scalar counts) cannot be confirmed without a live connection"
---

# Phase 7: Backend Public Profile Endpoints — Verification Report

**Phase Goal:** Three production-ready endpoints expose a friend's public profile data behind a friendship authorization gate
**Verified:** 2026-03-12
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Authenticated user can fetch another user's public profile stats via GET /auth/users/{id}/profile | VERIFIED | `views.py` line 120-128 — endpoint registered, calls `services.get_public_profile()` |
| 2 | GET /auth/users/{id}/profile returns HTTP 403 when caller is not friends with target | VERIFIED | `services.py` line 137-156 — `assert_are_friends()` raises `HTTP_403_FORBIDDEN` with "Not friends with this user"; `test_public_profile_403_not_friends` passes |
| 3 | Public profile response includes id, username, display_name, avatar_url, watched_count, friends_count, blends_count — but NOT taste_bio or favorite_genres | VERIFIED | `schemas.py` line 109-116 — `PublicProfileResponse` has exactly 7 fields, no taste_bio or favorite_genres; test asserts their absence |
| 4 | Authenticated user can fetch another user's watched movies (paginated) via GET /auth/users/{id}/watched | VERIFIED | `views.py` line 131-141 — endpoint registered with limit/offset Query params; `services.get_public_watched()` does JOIN on WatchedMovie+Movie with `.offset().limit()` |
| 5 | Authenticated user can fetch another user's friends list via GET /auth/users/{id}/friends | VERIFIED | `views.py` line 144-152 — endpoint registered; `services.get_public_friends()` queries Friendship both directions and resolves Profile per friend |
| 6 | GET /auth/users/{id}/watched returns HTTP 403 when caller is not friends with target | VERIFIED | `services.get_public_watched()` calls `assert_are_friends()` first; `test_get_public_watched_403` asserts 403 + detail message |
| 7 | GET /auth/users/{id}/friends returns HTTP 403 when caller is not friends with target | VERIFIED | `services.get_public_friends()` calls `assert_are_friends()` first; `test_get_public_friends_403` asserts 403 + detail message |

**Score:** 7/7 truths verified

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `blnd_backend/app/auth/schemas.py` | PublicProfileResponse, PublicFriendResponse, PublicWatchedMovieResponse, PublicWatchedListResponse, PublicFriendsListResponse | VERIFIED | All 5 schemas present at lines 109-139. PublicProfileResponse correctly excludes taste_bio and favorite_genres. |
| `blnd_backend/app/auth/services.py` | assert_are_friends() helper + get_public_profile(), get_public_watched(), get_public_friends() | VERIFIED | assert_are_friends() at line 137; get_public_profile() at line 159; get_public_watched() at line 205; get_public_friends() at line 243. All substantive — full DB logic, not stubs. |
| `blnd_backend/app/auth/views.py` | GET /users/{id}/profile, GET /users/{id}/watched, GET /users/{id}/friends endpoints | VERIFIED | All three endpoints at lines 120, 131, 144. Route order correct: /users/search (line 13) precedes all /users/{id}/* routes. |
| `blnd_backend/tests/conftest.py` | mock_db + app_client fixtures with dependency overrides | VERIFIED | mock_db uses MagicMock(spec=Session); app_client overrides get_current_user and get_db; rate limits disabled via BLND_DISABLE_RATE_LIMITS=true; teardown cleans overrides. |
| `blnd_backend/tests/test_auth_public_profile.py` | 9 tests covering all three endpoints (success, 403, edge cases) | VERIFIED | 9 concrete tests present, 0 skipped stubs. All three endpoints covered with success + 403 paths. |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `views.py` | `services.py` | get_user_profile() calls services.get_public_profile() | WIRED | Line 128: `return services.get_public_profile(user_id, id, db)` |
| `views.py` | `services.py` | get_user_watched() calls services.get_public_watched() | WIRED | Line 141: `return services.get_public_watched(user_id, id, limit, offset, db)` |
| `views.py` | `services.py` | get_user_friends() calls services.get_public_friends() | WIRED | Line 152: `return services.get_public_friends(user_id, id, db)` |
| `services.py` | `friends/models.py` | assert_are_friends() queries Friendship with status=="accepted" | WIRED | Line 140-151: queries Friendship.status == "accepted" with or_() for both directions |
| `services.py` | `schemas.py` | get_public_profile() returns dict matching PublicProfileResponse fields | WIRED | Lines 194-201: returns dict with id, username, display_name, avatar_url, watched_count, friends_count, blends_count — exact match |
| `services.py` | `services.py` | get_public_watched() and get_public_friends() call assert_are_friends() | WIRED | Line 209: `assert_are_friends(caller_id, target_id, db)`; Line 245: `assert_are_friends(caller_id, target_id, db)` |

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| API-01 | 07-01-PLAN.md | Authenticated user can fetch another user's public profile (username, display name, avatar, watched count, friends count, blends count) | SATISFIED | GET /auth/users/{id}/profile implemented and tested; PublicProfileResponse contains all 6 required fields plus id |
| API-02 | 07-02-PLAN.md | Authenticated user can fetch another user's watched movies (paginated, with tmdb_id, title, poster, rating) | SATISFIED | GET /auth/users/{id}/watched with limit/offset params; PublicWatchedMovieResponse has all 4 required fields |
| API-03 | 07-02-PLAN.md | Authenticated user can fetch another user's friends list (id, username, display name, avatar) | SATISFIED | GET /auth/users/{id}/friends; PublicFriendResponse has all 4 required fields |
| API-04 | 07-01-PLAN.md, 07-02-PLAN.md | All three public profile endpoints return 403 if caller is not friends with target | SATISFIED | assert_are_friends() gate called at the start of all three service functions; 3 separate 403 tests confirm the exact detail message |

All 4 requirement IDs from PLAN frontmatter accounted for. No orphaned requirements found — REQUIREMENTS.md maps API-01 through API-04 exclusively to Phase 7 and marks all as Complete.

---

## Anti-Patterns Found

No anti-patterns detected in phase files.

| File | Pattern | Severity | Notes |
|------|---------|----------|-------|
| `blnd_backend/app/auth/services.py` | None | — | No TODO/FIXME, no stub returns, no console.log equivalents |
| `blnd_backend/app/auth/views.py` | None | — | All three endpoints fully wired to services |
| `blnd_backend/app/auth/schemas.py` | None | — | All schemas substantive with typed fields |
| `blnd_backend/tests/test_auth_public_profile.py` | None | — | 0 skipped tests; all 9 tests are fully implemented |

---

## Human Verification Required

### 1. Live DB Query Accuracy

**Test:** Create two user accounts in the Supabase test environment, send a friend request and accept it, track 3 movies for user B, add user B to 1 group. Call GET /auth/users/{B_id}/profile as user A.
**Expected:** Returns `{"watched_count": 3, "friends_count": 1, "blends_count": 1, ...}`
**Why human:** All tests use MagicMock SQLAlchemy sessions with pre-configured return values. The actual SQL (scalar counts, JOIN correctness, or_() friendship filter covering both directions) is not exercised against a real Postgres instance.

### 2. Route Order Safety Under FastAPI

**Test:** Call GET /auth/users/search?q=alice and GET /auth/users/{some_uuid}/profile in sequence.
**Expected:** Search route resolves to the search endpoint, not treated as a profile lookup for id="search"
**Why human:** Although the route order in views.py places /users/search before /users/{id}/*, FastAPI routing behavior with path parameters vs. literal segments is best confirmed with a running server.

---

## Gaps Summary

No gaps. All seven observable truths are verified, all five required artifacts are substantive and wired, all four key links are confirmed in code, and all four requirement IDs (API-01 through API-04) are satisfied with test evidence. The phase goal — three production-ready endpoints behind a friendship authorization gate — is achieved.

---

_Verified: 2026-03-12_
_Verifier: Claude (gsd-verifier)_
