# Phase 9: FriendProfileView Revamp - Research

**Researched:** 2026-03-12
**Domain:** SwiftUI iOS — friend profile networking layer + view revamp
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Remove Friend placement: three-dot ellipsis menu in top-right toolbar, only "Remove Friend" action, keep existing `.alert()` confirmation, dismiss after removal
- Layout: no tab picker — stats row flows directly into poster grid (watched only; watchlist out of scope)
- StatsRow: 3 items (Watched, Friends, Blends); only Friends count is tappable
- Friends list presentation: tapping Friends count opens a `.sheet()` containing the friend's friends list; tapping a friend-of-friend dismisses the sheet then pushes a new FriendProfileView onto the navigation stack
- Sheet dismiss-before-navigate: no NavigationStack inside the sheet

### Claude's Discretion
- Loading indicator style (ProgressView spinner vs skeleton)
- Empty state wording and icon for friends with no watched movies
- Infinite scroll implementation details for the poster grid
- Friends list sheet layout and styling
- ProfileAPI networking layer structure

### Deferred Ideas (OUT OF SCOPE)
- PROF-02: Tappable blends count on friend profile (requires new endpoint + view)
- PROF-04: Taste compatibility display on friend profile
- PROF-05: Mutual friends indicator on friend profile
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| IOS-01 | User sees stats row on friend profile (watched count, friends count, blends count) | Backend PublicProfileResponse has all three counts; StatsRow shared component already accepts StatItem array with optional onTap |
| IOS-02 | User sees 3-column poster grid of friend's watched movies with star ratings | Backend GET /auth/users/{id}/watched returns PublicWatchedListResponse (results + total); PosterGrid + PosterTile shared components are drop-in ready |
| IOS-03 | User can tap a watched movie poster to navigate to MovieDetailView | Established pattern: NavigationLink { MovieDetailView(tmdbId:title:) } used in ProfileView; same approach applies |
| IOS-04 | User can tap friends count to see friend's friends list | Backend GET /auth/users/{id}/friends returns PublicFriendsListResponse; StatItem(onTap:) callback triggers .sheet() |
| IOS-05 | User can tap a friend-of-friend to open their profile (recursive navigation) | FriendProfileView(friend:) accepts FriendResponse — PublicFriendResponse maps to it; sheet dismiss + NavigationLink push pattern is safe in SwiftUI |
| IOS-07 | Loading and empty states displayed while data loads or when friend has no watched movies | ProgressView pattern verified in ProfileView; empty state Text() pattern established |
</phase_requirements>

---

## Summary

Phase 9 transforms FriendProfileView from a bare-bones remove-friend screen into a full profile view matching the depth of ProfileView. The backend is completely done (Phase 7): three endpoints at `GET /auth/users/{id}/profile`, `GET /auth/users/{id}/watched`, and `GET /auth/users/{id}/friends` are live in `app/auth/views.py` and return verified Pydantic schemas. The shared components are done (Phase 8): `PosterTile`, `StatsRow`/`StatItem`, and `PosterGrid` all exist in `Views/Shared/` and are already used by ProfileView.

The two deliverables are a new `ProfileAPI.swift` networking enum (3 static methods) with 5 new Codable model structs in `ProfileModels.swift`, and a rewrite of `FriendProfileView.swift` that parallel-loads data and renders the stats row, infinite-scroll poster grid, friends list sheet, and ellipsis menu. The recursive navigation pattern (sheet dismiss + NavigationStack push) is a standard SwiftUI idiom with no special library support needed.

