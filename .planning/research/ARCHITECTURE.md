# Architecture Research

**Domain:** Public user profile endpoints + FriendProfileView revamp (v1.2)
**Researched:** 2026-03-11
**Confidence:** HIGH — based entirely on direct codebase inspection, no inference required

---

## Context: What Already Exists

This document focuses on how the NEW v1.2 features slot into the existing architecture. It is not a general system overview — it is a precise integration map.

Existing patterns that all new code must follow:

- **Backend domain layout:** `app/{domain}/models.py`, `schemas.py`, `services.py`, `views.py`
- **Auth guard:** `user_id: str = Depends(get_current_user)` on every authenticated endpoint
- **Paginated response shape:** `{"results": [...], "total": int}` — matches existing `WatchHistoryResponse`
- **Services return dicts** (not model instances) via a `_to_response()` helper — see `tracking/services.py`
- **Router registration:** all routers added to `main.py` via `include_router()` with a prefix
- **iOS API layer:** static enum per domain (`FriendsAPI`, `TrackingAPI`, etc.) calling `APIClient.shared.request()`
- **iOS models:** `Codable` structs with `CodingKeys` for snake_case to camelCase mapping
- **iOS views:** own local `@State` for remote data, no shared observable for view-local concerns

---

## System Overview

### What is being added

Three new read-only backend endpoints (under the existing `auth` domain), three new iOS API calls (new `ProfileAPI` enum), three new iOS model types, and a full revamp of `FriendProfileView.swift`.

```
┌──────────────────────────────────── iOS App ────────────────────────────────────────┐
│                                                                                       │
│  Views/Friends/                  Networking/              Models/                     │
│  ┌─────────────────────┐         ┌─────────────┐          ┌─────────────────────┐    │
│  │ FriendProfileView   │         │ ProfileAPI  │          │ ProfileModels       │    │
│  │ (REVAMPED)          │─ async ─│ (NEW)       │          │ (NEW)               │    │
│  │  @State profile     │         │ static enum │          │ PublicProfileResponse│    │
│  │  @State watched[]   │         │ 3 endpoints │          │ PublicWatchedResponse│    │
│  │  @State friends[]   │         └──────┬──────┘          │ PublicFriendsResponse│    │
│  │  stats row          │                │                  └─────────────────────┘    │
│  │  poster grid        │                │                                              │
│  │  friends list       │         ┌──────┴──────┐                                      │
│  └─────────────────────┘         │ APIClient   │                                      │
│                                   │ (UNCHANGED) │                                      │
│                                   └──────┬──────┘                                      │
└──────────────────────────────────────────┼──────────────────────────────────────────┘
                                           │ GET /auth/users/{id}/profile
                                           │ GET /auth/users/{id}/watched
                                           │ GET /auth/users/{id}/friends
                                           │ Authorization: Bearer <token>
                                           v
┌─────────────────────────────── FastAPI Backend ──────────────────────────────────────┐
│                                                                                        │
│  app/auth/                                                                             │
│  ┌────────────────────────────────────────────────────────────────────────────────┐   │
│  │ views.py (MODIFIED — 3 new endpoints)                                           │   │
│  │  GET /users/{user_id}/profile  →  services.get_public_profile(uid, db)         │   │
│  │  GET /users/{user_id}/watched  →  services.get_public_watched(uid, lim, off, db)│  │
│  │  GET /users/{user_id}/friends  →  services.get_public_friends(uid, lim, off, db)│  │
│  └──────────────────────────────────────┬──────────────────────────────────────────┘  │
│                                          │ SQLAlchemy queries                          │
│                     ┌────────────────────┼────────────────────┐                       │
│                     v                    v                      v                      │
│              profiles table    watched_movies JOIN     friendships JOIN                │
│              + COUNT queries   movies table            profiles table                  │
│              (watched,         (paginated,             (paginated,                     │
│               friends,          ORDER BY               status='accepted')              │
│               groups)           watched_date DESC)                                     │
│                                                                                        │
│  app/auth/services.py (MODIFIED — 3 new functions)                                    │
│  app/auth/schemas.py  (MODIFIED — 3 new response types)                               │
│                                                                                        │
│  All other domains: UNCHANGED                                                          │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## New Components Required

### Backend: 3 new endpoints added to the existing `auth` domain

No new domain folder. The three endpoints are pure reads against existing tables and belong in `app/auth/` alongside `GET /auth/me` — which is where all user/profile concerns already live. The existing precedent is `GET /auth/users/search`, which is also a user-lookup endpoint in `app/auth/views.py`.

**Endpoint signatures:**

| Method | Path | Auth | Service call |
|---|---|---|---|
| `GET` | `/auth/users/{user_id}/profile` | JWT required | `get_public_profile(user_id, db)` |
| `GET` | `/auth/users/{user_id}/watched` | JWT required | `get_public_watched(user_id, limit, offset, db)` |
| `GET` | `/auth/users/{user_id}/friends` | JWT required | `get_public_friends(user_id, limit, offset, db)` |

All three require a valid JWT. The caller's identity is verified but not used for access control — any authenticated user can view any profile. If friend-gating is added later, the service layer is the correct place for the check: one `is_friends(caller_id, target_id, db)` guard, zero iOS changes.

**New schemas to add to `app/auth/schemas.py`:**

```python
from app.tracking.schemas import WatchedMovieResponse   # reuse
from app.friends.schemas import FriendResponse          # reuse

