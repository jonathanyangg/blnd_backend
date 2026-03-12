# Feature Landscape

**Domain:** Public user profile view + friend profile revamp (v1.2 milestone)
**Researched:** 2026-03-11
**Confidence:** HIGH (codebase inspection) / MEDIUM (social app UX patterns from research)

---

## Scope Note

This file covers ONLY net-new features for v1.2. Already built and out of scope:
- Own ProfileView: avatar, name/username, stats row (watched/watchlist/friends/blends), watched/watchlist poster grids, tappable friends/blends stats that switch tabs
- FriendProfileView: avatar, name/username, remove friend button
- Backend: GET /tracking/ (own watch history, paginated), GET /friends/ (own friends list), GET /groups/ (own groups)
- FriendResponse model: friendship_id, id, username, display_name, avatar_url

Net-new surface area for v1.2: three backend endpoints, one revamped iOS view, new iOS models, new API client methods.

---

## Table Stakes

Features users expect when viewing a friend's profile. Missing these = profile feels hollow.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Stats row on friend profile | Own ProfileView already shows watched/watchlist/friends/blends. Opening a friend's profile and seeing only avatar + remove button is jarring. Users expect parity. | LOW | Watched count, friends count, blends count — three numbers. No watchlist count (explicitly out of scope per milestone). Blends count is display-only. Requires new backend endpoint returning these three counts for an arbitrary user_id. |
| Watched poster grid on friend profile | Profile without a content grid feels unfinished. Letterboxd, Simkl, and Trakt all show a film grid on public profiles. It is the primary social signal for a movie app. | MEDIUM | Paginated endpoint needed: GET /users/{user_id}/watched. Returns same WatchedMovieResponse shape as own tracking endpoint. Poster grid reuses existing LazyVGrid + posterTile() pattern from ProfileView. |
| Tappable poster → MovieDetailView | Own ProfileView already does this. Every poster in the app navigates to MovieDetailView — inconsistency when friend posters do nothing is noticed immediately. | LOW | NavigationLink wrapping each poster tile, identical to existing ProfileView.watchedGrid implementation. MovieDetailView already accepts tmdbId + title. No new view needed. |
| Loading state while fetching | Every data-driven view in the app shows a spinner while loading. A blank-then-appearing grid without a loading indicator reads as broken. | LOW | ProgressView pattern already used in ProfileView. isLoading state variable, same as ProfileView.isLoadingWatched. |
| Empty state for zero watched films | Some users may have no watch history. An empty grid with no explanation looks like an error. | LOW | "No watched movies yet" empty state, identical to own ProfileView pattern. |

---

## Differentiators

Features that raise the social utility of the profile beyond bare minimum.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Tappable friends count → FriendsListView for that user | Social apps (Instagram, Twitter/X) make follower/following counts tappable to see who those connections are. Lets users discover new people through mutual friends. | MEDIUM | Requires a new backend endpoint: GET /users/{user_id}/friends — returns FriendListResponse scoped to a different user. New FriendsFriendsView or reuse FriendsListView with a userId parameter. In-app navigation: friends count taps to a NavigationLink destination showing that user's friend list. |
| Blends count shown (display-only) | Establishes that blends is a real social primitive, not just a solo feature. Seeing "3 blends" on a friend's profile creates curiosity about the social graph. | LOW | No extra endpoint needed — blends count returned in the same public profile stats endpoint. No tap destination needed per milestone scope. |
| Pagination on watched grid | Own ProfileView loads 50 films with no load-more. A friend who imported 500+ Letterboxd films will break this pattern. Users who discover "only 50 films shown" lose trust. | MEDIUM | Backend endpoint must support limit + offset (consistent with existing GET /tracking/ pattern). iOS implementation: detect last item in LazyVGrid, trigger load-more, append to array. SwiftUI LazyVGrid supports onAppear on the last cell for this pattern. |
| Remove friend button preserved | Users navigating to a friend's profile may want to manage the friendship from there. Removing the only current feature of FriendProfileView degrades utility. | LOW | Keep the existing remove friend button + alert. Position it below the stats row, consistent with its current placement. No logic change needed — friendshipId still available from FriendResponse. |

