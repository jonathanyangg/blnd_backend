# Phase 9: FriendProfileView Revamp - Context

**Gathered:** 2026-03-12
**Status:** Ready for planning

<domain>
## Phase Boundary

Transform FriendProfileView from a bare-bones avatar + remove-friend screen into a rich profile showing stats, watched movie poster grid, and friend connections — matching the depth of the user's own ProfileView (minus watchlist/private data). Backend endpoints already exist (Phase 7). Shared components already extracted (Phase 8).

</domain>

<decisions>
## Implementation Decisions

### Remove Friend Placement
- Move "Remove Friend" from centered capsule button to a three-dot ellipsis menu in the top-right toolbar
- Three-dot menu contains only "Remove Friend" — no other actions
- Keep the existing system `.alert()` confirmation dialog (Cancel + destructive Remove)
- After removal, dismiss back to FriendsListView (current behavior, unchanged)

### Layout Structure
- No tab picker — stats row flows directly into the poster grid (only watched movies shown, watchlist is private/out of scope)
- 3 stats in StatsRow: Watched, Friends, Blends (matches the 3 counts from GET /auth/users/{id}/profile)
- Only Friends count is tappable — opens the friend's friends list
- Watched count is not tappable (grid is right below), Blends count is not tappable (deferred to PROF-02)

### Friends List Presentation
- Tapping friends count opens a bottom sheet (`.sheet()`) showing the friend's friends list
- Each friend row in the sheet is tappable
- Tapping a friend-of-friend: dismiss the sheet, then push a new FriendProfileView onto the navigation stack
- Recursive navigation works naturally: each FriendProfileView can open its own friends list sheet, tapping someone dismisses and pushes another FriendProfileView

### Claude's Discretion
- Loading indicator style (ProgressView spinner vs skeleton)
- Empty state wording and icon for friends with no watched movies
- Infinite scroll implementation details for the poster grid
- Friends list sheet layout and styling
- ProfileAPI networking layer structure

</decisions>

<specifics>
## Specific Ideas

- The friends list sheet should dismiss before navigating — no NavigationStack inside the sheet
- FriendProfileView receives a `FriendResponse` (has id, username, displayName, avatarUrl) but needs to call the public profile API for stats and watched data
- Match ProfileView's visual structure: avatar → name/username → stats row → grid (just without the tab picker and top settings row)

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `PosterTile`: Shared component with posterPath + rating badge — use directly in the watched grid
- `StatsRow` + `StatItem`: Shared component with optional onTap callback — use for 3 stats (watched, friends, blends)
- `PosterGrid`: Generic @ViewBuilder wrapper around 3-column LazyVGrid — use for the watched movie grid
- `AvatarView`: Already used in current FriendProfileView — keep as-is
- `AppTheme`: Dark monochrome colors throughout
- `BackButton`: Already used in current FriendProfileView toolbar

### Established Patterns
- `async let` parallel loading: ProfileView loads watched + watchlist + counts in parallel — FriendProfileView should parallel-load profile stats + watched movies
- NavigationLink to MovieDetailView: ProfileView uses `NavigationLink { MovieDetailView(tmdbId:title:) }` — same pattern for watched grid
- `FriendsAPI.removeFriend()`: Already wired in current FriendProfileView — keep the remove logic
- `.swipeBackGesture()`: Already applied on FriendProfileView — keep it

### Integration Points
- New `ProfileAPI.swift` needed: 3 static methods calling GET /auth/users/{id}/profile, /watched, /friends
- New models needed: `PublicProfileResponse`, `PublicWatchedMovieResponse`, `PublicWatchedListResponse`, `PublicFriendResponse`, `PublicFriendsListResponse` (matching backend schemas)
- FriendsListView navigates to FriendProfileView via NavigationLink — no changes needed there
- Backend endpoints: `GET /auth/users/{id}/profile`, `GET /auth/users/{id}/watched?limit=&offset=`, `GET /auth/users/{id}/friends`

</code_context>

<deferred>
## Deferred Ideas

- PROF-02: Tappable blends count on friend profile (requires new endpoint + view)
- PROF-04: Taste compatibility display on friend profile
- PROF-05: Mutual friends indicator on friend profile

</deferred>

---

*Phase: 09-friendprofileview-revamp*
*Context gathered: 2026-03-12*
