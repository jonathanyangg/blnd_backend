# Requirements: Letterboxd Integration Frontend

**Defined:** 2026-03-09
**Core Value:** Users can import their complete Letterboxd history into BLND with a single zip upload — watched movies, ratings, reviews, watchlist, and likes all transfer accurately.

## v1.1 Requirements

Requirements for the Letterboxd Integration Frontend milestone. Each maps to roadmap phases.

### Import Flow

- [ ] **IMPT-01**: User can tap "Import from Letterboxd" from Profile to start the import flow
- [ ] **IMPT-02**: User sees an in-app webview loading Letterboxd's data export page
- [ ] **IMPT-03**: User can log into Letterboxd within the in-app webview
- [ ] **IMPT-04**: When user taps "Export Your Data" on Letterboxd, the app intercepts the ZIP download without leaving the app
- [ ] **IMPT-05**: After ZIP is captured, the app automatically uploads it to the backend import endpoint
- [ ] **IMPT-06**: User sees a loading indicator while the import is processing
- [ ] **IMPT-07**: User sees import results (imported/skipped/failed counts) when import completes
- [ ] **IMPT-08**: User can tap Done to return to Profile after viewing results
- [ ] **IMPT-09**: User sees an error message if the import fails, with ability to retry

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

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| .fileImporter / Files app file picker | User explicitly wants fully in-app flow via webview — no external file selection |
| Safari redirect for Letterboxd login | All interaction stays inside BLND — no leaving the app |
| Upload progress percentage bar | Backend processes synchronously (10-60s); no streaming progress signal from server. Indeterminate spinner is honest UX. |
| Import from other sources (Trakt, IMDb) | Validate Letterboxd pattern first; defer to v2+ |
| Streaming server-side progress | Requires backend endpoint restructuring for marginal UX gain |
| Two-step TMDB search fallback | Backend improvement — deferred from v1.0, not in v1.1 scope |
| Async background job processing | Backend improvement — deferred from v1.0, not in v1.1 scope |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| IMPT-01 | Phase 5 | Pending |
| IMPT-02 | Phase 5 | Pending |
| IMPT-03 | Phase 5 | Pending |
| IMPT-04 | Phase 5 | Pending |
| IMPT-05 | Phase 6 | Pending |
| IMPT-06 | Phase 6 | Pending |
| IMPT-07 | Phase 6 | Pending |
| IMPT-08 | Phase 6 | Pending |
| IMPT-09 | Phase 6 | Pending |
| BKND-01 | Phase 4 | Complete |

**Coverage:**
- v1.1 requirements: 10 total
- Mapped to phases: 10
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-09*
*Last updated: 2026-03-09 — traceability filled after roadmap creation*
