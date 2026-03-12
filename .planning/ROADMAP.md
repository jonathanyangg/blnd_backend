# Roadmap: BLND

## Milestones

- ✅ **v1.0 Letterboxd Import** — Phases 1-3 (shipped 2026-03-09)
- ✅ **v1.1 Letterboxd Integration Frontend** — Phases 4-6 (shipped 2026-03-12)
- 📋 **v1.2 Revamp Other User Profile View** — Phases 7-9 (planned)

## Phases

<details>
<summary>✅ v1.0 Letterboxd Import (Phases 1-3) — SHIPPED 2026-03-09</summary>

- [x] Phase 1: Schema (2/2 plans) — completed 2026-03-04
- [x] Phase 2: Core Import Workflow (3/3 plans) — completed 2026-03-05
- [x] Phase 3: Polish and Hardening (1/1 plan) — completed 2026-03-05

See: `.planning/milestones/v1.0-ROADMAP.md` for full details.

</details>

<details>
<summary>✅ v1.1 Letterboxd Integration Frontend (Phases 4-6) — SHIPPED 2026-03-12</summary>

- [x] Phase 4: Backend Taste Rebuild Hook (1/1 plan) — completed 2026-03-10
- [x] Phase 5: iOS Webview Import Flow (2/2 plans) — completed 2026-03-12
- [x] Phase 6: iOS Upload and Results (1/1 plan) — completed 2026-03-12

</details>

### 📋 v1.2 Revamp Other User Profile View (Planned)

**Milestone Goal:** Give users a rich profile view when tapping into a friend's profile — showing their watched movies, stats, and social connections — matching the depth of the user's own profile (minus watchlist).

#### Phase 7: Backend Public Profile Endpoints

**Goal**: Three production-ready endpoints expose a friend's public profile data behind a friendship authorization gate
**Depends on**: Nothing (first phase of v1.2)
**Requirements**: API-01, API-02, API-03, API-04
**Success Criteria** (what must be TRUE):
  1. An authenticated user can fetch another user's public profile stats (watched count, friends count, blends count) via `GET /auth/users/{id}/profile`
  2. An authenticated user can fetch another user's watched movies paginated via `GET /auth/users/{id}/watched`, including tmdb_id, title, poster, and rating
  3. An authenticated user can fetch another user's friends list via `GET /auth/users/{id}/friends`
  4. All three endpoints return HTTP 403 when the caller is not friends with the target user
**Plans**: 2 plans

Plans:
- [ ] 07-01-PLAN.md — PublicProfileResponse schema + friendship gate + stats endpoint + test scaffold
- [ ] 07-02-PLAN.md — Paginated watched movies endpoint + friends list endpoint

#### Phase 8: iOS Shared Component Extraction

**Goal**: PosterTile and StatsRow extracted from ProfileView into shared components, leaving ProfileView behavior identical and FriendProfileView able to reuse them
**Depends on**: Nothing (can proceed in parallel with Phase 7)
**Requirements**: IOS-06
**Success Criteria** (what must be TRUE):
  1. ProfileView compiles and behaves identically after the refactor — no visible change to any existing screen
  2. PosterTile, StatsRow, and PosterGrid exist as standalone components in `Views/Shared/` and are importable by any view
**Plans**: 1 plan

Plans:
- [ ] 08-01-PLAN.md — Extract PosterTile, StatsRow, PosterGrid to Views/Shared/ and refactor ProfileView to use them

#### Phase 9: FriendProfileView Revamp

**Goal**: FriendProfileView shows a friend's stats, watched poster grid, and tappable friends list with full navigation — matching the depth of the user's own profile
**Depends on**: Phase 7, Phase 8
**Requirements**: IOS-01, IOS-02, IOS-03, IOS-04, IOS-05, IOS-07
**Success Criteria** (what must be TRUE):
  1. User sees a stats row on a friend's profile displaying watched count, friends count, and blends count loaded from the backend
  2. User sees a 3-column poster grid of the friend's watched movies with star ratings, loading the next page automatically as they scroll
  3. User can tap a watched movie poster and land on MovieDetailView for that film
  4. User can tap the friends count and see a list of the friend's friends; tapping any friend-of-friend opens their FriendProfileView (recursive navigation works)
  5. User sees a loading indicator while data is fetching and a contextual empty state if the friend has no watched movies
**Plans**: 2 plans

Plans:
- [ ] 09-01-PLAN.md — ProfileAPI.swift + ProfileModels.swift networking layer
- [ ] 09-02-PLAN.md — FriendProfileView revamp — stats row, poster grid, friends list, loading/empty states, recursive navigation

## Phase Details

### Phase 4: Backend Taste Rebuild Hook
**Goal**: Backend triggers taste profile rebuild after every successful Letterboxd import
**Depends on**: Nothing (first phase of v1.1, independent of iOS)
**Requirements**: BKND-01
**Success Criteria** (what must be TRUE):
  1. After a successful `POST /import/letterboxd`, the user's taste profile is rebuilt without any additional API call
  2. The taste rebuild fires after the import response is returned to the client (non-blocking)
  3. A failed or zero-import result does not trigger an unnecessary rebuild
**Plans**: 1 plan

Plans:
- [x] 04-01-PLAN.md — Add BackgroundTasks rebuild hook to import_letterboxd endpoint (TDD)

