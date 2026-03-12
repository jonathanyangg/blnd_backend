# Project Research Summary

**Project:** BLND v1.2 — Public User Profile Endpoints + FriendProfileView Revamp
**Domain:** Social mobile app — public friend profile surface (FastAPI + SwiftUI)
**Researched:** 2026-03-11
**Confidence:** HIGH

## Executive Summary

BLND v1.2 is a tightly scoped milestone adding a public friend profile surface to an existing social movie-tracking app. The work covers three new read-only backend endpoints (`GET /auth/users/{id}/profile`, `/watched`, `/friends`) and a full revamp of the iOS `FriendProfileView` to show a stats row, watched poster grid, and tappable friends list. Research across all four domains confirms that no new libraries, database migrations, or router registrations are required — every building block already exists in the codebase. This milestone is additive schema and service logic wired to established patterns.

The recommended approach is backend-first, building incrementally within the existing `auth` domain rather than creating a new domain folder. On iOS, shared components (`PosterTile`, `StatsRow`) must be extracted from `ProfileView` before building `FriendProfileView` to avoid duplicating 38+ lines of UI logic. All three API calls from the revamped view should fire in parallel using `async let`, matching the pattern already in `ProfileView.swift`. The iOS and backend schemas map 1:1 with no translation surprises.

The top risks are security-related, not technical: a missing friendship gate on the watched movies endpoint would allow any authenticated user to enumerate any user's full watch history, and reusing the existing `UserResponse` schema would leak `taste_bio` and `favorite_genres` to any caller. Both are trivially prevented with a dedicated `PublicProfileResponse` schema and an `assert_are_friends()` service helper — but both are also the kind of shortcut that feels reasonable under time pressure. The N+1 query trap (calling `get_friends()` to get a count) is the most likely performance mistake.

---

## Key Findings

### Recommended Stack

No new stack decisions are required. The existing FastAPI 0.135.1 / SQLAlchemy 2.0.47 / Pydantic 2.12.5 / SwiftUI (iOS 17+) stack handles all v1.2 needs. All three new backend endpoints live on the existing `auth_router` — no `main.py` changes. All iOS networking goes through the existing `APIClient.shared.request()` singleton. The only additions are new Pydantic schemas in `auth/schemas.py`, new service functions in `auth/services.py`, and a new `ProfileAPI.swift` static enum following the identical pattern to `FriendsAPI.swift`.

**Core technologies:**
- FastAPI 0.135.1: HTTP routing — add 3 routes to existing `auth_router` in `auth/views.py`
- SQLAlchemy 2.0.47: ORM queries — `Profile`, `Friendship`, `WatchedMovie`, `GroupMember` models cover all needed joins with no new models or migrations
- Pydantic 2.12.5: Schemas — 3 new `BaseModel` subclasses in `auth/schemas.py`; reuse `WatchedMovieResponse` and `FriendResponse` from existing domains
- SwiftUI / `@Observable` / `async/await`: iOS UI and state — same local `@State` pattern as `ProfileView`; zero new SPM dependencies
- slowapi 0.1.9: Rate limiting — `@limiter.limit(LIMIT_DEFAULT)` applied to all three new endpoints unchanged

See [STACK.md](.planning/research/STACK.md) for full version matrix and integration point inventory.

### Expected Features

The feature research draws on codebase inspection and social app pattern analysis (Letterboxd, Instagram). The existing `ProfileView` sets the user's expectation baseline — `FriendProfileView` must reach parity on all visible surface areas.

**Must have (table stakes — v1.2):**
- Stats row on friend profile (watched count, friends count, blends count) — own profile already shows this; its absence on a friend profile reads as broken
- Watched poster grid (3-column `LazyVGrid`, paginated, sorted newest first) — the primary social signal in a movie app; Letterboxd and every comparable product show this
- Tappable poster → `MovieDetailView` — every poster in the app navigates; inconsistency if friend posters do not
- Loading states and empty states — existing app patterns; blank-then-appearing content reads as broken
- Remove friend button preserved — the only current feature of `FriendProfileView`; its removal degrades utility

**Should have (differentiators — v1.2 if time allows):**
- Tappable friends count → friend's friends list (new `FriendFriendsListView`) — makes counts interactive; enables social discovery
- Blends count display-only (zero extra cost — returned in the same stats endpoint)
- Pagination load-more on watched grid — users with 500+ Letterboxd imports need this