class PublicProfileResponse(BaseModel):
    id: str
    username: str
    display_name: str | None = None
    avatar_url: str | None = None
    taste_bio: str | None = None
    watched_count: int
    friends_count: int
    groups_count: int

class PublicWatchedResponse(BaseModel):
    results: list[WatchedMovieResponse]
    total: int

class PublicFriendsResponse(BaseModel):
    results: list[FriendResponse]
    total: int
```

`WatchedMovieResponse` and `FriendResponse` are already defined and match what the iOS views need — no duplication.

**New service functions to add to `app/auth/services.py`:**

```python
def get_public_profile(user_id: str, db: Session) -> dict | None:
    """Profile row + stat counts — three COUNT queries against existing tables."""
    profile = db.query(Profile).filter(Profile.id == user_id).first()
    if not profile:
        return None

    from sqlalchemy import func, or_
    from app.tracking.models import WatchedMovie
    from app.friends.models import Friendship
    from app.groups.models import GroupMember

    watched_count = (
        db.query(func.count(WatchedMovie.id))
        .filter(WatchedMovie.user_id == user_id)
        .scalar() or 0
    )
    friends_count = (
        db.query(func.count(Friendship.id))
        .filter(
            Friendship.status == "accepted",
            or_(Friendship.requester_id == user_id, Friendship.addressee_id == user_id),
        )
        .scalar() or 0
    )
    groups_count = (
        db.query(func.count(GroupMember.group_id))
        .filter(GroupMember.user_id == user_id)
        .scalar() or 0
    )

    return {
        "id": str(profile.id),
        "username": profile.username,
        "display_name": profile.display_name,
        "avatar_url": profile.avatar_url,
        "taste_bio": profile.taste_bio,
        "watched_count": watched_count,
        "friends_count": friends_count,
        "groups_count": groups_count,
    }
```

The cross-domain imports (`Friendship` from `app.friends.models`, `GroupMember` from `app.groups.models`, `WatchedMovie` from `app.tracking.models`) follow the existing pattern — `tracking/services.py` already imports `Friendship` and `Profile`, and `groups/services.py` already imports `WatchedMovie`.

`get_public_watched` is a direct copy of `tracking/services.get_watch_history` with the `user_id` as a parameter rather than the caller's identity. `get_public_friends` is a copy of `friends/services.get_friends` with pagination added. Do not call those service functions directly — they enforce ownership semantics via the `get_current_user` dependency at the view layer.

---

### iOS: 1 new API file + 1 new models file + 1 modified view

**New file: `Networking/ProfileAPI.swift`**

Follows the same static enum pattern as `FriendsAPI.swift`:

```swift
enum ProfileAPI {
    /// GET /auth/users/{user_id}/profile
    static func getPublicProfile(userId: String) async throws -> PublicProfileResponse {
        try await APIClient.shared.request(
            endpoint: "/auth/users/\(userId)/profile",
            authenticated: true
        )
    }

    /// GET /auth/users/{user_id}/watched
    static func getPublicWatched(
        userId: String,
        limit: Int = 50,
        offset: Int = 0
    ) async throws -> PublicWatchedResponse {
        try await APIClient.shared.request(
            endpoint: "/auth/users/\(userId)/watched?limit=\(limit)&offset=\(offset)",
            authenticated: true
        )
    }

