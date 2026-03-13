# Phase 7: Backend Public Profile Endpoints - Research

**Researched:** 2026-03-12
**Domain:** FastAPI + SQLAlchemy read-only public API endpoints with friendship authorization
**Confidence:** HIGH

## Summary

Phase 7 adds three read-only GET endpoints to the existing `app/auth/` domain. All three live under the `/auth/users/{id}/` URL prefix and are gated by a friendship authorization check that returns HTTP 403 if the caller is not friends with the target. No new database migrations are required — all necessary tables (`profiles`, `friendships`, `watched_movies`, `movies`, `group_members`) already exist.

The key engineering decisions are already locked in STATE.md: use `func.count()` scalar subqueries for stats (no N+1), create a new `PublicProfileResponse` schema (not reusing `UserResponse` which leaks `taste_bio`/`favorite_genres`), and implement a shared `assert_are_friends()` helper that can be called at the top of all three service functions. The pattern for paginated responses, JOIN queries, and friendship lookups is already established in `tracking/services.py` and `friends/services.py`.

The blends count is sourced from `GroupMember` rows — a user's group count equals the number of distinct `group_id` values where their `user_id` appears. This needs to be confirmed by reading the `group_members` table, but the model (`GroupMember`) is already in place.

**Primary recommendation:** Add all three endpoints to `app/auth/views.py` with service functions in `app/auth/services.py` and new Pydantic schemas in `app/auth/schemas.py`. This follows the locked decision to avoid a new domain folder.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| API-01 | Authenticated user can fetch another user's public profile (username, display name, avatar, watched count, friends count, blends count) | `Profile` model has all identity fields; counts via `func.count()` scalar queries on `watched_movies`, `friendships` (both directions), `group_members` |
| API-02 | Authenticated user can fetch another user's watched movies (paginated, with tmdb_id, title, poster, rating) | `WatchedMovie` + `Movie` JOIN query pattern already in `tracking/services.py::get_watch_history()`; schema is a subset of `WatchedMovieResponse` |
| API-03 | Authenticated user can fetch another user's friends list (id, username, display name, avatar) | `Friendship` bidirectional OR query + `Profile` lookup pattern already in `friends/services.py::get_friends()`; response is a list of `FriendResponse`-shaped dicts |
| API-04 | All three public profile endpoints return 403 if the caller is not friends with the target user | Shared `assert_are_friends(caller_id, target_id, db)` helper using OR-filter on `friendships` table; raises `HTTPException(403)` if no accepted friendship found |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| FastAPI | already installed | Router, path params, Query params, HTTPException | Project standard — all existing endpoints use it |
| SQLAlchemy ORM | already installed | `func.count()` scalar queries, JOIN queries, `or_()` filters | Project standard — no raw SQL for service logic |
| Pydantic v2 | already installed | `PublicProfileResponse`, `PublicWatchedMovieResponse`, `PublicFriendsListResponse` schemas | Project standard — all response models are Pydantic BaseModel |
| slowapi | already installed | `@limiter.limit(LIMIT_DEFAULT)` on all three new endpoints | Project standard — every auth/user-facing endpoint has this decorator |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| sqlalchemy `func` | already installed | `func.count()` for watched/friends/groups counts in stats | Use for scalar aggregates — never call `get_friends()` then `len()` (N+1 trap) |
| sqlalchemy `or_` | already installed | Friendship bidirectional lookup | Friendship rows can be in either direction (requester_id OR addressee_id) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `func.count()` scalar for stats | Call existing `get_friends()` service and `len()` the result | N+1: `get_friends()` fetches all Friendship + Profile rows; `func.count()` is a single COUNT query |
| New `PublicProfileResponse` schema | Reuse `UserResponse` | `UserResponse` includes `taste_bio` and `favorite_genres` — private fields that should not be exposed on someone else's profile |
| 403 on unauthorized access | 404 to hide user existence | Product decision locked as 403 in STATE.md; 403 is explicit and frontend-friendly |

**No new installation needed** — all dependencies are already in `requirements.txt`.

## Architecture Patterns

### Recommended Project Structure

These three endpoints extend the existing `app/auth/` domain. No new files or folders needed:

```
app/auth/
├── models.py      — Profile model (unchanged)
├── schemas.py     — ADD: PublicProfileResponse, PublicWatchedMovieResponse, PublicWatchedListResponse, PublicFriendResponse, PublicFriendsListResponse
├── services.py    — ADD: assert_are_friends(), get_public_profile(), get_public_watched(), get_public_friends()
└── views.py       — ADD: GET /users/{id}/profile, GET /users/{id}/watched, GET /users/{id}/friends
```

### Pattern 1: Friendship Gate Helper

**What:** A reusable service function that raises `HTTPException(403)` if no accepted friendship exists between caller and target.
**When to use:** Called at the top of all three public profile service functions before any data is returned.
**Example:**
```python
# Source: derived from friends/services.py friendship lookup pattern
from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.friends.models import Friendship

def assert_are_friends(caller_id: str, target_id: str, db: Session) -> None:
    """Raise 403 if caller and target are not accepted friends."""
    friendship = (
        db.query(Friendship)
        .filter(
            Friendship.status == "accepted",
            or_(
                (Friendship.requester_id == caller_id) & (Friendship.addressee_id == target_id),
                (Friendship.requester_id == target_id) & (Friendship.addressee_id == caller_id),
            ),
        )
        .first()
    )
    if not friendship:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not friends with this user",
        )
```

### Pattern 2: Stats via func.count() Scalar Queries

**What:** Three independent `func.count()` scalar queries for watched count, friends count, and groups (blends) count.
**When to use:** Public profile stats endpoint — must not call existing list-returning service functions for counting.
**Example:**
```python
# Source: derived from tracking/services.py::get_watch_history() count pattern
from sqlalchemy import func, or_
from app.tracking.models import WatchedMovie
from app.friends.models import Friendship
from app.groups.models import GroupMember

def get_public_profile(caller_id: str, target_id: str, db: Session) -> dict:
    assert_are_friends(caller_id, target_id, db)

    profile = db.query(Profile).filter(Profile.id == target_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="User not found")

    watched_count = (
        db.query(func.count(WatchedMovie.id))
        .filter(WatchedMovie.user_id == target_id)
        .scalar() or 0
    )

    friends_count = (
        db.query(func.count(Friendship.id))
        .filter(
            Friendship.status == "accepted",
            or_(
                Friendship.requester_id == target_id,
                Friendship.addressee_id == target_id,
            ),
        )
        .scalar() or 0
    )

    blends_count = (
        db.query(func.count(GroupMember.group_id))
        .filter(GroupMember.user_id == target_id)
        .scalar() or 0
    )

    return {
        "id": str(profile.id),
        "username": profile.username,
        "display_name": profile.display_name,
        "avatar_url": profile.avatar_url,
        "watched_count": watched_count,
        "friends_count": friends_count,
        "blends_count": blends_count,
    }
```

### Pattern 3: Paginated Watched Movies (JOIN Query)

**What:** Paginated `WatchedMovie` JOIN `Movie` query for another user's watched history, returning only public fields.
**When to use:** `GET /auth/users/{id}/watched` — reuse the `get_watch_history()` structure but for a different user_id.
**Example:**
```python
# Source: derived from tracking/services.py::get_watch_history()
def get_public_watched(
    caller_id: str, target_id: str, limit: int, offset: int, db: Session
) -> dict:
    assert_are_friends(caller_id, target_id, db)

    total = (
        db.query(func.count(WatchedMovie.id))
        .filter(WatchedMovie.user_id == target_id)
        .scalar() or 0
    )

    rows = (
        db.query(WatchedMovie, Movie)
        .join(Movie, WatchedMovie.tmdb_id == Movie.tmdb_id)
        .filter(WatchedMovie.user_id == target_id)
        .order_by(
            WatchedMovie.watched_date.desc().nulls_last(),
            WatchedMovie.created_at.desc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )

    results = [
        {
            "tmdb_id": entry.tmdb_id,
            "title": movie.title,
            "poster_path": movie.poster_path,
            "rating": entry.rating,
        }
        for entry, movie in rows
    ]
    return {"results": results, "total": total}
```

### Pattern 4: Friends List for Another User

