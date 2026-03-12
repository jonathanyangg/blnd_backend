# Stack Research

**Domain:** Public user profile API endpoints + iOS FriendProfileView revamp (v1.2)
**Researched:** 2026-03-11
**Confidence:** HIGH

---

## Context: What This Covers

This is the v1.2 milestone research. The existing stack (FastAPI 0.135.1,
SQLAlchemy 2.0.47, SwiftUI iOS 17+, `@Observable`, `APIClient` singleton,
zero third-party deps) is already validated and is not repeated here.

This file covers only what is NEW for v1.2:

1. Backend: three new public-profile endpoints under `/auth/users/{user_id}/`
2. iOS: `FriendProfileView` revamp with stats row, watched grid, tappable friends list

**Key finding up front:** No new libraries are required on either platform.
Every capability needed already exists in the codebase. This milestone is
pure schema + service logic additions wired to existing patterns.

---

## Summary: No New Libraries Required

All three backend endpoints use existing SQLAlchemy models, existing Pydantic
patterns, and the existing rate limiting decorator. The iOS revamp reuses
components already built for `ProfileView` — `LazyVGrid`, `AsyncImage` poster
tiles, `AvatarView`, `statItem`. No new Swift Package Manager dependencies.

---

## Backend

### Core Technologies (No Changes)

| Technology | Version (pinned) | Role | Status for v1.2 |
|------------|-----------------|------|-----------------|
| FastAPI | 0.135.1 | HTTP router | Add 3 routes to existing `auth_router` in `auth/views.py` |
| SQLAlchemy | 2.0.47 | ORM queries | Existing `Profile`, `Friendship`, `WatchedMovie`, `GroupMember` models cover all needed joins — no new models |
| Pydantic | 2.12.5 | Schemas | Add 3 new response schemas to `auth/schemas.py` using `BaseModel` subclassing |
| slowapi | 0.1.9 | Rate limiting | Apply `@limiter.limit(LIMIT_DEFAULT)` to all three new endpoints unchanged |
| psycopg2-binary | 2.9.11 | Postgres driver | No change |

### New Backend Work: Schema + Service Logic Only

The three new endpoints live in the `auth` domain — they expose other users'
profile data, consistent with the existing `/auth/users/search` endpoint:

```
GET /auth/users/{user_id}/profile   → PublicProfileResponse
GET /auth/users/{user_id}/watched   → PublicWatchHistoryResponse  (paginated)
GET /auth/users/{user_id}/friends   → PublicFriendsResponse
```

Every query pattern already exists in the codebase:

| Query Need | Where the Pattern Lives |
|------------|------------------------|
| Profile lookup by UUID | `auth/services.py` `get_profile(user_id, db)` |
| Watched count | `tracking/services.py` — `db.query(WatchedMovie).filter(WatchedMovie.user_id == id).count()` |
| Paginated watched list | `tracking/views.py` `GET /tracking/` — `limit`/`offset` Query params + `WatchHistoryResponse` shape |
| Friends count | `friends/services.py` `get_friends()` — `or_(requester_id == id, addressee_id == id)` + status filter |
| Friends list by arbitrary user ID | `friends/services.py` `get_friends(user_id, db)` — already accepts any user_id string |
| Groups count | `groups/models.py` `GroupMember` — `db.query(GroupMember).filter(GroupMember.user_id == id).count()` |

No new SQLAlchemy relationships. No new migrations. No new tables. Counts are
query-time aggregations — no materialized columns needed at current scale.

### New Pydantic Schemas (auth/schemas.py additions)

```python
class PublicProfileResponse(BaseModel):
    id: str
    username: str
    display_name: str | None = None
    avatar_url: str | None = None
    watched_count: int
    friends_count: int
    groups_count: int

class PublicWatchHistoryResponse(BaseModel):
    results: list[WatchedMovieResponse]  # reuse existing schema from tracking
    total: int

class PublicFriendsResponse(BaseModel):
    friends: list[FriendResponse]  # reuse existing schema from friends
```