    /// GET /auth/users/{user_id}/friends
    static func getPublicFriends(
        userId: String,
        limit: Int = 20,
        offset: Int = 0
    ) async throws -> PublicFriendsResponse {
        try await APIClient.shared.request(
            endpoint: "/auth/users/\(userId)/friends?limit=\(limit)&offset=\(offset)",
            authenticated: true
        )
    }
}
```

**New file: `Models/ProfileModels.swift`**

```swift
struct PublicProfileResponse: Decodable {
    let id: String
    let username: String
    let displayName: String?
    let avatarUrl: String?
    let tasteBio: String?
    let watchedCount: Int
    let friendsCount: Int
    let groupsCount: Int

    enum CodingKeys: String, CodingKey {
        case id, username
        case displayName = "display_name"
        case avatarUrl = "avatar_url"
        case tasteBio = "taste_bio"
        case watchedCount = "watched_count"
        case friendsCount = "friends_count"
        case groupsCount = "groups_count"
    }
}

struct PublicWatchedResponse: Decodable {
    let results: [WatchedMovieResponse]   // from TrackingModels.swift
    let total: Int
}

struct PublicFriendsResponse: Decodable {
    let results: [FriendResponse]          // from FriendModels.swift
    let total: Int
}
```

**Modified file: `Views/Friends/FriendProfileView.swift`** — full revamp

Current state: takes `FriendResponse` (which carries `id`, `username`, `displayName`, `avatarUrl`, `friendshipId`), shows avatar + name + remove-friend button. Nothing else.

After revamp, `FriendProfileView` mirrors the structure of `ProfileView.swift`:

- `@State private var profile: PublicProfileResponse?` — loaded via `ProfileAPI.getPublicProfile`
- `@State private var watchedMovies: [WatchedMovieResponse] = []` — loaded via `ProfileAPI.getPublicWatched`
- `@State private var friends: [FriendResponse] = []` — loaded via `ProfileAPI.getPublicFriends`
- Stats row showing `profile.watchedCount`, `profile.friendsCount`, `profile.groupsCount`
- Watched poster grid (copy `posterTile` and `LazyVGrid` from `ProfileView.swift` — identical implementation)
- Tappable friends list that navigates to another `FriendProfileView` (SwiftUI `NavigationStack` handles recursive push depth natively)
- Remove-friend button remains in place

The `FriendResponse.id` field is already a `String` (UUID). It is used directly as the `userId` argument to all three `ProfileAPI` calls. No model changes to `FriendResponse` are needed.

---

## Data Flow

### Request Flow (Backend)

```
iOS FriendProfileView.task fires 3 parallel requests
    ↓
ProfileAPI.getPublicProfile(userId: friend.id)
ProfileAPI.getPublicWatched(userId: friend.id, limit: 50)
ProfileAPI.getPublicFriends(userId: friend.id, limit: 20)
    ↓
GET /auth/users/{user_id}/profile  [+2 more in parallel]
    ↓  Depends(get_current_user) — validates caller JWT
auth/views.py: get_public_profile_endpoint(user_id, current_user_id, db)
    ↓
auth/services.py: get_public_profile(user_id, db)
    ├─ SELECT profiles WHERE id = user_id
    ├─ COUNT watched_movies WHERE user_id = user_id
    ├─ COUNT friendships WHERE (req=user_id OR add=user_id) AND status='accepted'
    └─ COUNT group_members WHERE user_id = user_id
    ↓
PublicProfileResponse JSON → APIClient.decoder → PublicProfileResponse struct
    ↓