---

## Anti-Features

Features that seem valuable but create disproportionate complexity or design problems.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Watchlist visible on friend profiles | Tempting since own ProfileView shows watchlist tab. But watchlist is a planning artifact (want-to-watch), not a social signal in the same way as watch history. Users may feel watchlist is more private — "intent" vs "history". Milestone spec explicitly excludes it. | Show watched grid only. No watchlist tab on FriendProfileView. If requested later, add as a separately considered feature with privacy controls. |
| Ratings visible on friend's watched posters | Own ProfileView shows the star rating badge on each poster. Showing a friend's rating creates a potential social comparison / judgment dynamic not yet designed for. Also requires careful UI — "is this their rating or my rating?" ambiguity in shared views like MovieDetailView. | Show posters without rating badges on friend profiles for now. Rating data may be in the response payload but render without it. |
| Block / report / privacy controls | Production social apps need these. But this is a friends-only social graph — you can only see someone if you're friends with them (implicit privacy model). Adding block/report is a separate moderation system. | The current "friends only" model is the privacy layer. Add block/report in a dedicated moderation milestone when the user base justifies it. |
| "Follow" model vs "friends" model | Could add follow (asymmetric) to let users see profiles without mutual acceptance. Increases reach but removes the intentional social graph. | Keep mutual friends model. The current schema (friendships table with requester/addressee) enforces this. |
| Profile editing from friend's profile | iOS pattern: a user might tap "Edit" expecting to edit their own profile from any view. | Use navigationBarTitle or header to clearly identify whose profile is shown. Never show edit affordances on FriendProfileView. |
| Infinite scroll pagination visible count mismatch | If stats row shows "watched: 312" but grid only loads 20 at a time, users may be confused why they see fewer films than the count shows. | Display the count from the backend total field (same pattern as own ProfileView where watchedTotal is separate from watchedMovies.count). |

---

## Feature Dependencies

```
[Backend: GET /users/{user_id}/profile]
    └──required by──> [Stats row (watched count, friends count, blends count)]
    └──required by──> [Correct total counts in stats numbers]

[Backend: GET /users/{user_id}/watched]
    └──required by──> [Watched poster grid]
                          └──required by──> [Tappable poster → MovieDetailView]
                          └──requires──> [Pagination (load-more) if > first page]

[Backend: GET /users/{user_id}/friends]
    └──required by──> [Tappable friends count → friend's friends list]
    └──optional for──> [Blends count display-only (covered by /profile endpoint)]

[Existing FriendResponse (id, username, display_name, avatar_url, friendship_id)]
    └──already satisfies──> [user_id for new endpoint calls]
    └──already satisfies──> [Remove friend button (friendship_id)]

[Existing ProfileView.posterTile()]
    └──can be extracted to──> [Shared component or duplicated in FriendProfileView]
    NOTE: posterTile() is private in ProfileView. Either make it internal/shared or duplicate it.

[Existing LazyVGrid + posterColumns definition]
    └──same 3-column layout──> [Reuse pattern in FriendProfileView]

[Existing FriendsListView]
    └──can be reused with userId param──> [Friend's friends list destination]
    NOTE: FriendsListView currently loads own friends. Requires parameterization OR a new
    view. New view is lower risk (avoids modifying working code).
```

### Dependency Notes