### Phase 5: iOS Webview Import Flow
**Goal**: User can reach the Letterboxd export page inside BLND and the app captures the ZIP download automatically
**Depends on**: Nothing (parallel to Phase 4)
**Requirements**: IMPT-01, IMPT-02, IMPT-03, IMPT-04
**Success Criteria** (what must be TRUE):
  1. User can tap "Import from Letterboxd" in Profile and an in-app screen appears
  2. A WKWebView loads Letterboxd's data export page without leaving the app
  3. User can log into their Letterboxd account inside the webview
  4. When user taps "Export Your Data" on Letterboxd, the app intercepts the ZIP download and the user never sees a Safari redirect or system download prompt
**Plans**: 2 plans

Plans:
- [x] 05-01-PLAN.md — WKWebView bridge with download interception + Letterboxd webview container
- [x] 05-02-PLAN.md — Import button on ProfileView + context/instructions screen + flow wiring

### Phase 6: iOS Upload and Results
**Goal**: After ZIP is captured, the app uploads it and shows the user what happened
**Depends on**: Phase 5
**Requirements**: IMPT-05, IMPT-06, IMPT-07, IMPT-08, IMPT-09
**Success Criteria** (what must be TRUE):
  1. After ZIP capture, upload to the backend begins automatically with no user action required
  2. User sees a loading indicator while the import is processing
  3. User sees imported, skipped, and failed counts when the import completes
  4. User can tap Done to return to Profile after viewing results
  5. If the import fails, user sees an error message and can retry without leaving the screen
**Plans**: 1 plan

Plans:
- [x] 06-01-PLAN.md — Multipart upload API + ImportContextView 4-state machine (loading/results/error)

### Phase 7: Backend Public Profile Endpoints
**Goal**: Three production-ready endpoints expose a friend's public profile data behind a friendship authorization gate
**Depends on**: Nothing (first phase of v1.2, no dependency on v1.1 iOS work)
**Requirements**: API-01, API-02, API-03, API-04
**Success Criteria** (what must be TRUE):
  1. An authenticated user can fetch another user's public profile stats (watched count, friends count, blends count) via `GET /auth/users/{id}/profile`
  2. An authenticated user can fetch another user's watched movies paginated via `GET /auth/users/{id}/watched`, including tmdb_id, title, poster, and rating
  3. An authenticated user can fetch another user's friends list via `GET /auth/users/{id}/friends`
  4. All three endpoints return HTTP 403 when the caller is not friends with the target user
**Plans**: 2 plans

Plans:
- [ ] 07-01-PLAN.md — PublicProfileResponse schema + friendship gate + stats endpoint + test scaffold
- [ ] 07-02-PLAN.md — Paginated watched movies endpoint + friends list endpoint

### Phase 8: iOS Shared Component Extraction
**Goal**: PosterTile and StatsRow extracted from ProfileView into shared components, leaving ProfileView behavior identical and FriendProfileView able to reuse them
**Depends on**: Nothing (can proceed in parallel with Phase 7)
**Requirements**: IOS-06
**Success Criteria** (what must be TRUE):
  1. ProfileView compiles and behaves identically after the refactor — no visible change to any existing screen
  2. PosterTile, StatsRow, and PosterGrid exist as standalone components in `Views/Shared/` and are importable by any view
**Plans**: 1 plan

Plans:
- [ ] 08-01-PLAN.md — Extract PosterTile, StatsRow, PosterGrid to Views/Shared/ and refactor ProfileView to use them

### Phase 9: FriendProfileView Revamp
**Goal**: FriendProfileView shows a friend's stats, watched poster grid, and tappable friends list with full navigation — matching the depth of the user's own profile
**Depends on**: Phase 7, Phase 8
**Requirements**: IOS-01, IOS-02, IOS-03, IOS-04, IOS-05, IOS-07
**Success Criteria** (what must be TRUE):
  1. User sees a stats row on a friend's profile displaying watched count, friends count, and blends count loaded from the backend
  2. User sees a 3-column poster grid of the friend's watched movies with star ratings, loading the next page automatically as they scroll
  3. User can tap a watched movie poster and land on MovieDetailView for that film
  4. User can tap the friends count and see a list of the friend's friends; tapping any friend-of-friend opens their FriendProfileView (recursive navigation works)
  5. User sees a loading indicator while data is fetching and a contextual empty state if the friend has no watched movies
**Plans**: 2 plans

Plans:
- [ ] 09-01-PLAN.md — ProfileAPI.swift + ProfileModels.swift networking layer
- [ ] 09-02-PLAN.md — FriendProfileView revamp — stats row, poster grid, friends list, loading/empty states, recursive navigation

## Progress

**Execution Order:**
Phase 7 and Phase 8 are independent (parallel tracks). Phase 9 depends on both 7 and 8. Recommended order: 7 + 8 (parallel) → 9.

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Schema | v1.0 | 2/2 | Complete | 2026-03-04 |
| 2. Core Import Workflow | v1.0 | 3/3 | Complete | 2026-03-05 |
| 3. Polish and Hardening | v1.0 | 1/1 | Complete | 2026-03-05 |
| 4. Backend Taste Rebuild Hook | v1.1 | 1/1 | Complete | 2026-03-10 |
| 5. iOS Webview Import Flow | v1.1 | 2/2 | Complete | 2026-03-12 |
| 6. iOS Upload and Results | v1.1 | 1/1 | Complete | 2026-03-12 |
| 7. Backend Public Profile Endpoints | 2/2 | Complete    | 2026-03-12 | - |
| 8. iOS Shared Component Extraction | 1/1 | Complete    | 2026-03-12 | - |
| 9. FriendProfileView Revamp | v1.2 | 0/2 | Not started | - |
