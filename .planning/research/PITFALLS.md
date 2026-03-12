# Pitfalls Research

**Domain:** Public user profile endpoints + iOS FriendProfileView revamp (v1.2 milestone)
**Researched:** 2026-03-11
**Confidence:** HIGH (derived from direct inspection of existing codebase — backend services, models, iOS views — plus cross-referenced against FastAPI, SQLAlchemy, and SwiftUI known patterns)

---

## Critical Pitfalls

### Pitfall 1: Leaking Private Data Through Insufficiently Scoped "Public" Profile Endpoint

**What goes wrong:**
A new endpoint like `GET /users/{user_id}/profile` is intended to expose only public stats (watched count, friends count, groups count) but inadvertently returns fields from the `Profile` model that were never meant to be public. The existing `UserResponse` schema in `app/auth/schemas.py` includes `taste_bio`, `favorite_genres`, and would include `taste_embedding` if ever serialized. When the new service reuses `UserResponse` as its response schema, all these fields go out to any authenticated caller regardless of friendship status.

**Why it happens:**
The existing codebase has only one schema for a profile: `UserResponse`. It was designed for the authenticated user viewing their own profile (`GET /auth/me`). Building the new endpoint by reusing `UserResponse` for convenience is the obvious shortcut — it has username, display_name, avatar_url, and all required fields. The extra sensitive fields tag along silently.

**How to avoid:**
Create a dedicated `PublicProfileResponse` Pydantic schema in `app/auth/schemas.py` (or a new `app/profiles/` domain) that contains only the fields safe to expose publicly. At minimum, exclude `taste_bio` and `favorite_genres` from what any caller can see for another user, unless explicitly decided to expose them. Add the stats fields (`watched_count`, `friends_count`, `groups_count`) to this dedicated schema, not to `UserResponse`. Never reuse `UserResponse` for a public endpoint.

**Warning signs:**
- The new endpoint response includes `taste_bio` or `favorite_genres` in the JSON
- The Pydantic schema for the new endpoint is `UserResponse` or imports directly from it
- No new schema file or class was added for the v1.2 endpoint

**Phase to address:**
Backend public profile endpoint — schema design step, before writing any service logic.

---

### Pitfall 2: Missing Friendship Check Allows Any Authenticated User to Enumerate Any Other User's Watched Movies

**What goes wrong:**
The new `GET /users/{user_id}/watched` endpoint is meant to show a friend's watched movies. If the endpoint only validates that the caller is authenticated (JWT present) but does not verify a friendship relationship, any user can request any other user's complete watch history by guessing or iterating user IDs. The current app uses UUID user IDs which are hard to guess, but the `/auth/users/search` endpoint leaks UUIDs in its results, making enumeration trivial.

**Why it happens:**
The existing tracking endpoints only need `user_id = Depends(get_current_user)` for authorization because they always scope to the caller. When building the new endpoints, it is easy to carry over the same authorization pattern — "the caller is authenticated, that's enough" — without adding the friendship gate. The friends service already has the query to check friendship status (the bidirectional `or_` query in `friends/services.py`); it just isn't used in the new context.

**How to avoid:**
Every new endpoint that returns another user's data must run a friendship check before returning any data. Create a reusable helper:

```python
def assert_are_friends(viewer_id: str, target_id: str, db: Session) -> None:
    """Raise 403 if viewer and target do not have an accepted friendship."""
    friendship = (
        db.query(Friendship)
        .filter(
            Friendship.status == "accepted",
            or_(
                (Friendship.requester_id == viewer_id) & (Friendship.addressee_id == target_id),
                (Friendship.requester_id == target_id) & (Friendship.addressee_id == viewer_id),
            ),
        )
        .first()
    )
    if not friendship:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not friends")
```

Call this at the top of every service function that accesses another user's data. The correct HTTP status is 403 (not 404) — returning 404 leaks information about whether the user exists.