**What:** Bidirectional Friendship query to get another user's friend list, returning `FriendResponse`-shaped dicts.
**When to use:** `GET /auth/users/{id}/friends` — reuses friendship lookup logic from `friends/services.py`.
**Example:**
```python
# Source: derived from friends/services.py::get_friends()
def get_public_friends(caller_id: str, target_id: str, db: Session) -> dict:
    assert_are_friends(caller_id, target_id, db)

    friendships = (
        db.query(Friendship)
        .filter(
            Friendship.status == "accepted",
            or_(
                Friendship.requester_id == target_id,
                Friendship.addressee_id == target_id,
            ),
        )
        .all()
    )

    friends = []
    for f in friendships:
        friend_id = f.addressee_id if str(f.requester_id) == target_id else f.requester_id
        profile = db.query(Profile).filter(Profile.id == friend_id).first()
        if profile:
            friends.append({
                "id": str(profile.id),
                "username": profile.username,
                "display_name": profile.display_name,
                "avatar_url": profile.avatar_url,
            })

    return {"friends": friends}
```

### Pattern 5: View Layer (FastAPI Router)

**What:** GET endpoints added to the existing `auth_router` in `app/auth/views.py`.
**When to use:** All three endpoints follow the same structure — path param `id`, `user_id` from JWT, `db` session.
**Example:**
```python
# Source: derived from app/auth/views.py::search_users() pattern
@router.get("/users/{id}/profile", response_model=schemas.PublicProfileResponse)
@limiter.limit(LIMIT_DEFAULT)
def get_public_profile(
    request: Request,
    id: str,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.get_public_profile(user_id, id, db)
```

### Anti-Patterns to Avoid

- **Calling `get_friends()` to count friends:** `get_friends()` returns full profile objects for each friend with a profile lookup per friendship (N+1). Use `func.count(Friendship.id)` with a scalar query.
- **Reusing `UserResponse` for public profile:** `UserResponse` includes `taste_bio` and `favorite_genres` which are private. Create `PublicProfileResponse` without those fields.
- **Raising 404 when user exists but caller is not friends:** The locked decision is 403. Do not silently hide the user's existence with 404 — that is a different policy choice.
- **Using a new domain folder:** `app/public_profile/` or similar was explicitly ruled out in REQUIREMENTS.md Out of Scope. Three read-only endpoints live in `app/auth/`.
- **Mixing caller_id and target_id in friendship check:** The `or_()` must check both `(requester=caller, addressee=target)` AND `(requester=target, addressee=caller)` since friendships can be initiated in either direction.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JWT verification | Custom token decode | `get_current_user` dependency from `app/dependencies.py` | Already wired into all endpoints; handles Supabase JWT validation |
| Rate limiting | Manual per-IP tracking | `@limiter.limit(LIMIT_DEFAULT)` from `app/core/rate_limit.py` | Project-wide slowapi setup; already handles key_func and error handler |
| Friend count | `len(get_friends(...))` | `func.count(Friendship.id)` scalar query | Avoids loading all Profile objects just to count them |
| Pagination | Custom slice logic | SQLAlchemy `.offset(offset).limit(limit)` | Matches established pattern in `get_watch_history()` and `get_watchlist()` |

**Key insight:** All infrastructure (auth, rate limiting, DB session, friendship model, profile model, movie model) is already in place. Phase 7 is pure read-only data assembly using existing patterns.

## Common Pitfalls

### Pitfall 1: Bidirectional Friendship Lookup Direction Error
**What goes wrong:** Checking only `requester_id == caller_id AND addressee_id == target_id` misses friendships where the target initiated the request.
**Why it happens:** Friendships store the direction of who sent the request; acceptance does not flip or normalize the direction.
**How to avoid:** Always use `or_()` with both directions as shown in Pattern 1. This pattern already exists in `friends/services.py::get_friends()` and `tracking/services.py::get_friends_who_watched()`.
**Warning signs:** Friends who accepted a request from the target user get 403 when calling the endpoint.

### Pitfall 2: Route Order Conflict in FastAPI
**What goes wrong:** Adding `/users/{id}/profile` after `/users/search` is fine, but adding a new route that matches `/users/{id}` exactly could shadow the existing `search_users` route at `/users/search`.
**Why it happens:** FastAPI matches routes in registration order; `/users/{id}` would match the literal string "search".
**How to avoid:** The three new routes use distinct sub-paths: `/users/{id}/profile`, `/users/{id}/watched`, `/users/{id}/friends`. These do not conflict with `/users/search`. Confirm route order in `views.py` after adding.
**Warning signs:** `GET /auth/users/search?q=foo` starts 404-ing or returning unexpected data.