- **New models needed on iOS:** `PublicProfileStatsResponse` (watched_count, friends_count, blends_count), `PublicWatchHistoryResponse` (mirrors WatchHistoryResponse but for another user), new `PublicFriendListResponse` (list of friends for another user). These may reuse existing `WatchedMovieResponse` and `FriendResponse` types as their item types.
- **Backend authorization boundary:** All three new endpoints require auth (JWT). They scope their queries to the requested user_id, not the caller's user_id. Authorization check: caller must be friends with the requested user, OR the endpoint returns the requested user's public data to any authenticated user (simpler model). The "friends only" visibility model is the logical choice for a social app where you only have friends you accepted — but the milestone description does not specify the authorization check. Recommendation: scope to any authenticated user for simplicity, revisit when/if privacy controls are needed.
- **Pagination offset tracking:** FriendProfileView needs state vars for: `watchedMovies: [WatchedMovieResponse]`, `watchedTotal: Int`, `isLoadingWatched: Bool`, `watchedOffset: Int`, `hasMoreWatched: Bool`. This is more state than the current FriendProfileView carries. Using a dedicated view model or keeping it as local @State is a design decision for the build phase.
- **posterTile() sharing:** The private `posterTile(path:rating:)` function in ProfileView is needed in FriendProfileView too. Options: (a) extract to a shared `PosterTileView` component in Views/Shared/, (b) duplicate the function. Extraction is cleaner and aligns with existing pattern of shared components (MovieCard, AvatarView). Recommend extraction.

---

## MVP Definition

### Launch With (v1.2)

Backend (three new endpoints):
- [ ] GET /users/{user_id}/profile — returns `{watched_count, friends_count, blends_count}` for any authenticated caller looking up any user_id
- [ ] GET /users/{user_id}/watched — paginated watch history for another user, same limit/offset params as GET /tracking/, returns `WatchHistoryResponse` shape
- [ ] GET /users/{user_id}/friends — returns friends list for another user, same shape as GET /friends/ (`FriendListResponse`)