**Primary recommendation:** Model ProfileAPI after TrackingAPI (static enum, `APIClient.shared.request`, query-string pagination). Model FriendProfileView after ProfileView (local `@State`, `async let` parallel loading, `.task {}`, ProgressView for loading, Text for empty state). The sheet-dismiss-before-navigate pattern is the only novel interaction to implement carefully.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SwiftUI | iOS 17+ | UI framework | Project constraint; all views are SwiftUI |
| Foundation | iOS 17+ | Networking models (Codable, URLSession) | Used by all existing API layers |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| APIClient.shared | project | Central HTTP client with JWT injection | All network calls go through it |
| PosterTile | project (Phase 8) | Poster image + rating badge tile | All poster grid cells |
| StatsRow + StatItem | project (Phase 8) | Tappable/non-tappable stats row | Friend profile header |
| PosterGrid | project (Phase 8) | 3-column LazyVGrid wrapper | Watched movie grid |
| AvatarView | project | Avatar with AsyncImage + gradient fallback | Profile header + friends list rows |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Static `enum ProfileAPI` | `class ProfileAPI` | Enum is consistent with all other API files (FriendsAPI, TrackingAPI, MoviesAPI) — no reason to deviate |
| ProgressView spinner | Skeleton/redacted placeholder | Spinner is simpler, matches ProfileView pattern. Skeleton is discretionary — spinner preferred for consistency |
| `.sheet()` for friends list | `.fullScreenCover()` | Sheet is the locked decision; matches the "peek" mental model for browsing a friend's friends |

**Installation:** No new dependencies. Zero third-party packages per project rules.

---

## Architecture Patterns

### Recommended Project Structure
```
blnd_ios/blnd_ios/
├── Models/
│   └── ProfileModels.swift          NEW — 5 Codable structs matching backend public profile schemas
├── Networking/
│   └── ProfileAPI.swift             NEW — 3 static methods for the public profile endpoints
└── Views/
    └── Friends/
        └── FriendProfileView.swift  REWRITE — stats row, poster grid, friends sheet, ellipsis menu
```

### Pattern 1: Static API Enum (ProfileAPI)
**What:** An `enum` with no cases, containing only `static func` methods. Each method calls `APIClient.shared.request()` or `requestVoid()` with the appropriate endpoint string.
**When to use:** Every domain in the project follows this shape (FriendsAPI, TrackingAPI, MoviesAPI, GroupsAPI).
**Example:**
```swift
// Mirrors TrackingAPI.getWatchHistory pattern exactly
enum ProfileAPI {
    static func getPublicProfile(userId: String) async throws -> PublicProfileResponse {
        try await APIClient.shared.request(
            endpoint: "/auth/users/\(userId)/profile",
            authenticated: true
        )
    }

    static func getPublicWatched(
        userId: String,
        limit: Int = 20,
        offset: Int = 0
    ) async throws -> PublicWatchedListResponse {
        try await APIClient.shared.request(
            endpoint: "/auth/users/\(userId)/watched?limit=\(limit)&offset=\(offset)",
            authenticated: true
        )
    }

    static func getPublicFriends(userId: String) async throws -> PublicFriendsListResponse {
        try await APIClient.shared.request(
            endpoint: "/auth/users/\(userId)/friends",
            authenticated: true
        )
    }
}
```

### Pattern 2: Codable Model Structs (ProfileModels)
**What:** Pure `Decodable` structs matching the backend Pydantic schema field-for-field. `CodingKeys` handles snake_case → camelCase conversion. Every model file in the project uses this shape.
**When to use:** Any new backend response type.
**Example — full set of 5 models needed:**
```swift
// PublicProfileResponse — from GET /auth/users/{id}/profile
struct PublicProfileResponse: Decodable {
    let id: String
    let username: String
    let displayName: String?
    let avatarUrl: String?
    let watchedCount: Int
    let friendsCount: Int
    let blendsCount: Int

    enum CodingKeys: String, CodingKey {
        case id, username
        case displayName = "display_name"
        case avatarUrl = "avatar_url"
        case watchedCount = "watched_count"
        case friendsCount = "friends_count"
        case blendsCount = "blends_count"
    }
}

// PublicWatchedMovieResponse — items in PublicWatchedListResponse.results
struct PublicWatchedMovieResponse: Decodable, Identifiable {
    let tmdbId: Int
    let title: String
    let posterPath: String?
    let rating: Double?

    var id: Int { tmdbId }   // Identifiable via tmdbId

    enum CodingKeys: String, CodingKey {
        case tmdbId = "tmdb_id"
        case title
        case posterPath = "poster_path"
        case rating
    }
}

// PublicWatchedListResponse — paginated envelope
struct PublicWatchedListResponse: Decodable {
    let results: [PublicWatchedMovieResponse]
    let total: Int
}

// PublicFriendResponse — items in PublicFriendsListResponse.friends
// Note: no friendshipId — this is a public view of user info only
struct PublicFriendResponse: Decodable, Identifiable {
    let id: String
    let username: String
    let displayName: String?
    let avatarUrl: String?

    enum CodingKeys: String, CodingKey {
        case id, username
        case displayName = "display_name"
        case avatarUrl = "avatar_url"
    }
}

// PublicFriendsListResponse — friends list envelope
struct PublicFriendsListResponse: Decodable {
    let friends: [PublicFriendResponse]
}
```