**Warning signs:**
- New service functions only call `get_current_user` for authorization
- The endpoint works with any `user_id` path parameter regardless of friendship status
- No `Friendship` model import in the new service file

**Phase to address:**
Backend public profile endpoint — authorization layer, first thing implemented in each service function.

---

### Pitfall 3: N+1 Query When Loading Friends Count (and Friends List) for a Profile

**What goes wrong:**
The new public profile stats endpoint needs three counts: watched movie count, friends count, and groups count. The existing `get_friends()` service in `app/friends/services.py` loads all `Friendship` rows then issues a separate `db.query(Profile)` per friendship to get each friend's profile. This pattern (lines 132–137 in services.py) is an N+1 query. On the public profile endpoint it triggers for every profile view. For a user with 50 friends, loading their profile issues 51 database queries. The stats endpoint only needs the count, not the profiles — but the temptation is to call `get_friends()` and take `len(result["friends"])`.

**Why it happens:**
The natural implementation for "how many friends does this user have?" is to call the existing `get_friends()` helper since it already exists. Its return value is a list, so `len(get_friends(user_id, db)["friends"])` feels correct. The N+1 is hidden inside the helper — it is not visible at the call site.

**How to avoid:**
Use `db.query(func.count(Friendship.id))` directly for the friends count query. Do not call `get_friends()` when only the count is needed:

```python
from sqlalchemy import func, or_

friends_count = (
    db.query(func.count(Friendship.id))
    .filter(
        Friendship.status == "accepted",
        or_(
            Friendship.requester_id == user_id,
            Friendship.addressee_id == user_id,
        ),
    )
    .scalar() or 0
)
```

Similarly, use `func.count(WatchedMovie.id)` for watched count and `func.count(GroupMember.group_id)` for groups count. All three counts can be fetched in a single service call with three separate scalar queries — three round trips versus 50+.

**Warning signs:**
- The stats service function calls `get_friends(user_id, db)` and takes the length of the result
- SQLAlchemy query logs show 50+ SELECT queries per profile view
- Profile view latency correlates with the friend's friends count, not with a fixed cost

**Phase to address:**
Backend public profile endpoint — service implementation step for the stats query.

---

### Pitfall 4: Exposing the Watched Movies Endpoint Without Pagination Causes Out-of-Memory Responses

**What goes wrong:**
The existing `GET /tracking/` (own watch history) is paginated with `limit` and `offset` query parameters. When building the new `GET /users/{user_id}/watched` endpoint, the pagination is sometimes omitted because "it's just a friend's profile, it doesn't need to be that careful." A user who imported 2,000 Letterboxd films has 2,000 watched entries. Fetching all 2,000 in a single response returns a multi-megabyte JSON payload to the iOS client, inflates memory usage, and makes the LazyVGrid scroll to build all 2,000 poster tiles simultaneously — defeating its lazy loading.

**Why it happens:**
Profile views in most apps show a poster grid that looks small in design comps (a few rows of posters). The scale of a Letterboxd user's watched history is not apparent during development when testing with a fresh account. The existing `get_watch_history()` service already accepts `limit` and `offset` — copying it without the pagination parameters is the omission.

**How to avoid:**
Mirror the existing `GET /tracking/` endpoint exactly: require `limit` (default 20, max 100) and `offset` query parameters. The iOS `FriendProfileView` grid should use `LazyVGrid` (as `ProfileView` already does) and trigger pagination when the user scrolls near the bottom. The backend response must include a `total` count so the iOS client knows when it has reached the end. Use the same `WatchHistoryResponse` schema shape (`results` + `total`) for consistency.

**Warning signs:**
- New endpoint has no `limit` or `offset` parameters
- Service function calls `db.query(WatchedMovie).filter(...).all()` without `.limit()`
- iOS client loads the full grid at once rather than incrementally

**Phase to address:**
Backend watched movies endpoint — endpoint signature design, before any service code is written.