iOS (FriendProfileView revamp):
- [ ] Stats row: watched count / friends count / blends count (display-only). Reuses `statItem()` pattern from ProfileView. Loaded from GET /users/{user_id}/profile.
- [ ] Watched poster grid: 3-column LazyVGrid, same posterTile layout as ProfileView (without rating badge), infinite scroll / load-more triggering GET /users/{user_id}/watched with pagination.
- [ ] Each poster tappable → NavigationLink to MovieDetailView(tmdbId:title:). Already built.
- [ ] Friends count tappable → NavigationLink to new FriendFriendsListView (shows that user's friends, read-only, no accept/reject). Calls GET /users/{user_id}/friends.
- [ ] Remove friend button preserved, positioned below stats row.
- [ ] Loading states and empty state per existing app patterns.

### Add After Validation (v1.x)

- [ ] Rating badges on friend posters — once the social comparison UX has been validated and "whose rating?" ambiguity is resolved
- [ ] Blends count tappable — navigate to a list of mutual blends or that user's blends; requires a new endpoint and a new view
- [ ] Privacy controls — "friends only" vs "public" profile setting on own profile affecting what gets returned from /users/{user_id}/* endpoints

### Future Consideration (v2+)

- [ ] Taste compatibility display on friend profile — show match % or taste overlap (cosine similarity between taste embeddings) as a social feature
- [ ] Activity feed on friend profile — recent watches, ratings, reviews in chronological order
- [ ] Mutual friends display — "3 mutual friends" shown on friend profile

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Backend GET /users/{user_id}/profile (stats) | HIGH | LOW (3 count queries) | P1 |
| Backend GET /users/{user_id}/watched (paginated) | HIGH | LOW (mirrors existing get_watch_history) | P1 |
| Stats row on FriendProfileView | HIGH | LOW (reuse statItem pattern) | P1 |
| Watched poster grid on FriendProfileView | HIGH | MEDIUM (pagination state, posterTile extraction) | P1 |
| Tappable poster → MovieDetailView | HIGH | LOW (NavigationLink, already built) | P1 |
| Loading + empty states | HIGH | LOW (existing patterns) | P1 |
| Backend GET /users/{user_id}/friends | MEDIUM | LOW (mirrors existing get_friends) | P2 |
| Friends count tappable → FriendFriendsListView | MEDIUM | MEDIUM (new view, new API call) | P2 |
| Blends count display-only | LOW | LOW (in stats endpoint already) | P1 (zero cost) |
| Rating badges on friend posters | LOW | LOW (data available, design question) | P3 |
| Pagination load-more on watched grid | MEDIUM | MEDIUM (offset state + onAppear trigger) | P2 |

**Priority key:**
- P1: Must have for v1.2 launch
- P2: Should have, add in same pass if time allows
- P3: Nice to have, future milestone
- DO NOT BUILD: Creates worse UX than the simpler alternative

---

## Social App Pattern Analysis

| Pattern | Letterboxd | Instagram | Our Approach |
|---------|-----------|-----------|--------------|
| Profile stats row | Films / This Year / Lists (counts, some tappable) | Posts / Followers / Following (all tappable) | Watched / Friends / Blends — watched and friends tappable, blends display-only |
| Content grid | All films watched, paginated | Photo grid, paginated | 3-col poster grid, paginated, sorted by most recent |
| Public vs private | Public by default, private option | Public by default, private option | Friends-only implied by mutual friendship model — no explicit toggle for v1.2 |
| Rating visibility on public profile | Ratings shown on public film entries | N/A | Defer for v1.2 to avoid "whose rating?" confusion |
| Watchlist on public profile | No (watchlist is private) | N/A | No — milestone spec explicitly excludes |

---

## Sources

- Codebase: `/Users/adamrose/Desktop/blnd/blnd_ios/blnd_ios/Views/Profile/ProfileView.swift` — statsRow, watchedGrid, posterTile(), statItem() patterns confirmed
- Codebase: `/Users/adamrose/Desktop/blnd/blnd_ios/blnd_ios/Views/Friends/FriendProfileView.swift` — current state: avatar, name, remove friend only
- Codebase: `/Users/adamrose/Desktop/blnd/blnd_ios/blnd_ios/Models/FriendModels.swift` — FriendResponse fields (id, username, display_name, avatar_url, friendship_id)
- Codebase: `/Users/adamrose/Desktop/blnd/blnd_ios/blnd_ios/Models/TrackingModels.swift` — WatchedMovieResponse, WatchHistoryResponse shapes confirmed
- Codebase: `/Users/adamrose/Desktop/blnd/blnd_backend/app/tracking/views.py` — GET /tracking/ pagination pattern (limit/offset Query params)
- Codebase: `/Users/adamrose/Desktop/blnd/blnd_backend/app/friends/views.py` — GET /friends/ pattern
- Codebase: `/Users/adamrose/Desktop/blnd/blnd_backend/app/friends/schemas.py` — FriendListResponse shape
- Codebase: `/Users/adamrose/Desktop/blnd/blnd_ios/CLAUDE.md` — app architecture, conventions, swiftlint rules
- Codebase: `/Users/adamrose/Desktop/blnd/blnd_backend/CLAUDE.md` — backend domain structure, conventions
- [Letterboxd profile features](https://letterboxd.com/about/faq/) — public profile shows films, followers, lists; watchlist is private by default
- [SwiftUI LazyVGrid pagination — tanaschita.com](https://tanaschita.com/20230828-pagination-in-swiftui-list/) — onAppear on last item as load-more trigger
- [Implementing Load More Pagination in LazyVGrid in SwiftUI — Medium](https://medium.com/@naylinn/implementing-load-more-pagination-in-lazyvgrid-in-swiftui-ed5d3e0c1486) — LazyVGrid pagination pattern
- [GitHub REST API — GET /users/{username}](https://docs.github.com/en/rest/users/users) — public profile endpoint pattern, scoped to requested user not caller

---

*Feature research for: Public user profile endpoints + FriendProfileView revamp (v1.2)*
*Researched: 2026-03-11*