### Pattern 3: Parallel Data Loading in FriendProfileView
**What:** `async let` bindings that launch both the profile stats and the first page of watched movies concurrently, then await both results together. Identical to ProfileView's `loadData()` pattern.
**When to use:** Any view that needs multiple independent API responses on appear.
**Example:**
```swift
// In FriendProfileView
private func loadData() async {
    isLoading = true
    do {
        async let profile = ProfileAPI.getPublicProfile(userId: friend.id)
        async let watched = ProfileAPI.getPublicWatched(userId: friend.id, limit: 20, offset: 0)
        let (profileResult, watchedResult) = try await (profile, watched)
        publicProfile = profileResult
        watchedMovies = watchedResult.results
        watchedTotal = watchedResult.total
    } catch is CancellationError {
        return
    } catch {
        print("[FriendProfileView] loadData error: \(error)")
    }
    isLoading = false
}
```

### Pattern 4: Infinite Scroll via onAppear
**What:** Attach `.onAppear` to the last item in the poster grid's `ForEach`. When the last item appears, fetch the next page and append to the array. Track `isLoadingMore` to prevent double-fetches.
**When to use:** Any paginated poster grid. The backend supports `limit` + `offset` on the watched endpoint.
**Example:**
```swift
// Inside PosterGrid ForEach
ForEach(watchedMovies) { movie in
    NavigationLink {
        MovieDetailView(tmdbId: movie.tmdbId, title: movie.title)
    } label: {
        PosterTile(posterPath: movie.posterPath, rating: movie.rating)
    }
    .buttonStyle(.plain)
    .onAppear {
        if movie.id == watchedMovies.last?.id {
            Task { await loadMoreWatched() }
        }
    }
}

private func loadMoreWatched() async {
    guard !isLoadingMore, watchedMovies.count < watchedTotal else { return }
    isLoadingMore = true
    do {
        let next = try await ProfileAPI.getPublicWatched(
            userId: friend.id,
            limit: 20,
            offset: watchedMovies.count
        )
        watchedMovies.append(contentsOf: next.results)
    } catch is CancellationError {
        return
    } catch {
        print("[FriendProfileView] loadMoreWatched error: \(error)")
    }
    isLoadingMore = false
}
```

### Pattern 5: Sheet Dismiss + NavigationStack Push (Recursive Navigation)
**What:** The friends list sheet is presented from FriendProfileView. When the user taps a friend-of-friend, the sheet is dismissed (via `@Environment(\.dismiss)`) and then a new FriendProfileView is pushed onto the parent NavigationStack. This avoids nesting a NavigationStack inside a sheet.
**When to use:** Whenever a sheet needs to trigger navigation after dismissal — the locked pattern for this phase.
**Example:**
```swift
// FriendsListSheet — presented as .sheet() from FriendProfileView
struct FriendsListSheet: View {
    let friends: [PublicFriendResponse]
    // Closure called when user taps a friend-of-friend; sheet dismisses then parent navigates
    let onSelectFriend: (PublicFriendResponse) -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        // ... list of friend rows
        // On row tap:
        Button {
            dismiss()
            onSelectFriend(friend)
        } label: {
            FriendOfFriendRow(friend: friend)
        }
    }
}

// FriendProfileView state
@State private var showFriendsList = false
@State private var selectedFriendOfFriend: PublicFriendResponse? = nil

// Body — push FriendProfileView when selectedFriendOfFriend is set
.navigationDestination(item: $selectedFriendOfFriend) { fof in
    FriendProfileView(
        friend: FriendResponse(
            friendshipId: nil,
            id: fof.id,
            username: fof.username,
            displayName: fof.displayName,
            avatarUrl: fof.avatarUrl
        )
    )
}

// Sheet presentation
.sheet(isPresented: $showFriendsList) {
    FriendsListSheet(friends: friendsList) { selected in
        selectedFriendOfFriend = selected
    }
    .presentationBackground(AppTheme.background)
}
```