---

### Pitfall 5: `FriendProfileView` Duplicates All of `ProfileView`'s UI Logic Instead of Extracting Shared Components

**What goes wrong:**
`ProfileView.swift` is 348 lines containing: avatar + name header, stats row with four stat items, tab picker, poster grid with `LazyVGrid`, poster tile renderer, empty state, and data loading functions. `FriendProfileView.swift` currently has 101 lines with only a header and Remove Friend button. Adding watched poster grid, stats row, and friends list to `FriendProfileView` by copy-pasting from `ProfileView` creates 600+ lines of duplicated SwiftUI code. When the design changes (e.g. stat tile font size, poster tile corner radius), both files need updating. The poster tile function is already 38 lines — duplicating it is immediately noticeable debt.

**Why it happens:**
SwiftUI views use private helper functions and computed view properties, which cannot be called from other structs. The temptation is to copy the working implementations from `ProfileView` rather than extracting them into shared components, because extraction requires refactoring existing, working code.

**How to avoid:**
Extract the following as shared `Views/Shared/` components before building `FriendProfileView`:
- `PosterTile(path: String?, rating: Double?) -> some View` — already 38 lines, very extractable
- `StatsRow(stats: [(value: String, label: String, action: (() -> Void)?)]) -> some View` — the stats row with dividers
- `PosterGrid(movies: [any PosterItem], isLoading: Bool, emptyMessage: String) -> some View`

`ProfileView` is then refactored to use these components, and `FriendProfileView` uses the same components with different data. This is required before building `FriendProfileView`, not after.

**Warning signs:**
- `FriendProfileView.swift` grows beyond 200 lines with private functions that match functions in `ProfileView.swift`
- The `posterTile(path:rating:)` function appears in both files
- `LazyVGrid` with three columns is defined in both files

**Phase to address:**
iOS FriendProfileView — component extraction step, before any new UI is added to `FriendProfileView`.

---

### Pitfall 6: Stats Loading in `FriendProfileView` Makes Three Sequential API Calls Instead of One

**What goes wrong:**
`ProfileView.loadCounts()` makes two sequential calls for friends and groups counts after loading watched movies. For `FriendProfileView`, the temptation is to build a similar pattern: call the public profile stats endpoint, then separately call the watched movies endpoint, then optionally call the friends list endpoint. If these are not concurrent, the view takes 3x the network round trip time to become interactive. On a typical mobile connection (100-200ms round trip), that is 300-600ms of stall before any content appears.

**Why it happens:**
SwiftUI data loading is often written procedurally: `await loadStats(); await loadWatched(); await loadFriends()`. Each `await` suspends until the previous call completes. `ProfileView` partially avoids this with `async let` parallelism, but the pattern is easy to miss.

**How to avoid:**
Use `async let` parallelism for all three fetches, exactly as `ProfileView` does in `.task`:
```swift
.task {
    async let stats: () = loadStats()
    async let watched: () = loadWatched()
    _ = await (stats, watched)
}
```
Keep the stats endpoint as a single endpoint that returns all three counts (watched, friends, groups) in one response — not three separate count endpoints. This reduces the minimum round trips to two (stats + first page of watched movies).

**Warning signs:**
- `loadStats()` and `loadWatched()` are called sequentially with `await` rather than `async let`
- The public stats endpoint returns only one count (e.g. watched count only) requiring multiple calls
- View appears blank for more than 200ms on a normal connection

**Phase to address:**
iOS FriendProfileView — data loading implementation, and backend stats endpoint design (single endpoint returning all counts).

---

### Pitfall 7: User Can Request Their Own Profile Through the "Other User" Endpoint — Edge Case Causes Subtle Bugs