### Pitfall 3: func.count() Returns None, Not 0
**What goes wrong:** `db.query(func.count(...)).scalar()` returns `None` if the table is empty or no rows match.
**Why it happens:** SQLAlchemy scalar() passes through None for NULL aggregate results.
**How to avoid:** Always use `... .scalar() or 0` to coerce None to 0. See the count pattern in `tracking/services.py::get_watch_history()`.
**Warning signs:** `watched_count` is `None` in the response for users with no watch history; Pydantic validation error if schema declares `int` not `int | None`.

### Pitfall 4: UUID Type Mismatch in Friendship Filter
**What goes wrong:** Comparing `Friendship.requester_id == caller_id` where `caller_id` is a Python `str` and `requester_id` is `UUID(as_uuid=True)` can fail or return no results depending on SQLAlchemy version.
**Why it happens:** `get_current_user()` returns `str(user_response.user.id)` — a string UUID. The model uses `UUID(as_uuid=True)`.
**How to avoid:** SQLAlchemy handles this coercion automatically for most cases. The existing codebase (`friends/services.py`) passes `user_id: str` directly to UUID column filters throughout and it works. Follow the same pattern — do not add explicit `uuid.UUID()` conversion unless a type error appears.
**Warning signs:** Friendship check always returns None even when friendship exists.

### Pitfall 5: Blends Count Sources GroupMember, Not Group
**What goes wrong:** Counting `Group.created_by == target_id` only counts groups the user created, missing groups they joined.
**Why it happens:** A user's "blend count" is how many blend groups they belong to, not how many they own.
**How to avoid:** Count `GroupMember` rows where `user_id == target_id`. The `GroupMember` model uses a composite PK of `(group_id, user_id)` — one row per membership.
**Warning signs:** Blends count is 0 for users who joined groups they didn't create.

## Code Examples

Verified patterns from existing codebase:

### Pagination Response Shape (from tracking/services.py)
```python
# Source: app/tracking/services.py::get_watch_history()
return {"results": results, "total": total or 0}
# Schema: class WatchHistoryResponse(BaseModel): results: list[...]; total: int
```

### Scalar Count Query (from tracking/services.py)
```python
# Source: app/tracking/services.py::get_watch_history() and get_friends_who_watched()
total = (
    db.query(func.count(WatchedMovie.id))
    .filter(WatchedMovie.user_id == user_id)
    .scalar()
)
```

### Bidirectional Friendship OR Filter (from friends/services.py)
```python
# Source: app/friends/services.py::get_friends()
friendships = (
    db.query(Friendship)
    .filter(
        Friendship.status == "accepted",
        or_(
            Friendship.requester_id == user_id,
            Friendship.addressee_id == user_id,
        ),
    )
    .all()
)
```

### Friend-side Resolution (from friends/services.py)
```python
# Source: app/friends/services.py::get_friends()
friend_id = f.addressee_id if str(f.requester_id) == user_id else f.requester_id
```

### Rate-Limited GET Endpoint (from auth/views.py)
```python
# Source: app/auth/views.py::search_users()
@router.get("/users/search", response_model=schemas.UserSearchResponse)
@limiter.limit(LIMIT_DEFAULT)
def search_users(
    request: Request,
    q: str = Query(min_length=1, max_length=30),
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
```