@State vars updated → SwiftUI re-render
```

### Parallel iOS Data Loading

```swift
// In FriendProfileView.task — matches ProfileView.swift pattern exactly
.task {
    async let profileLoad  = ProfileAPI.getPublicProfile(userId: friend.id)
    async let watchedLoad  = ProfileAPI.getPublicWatched(userId: friend.id, limit: 50)
    async let friendsLoad  = ProfileAPI.getPublicFriends(userId: friend.id, limit: 20)
    do {
        let (p, w, f) = try await (profileLoad, watchedLoad, friendsLoad)
        profile = p
        watchedMovies = w.results
        friends = f.results
    } catch is CancellationError {
        return
    } catch {
        print("[FriendProfileView] load error: \(error)")
    }
}
```

This is the same concurrent `async let` pattern used in `ProfileView.swift` lines 58-63.

---

## New vs Modified — Explicit Inventory

### NEW (create from scratch)

| File | Type | What it contains |
|---|---|---|
| `blnd_ios/blnd_ios/Networking/ProfileAPI.swift` | Swift enum | `getPublicProfile`, `getPublicWatched`, `getPublicFriends` |
| `blnd_ios/blnd_ios/Models/ProfileModels.swift` | Swift structs | `PublicProfileResponse`, `PublicWatchedResponse`, `PublicFriendsResponse` |

### MODIFIED (add to existing files)

| File | What changes |
|---|---|
| `blnd_backend/app/auth/views.py` | Add 3 new `@router.get` endpoints: `/users/{user_id}/profile`, `/users/{user_id}/watched`, `/users/{user_id}/friends` |
| `blnd_backend/app/auth/services.py` | Add 3 new functions: `get_public_profile`, `get_public_watched`, `get_public_friends` |
| `blnd_backend/app/auth/schemas.py` | Add 3 new response schemas: `PublicProfileResponse`, `PublicWatchedResponse`, `PublicFriendsResponse` |
| `blnd_ios/blnd_ios/Views/Friends/FriendProfileView.swift` | Full revamp — add loading state, `@State` vars, stats row, poster grid, friends list |

### UNCHANGED (zero modification needed)

| File | Why |
|---|---|
| `blnd_backend/main.py` | `auth_router` already registered at `/auth` prefix; new endpoints live there automatically |
| `blnd_backend/app/auth/models.py` | No schema changes — reads existing `profiles` table only |
| `blnd_backend/app/friends/schemas.py` | `FriendResponse` reused as-is in `PublicFriendsResponse` |
| `blnd_backend/app/tracking/schemas.py` | `WatchedMovieResponse` reused as-is in `PublicWatchedResponse` |
| `blnd_backend/app/friends/services.py` | Logic is copied, not called |
| `blnd_backend/app/tracking/services.py` | Logic is copied, not called |
| `blnd_ios/blnd_ios/Networking/FriendsAPI.swift` | No new friends endpoints needed |
| `blnd_ios/blnd_ios/Networking/APIClient.swift` | No changes — `request<T>()` already handles all three new calls |
| `blnd_ios/blnd_ios/Models/FriendModels.swift` | `FriendResponse.id` already present and is a `String` (UUID) |
| `blnd_ios/blnd_ios/Models/TrackingModels.swift` | `WatchedMovieResponse` already Decodable, reused in `PublicWatchedResponse` |
| `blnd_ios/blnd_ios/Views/Friends/FriendsListView.swift` | Navigation push to `FriendProfileView` already wired |
| Database schema | No migrations — reads existing tables: `profiles`, `watched_movies`, `friendships`, `group_members` |

---

## URL Design Decision

**Option A: Under `/auth/` prefix (chosen)**
```
GET /auth/users/{user_id}/profile
GET /auth/users/{user_id}/watched
GET /auth/users/{user_id}/friends
```
- Requires zero changes to `main.py`
- Consistent with existing `/auth/users/search`
- Auth domain owns all user/profile concerns

**Option B: New `/users/` prefix**
```
GET /users/{user_id}/profile
GET /users/{user_id}/watched
GET /users/{user_id}/friends
```
- Cleaner REST semantics
- Requires a new router and `include_router()` call in `main.py` (or a new domain folder)
- More work for no functional benefit at this scale

**Decision: Option A.** The existing `/auth/users/search` precedent makes `/auth/users/{user_id}/...` the consistent choice. No `main.py` changes required.

---

## Suggested Build Order

Dependencies flow backend-first: the iOS view cannot load data until the endpoints exist. Within each tier, steps can be parallelized.

### Step 1 — Backend schemas (prerequisite for steps 2 and 3)

Add `PublicProfileResponse`, `PublicWatchedResponse`, `PublicFriendsResponse` to `app/auth/schemas.py`.
Import `WatchedMovieResponse` from `app.tracking.schemas` and `FriendResponse` from `app.friends.schemas`.
No moving parts — pure Pydantic class additions.

### Step 2 — Backend services

Add `get_public_profile`, `get_public_watched`, `get_public_friends` to `app/auth/services.py`.
Start with `get_public_profile` (highest value — gates whether the stats row renders).
Verify each with a direct Python/SQLAlchemy call before wiring to views.

### Step 3 — Backend views

Add the three `@router.get` endpoints to `app/auth/views.py`.
Verify via `curl -H "Authorization: Bearer <token>" localhost:8000/auth/users/<uid>/profile`.

### Step 4 — iOS models (no backend dependency)

Create `Models/ProfileModels.swift` with the three `Decodable` structs.
Can be done in parallel with steps 1-3.

### Step 5 — iOS API layer

Create `Networking/ProfileAPI.swift`. Can be tested via Swift REPL or debug print against a running backend.

### Step 6 — iOS FriendProfileView revamp

Replace the current minimal view. Build incrementally:

1. Add `.task` loading block with the three parallel `ProfileAPI` calls
2. Wire stats row from `profile.watchedCount / friendsCount / groupsCount`
3. Add watched poster grid (copy `posterTile` and `LazyVGrid` from `ProfileView.swift`)
4. Add friends list section with `NavigationLink` to nested `FriendProfileView`

The remove-friend button already works and should not be touched until the end.

---

## Architecture Constraints

**No pagination UI in v1.2.** Load 50 watched and 20 friends in a single `.task` call. This matches `ProfileView.swift`'s approach (`TrackingAPI.getWatchHistory(limit: 50)`). Infinite scroll is out of scope.

**Stat counts are computed at read time, not stored.** The `profiles` table has no `watched_count` column. Three COUNT queries run on every `GET /auth/users/{id}/profile` call. This is consistent with how `ProfileView.swift` currently loads stats (it calls `FriendsAPI.listFriends()` and counts `.friends.count` client-side). The new endpoint consolidates all three counts server-side to reduce iOS round-trips from 3 to 1.

**`FriendResponse.id` is already a `String` (UUID).** No model changes needed — this field is passed directly to `ProfileAPI` calls.

**No friend-of-friend access control.** Endpoints return data for any valid `user_id`. If privacy gating is needed later, add one `is_friends(caller_id, target_id, db)` check to the service and raise `HTTPException(403)`. Zero iOS changes required.

**`FriendProfileView` passes `FriendResponse` as its init argument — this stays.** The view receives a `FriendResponse` (containing `id`) from the friends list. The `PublicProfileResponse` is loaded on demand inside the view. Do not change the init signature; it would break `FriendsListView` navigation.

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: New domain folder for public profile reads

**What people do:** Create `app/profile/` with `models.py`, `schemas.py`, `services.py`, `views.py` for three read-only endpoints.

**Why it's wrong:** The data lives in tables already owned by `auth`, `tracking`, `friends`, `groups`. A new domain adds a layer with no new model or distinct business concern. The existing `/auth/users/search` already establishes that user-lookup endpoints belong in `auth`.

**Do this instead:** Add the three endpoints, services, and schemas directly to the existing `auth` domain.

### Anti-Pattern 2: Calling existing service functions directly from the new services

**What people do:** Call `tracking.services.get_watch_history(user_id, limit, offset, db)` or `friends.services.get_friends(user_id, db)` from the new auth services to avoid code duplication.

**Why it's wrong:** `get_watch_history` returns data scoped to the calling user — the function has no concept of "target user" vs "caller". `get_friends` returns an unpaginated list. Calling them from `get_public_watched`/`get_public_friends` would silently return wrong data (the caller's history instead of the target's) or miss pagination support.

**Do this instead:** Copy the query logic into new service functions (`get_public_watched`, `get_public_friends`) with the correct `user_id` parameterization and pagination.

### Anti-Pattern 3: Separate `@Observable` state for friend profile data

**What people do:** Create `FriendProfileState: Observable` to hold watched movies and profile data, inject via `.environment()`.

**Why it's wrong:** `FriendProfileView` is a leaf view pushed onto the nav stack. Its data does not survive outside that view's lifetime. The entire iOS app uses local `@State` for view-local data; `@Observable` state is only used for cross-view concerns (`AuthState`, `TabState`). Creating an observable for leaf-view data would either require instantiating and injecting it for every friend that could be tapped, or sharing mutable state across concurrent friend profile views.

**Do this instead:** `@State private var` properties inside `FriendProfileView`, loaded in `.task` — exactly as `ProfileView.swift` does.

### Anti-Pattern 4: Duplicating `WatchedMovieResponse` or `FriendResponse`

**What people do:** Define new `PublicWatchedMovieResponse` or `PublicFriendEntryResponse` structs that are near-identical copies of the existing ones, "to keep domains separate."

**Why it's wrong:** The iOS models use a flat `Models/` folder — they are not domain-namespaced. The backend already imports schemas cross-domain (`tracking/services.py` imports `Profile`, `groups/services.py` imports `WatchedMovie`). Duplication creates maintenance burden for no isolation benefit.

**Do this instead:** Import and reuse `WatchedMovieResponse` from `app.tracking.schemas` and `FriendResponse` from `app.friends.schemas`.

### Anti-Pattern 5: Changing `FriendProfileView`'s init signature

**What people do:** Refactor `FriendProfileView` to accept a `userId: String` instead of `FriendResponse`, since the view now loads its own data.

**Why it's wrong:** `FriendsListView` passes a `FriendResponse` to `FriendProfileView` via `NavigationLink`. The `FriendResponse` carries `friendshipId` which is needed for the remove-friend action. Changing the init to `userId: String` would require either a second API call to get the `friendshipId`, or passing both separately. Neither is simpler than the current shape.

**Do this instead:** Keep `let friend: FriendResponse` as the init argument. Use `friend.id` for `ProfileAPI` calls and `friend.friendshipId` for the remove action.

---

## Integration Points

| Boundary | Communication | Notes |
|---|---|---|
| `auth/views.py` new endpoints → `auth/services.py` new functions | Direct function call | Standard FastAPI service-view split |
| `auth/services.py` → `tracking.models.WatchedMovie` | SQLAlchemy query on shared DB | Cross-domain model import — established pattern in codebase |
| `auth/services.py` → `friends.models.Friendship` | SQLAlchemy query on shared DB | Same pattern |
| `auth/services.py` → `groups.models.GroupMember` | SQLAlchemy query on shared DB | Same pattern |
| `auth/schemas.py` → `tracking.schemas.WatchedMovieResponse` | Python import | Reuse existing type |
| `auth/schemas.py` → `friends.schemas.FriendResponse` | Python import | Reuse existing type |
| iOS `ProfileAPI` → `APIClient.shared` | Same `request<T>()` call as every other iOS API enum | No changes to `APIClient` |
| iOS `FriendProfileView` → `FriendProfileView` (recursive) | `NavigationLink` inside the friends list section | SwiftUI `NavigationStack` handles arbitrary push depth |
| iOS `ProfileModels.PublicWatchedResponse.results` → `WatchedMovieResponse` | Type reuse across model files | Swift module visibility — both in `Models/` folder, no import needed |

---

## Sources

- Direct codebase inspection — `app/auth/views.py`: confirmed existing `GET /users/search` at `/auth` prefix, `Depends(get_current_user)` pattern, `@limiter.limit(LIMIT_DEFAULT)` decorator
- Direct codebase inspection — `app/auth/services.py`: confirmed `get_profile(user_id, db)` pattern — same structure as the new `get_public_profile`
- Direct codebase inspection — `app/auth/schemas.py`: confirmed `UserResponse` — `PublicProfileResponse` follows same structure
- Direct codebase inspection — `app/tracking/services.py`: confirmed `get_watch_history` paginated query pattern and `_to_response()` convention
- Direct codebase inspection — `app/friends/services.py`: confirmed `get_friends(user_id, db)` accepts-both-directions friendship query
- Direct codebase inspection — `app/groups/services.py`: confirmed `GroupMember` cross-domain import from `tracking.models` (established precedent)
- Direct codebase inspection — `blnd_ios/blnd_ios/Views/Profile/ProfileView.swift`: confirmed `async let` parallel loading pattern (lines 58-63), `statItem()`, `posterTile()`, `LazyVGrid` — all directly reusable
- Direct codebase inspection — `blnd_ios/blnd_ios/Views/Friends/FriendProfileView.swift`: confirmed current minimal state, `FriendResponse` init argument, `friend.friendshipId` usage
- Direct codebase inspection — `blnd_ios/blnd_ios/Models/FriendModels.swift`: confirmed `FriendResponse.id: String` field present
- Direct codebase inspection — `blnd_ios/blnd_ios/Networking/FriendsAPI.swift`: confirmed static enum pattern — `ProfileAPI` follows same structure
- Direct codebase inspection — `main.py`: confirmed `auth_router` registered at `/auth` prefix — no changes needed

---

*Architecture research for: BLND v1.2 public profile endpoints + FriendProfileView revamp*
*Researched: 2026-03-11*