`PublicProfileResponse` mirrors `UserResponse` but omits private fields
(`taste_bio`, `favorite_genres`) and adds computed stat counts.
`PublicWatchHistoryResponse` and `PublicFriendsResponse` mirror the existing
`WatchHistoryResponse` and `FriendListResponse` shapes — they may be type
aliases or identical copies depending on import structure.

### Endpoint Placement

Register on the existing `auth_router`. No new router file, no new `main.py`
registration:

```python
# auth/views.py — add after /users/search
@router.get("/users/{user_id}/profile", response_model=schemas.PublicProfileResponse)
@limiter.limit(LIMIT_DEFAULT)
async def get_user_profile(
    request: Request,
    user_id: str,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
): ...

@router.get("/users/{user_id}/watched", response_model=schemas.PublicWatchHistoryResponse)
@limiter.limit(LIMIT_DEFAULT)
async def get_user_watched(
    request: Request,
    user_id: str,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
): ...

@router.get("/users/{user_id}/friends", response_model=schemas.PublicFriendsResponse)
@limiter.limit(LIMIT_DEFAULT)
async def get_user_friends(
    request: Request,
    user_id: str,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
): ...
```

All three require JWT auth via `get_current_user` — public in the sense that
any authenticated user can view any other user's profile. No friend-gating.

---

## iOS

### Core Technologies (No Changes)

| Technology | Role | Status for v1.2 |
|------------|------|-----------------|
| SwiftUI (iOS 17+) | UI framework | `FriendProfileView` revamp is pure SwiftUI |
| `@Observable` / `@State` | State management | Same local `@State` pattern as `ProfileView` |
| `async/await` + `APIClient` | Networking | New methods on `FriendsAPI` static enum, same call style |
| `AsyncImage` | Remote poster images | Already in `ProfileView.posterTile()` — copy directly |
| `LazyVGrid` | Poster grid layout | Already in `ProfileView` with 3-column config |
| `AvatarView` | Avatar rendering | Already accepts optional `url:` param |
| `NavigationLink` | Poster tap → MovieDetailView | Same pattern as `ProfileView.watchedGrid` |

Zero new Swift Package Manager dependencies.

### New iOS Work

**New model in `FriendModels.swift`:**

```swift
struct PublicProfileResponse: Decodable {
    let id: String
    let username: String
    let displayName: String?
    let avatarUrl: String?
    let watchedCount: Int
    let friendsCount: Int
    let groupsCount: Int

    enum CodingKeys: String, CodingKey {
        case id, username
        case displayName = "display_name"
        case avatarUrl = "avatar_url"
        case watchedCount = "watched_count"
        case friendsCount = "friends_count"
        case groupsCount = "groups_count"
    }
}
```

`WatchHistoryResponse` and `FriendListResponse` already exist in
`TrackingModels.swift` and `FriendModels.swift` — reuse directly.

**New API methods in `FriendsAPI.swift`:**

```swift
/// GET /auth/users/{userId}/profile
static func getPublicProfile(userId: String) async throws -> PublicProfileResponse

/// GET /auth/users/{userId}/watched
static func getUserWatched(userId: String, limit: Int = 50, offset: Int = 0) async throws -> WatchHistoryResponse

/// GET /auth/users/{userId}/friends
static func getUserFriends(userId: String) async throws -> FriendListResponse
```

**`FriendProfileView.swift` revamp:**

The view receives `FriendResponse` (already has `id`, `username`,
`displayName`, `avatarUrl`, `friendshipId`). On `.task`, it fires three
parallel async loads: profile stats, watched movies, friends list.