### Pattern 6: Ellipsis Menu in Toolbar
**What:** Move "Remove Friend" from a capsule button in the body to a `.menu` inside `ToolbarItem(placement: .navigationBarTrailing)`. The `.alert()` confirmation stays on FriendProfileView.
**When to use:** Locked decision from CONTEXT.md.
**Example:**
```swift
.toolbar {
    ToolbarItem(placement: .navigationBarLeading) {
        BackButton()
    }
    ToolbarItem(placement: .navigationBarTrailing) {
        Menu {
            Button(role: .destructive) {
                showRemoveAlert = true
            } label: {
                Label("Remove Friend", systemImage: "person.badge.minus")
            }
        } label: {
            Image(systemName: "ellipsis")
                .font(.system(size: 20))
                .foregroundStyle(AppTheme.textDim)
        }
    }
}
```

### Anti-Patterns to Avoid
- **NavigationStack inside .sheet():** Never wrap the friends list sheet in a NavigationStack. The locked decision is dismiss-then-push on the parent stack.
- **Fetching friends list eagerly:** Only fetch `GET /auth/users/{id}/friends` when the user taps the Friends stat, not during initial load. Avoids an unnecessary API call for every profile view.
- **Using `@Observable` class for FriendProfileView:** REQUIREMENTS.md explicitly calls this out of scope — local `@State` is correct for a leaf view.
- **Reusing `FriendResponse` for friend-of-friend navigation without mapping:** `PublicFriendResponse` has no `friendshipId` (it's not in the public API). Construct a `FriendResponse(friendshipId: nil, ...)` when pushing a FriendProfileView for a friend-of-friend. The `removeFriend()` guard already checks `guard let friendshipId = friend.friendshipId else { return }`, so nil friendshipId safely disables removal on transitive profile views.
- **Loading all watched movies at once:** The backend caps at 100 per request (`le=100`). Use page size 20 and infinite scroll to avoid large initial payloads.
- **Calling `db.query(Friendship).filter(...).first()` pattern in Swift:** Not applicable — this is pure iOS work. No backend changes in this phase.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 3-column poster grid | Custom LazyVGrid setup | `PosterGrid` (Phase 8) | Already exists, already matches visual spec |
| Poster image + rating badge | Custom AsyncImage + overlay | `PosterTile` (Phase 8) | Already handles all edge cases (nil path, nil rating, aspect ratio) |
| Stats row with optional taps | Custom HStack stat cells | `StatsRow` + `StatItem` (Phase 8) | Already handles tappable vs non-tappable via `onTap: (() -> Void)?` |
| Avatar rendering | Custom AsyncImage with fallback | `AvatarView(url:size:)` | Handles nil URL, gradient fallback, size parameter |
| HTTP request + JWT injection | Custom URLSession | `APIClient.shared.request()` | Handles auth, error mapping, decoding |
| snake_case ↔ camelCase mapping | Custom JSON parsing | `CodingKeys` enum | Standard Swift pattern used everywhere |
| Edge-swipe dismiss | Custom gesture recognizer | `.swipeBackGesture()` modifier | Already on FriendProfileView — keep it |

**Key insight:** Phase 8 was done specifically to unblock this phase. Every visual component is reusable. The only new code is networking glue and view orchestration.

---

## Common Pitfalls

### Pitfall 1: friendshipId is nil for friend-of-friend profiles
**What goes wrong:** Tapping a friend-of-friend pushes `FriendProfileView(friend:)` but `friendshipId` is nil because `PublicFriendResponse` does not expose it. The "Remove Friend" button fires but guard fails silently — or worse, you crash trying to unwrap it.
**Why it happens:** The public friends list endpoint returns `PublicFriendResponse` (id, username, display_name, avatar_url only) — no `friendshipId` because it's not relevant to a third-party viewer.
**How to avoid:** Construct `FriendResponse(friendshipId: nil, ...)` when navigating. The existing `removeFriend()` guard already handles nil: `guard let friendshipId = friend.friendshipId else { return }`. The ellipsis menu will still appear but "Remove Friend" will silently no-op. This is correct UX — the viewer is not friends with the friend-of-friend (they might be, but we have no friendship ID in scope).
**Warning signs:** If you see "Remove Friend" working on a transitive profile, you've passed the wrong friendshipId.

### Pitfall 2: Double-fetch on scroll with isLoadingMore guard missing
**What goes wrong:** `onAppear` on the last cell fires multiple times as the user scrolls near the bottom. Without a guard, `loadMoreWatched()` is called multiple times concurrently, causing duplicate appends.
**Why it happens:** `LazyVGrid` cells can trigger `onAppear` more than once as they enter and leave the visible area.
**How to avoid:** Guard with `guard !isLoadingMore, watchedMovies.count < watchedTotal else { return }` at the start of `loadMoreWatched()`.
**Warning signs:** Duplicate movies appearing in the grid.

### Pitfall 3: Sheet state not resetting between different friend profiles
**What goes wrong:** If the same FriendProfileView instance is reused (uncommon but possible with NavigationStack caching), `showFriendsList` or `selectedFriendOfFriend` retains stale values from the previous profile.
**Why it happens:** `@State` persists for the view's lifetime. Recursive navigation creates new instances, so in practice this is low risk — but the friends list load (`friendsList`) should be cleared on `loadData()`.
**How to avoid:** Assign an empty array to `friendsList` at the start of `loadFriends()`, not just on success.

### Pitfall 4: NavigationDestination item binding conflicts
**What goes wrong:** Using `navigationDestination(item:)` with `$selectedFriendOfFriend` of type `PublicFriendResponse?` requires `PublicFriendResponse` to conform to `Hashable`. If it doesn't, the view won't compile.
**Why it happens:** `navigationDestination(item:)` requires the item type to be `Hashable`.
**How to avoid:** Add `Hashable` conformance to `PublicFriendResponse`. Since all fields are `String?`, synthesized conformance works: `struct PublicFriendResponse: Decodable, Identifiable, Hashable { ... }`.

### Pitfall 5: Fetching friends list on every view appear
**What goes wrong:** If `loadFriends()` is called in `.task {}` alongside the other two loads, every time the view appears (including when returning from MovieDetailView) you make an unnecessary third API call.
**Why it happens:** `.task {}` runs on every view appear by default.
**How to avoid:** Only fetch friends lazily — call `ProfileAPI.getPublicFriends()` inside the `.sheet(isPresented:)` `onAppear` or when the Friends stat is tapped. Use a separate `@State private var isLoadingFriends` and `@State private var friendsList`.

### Pitfall 6: swiftlint type_body_length violation
**What goes wrong:** FriendProfileView will be significantly larger than the current 87-line version. If it exceeds 300 lines, swiftlint's `type_body_length` rule fires.
**Why it happens:** swiftlint max is 300 lines for a type body.
**How to avoid:** Extract heavy sub-views as private structs (e.g., `FriendsListSheet` as a separate struct in the same file, or its own file). ProfileView at 271 lines is just under the limit — FriendProfileView may need similar structural splitting.

---

## Code Examples

Verified patterns from the project codebase:

### Loading State Pattern (from ProfileView)
```swift
// Source: blnd_ios/blnd_ios/Views/Profile/ProfileView.swift
@State private var isLoadingWatched = false

private var watchedGrid: some View {
    Group {
        if isLoadingWatched {
            ProgressView()
                .tint(.white)
                .padding(.top, 40)
        } else if watchedMovies.isEmpty {
            emptyState(message: "No watched movies yet")
        } else {
            PosterGrid {
                ForEach(watchedMovies) { movie in
                    NavigationLink {
                        MovieDetailView(tmdbId: movie.tmdbId, title: movie.title)
                    } label: {
                        PosterTile(posterPath: movie.posterPath, rating: movie.rating)
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }
}
```

### Empty State Pattern (from ProfileView)
```swift
// Source: blnd_ios/blnd_ios/Views/Profile/ProfileView.swift
private func emptyState(message: String) -> some View {
    Text(message)
        .font(.system(size: 14))
        .foregroundStyle(AppTheme.textMuted)
        .frame(maxWidth: .infinity)
        .padding(.top, 40)
}
```

### Async Let Parallel Load (from ProfileView)
```swift
// Source: blnd_ios/blnd_ios/Views/Profile/ProfileView.swift
.task {
    await authState.fetchCurrentUser()
    async let watched: () = loadWatched()
    async let watchlist: () = loadWatchlist()
    async let counts: () = loadCounts()
    _ = await (watched, watchlist, counts)
}
```

### StatsRow with Tappable Item (from ProfileView)
```swift
// Source: blnd_ios/blnd_ios/Views/Profile/ProfileView.swift
StatsRow(items: [
    StatItem(label: "Watched", value: watchedTotal, onTap: nil),
    StatItem(label: "Watchlist", value: watchlistTotal, onTap: nil),
    StatItem(
        label: "Friends",
        value: friendsCount,
        onTap: { tabState.switchTab(1) }
    ),
    StatItem(
        label: "Blends",
        value: groupsCount,
        onTap: { tabState.switchTab(2) }
    ),
])
// For FriendProfileView: 3 items — Watched (nil), Friends (opens sheet), Blends (nil)
```

### Pagination with Query String (from TrackingAPI)
```swift
// Source: blnd_ios/blnd_ios/Networking/TrackingAPI.swift
static func getWatchHistory(
    limit: Int = 20,
    offset: Int = 0
) async throws -> WatchHistoryResponse {
    try await APIClient.shared.request(
        endpoint: "/tracking/?limit=\(limit)&offset=\(offset)",
        authenticated: true
    )
}
```

### CancellationError Guard in Load Functions (from ProfileView)
```swift
// Source: blnd_ios/blnd_ios/Views/Profile/ProfileView.swift
} catch is CancellationError {
    return   // Don't update UI state on cancellation
} catch {
    print("[ProfileView] loadWatched error: \(error)")
}
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| ObservableObject + @Published | @Observable (Swift 5.9 macro) | iOS 17 | FriendProfileView uses local @State — leaf view pattern, no Observable needed |
| Combine publishers for async | async/await + Task | Swift 5.5 | All network calls use async/await throughout the project |
| NavigationView | NavigationStack | iOS 16 | FriendProfileView is already in a NavigationStack from FriendsListView |

**Deprecated/outdated:**
- `@ObservedObject` / `@StateObject`: Not used anywhere in project — use `@Observable` or local `@State`
- Closure-based URLSession: Not used — `APIClient.shared` uses async/await
- `sheet(item:)` with `Identifiable` presented item: Viable alternative to `sheet(isPresented:)` for the friends list, but `isPresented` is simpler when the sheet content is static

---

## Open Questions

1. **friendshipId for friend-of-friend removal**
   - What we know: `PublicFriendResponse` has no `friendshipId`. Friend-of-friend profiles get `FriendResponse(friendshipId: nil, ...)`.
   - What's unclear: Should the ellipsis menu be hidden entirely on friend-of-friend profiles (nil friendshipId), or shown but no-op?
   - Recommendation: Show the menu — the existing `guard let friendshipId` no-op is correct behavior. If the viewer happens to also be friends with the friend-of-friend, they still can't remove via this path (no friendshipId in scope). Edge case is acceptable for now.

2. **Friends list sheet — pagination needed?**
   - What we know: `GET /auth/users/{id}/friends` returns all friends with no pagination (no `limit`/`offset` params in the backend endpoint). `PublicFriendsListResponse` has `friends: [PublicFriendResponse]` — no `total` field.
   - What's unclear: If a friend has hundreds of friends, performance could degrade.
   - Recommendation: Load all friends in a single call (no pagination) — matches the backend design. Use a `List` or `ScrollView` with `LazyVStack` in the sheet for efficient rendering if the list is long.

---

## Validation Architecture

> Note: `workflow.nyquist_validation` key is absent from `.planning/config.json`, so validation is treated as enabled. However, this is a pure iOS SwiftUI phase with zero third-party test frameworks configured in the project. The blnd_ios project has only placeholder test files (`blnd_iosTests.swift` with no tests). No automated test runner is viable without setting up XCTest infrastructure.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | XCTest (project-included, no setup needed) |
| Config file | blnd_ios.xcodeproj (Xcode scheme) |
| Quick run command | `xcodebuild build -scheme blnd_ios -destination 'platform=iOS Simulator,name=iPhone 16'` |
| Full suite command | `xcodebuild test -scheme blnd_ios -destination 'platform=iOS Simulator,name=iPhone 16'` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| IOS-01 | Stats row displays watched/friends/blends counts | manual-only | Build compiles: `xcodebuild build -scheme blnd_ios -destination 'platform=iOS Simulator,name=iPhone 16' 2>&1 \| tail -5` | ❌ Wave 0 (stub only) |
| IOS-02 | 3-column poster grid renders friend's watched movies | manual-only | Same build check | ❌ Wave 0 |
| IOS-03 | Tapping poster navigates to MovieDetailView | manual-only | Same build check | ❌ Wave 0 |
| IOS-04 | Tapping friends count opens bottom sheet | manual-only | Same build check | ❌ Wave 0 |
| IOS-05 | Tapping friend-of-friend pushes FriendProfileView | manual-only | Same build check | ❌ Wave 0 |
| IOS-07 | Loading indicator and empty state display correctly | manual-only | Same build check | ❌ Wave 0 |

**Manual-only justification:** SwiftUI view behavior (navigation, sheet presentation, lazy loading) requires a running simulator. These behaviors cannot be meaningfully tested without XCTest UI tests, which have no existing infrastructure in the project.

### Sampling Rate
- **Per task commit:** `xcodebuild build -scheme blnd_ios -destination 'platform=iOS Simulator,name=iPhone 16' 2>&1 | tail -5`
- **Per wave merge:** Same build check + human simulator verification
- **Phase gate:** Build succeeds + human verifies all 5 success criteria in simulator before `/gsd:verify-work`

### Wave 0 Gaps
- None for test files — no automated unit tests are being added (manual-only per above justification). Build compilation serves as the automated gate.

---

## Sources

### Primary (HIGH confidence)
- `blnd_ios/blnd_ios/Views/Friends/FriendProfileView.swift` — current FriendProfileView implementation (87 lines)
- `blnd_ios/blnd_ios/Views/Profile/ProfileView.swift` — reference implementation for parallel loading, grid, and stats patterns
- `blnd_ios/blnd_ios/Views/Shared/PosterTile.swift`, `StatsRow.swift`, `PosterGrid.swift` — Phase 8 shared components, verified complete
- `blnd_ios/blnd_ios/Networking/FriendsAPI.swift`, `TrackingAPI.swift`, `APIClient.swift` — networking patterns
- `blnd_ios/blnd_ios/Models/FriendModels.swift`, `TrackingModels.swift` — model struct patterns
- `blnd_backend/app/auth/schemas.py` — all 5 public profile Pydantic schemas verified present
- `blnd_backend/app/auth/views.py` — all 3 public profile endpoints verified live (lines 120–152)
- `blnd_ios/CLAUDE.md` — SwiftUI conventions, architecture, linting rules

### Secondary (MEDIUM confidence)
- `blnd_ios/blnd_ios/Theme/AppTheme.swift` — color constants for styling decisions
- `blnd_ios/blnd_ios/Views/Friends/FriendsListView.swift` — FriendRow layout pattern for friends sheet rows

### Tertiary (LOW confidence)
- None

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries are project-internal, verified in-repo
- Architecture: HIGH — all patterns are taken directly from existing files (ProfileView, FriendsAPI, TrackingAPI)
- Pitfalls: HIGH — identified from direct code inspection (FriendResponse.friendshipId, onAppear double-fire, swiftlint limits)

**Research date:** 2026-03-12
**Valid until:** 2026-04-12 (stable project, no fast-moving external dependencies)