**What goes wrong:**
`GET /users/{user_id}/watched` is called from `FriendProfileView` which is only reached via the friends list. However, nothing prevents a user from calling this endpoint with their own `user_id`. The friendship check (Pitfall 2) would fail (a user is not their own friend in the `friendships` table). The user gets a 403 on their own profile data. This is a minor bug but can surface in edge cases: if a user appears in their own friend search results (which the search endpoint already guards against), or if a deep link opens `FriendProfileView` for the current user.

**Why it happens:**
The authorization logic is written as "viewer must be friends with target," not "viewer must be friends with target OR viewer is target." The self-case is assumed to never reach the endpoint.

**How to avoid:**
Add an explicit self-check before the friendship check:
```python
if viewer_id == target_id:
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Use /tracking/ for your own watch history"
    )
```
On the iOS side, before navigating to `FriendProfileView`, check `friend.id != authState.currentUser?.id` and skip navigation if equal. This is a belt-and-suspenders defense.

**Warning signs:**
- Friendship check returns 403 when the user navigates to their own profile
- No guard against `user_id == current_user_id` in the service layer

**Phase to address:**
Backend public profile endpoint — service layer guards, after friendship check is implemented.

---

### Pitfall 8: iOS `FriendProfileView` Holds Stale Data After Remove Friend Action

**What goes wrong:**
`FriendProfileView` loads the friend's watched movies and stats on `.task`. After the user taps "Remove Friend" and the request succeeds, the view dismisses via `dismiss()`. However, the parent `FriendsListView` still shows the removed user in its friends list until it refreshes. If the user navigates back to the same profile row before the list refreshes, they re-enter `FriendProfileView` and attempt to load data for a user they are no longer friends with, causing a 403 error. The error state may show no data, a crash (if unhandled), or stale data from before the relationship ended.

**Why it happens:**
`FriendsListView` uses a static `@State` array loaded on `.task`. Dismissing `FriendProfileView` does not trigger a re-fetch in `FriendsListView`. There is no shared observable state between the two views — the existing codebase uses environment-level state sparingly.

**How to avoid:**
After successful friend removal in `FriendProfileView`, pass a callback or use `.onDisappear` in `FriendsListView` to trigger a re-fetch. The simplest approach is to add a `@State private var needsRefresh = false` flag and call `loadFriends()` in `.onAppear` (which fires when the navigation stack pops back):

```swift
// FriendsListView
.onAppear {
    Task { await loadFriends() }
}
```

This is idempotent because `loadFriends()` replaces the array — it doesn't append. Also add error handling in `FriendProfileView`'s data loading: if the watched movies endpoint returns 403, show a "No longer friends" empty state rather than a generic error.

**Warning signs:**
- Removed friend still appears in `FriendsListView` immediately after removal
- Re-entering a removed friend's profile shows data or crashes
- 403 from the watched movies endpoint is not handled gracefully in the iOS view

**Phase to address:**
iOS FriendProfileView — remove friend action and parent list refresh, after the watched grid is implemented.

---

### Pitfall 9: Backend `get_friends_for_profile` Reuses the N+1 Pattern from `get_friends()` for the Friend's Friends List

**What goes wrong:**
The friends list endpoint for a public profile (`GET /users/{user_id}/friends`) must return the target user's friends (so the viewer can see who their friend is friends with). The existing `get_friends(user_id, db)` service fetches all accepted friendships then issues a `db.query(Profile)` per friendship row (lines 132–137 in `friends/services.py`). This was acceptable when called once for the current user's own list. On a public profile view that could be called repeatedly as users browse profiles, it magnifies the N+1 cost and also runs the viewer's identity through an authorization check on every profile visit.

**Why it happens:**
`get_friends()` exists and is tested. Calling it for the target user's friends list (`get_friends(target_id, db)`) instead of the current user (`get_friends(current_user_id, db)`) seems like a one-line change. The N+1 problem and performance cost are the same — they just now affect a public endpoint.