**Defer (v1.x / v2+):**
- Rating badges on friend posters — "whose rating?" ambiguity not yet designed for
- Blends count tappable (requires new endpoint and new view)
- Privacy controls (friends-only vs public visibility toggle)
- Taste compatibility display, activity feed, mutual friends indicator

**Anti-features to avoid:**
- Watchlist tab on friend profile — excluded by milestone spec; watchlist is intent, not social signal
- `@Observable` state class for friend profile data — leaf view, local `@State` is correct
- New FastAPI domain folder for public profile reads — three read-only endpoints do not justify a new domain

See [FEATURES.md](.planning/research/FEATURES.md) for full prioritization matrix and social app pattern comparison.

### Architecture Approach

The architecture is an additive integration into existing patterns, not a new design. Three files are modified on the backend (`auth/views.py`, `auth/services.py`, `auth/schemas.py`), two new files are created on iOS (`Networking/ProfileAPI.swift`, `Models/ProfileModels.swift`), and one view is revamped (`FriendProfileView.swift`). Database schema is unchanged — no migrations. The `auth_router` prefix already covers the `/auth/users/{id}/...` URL space; `main.py` requires no changes.

**Major components:**
1. `app/auth/` (backend, modified) — three new endpoints: stats counts via scalar `func.count()` queries, paginated watched list (mirrors `GET /tracking/`), friends list with JOIN query
2. `Networking/ProfileAPI.swift` (iOS, new) — static enum with `getPublicProfile`, `getPublicWatched`, `getPublicFriends`; same pattern as `FriendsAPI.swift`
3. `Models/ProfileModels.swift` (iOS, new) — `PublicProfileResponse`, `PublicWatchedResponse`, `PublicFriendsResponse`; reuses `WatchedMovieResponse` and `FriendResponse` from existing model files
4. `FriendProfileView.swift` (iOS, revamped) — receives `FriendResponse`, fires three parallel `async let` loads on `.task`, renders stats row + poster grid + friends list

**Key architectural constraint:** Do not call `get_friends()` or `get_watch_history()` from the new service functions — those functions enforce ownership semantics and will silently return the caller's own data, not the target's. Copy the query logic into new functions with correct `user_id` parameterization.

See [ARCHITECTURE.md](.planning/research/ARCHITECTURE.md) for full component diagram, data flow, and anti-pattern catalog.

### Critical Pitfalls

Nine pitfalls identified; the five most likely to cause harm if ignored:

1. **Schema leak via `UserResponse` reuse** — The existing `UserResponse` includes `taste_bio` and `favorite_genres`. Reusing it for the public profile endpoint exposes private data to any authenticated caller. Prevention: create a dedicated `PublicProfileResponse` schema before writing any service logic.

2. **Missing friendship gate on watched movies endpoint** — JWT auth alone allows any authenticated user to read any user's full watch history. User IDs are UUIDs but are already leaked via `/auth/users/search`. Prevention: implement `assert_are_friends(viewer_id, target_id, db)` called at the top of every service function that accesses another user's data. Return 403, not 404.

3. **N+1 query via `get_friends()` for counts** — Calling the existing `get_friends(user_id, db)` helper for a count issues 1+N database queries. Prevention: use `db.query(func.count(Friendship.id)).filter(...).scalar()` directly. Same applies to the friends list endpoint — use a JOIN query, not `get_friends()`.

4. **Unpaginated watched movies endpoint** — Users who imported from Letterboxd may have 2,000+ entries. A `SELECT * FROM watched_movies WHERE user_id = ?` without `LIMIT` returns megabytes of JSON. Prevention: mirror `GET /tracking/` exactly — require `limit` (default 20, max 100) and `offset` params; include `total` in the response.

5. **UI code duplication across `ProfileView` and `FriendProfileView`** — `posterTile()` is 38 lines of private SwiftUI code. Duplicating it creates maintenance debt. Prevention: extract `PosterTile`, `StatsRow`, and `PosterGrid` to `Views/Shared/` before adding any new UI to `FriendProfileView`. This refactor is a prerequisite, not optional cleanup.

See [PITFALLS.md](.planning/research/PITFALLS.md) for the complete nine-pitfall catalog including sequential iOS API calls, stale parent list after friend removal, self-access edge case, and the "looks done but isn't" verification checklist.

---

## Implications for Roadmap

Based on research, the natural build order follows backend-then-iOS dependency flow with one prerequisite iOS refactor before the main view work. Four phases, no unknowns.