Key structural changes:
- Add `@State private var profile: PublicProfileResponse?` for stat counts
- Add `@State private var watchedMovies: [WatchedMovieResponse]` + loading flag
- Add `@State private var friends: [FriendResponse]` + loading flag
- Stats row: copy `ProfileView.statsRow` / `statItem()` verbatim, make all
  three stats non-tappable (this is someone else's profile, not nav-linked)
- Watched grid: copy `ProfileView.watchedGrid` + `posterTile()` verbatim,
  `NavigationLink` → `MovieDetailView(tmdbId:title:)` unchanged
- Friends list section: horizontal scroll row of `AvatarView` + username
  tapping into nested `FriendProfileView` push (only show mutual friends,
  or all — product decision at implementation time)
- Keep existing "Remove Friend" button at bottom of header section

No new shared components needed — all building blocks already exist.

---

## What NOT to Add

| Avoid | Why | Impact if Added |
|-------|-----|----------------|
| New FastAPI domain folder (`app/users/`) | Public profile is auth-domain scope — splitting creates a 3-endpoint domain with no business logic of its own | Adds folder structure complexity with zero benefit |
| New router registration in `main.py` | Endpoints go on existing `auth_router`; `/auth/users/{id}/` prefix is consistent with `/auth/users/search` | Inconsistent URL structure if added separately |
| `UserProfileState` (@Observable class for friend profile) | `FriendProfileView` is a leaf navigation screen with no cross-view state sharing — local `@State` is correct | Premature abstraction, adds indirection without benefit |
| Pagination on friends endpoint | Friend lists are bounded (social graph size); existing `GET /friends/` returns full list with no pagination — same pattern applies here | Complexity for no practical gain at current user count |
| Infinite scroll / load-more on watched grid | `ProfileView` uses `limit: 50` without load-more; parity is correct for v1.2 | Out of scope; defer to future milestone |
| New DB migration | All stat counts are query-time; no schema changes needed | Adds migration overhead for no schema change |
| `friendship_id` enforcement for profile access | Viewing someone's profile does not require being their friend; auth via JWT is sufficient | Unnecessarily restrictive — users should be able to look up profiles before friending |

---

## Integration Points Summary

| Integration | Details |
|-------------|---------|
| Backend endpoint prefix | `/auth/users/{user_id}/` — consistent with `/auth/users/search` |
| iOS model file | Add `PublicProfileResponse` to existing `FriendModels.swift` |
| iOS networking | Add 3 methods to existing `FriendsAPI.swift` enum |
| iOS view | Revamp `FriendProfileView.swift` in-place — same file, same init signature `(friend: FriendResponse)` |
| Reused schemas | `WatchedMovieResponse` from tracking, `FriendResponse` from friends — no copies needed |
| Reused UI components | `posterTile()`, `statItem()`, `AvatarView`, `LazyVGrid` config, `MovieDetailView` NavigationLink |

---

## Version Compatibility

All existing pinned versions are compatible. No version bumps needed.

| Package | Version | Compatible With New Work |
|---------|---------|--------------------------|
| fastapi | 0.135.1 | YES — standard APIRouter path param + Query param patterns |
| pydantic | 2.12.5 | YES — `BaseModel` subclassing for 3 new schemas |
| sqlalchemy | 2.0.47 | YES — existing ORM `filter().count()` and `filter().offset().limit().all()` patterns |
| iOS 17+ / Swift 5.9+ | system | YES — `@Observable`, `async/await`, `LazyVGrid`, `AsyncImage` all available |
| slowapi | 0.1.9 | YES — `@limiter.limit(LIMIT_DEFAULT)` decorator unchanged |

---

## Sources

- Codebase audit: `/Users/adamrose/Desktop/blnd/blnd_backend/app/` — HIGH confidence
  (direct inspection of `auth/`, `friends/`, `tracking/`, `groups/` services and schemas)
- Codebase audit: `/Users/adamrose/Desktop/blnd/blnd_ios/blnd_ios/` — HIGH confidence
  (direct inspection of `ProfileView.swift`, `FriendProfileView.swift`, `FriendModels.swift`,
  `FriendsAPI.swift`, `TrackingModels.swift`)
- `requirements.txt` — pinned versions verified from file — HIGH confidence
- `blnd_backend/CLAUDE.md` — domain-driven structure, conventions — HIGH confidence
- `blnd_ios/CLAUDE.md` — iOS architecture, conventions, zero third-party policy — HIGH confidence

---

*Stack research for: BLND v1.2 — public user profile endpoints + FriendProfileView revamp*
*Researched: 2026-03-11*