**How to avoid:**
Use a JOIN query to load friends and their profiles in a single database round trip:
```python
from sqlalchemy.orm import aliased

friend_profile = aliased(Profile)
rows = (
    db.query(friend_profile)
    .join(
        Friendship,
        or_(
            (Friendship.requester_id == target_id) & (Friendship.addressee_id == friend_profile.id),
            (Friendship.addressee_id == target_id) & (Friendship.requester_id == friend_profile.id),
        ),
    )
    .filter(Friendship.status == "accepted")
    .all()
)
```
This returns all friend profiles in one query. The existing `get_friends()` should also be refactored to use this pattern (it is a pre-existing debt), but the new public endpoint must not inherit the old pattern.

**Warning signs:**
- The new friends-of-friend service calls `get_friends(target_id, db)` directly
- SQLAlchemy logs show SELECT queries proportional to friend count on a single profile view
- Profiling shows profile page latency scales linearly with the target user's friend count

**Phase to address:**
Backend friends list endpoint — before any iOS integration. Fix the N+1 at the service layer first.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Reuse `UserResponse` schema for public profile | One less Pydantic class | Leaks `taste_bio`, `favorite_genres` to any authenticated caller | Never — create a dedicated `PublicProfileResponse` |
| Call `get_friends(user_id, db)` for counts | No new query code | N+1 query: 1 + N DB round trips for N friends | Never — use `func.count()` scalar |
| Copy `posterTile` + grid code into `FriendProfileView` | Faster to ship | Duplicated 38-line function; design changes require dual maintenance | Acceptable only as a temporary spike; must extract before merging |
| Skip friendship check on watched movies endpoint | Simpler service | Any authenticated user can read any user's watch history | Never — friendship gate is required |
| Single endpoint returning full list (no pagination) for watched | Simpler iOS client | Out-of-memory for Letterboxd users with 2000+ films | Never — paginate all watched movie endpoints |
| Load stats and watched sequentially (not `async let`) | Simpler code | 2-3x view load time | Acceptable only in prototype; must parallelize before shipping |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| FastAPI + SQLAlchemy friendship check | Query Friendship by single field (only `requester_id == viewer`) | Always query both directions: `or_((requester == A) & (addressee == B), (requester == B) & (addressee == A))` |
| Pydantic response schema reuse | Use `UserResponse` for public endpoint | Define `PublicProfileResponse` with only safe fields; never expose `taste_embedding` |
| SwiftUI `NavigationLink` to `FriendProfileView` | Pass `FriendResponse` (basic model) and fetch everything inside | Pass `userId` and `username` only; the view fetches enriched data itself |
| `FriendProfileView` model type | Use `FriendResponse` as the view's data model after enrichment | Define a separate `FriendProfileData` struct that holds stats + watched movies; don't expand `FriendResponse` |
| iOS `async let` vs sequential `await` | Sequential `await loadStats(); await loadWatched()` | `async let s: () = loadStats(); async let w: () = loadWatched(); _ = await (s, w)` |
| Backend route ordering in FastAPI | `/users/{user_id}/profile` conflicts with `/users/me` if added later | Register `/users/me` before `/users/{user_id}` — FastAPI matches routes top-down |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| N+1 friends count via `get_friends()` | Profile view latency scales with target user's friend count | Use `func.count(Friendship.id)` scalar query | Any user with >10 friends (50 DB calls for 50 friends) |
| Unpaginated watched movies endpoint | Multi-MB JSON response; iOS scrolling jank | `limit`/`offset` on all watched movie endpoints | Any Letterboxd user (2000+ entries = ~500KB+ JSON) |
| Sequential stats + watched API calls in iOS | 400-600ms blank view on normal connection | `async let` parallelism for all initial fetches | Every profile view on any real network |
| Loading full friends list for a friend's profile page | N+1 + large response for users with many friends | Use JOIN query; paginate if >20 friends shown | Users with >20 friends (most active users) |
| `LazyVGrid` with non-lazy data source | All poster tiles render on view appear, not on scroll | Ensure `watchedMovies` is populated incrementally from a paginated endpoint | Letterboxd users (50+ posters visible at once defeats lazy loading) |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| No friendship gate on watched movies endpoint | Any authenticated user reads any user's full watch history | `assert_are_friends(viewer_id, target_id, db)` before any data access |
| Returning 404 instead of 403 for non-friends | Leaks whether the target user ID is valid | Return 403 "Not friends" for unauthorized profile access; 404 only for user not found |
| Exposing `taste_embedding` in public profile response | User's full 1536-dimension taste vector is public; could be used to infer watching habits at scale | Never include vector fields in any response schema; keep `taste_embedding` out of all Pydantic models |
| No rate limit on public profile endpoints | Attacker scrapes all users' watch histories in bulk | Apply `LIMIT_DEFAULT` (60/min) via the existing `@limiter.limit()` decorator — it is per-user, not per-IP |
| Public stats endpoint callable without friendship check | Reveals that User A exists and has watched N movies | Stats endpoint (watched count, friends count, groups count) is lower risk than full watch history, but should still gate on friendship for this friends-only app |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| No loading skeleton for poster grid | Blank white space for 200-400ms, then sudden grid pop-in | Show 9 placeholder `RoundedRectangle` tiles with `.redacted(reason: .placeholder)` while loading |
| Stats row shows 0 during data load | Friends count + watched count flash "0" then update, causing layout shift | Initialize stat values to `nil` and show a dash or hidden state until loaded |
| Tapping a friend's poster navigates to `MovieDetailView` with full watched/rate UI | Viewer can attempt to rate a movie on a friend's profile | `MovieDetailView` is appropriate (it shows the film, not the friend's rating) — but disable "Rate" and "Add to watchlist" when viewing from `FriendProfileView` context |
| Remove Friend button present when viewing a profile from a non-friends context | Confusing if profiles become accessible outside the friends list | Only show Remove Friend button when `friend.friendshipId` is non-nil |
| Empty state for watched movies shows generic "No watched movies yet" | Misleading — the friend may have movies but visibility is restricted | If the API returns 403, show "Can't load watched movies" not "No watched movies" |

---

## "Looks Done But Isn't" Checklist

- [ ] **Friendship gate:** Call `GET /users/{other_id}/watched` as a non-friend — must return 403, not 200
- [ ] **Self-access guard:** Call `GET /users/{own_id}/watched` as the owner — must return 400 or redirect, not use the public endpoint
- [ ] **No taste_bio leak:** Check the public profile response JSON — `taste_bio` and `favorite_genres` must not be present
- [ ] **Pagination works:** Call watched endpoint with `limit=5&offset=5` for a user with 10 films — must return exactly 5 results
- [ ] **Stats are counts, not lists:** Confirm stats endpoint returns integers (`watched_count`, `friends_count`, `groups_count`), not arrays
- [ ] **N+1 check:** Enable SQLAlchemy query logging and load a profile — count of SELECT statements must be constant (not proportional to friend count)
- [ ] **Shared components extracted:** `posterTile` equivalent does NOT appear as a private function in both `ProfileView.swift` and `FriendProfileView.swift`
- [ ] **Parallel iOS loading:** Instrument with `CFAbsoluteTimeGetCurrent()` — stats and watched requests must overlap (start within ~10ms of each other), not be sequential
- [ ] **Remove friend refreshes parent:** After removing a friend, pop back to `FriendsListView` and confirm the removed friend is no longer in the list without a manual pull-to-refresh
- [ ] **403 error state:** Call watched endpoint from a removed friend scenario — `FriendProfileView` must show a graceful empty/error state, not crash

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Data leak via `UserResponse` schema | LOW | Add `PublicProfileResponse` schema, update endpoint response type, deploy |
| Missing friendship gate ships to production | HIGH | Hotfix deploy with gate added; audit logs to check if unauthorized access occurred; no data loss but privacy incident |
| N+1 query slows profile views | MEDIUM | Add JOIN query in service; no schema or migration changes; requires deploy |
| Unpaginated endpoint with large payload | MEDIUM | Add pagination params; iOS client needs update to handle paginated response; coordinated deploy |
| Shared component not extracted | LOW | Extract `PosterTile` and `StatsRow` post-hoc; update both views; no backend changes |
| Stale FriendsListView after removal | LOW | Add `.onAppear` refresh in `FriendsListView`; iOS-only change |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| `UserResponse` schema leak | Backend endpoint — schema design | Check response JSON for `taste_bio` absence |
| Missing friendship authorization | Backend endpoint — service layer | 403 from non-friend, 200 from friend |
| N+1 friends count query | Backend endpoint — stats service | SQLAlchemy query log: constant query count per profile view |
| No pagination on watched endpoint | Backend endpoint — endpoint signature | `limit=5&offset=0` returns 5 results; `total` count present |
| Duplicated UI code in FriendProfileView | iOS — component extraction before new UI | No private `posterTile` / `LazyVGrid` in both files |
| Sequential iOS API calls | iOS — data loading implementation | Network trace shows overlapping requests |
| Self-profile via public endpoint | Backend endpoint — service guards | Calling own user_id returns 400 |
| Stale parent list after remove | iOS — remove friend wiring | FriendsListView refreshes automatically on pop |
| N+1 friends-of-friend list query | Backend friends list endpoint | JOIN-based query confirmed in service |
| Privacy: exposing stats without friendship gate | Backend endpoint — authorization | Non-friend gets 403 on stats endpoint |

---

## Sources

- Existing codebase: `/Users/adamrose/Desktop/blnd/blnd_backend/app/friends/services.py` (N+1 pattern in `get_friends()`, lines 132–137; bidirectional `or_` friendship query pattern)
- Existing codebase: `/Users/adamrose/Desktop/blnd/blnd_backend/app/auth/schemas.py` (`UserResponse` includes `taste_bio` and `favorite_genres` — unsafe to reuse for public endpoint)
- Existing codebase: `/Users/adamrose/Desktop/blnd/blnd_backend/app/tracking/services.py` (pagination pattern with `func.count` + `limit`/`offset`; `get_friends_who_watched` shows correct JOIN pattern)
- Existing codebase: `/Users/adamrose/Desktop/blnd/blnd_ios/blnd_ios/Views/Profile/ProfileView.swift` (poster grid, stats row, `async let` parallelism pattern at lines 59–63)
- Existing codebase: `/Users/adamrose/Desktop/blnd/blnd_ios/blnd_ios/Views/Friends/FriendProfileView.swift` (current 101-line stub; profile header reused but no grid/stats)
- Existing codebase: `/Users/adamrose/Desktop/blnd/blnd_backend/app/auth/views.py` (route ordering: `/users/search` registered before — confirms router prefix concern)
- Existing codebase: `/Users/adamrose/Desktop/blnd/blnd_backend/app/core/rate_limit.py` (LIMIT_DEFAULT = "60/minute", applied via `@limiter.limit()`)
- FastAPI docs: [Authorization](https://fastapi.tiangolo.com/tutorial/security/) — authorization is not automatic; each endpoint must check permissions explicitly
- SQLAlchemy docs: [ORM Querying Guide](https://docs.sqlalchemy.org/en/20/orm/queryguide/) — `func.count()` pattern for aggregate queries without loading rows
- SwiftUI docs: [Structured Concurrency async let](https://docs.swift.org/swift-book/documentation/the-swift-programming-language/concurrency/) — `async let` fires immediately without suspension

---
*Pitfalls research for: Public user profile endpoints + iOS FriendProfileView revamp (v1.2)*
*Researched: 2026-03-11*
