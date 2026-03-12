# Requirements: BLND

**Defined:** 2026-03-09
**Core Value:** Users can import their complete Letterboxd history into BLND with a single zip upload — watched movies, ratings, reviews, watchlist, and likes all transfer accurately.

## v1.2 Requirements

Requirements for the Revamp Other User Profile View milestone. Each maps to roadmap phases.

### Backend API

- [x] **API-01**: Authenticated user can fetch another user's public profile (username, display name, avatar, watched count, friends count, blends count)
- [ ] **API-02**: Authenticated user can fetch another user's watched movies (paginated, with tmdb_id, title, poster, rating)
- [ ] **API-03**: Authenticated user can fetch another user's friends list (id, username, display name, avatar)
- [x] **API-04**: All three public profile endpoints return 403 if the caller is not friends with the target user

### iOS Frontend

- [ ] **IOS-01**: User sees stats row on friend profile (watched count, friends count, blends count)
- [ ] **IOS-02**: User sees 3-column poster grid of friend's watched movies with star ratings
- [ ] **IOS-03**: User can tap a watched movie poster to navigate to MovieDetailView
- [ ] **IOS-04**: User can tap friends count to see friend's friends list
- [ ] **IOS-05**: User can tap a friend-of-friend to open their profile (recursive navigation)
- [x] **IOS-06**: PosterTile and StatsRow extracted as shared components used by both ProfileView and FriendProfileView
- [ ] **IOS-07**: Loading and empty states displayed while data loads or when friend has no watched movies

## v1.1 Requirements (Complete)

### Import Flow

- [x] **IMPT-01**: User can tap "Import from Letterboxd" from Profile to start the import flow
- [x] **IMPT-02**: User sees an in-app webview loading Letterboxd's data export page
- [x] **IMPT-03**: User can log into Letterboxd within the in-app webview
- [x] **IMPT-04**: When user taps "Export Your Data" on Letterboxd, the app intercepts the ZIP download without leaving the app
- [x] **IMPT-05**: After ZIP is captured, the app automatically uploads it to the backend import endpoint
- [x] **IMPT-06**: User sees a loading indicator while the import is processing
- [x] **IMPT-07**: User sees import results (imported/skipped/failed counts) when import completes
- [x] **IMPT-08**: User can tap Done to return to Profile after viewing results
- [x] **IMPT-09**: User sees an error message if the import fails, with ability to retry

### Backend

- [x] **BKND-01**: Taste profile is automatically rebuilt after a successful bulk import

## Future Requirements

Deferred to future release. Tracked but not in current roadmap.

### Import Enhancements

- **IMPT-10**: User sees import prompt during onboarding flow for first-time Letterboxd migrants
- **IMPT-11**: User sees "Last imported" timestamp in Settings after a successful import
- **IMPT-12**: User can incrementally re-import to pick up new Letterboxd entries since last import

### Data Surfacing

- **DATA-01**: Liked field exposed in tracking API responses
- **DATA-02**: Watchlist read/CRUD API endpoints
- **DATA-03**: Watchlist view in iOS app

### Profile Enhancements

- **PROF-01**: Rating badges on friend's watched movie posters show whose rating it is
- **PROF-02**: Tappable blends count on friend profile (requires new endpoint + view)
- **PROF-03**: Privacy controls (friends-only vs public visibility toggle)
- **PROF-04**: Taste compatibility display on friend profile
- **PROF-05**: Mutual friends indicator on friend profile

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Watchlist tab on friend profile | Watchlist is private intent, not social signal — excluded by milestone spec |
| @Observable state class for friend profile | Leaf view, local @State is correct pattern |
| New FastAPI domain folder for public profile | Three read-only endpoints don't justify a new domain — lives in auth/ |
| Rating badge ambiguity resolution | "Whose rating?" design not yet resolved — defer to future |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| IMPT-01 | Phase 5 | Complete |
| IMPT-02 | Phase 5 | Complete |
| IMPT-03 | Phase 5 | Complete |
| IMPT-04 | Phase 5 | Complete |
| IMPT-05 | Phase 6 | Complete |
| IMPT-06 | Phase 6 | Complete |
| IMPT-07 | Phase 6 | Complete |
| IMPT-08 | Phase 6 | Complete |
| IMPT-09 | Phase 6 | Complete |
| BKND-01 | Phase 4 | Complete |
| API-01 | Phase 7 | Complete |
| API-02 | Phase 7 | Pending |
| API-03 | Phase 7 | Pending |
| API-04 | Phase 7 | Complete |
| IOS-01 | Phase 9 | Pending |
| IOS-02 | Phase 9 | Pending |
| IOS-03 | Phase 9 | Pending |
| IOS-04 | Phase 9 | Pending |
| IOS-05 | Phase 9 | Pending |
| IOS-06 | Phase 8 | Complete |
| IOS-07 | Phase 9 | Pending |

**Coverage:**
- v1.2 requirements: 11 total
- Mapped to phases: 11
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-09*
*Last updated: 2026-03-12 — v1.2 traceability complete (Phases 7-9)*