### Phase 1: Backend Public Profile Endpoints

**Rationale:** iOS cannot load data until backend endpoints exist. Building backend first also forces the security decisions (friendship gate, dedicated schema) before any iOS integration, when the blast radius of a mistake is smallest.

**Delivers:** Three production-ready endpoints — `/auth/users/{id}/profile` (stats counts), `/auth/users/{id}/watched` (paginated), `/auth/users/{id}/friends` (friend list). Verified via `curl` against a running backend before any iOS work begins.

**Addresses:** Stats row data, watched poster grid data, friends list data (all table-stakes features from FEATURES.md).

**Avoids:** Schema leak (Pitfall 1), missing friendship gate (Pitfall 2), N+1 count query (Pitfall 3), unpaginated watched endpoint (Pitfall 4).

**Build order within phase:** schemas first (prerequisite for compiler), then services, then views. Verify each service function with direct Python/SQLAlchemy calls before wiring to routes.

### Phase 2: iOS Shared Component Extraction

**Rationale:** `FriendProfileView` cannot reuse `ProfileView`'s private helper functions. This phase is a hard prerequisite for Phase 4, not optional cleanup. Doing it after the revamp forces a second refactor pass through two views.

**Delivers:** `PosterTile`, `StatsRow`, and `PosterGrid` extracted from `ProfileView` to `Views/Shared/`. `ProfileView` refactored to use the shared components — all existing behavior preserved.

**Avoids:** UI duplication pitfall (Pitfall 5), maintenance debt on every future design change.

**Note for roadmapper:** This is a refactor phase with no visible user-facing change. Keep it small and focused — three components. Do not expand scope to other `ProfileView` cleanup.

### Phase 3: iOS ProfileAPI + Models

**Rationale:** Can be developed in parallel with Phase 1 (no backend dependency for file creation) but must complete before Phase 4. Establishes the networking layer and Decodable models before the view needs them.

**Delivers:** `Networking/ProfileAPI.swift` (static enum, 3 methods), `Models/ProfileModels.swift` (`PublicProfileResponse`, `PublicWatchedResponse`, `PublicFriendsResponse`). Can be verified via debug print against a running Phase 1 backend.

**Uses:** Existing `APIClient.shared.request<T>()` — no changes to `APIClient`. Reuses `WatchedMovieResponse` from `TrackingModels.swift` and `FriendResponse` from `FriendModels.swift` as item types.

### Phase 4: FriendProfileView Revamp

**Rationale:** All prerequisites (backend endpoints, shared components, iOS networking layer) are complete. The view revamp is the final integration step.

**Delivers:** Fully revamped `FriendProfileView.swift` with stats row, paginated watched poster grid, tappable friends list, and preserved remove-friend button. Loading states, empty states, and error states matching existing app patterns.

**Implements:** Parallel `async let` data loading on `.task`, stats row from shared `StatsRow` component, poster grid from shared `PosterGrid` + `PosterTile` components, `NavigationLink` to `MovieDetailView` on poster tap, `NavigationLink` to nested `FriendProfileView` on friends count tap.

**Avoids:** Sequential API calls (Pitfall 6), stale parent list after removal (Pitfall 8), missing self-access guard (Pitfall 7).

### Phase Ordering Rationale

- Backend before iOS: iOS views cannot render without live endpoints. Building backend first also surfaces security decisions before any client code exists.
- Shared component extraction before view revamp: `FriendProfileView` cannot call `ProfileView`'s private functions. This is a hard compile-time constraint.
- Models and API layer can overlap Phase 1: Swift file creation has no runtime dependency on a running backend. Model structs and the API enum can be written and reviewed while the backend is being built.
- Single phase for the full view revamp: stats row, poster grid, and friends list all depend on the same three API calls and the same `@State` loading pattern. Splitting them into sub-phases would require re-entering the same view file repeatedly for no benefit.

### Research Flags

Phases with well-documented patterns (skip `/gsd:research-phase`):
- **Phase 1 (Backend endpoints):** All query patterns exist in the codebase. Pydantic schema patterns are established. FastAPI route registration is standard. No unknowns.
- **Phase 3 (iOS models + API):** Static enum pattern is identical to `FriendsAPI.swift`. `Decodable` structs with `CodingKeys` are the app's standard pattern. No research needed.