### GroupMember Model (from groups/models.py)
```python
# Source: app/groups/models.py
class GroupMember(Base):
    __tablename__ = "group_members"
    group_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    joined_at: Mapped[datetime] = ...
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Checking only one friendship direction | OR-filter on both requester_id and addressee_id | Established in friends/services.py (current) | Must be replicated in new service functions |
| Separate domain for any new feature cluster | Stay in existing domain if no new models needed | Decided in v1.2 roadmap session | New endpoints go in app/auth/ — no new folder |

**Deprecated/outdated:**
- None — this is new functionality, no existing implementation to replace.

## Open Questions

1. **Blends count: confirm GroupMember is the source of truth**
   - What we know: `GroupMember` table has composite PK `(group_id, user_id)`, one row per user-per-group. The `Group` model also has `created_by`.
   - What's unclear: STATE.md flags "confirm `GroupMember` model maps to 'blends' at implementation time." The implication is that all group memberships (including ones the user created) count as "blends," not just non-creator memberships.
   - Recommendation: Count `func.count(GroupMember.group_id).filter(GroupMember.user_id == target_id)`. This counts all groups the user is a member of (including groups they created, since `create_group()` adds the creator as a `GroupMember` row). Verify at plan execution time by reading `groups/services.py::create_group()`.

2. **Friendship gate policy: gate all three or only profile?**
   - What we know: STATE.md records "all three endpoints require `assert_are_friends()`" as a locked decision.
   - What's unclear: Whether the friends list endpoint should also be gated (i.e., you must be friends with someone to see their friends list).
   - Recommendation: Gate all three endpoints. This is the locked decision per STATE.md.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.3.5 |
| Config file | `blnd_backend/pyproject.toml` (`testpaths = ["tests"]`, `asyncio_mode = "auto"`) |
| Quick run command | `cd blnd_backend && python -m pytest tests/test_auth_public_profile.py -x` |
| Full suite command | `cd blnd_backend && python -m pytest tests/ -x` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| API-01 | `GET /auth/users/{id}/profile` returns stats for a friend | unit (TestClient + MagicMock db) | `pytest tests/test_auth_public_profile.py::test_get_public_profile_success -x` | Wave 0 |
| API-02 | `GET /auth/users/{id}/watched` returns paginated movies | unit (TestClient + MagicMock db) | `pytest tests/test_auth_public_profile.py::test_get_public_watched_success -x` | Wave 0 |
| API-03 | `GET /auth/users/{id}/friends` returns friends list | unit (TestClient + MagicMock db) | `pytest tests/test_auth_public_profile.py::test_get_public_friends_success -x` | Wave 0 |
| API-04 | All three endpoints return 403 when not friends | unit (TestClient + MagicMock db) | `pytest tests/test_auth_public_profile.py::test_public_profile_403 -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `cd blnd_backend && python -m pytest tests/test_auth_public_profile.py -x`
- **Per wave merge:** `cd blnd_backend && python -m pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `blnd_backend/tests/test_auth_public_profile.py` — covers API-01 through API-04 (happy path + 403 cases)
- [ ] Existing `conftest.py` fixtures (`mock_db`, `mock_openai_client`, `app_client`) should be reusable; verify they cover the new endpoints or extend as needed

## Sources

### Primary (HIGH confidence)
- `app/auth/views.py` — existing endpoint structure and decorator pattern
- `app/auth/schemas.py` — existing `UserResponse` shape; basis for `PublicProfileResponse` diff
- `app/auth/services.py` — existing service pattern; `get_profile()` as profile fetch reference
- `app/friends/models.py` — `Friendship` model with `status`, `requester_id`, `addressee_id`
- `app/friends/services.py` — bidirectional friendship query and friend-side resolution patterns
- `app/tracking/services.py` — `func.count()` scalar pattern, paginated JOIN query, `get_friends_who_watched()` friendship+join pattern
- `app/tracking/models.py` — `WatchedMovie` model fields
- `app/movies/models.py` — `Movie` model fields (title, poster_path, etc.)
- `app/groups/models.py` — `GroupMember` model; confirms `user_id` column for counting memberships
- `app/core/rate_limit.py` — `LIMIT_DEFAULT` and `limiter` constants
- `app/dependencies.py` — `get_current_user`, `get_db` dependency signatures
- `main.py` — router registration; confirms new endpoints stay under `auth_router` prefix `/auth`
- `.planning/STATE.md` — locked decisions: auth domain, PublicProfileResponse, func.count(), 403 gate
- `.planning/REQUIREMENTS.md` — API-01 through API-04 field specifications; Out of Scope table

### Secondary (MEDIUM confidence)
- `blnd_backend/pyproject.toml` — pytest configuration (testpaths, asyncio_mode)
- Bytecode inspection of `tests/__pycache__/conftest.cpython-314.pyc` — fixture names: `mock_db`, `mock_openai_client`, `mock_rebuild_taste_profile`, `app_client`

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already installed and in use
- Architecture: HIGH — all patterns directly derived from existing production code
- Pitfalls: HIGH — bidirectional friendship, func.count() None coercion, and route ordering verified in existing code
- Blends count source: MEDIUM — GroupMember is the correct model but `create_group()` adding creator as GroupMember needs implementation-time verification

**Research date:** 2026-03-12
**Valid until:** 2026-04-12 (stable stack, no fast-moving dependencies)