Phases that may benefit from brief implementation-time spikes:
- **Phase 2 (Component extraction):** The `StatsRow` shared component needs a design decision on how to parameterize optional tap handlers (own profile's stats are tappable; friend profile's stats are not for all items). Options: optional `action: (() -> Void)?` parameter, or two separate components. 30-minute spike, not a full research phase.
- **Phase 4 (LazyVGrid pagination):** `LazyVGrid` load-more via `.onAppear` on the last cell has edge cases with rapid scroll and task cancellation. Reference the SwiftUI pagination examples cited in FEATURES.md sources before implementing.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Direct codebase inspection of pinned `requirements.txt` and both `CLAUDE.md` files. All technologies directly observed, no inference. |
| Features | HIGH (codebase) / MEDIUM (UX patterns) | Must-have features confirmed via codebase inspection of existing `ProfileView`. UX pattern comparisons (Letterboxd, Instagram) are MEDIUM — reasonable consensus but not user-tested for this specific app. |
| Architecture | HIGH | Based entirely on direct codebase inspection. Integration map is a direct read of existing file structures. Anti-patterns reference specific line numbers in existing services. |
| Pitfalls | HIGH | Each pitfall is grounded in a specific existing code location (e.g., `get_friends()` N+1 at lines 132-137 of `friends/services.py`; `UserResponse` fields in `auth/schemas.py`). Not speculative. |

**Overall confidence:** HIGH

### Gaps to Address

- **Blends count source:** The stats endpoint research assumes `groups_count` maps to "blends count" in the iOS display (the app calls groups "blends"). Confirm at implementation time that `GroupMember` is the correct model for blends — if groups and blends are modeled differently, the count query will be wrong.

- **Friend-gating policy:** Research recommends gating all three endpoints on friendship. The milestone description does not specify this. If the team decides on "any authenticated user can see any profile" (open model), Pitfall 2 and the `assert_are_friends()` helper are not needed. This is a product decision that should be confirmed before Phase 1 backend work begins.

- **`StatsRow` component tap handler design:** Whether to use an optional `action` parameter or two separate components for tappable vs non-tappable stat items is deferred to implementation. Both options are valid. Not a blocker.

- **Tiered authorization:** A tiered approach (open stats, gated watched/friends) is a viable alternative to applying the friendship gate to all three endpoints. Profile stats (counts only) are lower sensitivity than full watch history. Worth a brief team discussion before Phase 1.

---

## Sources

### Primary (HIGH confidence)
- `/Users/adamrose/Desktop/blnd/blnd_backend/app/` — direct inspection of `auth/`, `friends/`, `tracking/`, `groups/` services, schemas, models, and views
- `/Users/adamrose/Desktop/blnd/blnd_ios/blnd_ios/` — direct inspection of `ProfileView.swift`, `FriendProfileView.swift`, `FriendModels.swift`, `FriendsAPI.swift`, `TrackingModels.swift`, `APIClient.swift`
- `/Users/adamrose/Desktop/blnd/blnd_backend/requirements.txt` — pinned version verification
- `/Users/adamrose/Desktop/blnd/blnd_backend/CLAUDE.md` — domain-driven structure, conventions
- `/Users/adamrose/Desktop/blnd/blnd_ios/CLAUDE.md` — iOS architecture, zero third-party policy

### Secondary (MEDIUM confidence)
- [Letterboxd public profile FAQ](https://letterboxd.com/about/faq/) — public profile shows films, followers, lists; watchlist is private by default
- [SwiftUI LazyVGrid pagination — tanaschita.com](https://tanaschita.com/20230828-pagination-in-swiftui-list/) — `onAppear` on last item as load-more trigger
- [Implementing Load More Pagination in LazyVGrid — Medium](https://medium.com/@naylinn/implementing-load-more-pagination-in-lazyvgrid-in-swiftui-ed5d3e0c1486) — LazyVGrid pagination pattern

### Tertiary (Reference / validation)
- FastAPI docs: [Authorization](https://fastapi.tiangolo.com/tutorial/security/) — authorization is not automatic per endpoint
- SQLAlchemy docs: [ORM Querying Guide](https://docs.sqlalchemy.org/en/20/orm/queryguide/) — `func.count()` aggregate pattern
- SwiftUI docs: [Structured Concurrency async let](https://docs.swift.org/swift-book/documentation/the-swift-programming-language/concurrency/) — `async let` fires immediately without suspension

---

*Research completed: 2026-03-11*
*Ready for roadmap: yes*
